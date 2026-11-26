"""Document tab widget combining WebKit2 preview, GtkSourceView editor, Watch Mode, Diff, Search, and JS Bridge."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkSource", "300")

from gi.repository import Gdk, Gio, GLib, Gtk, GtkSource, WebKit2  # noqa: E402

from mdviewer.clipboard import read_clipboard_smart, write_clipboard_text  # noqa: E402
from mdviewer.context_inspector import DocumentContextReport, analyze_document  # noqa: E402
from mdviewer.dialogs import CommentEditorDialog  # noqa: E402
from mdviewer.diff_engine import DiffReport, compute_changed_lines, diff_texts  # noqa: E402
from mdviewer.gtk_styles import (  # noqa: E402
    get_gtksource_scheme_candidates,
    get_webview_bg_rgba,
)
from mdviewer.markdown_engine import (  # noqa: E402
    HeadingItem,
    RenderResult,
    detect_file_kind,
    render_document,
    toggle_task_checkbox_in_text,
)
from mdviewer.review_comments import ReviewComment, ReviewSession  # noqa: E402

_MAX_REVISIONS = 25
_WATCH_DEBOUNCE_MS = 150
_SPLIT_DEBOUNCE_MS = 180

_SUPPORTED_LOCAL_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".mdown",
        ".mkd",
        ".mdx",
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".toml",
        ".diff",
        ".patch",
        ".mmd",
        ".mermaid",
        ".txt",
    }
)


def _file_uri_to_path(uri: str) -> str:
    try:
        path, _host = GLib.filename_from_uri(uri)
        return path
    except Exception:
        parsed = urlparse(uri)
        return url2pathname(unquote(parsed.path))


class DocumentTab(Gtk.Box):
    """Self-contained document studio tab with Preview, Split, Edit, Watch Mode, Diff, and Search."""

    def __init__(
        self,
        *,
        file_path: str | None = None,
        initial_text: str | None = None,
        display_name: str | None = None,
        theme_id: str = "paper",
        zoom_level: float = 1.0,
        view_mode: str = "preview",
        readonly: bool = False,
        watch_enabled: bool = False,
        allow_remote_images: bool = False,
        vim_enabled: bool = True,
        custom_css: str = "",
        split_ratio: float = 0.5,
        clipboard_mode: bool = False,
        clipboard_was_html: bool = False,
        initial_line: int | None = None,
        initial_section: str | None = None,
        on_state_changed: Callable[[DocumentTab], None] | None = None,
        on_open_file_request: Callable[[str, bool, str | None], None] | None = None,
        on_always_allow_remote: Callable[[], None] | None = None,
        on_save_as_request: Callable[[DocumentTab], None] | None = None,
        on_comment_added: Callable[[DocumentTab], None] | None = None,
        on_status_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.current_file: str | None = (
            str(Path(file_path).resolve()) if file_path else None
        )
        self.display_name: str = (
            display_name
            or (Path(self.current_file).name if self.current_file else "Untitled.md")
        )
        self.dirty: bool = False
        self.readonly: bool = bool(readonly)
        self.view_mode: str = view_mode if view_mode in ("preview", "split", "edit") else "preview"
        if self.readonly and self.view_mode != "preview":
            self.view_mode = "preview"

        self.theme_id: str = theme_id
        self.zoom_level: float = max(0.5, min(3.0, float(zoom_level)))
        self.allow_remote_images: bool = bool(allow_remote_images)
        self.vim_enabled: bool = bool(vim_enabled)
        self.custom_css: str = custom_css or ""
        self.split_ratio: float = max(0.15, min(0.85, float(split_ratio)))
        self.clipboard_mode: bool = bool(clipboard_mode)

        # Document metadata & analysis
        self.headings: list[HeadingItem] = []
        self.last_render_result: RenderResult | None = None
        self.context_report: DocumentContextReport | None = None
        self.review_session: ReviewSession = ReviewSession()
        self.active_heading_slug: str = ""
        self.scroll_ratio: float = 0.0
        self.cursor_line: int = 1
        self.cursor_col: int = 1

        # Link navigation history
        self.history_back: list[str] = []
        self.history_forward: list[str] = []

        # Watch Mode state
        self.watch_enabled: bool = False
        self.watch_paused: bool = False
        self.follow_new_content: bool = False
        self.revisions: list[tuple[float, str]] = []
        self.revision_count: int = 0
        self.last_updated_ts: float | None = None
        self.pending_updates: int = 0
        self._file_monitor: Gio.FileMonitor | None = None
        self._watch_debounce_id: int = 0
        self._ignore_monitor_until: float = 0.0
        self._last_disk_text: str = ""
        self._remote_img_banner_dismissed: bool = False

        # Diff overlay state
        self.diff_active: bool = False
        self._diff_source_kind: str = ""
        self._diff_mode: str = "unified"
        self._diff_regen_fn: Callable[[str], DiffReport] | None = None

        # Internal guards
        self._suppress_buffer_changed: bool = False
        self._suppress_scroll_sync: bool = False
        self._split_debounce_id: int = 0
        self._expected_base_uri: str = "about:blank"
        self._replace_mode: bool = False
        self._cleaned_up: bool = False

        # Callbacks
        self._on_state_changed = on_state_changed
        self._on_open_file_request = on_open_file_request
        self._on_always_allow_remote = on_always_allow_remote
        self._on_save_as_request = on_save_as_request
        self._on_comment_added = on_comment_added
        self._on_status_message = on_status_message

        # Build UI components
        self._build_infobars()
        self._build_clipboard_bar(clipboard_was_html)
        self._build_watch_bar()
        self._build_diff_bar()
        self._build_search_bar()
        self._build_editor_and_preview()

        # Load initial content
        if initial_text is not None:
            text = initial_text
        elif self.current_file:
            text = self._read_disk_file(self.current_file)
        else:
            text = ""

        self._last_disk_text = text
        self._record_revision(text)
        self._set_buffer_text(text, mark_clean=True)
        self._configure_source_language()
        self.apply_theme(self.theme_id, rerender=False)
        self.set_zoom_level(self.zoom_level)

        self.render_preview(
            initial_scroll_ratio=0.0,
            initial_section=initial_section,
        )
        self.set_view_mode(self.view_mode)

        if initial_line is not None and initial_line > 0:
            self.jump_to_line(initial_line)

        if watch_enabled and self.current_file:
            self.set_watch_enabled(True)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_infobars(self) -> None:
        # 1. Conflict InfoBar (dirty + file changed externally)
        self._conflict_infobar = Gtk.InfoBar()
        self._conflict_infobar.set_message_type(Gtk.MessageType.WARNING)
        self._conflict_label = Gtk.Label(
            label="This file changed on disk while you have unsaved edits."
        )
        self._conflict_label.set_xalign(0.0)
        self._conflict_label.set_line_wrap(True)
        self._conflict_infobar.get_content_area().pack_start(
            self._conflict_label, True, True, 0
        )
        self._conflict_infobar.add_button("Reload from Disk", 1)
        self._conflict_infobar.add_button("View Diff", 2)
        self._conflict_infobar.add_button("Keep My Edits", 3)
        self._conflict_infobar.connect("response", self._on_conflict_response)
        self._conflict_infobar.show_all()
        self._conflict_infobar.set_no_show_all(True)
        self._conflict_infobar.hide()
        self.pack_start(self._conflict_infobar, False, False, 0)

        # 2. Remote Images Blocked InfoBar
        self._remote_img_infobar = Gtk.InfoBar()
        self._remote_img_infobar.set_message_type(Gtk.MessageType.INFO)
        self._remote_img_infobar.set_show_close_button(True)
        self._remote_img_label = Gtk.Label(label="Remote images blocked for privacy.")
        self._remote_img_label.set_xalign(0.0)
        self._remote_img_infobar.get_content_area().pack_start(
            self._remote_img_label, True, True, 0
        )
        self._remote_img_infobar.add_button("Load Remote Images", 1)
        self._remote_img_infobar.add_button("Always Allow", 2)
        self._remote_img_infobar.connect("response", self._on_remote_img_response)
        self._remote_img_infobar.show_all()
        self._remote_img_infobar.set_no_show_all(True)
        self._remote_img_infobar.hide()
        self.pack_start(self._remote_img_infobar, False, False, 0)

        # 3. General Notice / Error InfoBar
        self._notice_infobar = Gtk.InfoBar()
        self._notice_infobar.set_message_type(Gtk.MessageType.INFO)
        self._notice_infobar.set_show_close_button(True)
        self._notice_label = Gtk.Label(label="")
        self._notice_label.set_xalign(0.0)
        self._notice_label.set_line_wrap(True)
        self._notice_infobar.get_content_area().pack_start(
            self._notice_label, True, True, 0
        )
        self._notice_infobar.connect("response", lambda bar, _r: bar.hide())
        self._notice_infobar.show_all()
        self._notice_infobar.set_no_show_all(True)
        self._notice_infobar.hide()
        self.pack_start(self._notice_infobar, False, False, 0)

    def _build_clipboard_bar(self, was_html: bool) -> None:
        self._clipboard_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._clipboard_bar.get_style_context().add_class("search-bar")

        self._clipboard_status_lbl = Gtk.Label(
            label="Clipboard Studio · Converted from HTML"
            if was_html
            else "Clipboard Studio · Plain text"
        )
        self._clipboard_status_lbl.get_style_context().add_class("muted-label")
        self._clipboard_bar.pack_start(self._clipboard_status_lbl, True, True, 0)

        paste_html_btn = Gtk.Button(label="Paste HTML→MD")
        paste_html_btn.connect("clicked", lambda _b: self.paste_from_clipboard(True))
        self._clipboard_bar.pack_start(paste_html_btn, False, False, 0)

        paste_plain_btn = Gtk.Button(label="Paste Plain")
        paste_plain_btn.connect("clicked", lambda _b: self.paste_from_clipboard(False))
        self._clipboard_bar.pack_start(paste_plain_btn, False, False, 0)

        copy_md_btn = Gtk.Button(label="Copy Markdown")
        copy_md_btn.connect("clicked", self._on_copy_markdown_clicked)
        self._clipboard_bar.pack_start(copy_md_btn, False, False, 0)

        save_as_btn = Gtk.Button(label="Save As…")
        save_as_btn.get_style_context().add_class("suggested-action")
        save_as_btn.connect("clicked", self._on_clipboard_save_as)
        self._clipboard_bar.pack_start(save_as_btn, False, False, 0)

        self._clipboard_bar.show_all()
        self._clipboard_bar.set_no_show_all(True)
        if not self.clipboard_mode:
            self._clipboard_bar.hide()
        self.pack_start(self._clipboard_bar, False, False, 0)

    def _build_watch_bar(self) -> None:
        self._watch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._watch_bar.get_style_context().add_class("search-bar")

        self._watch_info_lbl = Gtk.Label(label="● Watching · Rev 1")
        self._watch_info_lbl.get_style_context().add_class("watch-badge")
        self._watch_info_lbl.get_style_context().add_class("active")
        self._watch_bar.pack_start(self._watch_info_lbl, False, False, 0)

        self._watch_pause_btn = Gtk.ToggleButton(label="Pause")
        self._watch_pause_btn.connect("toggled", self._on_watch_pause_toggled)
        self._watch_bar.pack_start(self._watch_pause_btn, False, False, 0)

        self._watch_follow_btn = Gtk.ToggleButton(label="Follow changes")
        self._watch_follow_btn.set_tooltip_text(
            "Automatically scroll to newly changed blocks on reload"
        )
        self._watch_follow_btn.connect("toggled", self._on_watch_follow_toggled)
        self._watch_bar.pack_start(self._watch_follow_btn, False, False, 0)

        self._watch_diff_btn = Gtk.Button(label="Diff Last Revision")
        self._watch_diff_btn.set_sensitive(False)
        self._watch_diff_btn.connect("clicked", lambda _b: self.show_last_revision_diff())
        self._watch_bar.pack_end(self._watch_diff_btn, False, False, 0)

        self._watch_bar.show_all()
        self._watch_bar.set_no_show_all(True)
        self._watch_bar.hide()
        self.pack_start(self._watch_bar, False, False, 0)

    def _build_diff_bar(self) -> None:
        self._diff_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._diff_bar.get_style_context().add_class("search-bar")

        self._diff_summary_lbl = Gtk.Label(label="Diff View")
        self._diff_summary_lbl.set_xalign(0.0)
        self._diff_bar.pack_start(self._diff_summary_lbl, True, True, 0)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        mode_box.get_style_context().add_class("linked")

        self._diff_unified_btn = Gtk.RadioButton.new_with_label(None, "Unified")
        self._diff_unified_btn.set_mode(False)
        self._diff_unified_btn.connect("toggled", self._on_diff_layout_toggled, "unified")
        mode_box.pack_start(self._diff_unified_btn, False, False, 0)

        self._diff_split_btn = Gtk.RadioButton.new_with_label_from_widget(
            self._diff_unified_btn, "Side-by-Side"
        )
        self._diff_split_btn.set_mode(False)
        self._diff_split_btn.connect("toggled", self._on_diff_layout_toggled, "split")
        mode_box.pack_start(self._diff_split_btn, False, False, 0)
        self._diff_bar.pack_start(mode_box, False, False, 0)

        back_btn = Gtk.Button(label="Back to Document")
        back_btn.get_style_context().add_class("suggested-action")
        back_btn.connect("clicked", lambda _b: self.hide_diff_overlay())
        self._diff_bar.pack_end(back_btn, False, False, 0)

        self._diff_bar.show_all()
        self._diff_bar.set_no_show_all(True)
        self._diff_bar.hide()
        self.pack_start(self._diff_bar, False, False, 0)

    def _build_search_bar(self) -> None:
        self._search_revealer = Gtk.Revealer()
        self._search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._search_revealer.set_reveal_child(False)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        container.get_style_context().add_class("search-bar")

        # Row 1: Find
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text("Find in document…")
        self._search_entry.set_width_chars(28)
        self._search_entry.connect("changed", self._on_search_changed)
        self._search_entry.connect("activate", lambda _e: self.search_next())
        self._search_entry.connect("key-press-event", self._on_search_key_press)
        find_row.pack_start(self._search_entry, True, True, 0)

        self._search_match_label = Gtk.Label(label="")
        self._search_match_label.get_style_context().add_class("search-match-label")
        find_row.pack_start(self._search_match_label, False, False, 0)

        prev_btn = Gtk.Button(label="Prev")
        prev_btn.connect("clicked", lambda _b: self.search_prev())
        find_row.pack_start(prev_btn, False, False, 0)

        next_btn = Gtk.Button(label="Next")
        next_btn.connect("clicked", lambda _b: self.search_next())
        find_row.pack_start(next_btn, False, False, 0)

        self._case_btn = Gtk.ToggleButton(label="Aa")
        self._case_btn.set_tooltip_text("Case-sensitive search")
        self._case_btn.connect("toggled", self._on_search_changed)
        find_row.pack_start(self._case_btn, False, False, 0)

        close_btn = Gtk.Button(label="×")
        close_btn.set_tooltip_text("Close search (Esc)")
        close_btn.connect("clicked", lambda _b: self.close_search())
        find_row.pack_end(close_btn, False, False, 0)

        container.pack_start(find_row, False, False, 0)

        # Row 2: Replace (edit/split only)
        self._replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self._replace_entry = Gtk.Entry()
        self._replace_entry.set_placeholder_text("Replace with…")
        self._replace_entry.set_width_chars(28)
        self._replace_entry.connect("activate", lambda _e: self.replace_current())
        self._replace_entry.connect("key-press-event", self._on_search_key_press)
        self._replace_row.pack_start(self._replace_entry, True, True, 0)

        rep_btn = Gtk.Button(label="Replace")
        rep_btn.connect("clicked", lambda _b: self.replace_current())
        self._replace_row.pack_start(rep_btn, False, False, 0)

        rep_all_btn = Gtk.Button(label="Replace All")
        rep_all_btn.connect("clicked", lambda _b: self.replace_all())
        self._replace_row.pack_start(rep_all_btn, False, False, 0)

        self._replace_row.show_all()
        self._replace_row.set_no_show_all(True)
        self._replace_row.hide()
        container.pack_start(self._replace_row, False, False, 0)
        self._search_revealer.add(container)
        self.pack_start(self._search_revealer, False, False, 0)

    def _build_editor_and_preview(self) -> None:
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.connect("notify::position", self._on_paned_position_changed)

        # Source editor (GtkSourceView)
        self.source_buffer = GtkSource.Buffer()
        self.source_buffer.set_highlight_syntax(True)
        self.source_buffer.set_highlight_matching_brackets(True)
        self.source_buffer.connect("changed", self._on_buffer_changed)
        self.source_buffer.connect("mark-set", self._on_cursor_moved)

        self._search_settings = GtkSource.SearchSettings()
        self._search_settings.set_wrap_around(True)
        self._search_context = GtkSource.SearchContext.new(
            self.source_buffer, self._search_settings
        )
        self._search_context.set_highlight(True)
        self._search_context.connect(
            "notify::occurrences-count", self._on_source_search_count_changed
        )

        self.source_view = GtkSource.View.new_with_buffer(self.source_buffer)
        self.source_view.get_style_context().add_class("editor-source")
        self.source_view.set_show_line_numbers(True)
        self.source_view.set_highlight_current_line(True)
        self.source_view.set_auto_indent(True)
        self.source_view.set_indent_on_tab(True)
        self.source_view.set_tab_width(4)
        self.source_view.set_insert_spaces_instead_of_tabs(True)
        self.source_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.source_view.set_left_margin(14)
        self.source_view.set_right_margin(14)
        self.source_view.set_top_margin(12)
        self.source_view.set_bottom_margin(12)
        self.source_view.set_editable(not self.readonly)
        self.source_view.set_cursor_visible(not self.readonly)

        self._source_scrolled = Gtk.ScrolledWindow()
        self._source_scrolled.get_style_context().add_class("source-scrolled")
        self._source_scrolled.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        self._source_scrolled.add(self.source_view)
        self._source_scrolled.show_all()
        self._source_scrolled.set_no_show_all(True)
        self._source_scrolled.get_vadjustment().connect(
            "value-changed", self._on_editor_scrolled
        )

        # WebKit2 Preview with JS Bridge
        self._ucm = WebKit2.UserContentManager()
        self._ucm.register_script_message_handler("mdv")
        self._ucm.connect("script-message-received::mdv", self._on_js_message)

        self.webview = WebKit2.WebView.new_with_user_content_manager(self._ucm)
        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_allow_universal_access_from_file_urls(False)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_enable_page_cache(False)
        if hasattr(settings, "set_enable_write_console_messages_to_stdout"):
            settings.set_enable_write_console_messages_to_stdout(False)

        self.webview.connect("decide-policy", self._on_decide_policy)

        self._find_controller = self.webview.get_find_controller()
        self._find_controller.connect("counted-matches", self._on_webkit_counted_matches)
        self._find_controller.connect(
            "failed-to-find-text", self._on_webkit_failed_to_find
        )

        self._preview_scrolled = Gtk.ScrolledWindow()
        self._preview_scrolled.get_style_context().add_class("preview-scrolled")
        self._preview_scrolled.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        self._preview_scrolled.add(self.webview)
        self._preview_scrolled.show_all()
        self._preview_scrolled.set_no_show_all(True)

        self._paned.pack1(self._source_scrolled, True, False)
        self._paned.pack2(self._preview_scrolled, True, False)
        self.pack_start(self._paned, True, True, 0)

    # ------------------------------------------------------------------
    # Document Text, Loading, and Saving
    # ------------------------------------------------------------------
    def get_text(self) -> str:
        return self.source_buffer.get_text(
            self.source_buffer.get_start_iter(),
            self.source_buffer.get_end_iter(),
            True,
        )

    def _set_buffer_text(self, text: str, *, mark_clean: bool = False) -> None:
        self._suppress_buffer_changed = True
        try:
            self.source_buffer.begin_not_undoable_action()
            self.source_buffer.set_text(text)
            self.source_buffer.end_not_undoable_action()
            if mark_clean:
                self.dirty = False
                self.source_buffer.set_modified(False)
        finally:
            self._suppress_buffer_changed = False

    def _read_disk_file(self, path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.show_notice(f"Could not read {Path(path).name}: {exc}", Gtk.MessageType.ERROR)
            return ""

    def _configure_source_language(self) -> None:
        lm = GtkSource.LanguageManager.get_default()
        lang = None
        if self.current_file:
            lang = lm.guess_language(self.current_file, None)
        if lang is None:
            lang = lm.get_language("markdown")
        self.source_buffer.set_language(lang)

    def _record_revision(self, text: str) -> None:
        if self.revisions and self.revisions[-1][1] == text:
            return
        ts = time.time()
        self.revisions.append((ts, text))
        if len(self.revisions) > _MAX_REVISIONS:
            self.revisions = self.revisions[-_MAX_REVISIONS:]
        self.revision_count += 1
        self.last_updated_ts = ts
        self._update_watch_bar()

    def save(self, target_path: str | None = None) -> bool:
        if self.readonly:
            self.show_notice("Document is open in read-only mode.", Gtk.MessageType.WARNING)
            return False
        dest = target_path or self.current_file
        if not dest:
            return False

        text = self.get_text()
        try:
            self._ignore_monitor_until = time.monotonic() + 0.6
            Path(dest).write_text(text, encoding="utf-8")
        except OSError as exc:
            self.show_notice(f"Failed to save file: {exc}", Gtk.MessageType.ERROR)
            return False

        old_file = self.current_file
        self.current_file = str(Path(dest).resolve())
        self.display_name = Path(self.current_file).name
        self.dirty = False
        self.source_buffer.set_modified(False)
        self._last_disk_text = text
        self._conflict_infobar.hide()
        self._record_revision(text)
        self._configure_source_language()

        if self.clipboard_mode:
            self.clipboard_mode = False
            self._clipboard_bar.hide()

        if self.watch_enabled and old_file != self.current_file:
            self._restart_file_monitor()

        self._notify_state_changed()
        if self._on_status_message:
            self._on_status_message(f"Saved {self.display_name}")
        return True

    def reload_from_disk(self, *, highlight_changes: bool = False) -> None:
        if not self.current_file:
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
            return
        disk_text = self._read_disk_file(self.current_file)
        prev_text = self.get_text()
        changed = compute_changed_lines(prev_text, disk_text) if highlight_changes else None

        self._last_disk_text = disk_text
        self._conflict_infobar.hide()
        self._set_buffer_text(disk_text, mark_clean=True)
        self._record_revision(disk_text)
        self.pending_updates = 0
        self._update_watch_bar()

        if not self.diff_active:
            self.render_preview(
                changed_lines=changed,
                initial_scroll_ratio=self.scroll_ratio,
                follow_changed=highlight_changes and self.follow_new_content,
            )
        self._notify_state_changed()

    # ------------------------------------------------------------------
    # Rendering, Theme, Zoom & View Modes
    # ------------------------------------------------------------------
    def _base_uri(self) -> str:
        if self.current_file:
            parent = Path(self.current_file).parent
            if parent.is_dir():
                uri = parent.as_uri()
                return uri if uri.endswith("/") else uri + "/"
        return "about:blank"

    def render_preview(
        self,
        *,
        changed_lines: set[int] | None = None,
        initial_scroll_ratio: float | None = None,
        initial_section: str | None = None,
        follow_changed: bool = False,
    ) -> None:
        if self._cleaned_up:
            return
        text = self.get_text()
        ratio = self.scroll_ratio if initial_scroll_ratio is None else initial_scroll_ratio

        result = render_document(
            text,
            file_path=self.current_file,
            theme=self.theme_id,
            allow_remote_images=self.allow_remote_images,
            custom_css=self.custom_css,
            changed_lines=changed_lines,
            vim_enabled=self.vim_enabled,
            initial_scroll_ratio=ratio,
            initial_section=initial_section,
            follow_changed=follow_changed,
        )
        self.last_render_result = result
        self.headings = list(result.headings)
        self.context_report = analyze_document(text, file_path=self.current_file)

        if result.blocked_remote_images > 0 and not self._remote_img_banner_dismissed:
            n = result.blocked_remote_images
            noun = "image" if n == 1 else "images"
            self._remote_img_label.set_text(
                f"{n} remote {noun} blocked for privacy."
            )
            self._remote_img_infobar.show_all()
            self._remote_img_infobar.show()
        else:
            self._remote_img_infobar.hide()

        base = self._base_uri()
        self._expected_base_uri = base
        self.webview.load_html(result.html, base)
        self._notify_state_changed()

    def apply_theme(self, theme_id: str, *, rerender: bool = True) -> None:
        self.theme_id = theme_id
        rgba = Gdk.RGBA(*get_webview_bg_rgba(theme_id))
        self.webview.set_background_color(rgba)

        sm = GtkSource.StyleSchemeManager.get_default()
        for sid in get_gtksource_scheme_candidates(theme_id):
            scheme = sm.get_scheme(sid)
            if scheme is not None:
                self.source_buffer.set_style_scheme(scheme)
                break

        if rerender:
            if self.diff_active and self._diff_regen_fn is not None:
                report = self._diff_regen_fn(self._diff_mode)
                self.show_diff_report(
                    report,
                    self._diff_source_kind,
                    mode=self._diff_mode,
                    regenerate_fn=self._diff_regen_fn,
                )
            else:
                self.render_preview(initial_scroll_ratio=self.scroll_ratio)

    def apply_preferences(
        self,
        *,
        vim_enabled: bool,
        allow_remote_images: bool,
        custom_css: str,
    ) -> None:
        changed = (
            self.vim_enabled != vim_enabled
            or self.allow_remote_images != allow_remote_images
            or self.custom_css != custom_css
        )
        self.vim_enabled = vim_enabled
        self.allow_remote_images = allow_remote_images
        self.custom_css = custom_css
        if changed and not self.diff_active:
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)

    def set_zoom_level(self, zoom: float) -> None:
        self.zoom_level = max(0.5, min(3.0, float(zoom)))
        self.webview.set_zoom_level(self.zoom_level)

    def set_view_mode(self, mode: str) -> None:
        if mode not in ("preview", "split", "edit"):
            return
        if self.readonly and mode != "preview":
            mode = "preview"
        self.view_mode = mode

        if self.diff_active:
            self._source_scrolled.hide()
            self._preview_scrolled.show_all()
            self._preview_scrolled.show()
            return

        if mode == "preview":
            self._source_scrolled.hide()
            self._preview_scrolled.show_all()
            self._preview_scrolled.show()
            self._replace_row.hide()
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
        elif mode == "edit":
            self._preview_scrolled.hide()
            self._source_scrolled.show_all()
            self._source_scrolled.show()
            if self._replace_mode and not self.readonly:
                self._replace_row.show_all()
                self._replace_row.show()
            self.source_view.grab_focus()
        elif mode == "split":
            self._source_scrolled.show_all()
            self._source_scrolled.show()
            self._preview_scrolled.show_all()
            self._preview_scrolled.show()
            if self._replace_mode and not self.readonly:
                self._replace_row.show_all()
                self._replace_row.show()
            alloc = self._paned.get_allocation()
            if alloc.width > 100:
                self._paned.set_position(int(alloc.width * self.split_ratio))
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)

        if self._search_revealer.get_reveal_child():
            self._run_search_query()
        self._notify_state_changed()

    def _on_paned_position_changed(self, paned: Gtk.Paned, _pspec: object) -> None:
        if self.view_mode == "split":
            alloc = paned.get_allocation()
            if alloc.width > 100:
                ratio = paned.get_position() / float(alloc.width)
                self.split_ratio = max(0.15, min(0.85, ratio))

    # ------------------------------------------------------------------
    # Editor Signals & Split Sync
    # ------------------------------------------------------------------
    def _on_buffer_changed(self, _buf: GtkSource.Buffer) -> None:
        if self._suppress_buffer_changed:
            return
        self.dirty = True
        self._notify_state_changed()

        if self.view_mode == "split" and not self.diff_active:
            if self._split_debounce_id:
                GLib.source_remove(self._split_debounce_id)
            self._split_debounce_id = GLib.timeout_add(
                _SPLIT_DEBOUNCE_MS, self._flush_split_preview
            )

    def _flush_split_preview(self) -> bool:
        self._split_debounce_id = 0
        if not self._cleaned_up and self.view_mode == "split" and not self.diff_active:
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
        return False

    def _on_cursor_moved(
        self, buf: GtkSource.Buffer, _location: Gtk.TextIter, mark: Gtk.TextMark
    ) -> None:
        if mark != buf.get_insert():
            return
        it = buf.get_iter_at_mark(mark)
        self.cursor_line = it.get_line() + 1
        self.cursor_col = it.get_line_offset() + 1
        self._notify_state_changed()

    def _on_editor_scrolled(self, adj: Gtk.Adjustment) -> None:
        if self._suppress_scroll_sync or self.view_mode != "split" or self.diff_active:
            return
        upper = adj.get_upper() - adj.get_page_size()
        if upper <= 0:
            return
        ratio = max(0.0, min(1.0, adj.get_value() / upper))
        self.scroll_ratio = ratio
        self._eval_js(f"window.__mdv && window.__mdv.scrollToRatio({ratio:.4f});")

    # ------------------------------------------------------------------
    # Safe JS Evaluator & Bridge
    # ------------------------------------------------------------------
    def _eval_js(self, script: str) -> None:
        if self._cleaned_up:
            return
        try:
            if hasattr(self.webview, "evaluate_javascript"):
                self.webview.evaluate_javascript(script, -1, None, None, None, None, None)
            elif hasattr(self.webview, "run_javascript"):
                self.webview.run_javascript(script, None, None, None)
        except Exception:
            pass

    def scroll_to_slug(self, slug: str) -> None:
        if not slug:
            return
        escaped = json.dumps(slug)
        self._eval_js(f"window.__mdv && window.__mdv.scrollToSlug({escaped});")

    def jump_to_line(self, line_1based: int) -> None:
        line_idx = max(0, int(line_1based) - 1)
        total = max(1, self.source_buffer.get_line_count())
        line_idx = min(line_idx, total - 1)
        it = self.source_buffer.get_iter_at_line(line_idx)
        self.source_buffer.place_cursor(it)
        self.source_view.scroll_to_iter(it, 0.15, True, 0.0, 0.2)

    def _on_js_message(
        self, _ucm: WebKit2.UserContentManager, js_result: object
    ) -> None:
        if self._cleaned_up:
            return
        try:
            if hasattr(js_result, "get_js_value"):
                js_val = js_result.get_js_value()
                raw = js_val.to_string() if js_val is not None else ""
            elif hasattr(js_result, "get_value"):
                js_val = js_result.get_value()
                raw = js_val.to_string() if js_val is not None else ""
            else:
                return
            payload = json.loads(raw)
        except Exception:
            return

        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")

        if msg_type == "scroll-update":
            try:
                self.scroll_ratio = max(0.0, min(1.0, float(payload.get("ratio", 0.0))))
            except (TypeError, ValueError):
                pass
            slug = str(payload.get("activeSlug") or "")
            if slug != self.active_heading_slug:
                self.active_heading_slug = slug
                self._notify_state_changed()

        elif msg_type == "copy-text":
            text = str(payload.get("text") or "")
            if text:
                write_clipboard_text(text)
                if self._on_status_message:
                    self._on_status_message("Copied to clipboard")

        elif msg_type == "copy-heading":
            slug = str(payload.get("slug") or "")
            if slug:
                prefix = Path(self.current_file).name if self.current_file else ""
                ref = f"{prefix}#{slug}" if prefix else f"#{slug}"
                write_clipboard_text(ref)
                if self._on_status_message:
                    self._on_status_message(f"Copied {ref}")

        elif msg_type == "checkbox-toggle":
            self._handle_checkbox_toggle(payload)

        elif msg_type == "add-comment":
            heading = str(payload.get("heading") or "Document")
            quote = str(payload.get("quote") or "")
            self._prompt_add_comment(heading, quote)

        elif msg_type == "open-search":
            self.open_search(replace=False)

    def _handle_checkbox_toggle(self, payload: dict[str, object]) -> None:
        if self.readonly:
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
            return
        try:
            task_index = int(payload.get("index", 0))
        except (TypeError, ValueError):
            task_index = 0
        raw_line = payload.get("line")
        line_hint = int(raw_line) if isinstance(raw_line, int) else None
        checked = bool(payload.get("checked", False))

        old_text = self.get_text()
        new_text = toggle_task_checkbox_in_text(
            old_text, task_index, line_hint, checked
        )
        if new_text == old_text:
            return

        was_clean = not self.dirty
        self._set_buffer_text(new_text, mark_clean=False)

        if was_clean and self.current_file:
            try:
                self._ignore_monitor_until = time.monotonic() + 0.6
                Path(self.current_file).write_text(new_text, encoding="utf-8")
                self._last_disk_text = new_text
                self.dirty = False
                self.source_buffer.set_modified(False)
                self._record_revision(new_text)
            except OSError:
                self.dirty = True
        else:
            self.dirty = True

        self.render_preview(initial_scroll_ratio=self.scroll_ratio)
        self._notify_state_changed()

    def _prompt_add_comment(self, heading: str, quote: str) -> None:
        toplevel = self.get_toplevel()
        parent = toplevel if isinstance(toplevel, Gtk.Window) else None
        dialog = CommentEditorDialog(
            parent,
            heading=heading,
            quote=quote,
            title="Add Review Comment",
        )
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            feedback = dialog.get_feedback()
            if feedback:
                self.review_session.add(heading=heading, quote=quote, feedback=feedback)
                if self._on_comment_added:
                    self._on_comment_added(self)
                self._notify_state_changed()
        dialog.destroy()

    def edit_review_comment(self, comment: ReviewComment) -> None:
        toplevel = self.get_toplevel()
        parent = toplevel if isinstance(toplevel, Gtk.Window) else None
        dialog = CommentEditorDialog(
            parent,
            heading=comment.heading,
            quote=comment.quote,
            initial_feedback=comment.feedback,
            title="Edit Review Comment",
        )
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            feedback = dialog.get_feedback()
            if feedback:
                self.review_session.update(comment.id, feedback=feedback)
                self._notify_state_changed()
        dialog.destroy()

    def delete_review_comment(self, comment_id: str) -> None:
        if self.review_session.delete(comment_id):
            self._notify_state_changed()

    # ------------------------------------------------------------------
    # Navigation Policy & History
    # ------------------------------------------------------------------
    def _on_decide_policy(
        self,
        _webview: WebKit2.WebView,
        decision: WebKit2.PolicyDecision,
        decision_type: WebKit2.PolicyDecisionType,
    ) -> bool:
        if decision_type not in (
            WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
            WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION,
        ):
            return False

        nav_action = decision.get_navigation_action()
        req = nav_action.get_request()
        uri = req.get_uri() if req else ""
        nav_type = nav_action.get_navigation_type()

        # Allow our own load_html() initial navigation
        if nav_type == WebKit2.NavigationType.OTHER and (
            not uri
            or uri == "about:blank"
            or uri == self._expected_base_uri
        ):
            decision.use()
            return True

        parsed = urlparse(uri)

        # Same-document #fragment navigation
        base_without_frag = uri.split("#", 1)[0]
        if parsed.fragment and base_without_frag in (
            "",
            "about:blank",
            self._expected_base_uri,
            self._expected_base_uri.rstrip("/"),
        ):
            decision.ignore()
            self.scroll_to_slug(unquote(parsed.fragment))
            return True

        # Local file:// links
        if parsed.scheme == "file":
            decision.ignore()
            local_path = _file_uri_to_path(uri.split("#", 1)[0])
            target = Path(local_path)
            if not target.is_file() and self.current_file:
                rel_candidate = Path(self.current_file).parent / local_path.lstrip("/")
                if rel_candidate.is_file():
                    target = rel_candidate

            if target.is_file() and target.suffix.lower() in _SUPPORTED_LOCAL_SUFFIXES:
                target_str = str(target.resolve())
                frag = unquote(parsed.fragment) if parsed.fragment else None
                if self.current_file and target_str == self.current_file and frag:
                    self.scroll_to_slug(frag)
                    return True

                open_new_tab = (
                    decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION
                    or nav_action.get_mouse_button() == 2
                    or bool(nav_action.get_modifiers() & Gdk.ModifierType.CONTROL_MASK)
                )
                if open_new_tab and self._on_open_file_request:
                    self._on_open_file_request(target_str, True, frag)
                else:
                    self.navigate_to_file(target_str, section=frag)
            return True

        # External http / https / mailto links
        if parsed.scheme in ("http", "https", "mailto"):
            decision.ignore()
            toplevel = self.get_toplevel()
            win = toplevel if isinstance(toplevel, Gtk.Window) else None
            try:
                Gtk.show_uri_on_window(win, uri, Gdk.CURRENT_TIME)
            except Exception:
                pass
            return True

        # Block javascript:, vbscript:, data:, and everything else
        decision.ignore()
        return True

    def navigate_to_file(
        self,
        target_path: str,
        *,
        section: str | None = None,
        push_history: bool = True,
    ) -> None:
        resolved = str(Path(target_path).resolve())
        if not Path(resolved).is_file():
            self.show_notice(f"File not found: {target_path}", Gtk.MessageType.ERROR)
            return
        if push_history and self.current_file and self.current_file != resolved:
            self.history_back.append(self.current_file)
            self.history_forward.clear()

        self.current_file = resolved
        self.display_name = Path(resolved).name
        self.diff_active = False
        self._diff_bar.hide()
        self.scroll_ratio = 0.0
        self._remote_img_banner_dismissed = False

        text = self._read_disk_file(resolved)
        self._last_disk_text = text
        self.revisions.clear()
        self.revision_count = 0
        self._record_revision(text)
        self._set_buffer_text(text, mark_clean=True)
        self._configure_source_language()
        if self.watch_enabled:
            self._restart_file_monitor()
        self.render_preview(initial_scroll_ratio=0.0, initial_section=section)
        self._notify_state_changed()

    def can_go_back(self) -> bool:
        return bool(self.history_back)

    def can_go_forward(self) -> bool:
        return bool(self.history_forward)

    def go_back(self) -> bool:
        if not self.history_back:
            return False
        prev = self.history_back.pop()
        if self.current_file:
            self.history_forward.append(self.current_file)
        self.navigate_to_file(prev, push_history=False)
        return True

    def go_forward(self) -> bool:
        if not self.history_forward:
            return False
        nxt = self.history_forward.pop()
        if self.current_file:
            self.history_back.append(self.current_file)
        self.navigate_to_file(nxt, push_history=False)
        return True

    # ------------------------------------------------------------------
    # Agent Watch Mode
    # ------------------------------------------------------------------
    def set_watch_enabled(self, enabled: bool) -> None:
        if enabled and not self.current_file:
            self.show_notice(
                "Save the document to a file before enabling Watch Mode.",
                Gtk.MessageType.INFO,
            )
            self.watch_enabled = False
            self._watch_bar.hide()
            self._notify_state_changed()
            return

        self.watch_enabled = bool(enabled)
        if self.watch_enabled:
            self.watch_paused = False
            self.pending_updates = 0
            self._watch_pause_btn.set_active(False)
            self._restart_file_monitor()
            self._update_watch_bar()
            self._watch_bar.show_all()
            self._watch_bar.show()
        else:
            self._stop_file_monitor()
            self.pending_updates = 0
            self._watch_bar.hide()

        self._notify_state_changed()

    def _restart_file_monitor(self) -> None:
        self._stop_file_monitor()
        if not self.current_file:
            return
        try:
            gfile = Gio.File.new_for_path(self.current_file)
            self._file_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._file_monitor.connect("changed", self._on_file_monitor_event)
        except Exception as exc:
            self.show_notice(f"Watch Mode unavailable: {exc}", Gtk.MessageType.WARNING)
            self.watch_enabled = False
            self._watch_bar.hide()

    def _stop_file_monitor(self) -> None:
        if self._watch_debounce_id:
            GLib.source_remove(self._watch_debounce_id)
            self._watch_debounce_id = 0
        if self._file_monitor is not None:
            try:
                self._file_monitor.cancel()
            except Exception:
                pass
            self._file_monitor = None

    def _on_file_monitor_event(
        self,
        _monitor: Gio.FileMonitor,
        _file: Gio.File,
        _other_file: Gio.File | None,
        event_type: Gio.FileMonitorEvent,
    ) -> None:
        if self._cleaned_up or not self.watch_enabled:
            return
        if time.monotonic() < self._ignore_monitor_until:
            return
        if event_type not in (
            Gio.FileMonitorEvent.CHANGED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            return
        if self._watch_debounce_id:
            GLib.source_remove(self._watch_debounce_id)
        self._watch_debounce_id = GLib.timeout_add(
            _WATCH_DEBOUNCE_MS, self._handle_watch_debounced
        )

    def _handle_watch_debounced(self) -> bool:
        self._watch_debounce_id = 0
        if self._cleaned_up or not self.watch_enabled or not self.current_file:
            return False
        path = Path(self.current_file)
        if not path.is_file():
            return False
        try:
            disk_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False

        if disk_text == self._last_disk_text:
            return False

        if self.watch_paused:
            self.pending_updates += 1
            self._update_watch_bar()
            self._notify_state_changed()
            return False

        if self.dirty:
            self._conflict_infobar.show_all()
            self._conflict_infobar.show()
            return False

        prev_text = self.get_text()
        changed = compute_changed_lines(prev_text, disk_text)
        self._last_disk_text = disk_text
        self._set_buffer_text(disk_text, mark_clean=True)
        self._record_revision(disk_text)
        self.pending_updates = 0
        self._update_watch_bar()

        if not self.diff_active:
            self.render_preview(
                changed_lines=changed,
                initial_scroll_ratio=self.scroll_ratio,
                follow_changed=self.follow_new_content,
            )
        self._notify_state_changed()
        return False

    def _update_watch_bar(self) -> None:
        rev_num = max(1, self.revision_count)
        if self.watch_paused:
            suffix = f" ({self.pending_updates} pending)" if self.pending_updates else ""
            self._watch_info_lbl.set_text(f"⏸ Paused · Rev {rev_num}{suffix}")
            self._watch_info_lbl.get_style_context().remove_class("active")
            self._watch_pause_btn.set_label(
                f"Resume ({self.pending_updates})" if self.pending_updates else "Resume"
            )
        else:
            self._watch_info_lbl.set_text(f"● Watching · Rev {rev_num}")
            self._watch_info_lbl.get_style_context().add_class("active")
            self._watch_pause_btn.set_label("Pause")
        self._watch_diff_btn.set_sensitive(len(self.revisions) >= 2)

    def _on_watch_pause_toggled(self, btn: Gtk.ToggleButton) -> None:
        self.watch_paused = btn.get_active()
        if not self.watch_paused and self.pending_updates > 0:
            self.reload_from_disk(highlight_changes=True)
        else:
            self._update_watch_bar()
            self._notify_state_changed()

    def _on_watch_follow_toggled(self, btn: Gtk.ToggleButton) -> None:
        self.follow_new_content = btn.get_active()

    # ------------------------------------------------------------------
    # Diff Overlay
    # ------------------------------------------------------------------
    def show_diff_report(
        self,
        report: DiffReport,
        source_kind: str = "diff",
        *,
        mode: str = "unified",
        regenerate_fn: Callable[[str], DiffReport] | None = None,
    ) -> None:
        if report.error:
            self.show_notice(report.error, Gtk.MessageType.WARNING)
            return

        self.diff_active = True
        self._diff_source_kind = source_kind
        self._diff_mode = mode if mode in ("unified", "split") else "unified"
        self._diff_regen_fn = regenerate_fn

        self._diff_summary_lbl.set_text(
            f"{report.old_label} → {report.new_label}   (+{report.additions} / -{report.deletions})"
        )
        if self._diff_mode == "split":
            self._diff_split_btn.set_active(True)
        else:
            self._diff_unified_btn.set_active(True)
        self._diff_unified_btn.set_sensitive(regenerate_fn is not None)
        self._diff_split_btn.set_sensitive(regenerate_fn is not None)

        self._diff_bar.show_all()
        self._diff_bar.show()
        self._source_scrolled.hide()
        self._preview_scrolled.show_all()
        self._preview_scrolled.show()

        result = render_document(
            "",
            file_path=self.current_file,
            theme=self.theme_id,
            allow_remote_images=False,
            custom_css=self.custom_css,
            body_html_override=report.html,
            vim_enabled=self.vim_enabled,
        )
        self._expected_base_uri = "about:blank"
        self.webview.load_html(result.html, "about:blank")
        self._notify_state_changed()

    def show_last_revision_diff(self, mode: str = "unified") -> None:
        if len(self.revisions) < 2:
            self.show_notice(
                "Need at least two revisions to compare.", Gtk.MessageType.INFO
            )
            return
        old_text = self.revisions[-2][1]
        new_text = self.revisions[-1][1]
        rev_new = self.revision_count
        rev_old = max(1, rev_new - 1)

        def _regen(m: str) -> DiffReport:
            return diff_texts(
                old_text,
                new_text,
                old_label=f"Rev {rev_old}",
                new_label=f"Rev {rev_new}",
                mode=m,
            )

        self.show_diff_report(_regen(mode), "revision", mode=mode, regenerate_fn=_regen)

    def hide_diff_overlay(self) -> None:
        if not self.diff_active:
            return
        self.diff_active = False
        self._diff_regen_fn = None
        self._diff_bar.hide()
        self.set_view_mode(self.view_mode)

    def _on_diff_layout_toggled(self, btn: Gtk.ToggleButton, mode: str) -> None:
        if not btn.get_active() or not self.diff_active:
            return
        if mode == self._diff_mode or self._diff_regen_fn is None:
            return
        report = self._diff_regen_fn(mode)
        self.show_diff_report(
            report,
            self._diff_source_kind,
            mode=mode,
            regenerate_fn=self._diff_regen_fn,
        )

    # ------------------------------------------------------------------
    # InfoBar & Clipboard Bar Handlers
    # ------------------------------------------------------------------
    def show_notice(
        self, message: str, msg_type: Gtk.MessageType = Gtk.MessageType.INFO
    ) -> None:
        self._notice_infobar.set_message_type(msg_type)
        self._notice_label.set_text(message)
        self._notice_infobar.show_all()
        self._notice_infobar.show()

    def _on_conflict_response(self, bar: Gtk.InfoBar, response_id: int) -> None:
        if response_id == 1:  # Reload from Disk
            bar.hide()
            self.reload_from_disk(highlight_changes=True)
        elif response_id == 2:  # View Diff (Disk vs Buffer)
            if self.current_file:
                disk_text = self._read_disk_file(self.current_file)
                buf_text = self.get_text()

                def _regen(m: str) -> DiffReport:
                    return diff_texts(
                        disk_text,
                        buf_text,
                        old_label="On Disk",
                        new_label="Your Edits",
                        mode=m,
                    )

                self.show_diff_report(
                    _regen("unified"), "conflict", mode="unified", regenerate_fn=_regen
                )
        elif response_id == 3:  # Keep My Edits
            bar.hide()
            if self.current_file:
                self._last_disk_text = self._read_disk_file(self.current_file)

    def _on_remote_img_response(self, bar: Gtk.InfoBar, response_id: int) -> None:
        bar.hide()
        if response_id == 1:  # Load Remote Images (this tab)
            self.allow_remote_images = True
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
        elif response_id == 2:  # Always Allow
            self.allow_remote_images = True
            if self._on_always_allow_remote:
                self._on_always_allow_remote()
            self.render_preview(initial_scroll_ratio=self.scroll_ratio)
        else:
            self._remote_img_banner_dismissed = True

    def paste_from_clipboard(self, prefer_html_convert: bool = True) -> None:
        payload = read_clipboard_smart(prefer_html_convert=prefer_html_convert)
        if not payload.text:
            self.show_notice("Clipboard is empty.", Gtk.MessageType.INFO)
            return
        self._set_buffer_text(payload.text, mark_clean=False)
        self.dirty = True
        self._record_revision(payload.text)
        self._clipboard_status_lbl.set_text(
            "Clipboard Studio · Converted from HTML"
            if payload.was_html
            else "Clipboard Studio · Plain text"
        )
        self.render_preview(initial_scroll_ratio=0.0)
        self._notify_state_changed()

    def _on_copy_markdown_clicked(self, _btn: Gtk.Button) -> None:
        write_clipboard_text(self.get_text())
        if self._on_status_message:
            self._on_status_message("Copied Markdown to clipboard")

    def _on_clipboard_save_as(self, _btn: Gtk.Button) -> None:
        if self._on_save_as_request:
            self._on_save_as_request(self)

    # ------------------------------------------------------------------
    # Inline Search & Replace
    # ------------------------------------------------------------------
    def open_search(self, *, replace: bool = False) -> None:
        self._replace_mode = bool(replace)
        self._search_revealer.set_reveal_child(True)
        if self._replace_mode and self.view_mode != "preview" and not self.readonly:
            self._replace_row.show_all()
            self._replace_row.show()
        else:
            self._replace_row.hide()
        self._search_entry.grab_focus()
        self._search_entry.select_region(0, -1)
        self._run_search_query()

    def close_search(self) -> None:
        self._search_revealer.set_reveal_child(False)
        self._search_match_label.set_text("")
        self._find_controller.search_finish()
        self._search_settings.set_search_text(None)
        if self.view_mode == "edit":
            self.source_view.grab_focus()
        else:
            self.webview.grab_focus()

    def is_search_open(self) -> bool:
        return bool(self._search_revealer.get_reveal_child())

    def _on_search_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.close_search()
            return True
        return False

    def _on_search_changed(self, *_args: object) -> None:
        self._run_search_query()

    def _run_search_query(self) -> None:
        query = self._search_entry.get_text()
        case_sensitive = self._case_btn.get_active()

        if not query:
            self._search_match_label.set_text("")
            self._find_controller.search_finish()
            self._search_settings.set_search_text(None)
            return

        if self.view_mode == "preview" or self.diff_active:
            opts = WebKit2.FindOptions.WRAP_AROUND
            if not case_sensitive:
                opts |= WebKit2.FindOptions.CASE_INSENSITIVE
            self._find_controller.search(query, opts, 1000)
            self._find_controller.count_matches(query, opts, 1000)
        else:
            self._search_settings.set_case_sensitive(case_sensitive)
            self._search_settings.set_search_text(query)
            self._search_source(forward=True, from_start_of_selection=True)

    def search_next(self) -> None:
        query = self._search_entry.get_text()
        if not query:
            return
        if self.view_mode == "preview" or self.diff_active:
            self._find_controller.search_next()
        else:
            self._search_source(forward=True, from_start_of_selection=False)

    def search_prev(self) -> None:
        query = self._search_entry.get_text()
        if not query:
            return
        if self.view_mode == "preview" or self.diff_active:
            self._find_controller.search_previous()
        else:
            self._search_source(forward=False, from_start_of_selection=False)

    def _search_source(
        self, *, forward: bool, from_start_of_selection: bool
    ) -> bool:
        buf = self.source_buffer
        bounds = buf.get_selection_bounds()
        if bounds:
            start_it = bounds[0] if (from_start_of_selection or not forward) else bounds[1]
        else:
            start_it = buf.get_iter_at_mark(buf.get_insert())

        res = (
            self._search_context.forward(start_it)
            if forward
            else self._search_context.backward(start_it)
        )
        found = bool(res[0])
        if found:
            match_start, match_end = res[1], res[2]
            buf.select_range(match_start, match_end)
            self.source_view.scroll_to_iter(match_start, 0.15, False, 0.0, 0.5)
        return found

    def replace_current(self) -> None:
        if self.readonly or self.view_mode == "preview":
            return
        bounds = self.source_buffer.get_selection_bounds()
        if not bounds:
            if not self._search_source(forward=True, from_start_of_selection=True):
                return
            bounds = self.source_buffer.get_selection_bounds()
        if not bounds:
            return
        replacement = self._replace_entry.get_text()
        try:
            self._search_context.replace(bounds[0], bounds[1], replacement, -1)
        except Exception:
            pass
        self.search_next()

    def replace_all(self) -> None:
        if self.readonly or self.view_mode == "preview":
            return
        replacement = self._replace_entry.get_text()
        try:
            self._search_context.replace_all(replacement, -1)
        except Exception:
            pass

    def _on_webkit_counted_matches(
        self, _controller: WebKit2.FindController, count: int
    ) -> None:
        if count == 0:
            self._search_match_label.set_text("No matches")
        elif count == 1:
            self._search_match_label.set_text("1 match")
        else:
            self._search_match_label.set_text(f"{count} matches")

    def _on_webkit_failed_to_find(self, _controller: WebKit2.FindController) -> None:
        self._search_match_label.set_text("No matches")

    def _on_source_search_count_changed(
        self, ctx: GtkSource.SearchContext, _pspec: object
    ) -> None:
        if self.view_mode == "preview":
            return
        count = ctx.get_occurrences_count()
        if count < 0:
            return
        if count == 0:
            self._search_match_label.set_text("No matches")
        elif count == 1:
            self._search_match_label.set_text("1 match")
        else:
            self._search_match_label.set_text(f"{count} matches")

    # ------------------------------------------------------------------
    # Print & Cleanup
    # ------------------------------------------------------------------
    def print_document(self, parent_window: Gtk.Window | None = None) -> None:
        op = WebKit2.PrintOperation.new(self.webview)
        op.run_dialog(parent_window)

    def get_file_kind(self) -> str:
        if self.last_render_result is not None:
            return self.last_render_result.file_kind
        return detect_file_kind(self.current_file)

    def _notify_state_changed(self) -> None:
        if not self._cleaned_up and self._on_state_changed:
            self._on_state_changed(self)

    def cleanup(self) -> None:
        """Stop file monitors and cancel pending GLib timers before tab destruction."""
        self._cleaned_up = True
        self._stop_file_monitor()
        if self._split_debounce_id:
            GLib.source_remove(self._split_debounce_id)
            self._split_debounce_id = 0
