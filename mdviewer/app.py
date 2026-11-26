"""Main GTK3 Application, multi-tab window, HeaderBar, StatusBar, and shortcuts for Markveil."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkSource", "300")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from mdviewer.cli import LaunchOptions  # noqa: E402
from mdviewer.clipboard import read_clipboard_smart, write_clipboard_text  # noqa: E402
from mdviewer.config import (  # noqa: E402
    AppConfig,
    add_recent_file,
    load_config,
    save_config,
)
from mdviewer.context_inspector import SectionStats  # noqa: E402
from mdviewer.dialogs import (  # noqa: E402
    AskAgentDialog,
    DiffPickerDialog,
    PreferencesDialog,
    ShortcutsDialog,
    WelcomeView,
)
from mdviewer.diff_engine import diff_files, diff_git_head  # noqa: E402
from mdviewer.gtk_styles import build_gtk_css  # noqa: E402
from mdviewer.markdown_engine import HeadingItem  # noqa: E402
from mdviewer.review_comments import ReviewComment  # noqa: E402
from mdviewer.sidebar import DocumentSidebar  # noqa: E402
from mdviewer.tab import DocumentTab, _record_clipboard_history  # noqa: E402
from mdviewer.themes import (  # noqa: E402
    THEMES,
    THEME_ORDER,
    resolve_theme_id,
)

_VIEW_MODE_CYCLE = ("preview", "split", "edit")
_CONFIG_SAVE_DEBOUNCE_MS = 300


def _detect_system_dark() -> bool:
    """Detect dark desktop preference via GNOME color-scheme, GTK settings, or theme luminance."""
    try:
        schema_source = Gio.SettingsSchemaSource.get_default()
        schema = (
            schema_source.lookup("org.gnome.desktop.interface", True)
            if schema_source is not None
            else None
        )
        if schema is not None and schema.has_key("color-scheme"):
            iface = Gio.Settings.new("org.gnome.desktop.interface")
            scheme = str(iface.get_string("color-scheme") or "").lower()
            if "dark" in scheme:
                return True
            if "light" in scheme:
                return False
    except Exception:
        pass

    settings = Gtk.Settings.get_default()
    if settings is not None:
        try:
            if settings.get_property("gtk-application-prefer-dark-theme"):
                return True
            theme_name = str(settings.get_property("gtk-theme-name") or "").lower()
            if "dark" in theme_name:
                return True
        except Exception:
            pass

    # Fallback: measure actual GTK theme background luminance (catches themes like Obsidian-Glass, Dracula, Nord)
    probe: Gtk.Window | None = None
    try:
        probe = Gtk.Window()
        ok, rgba = probe.get_style_context().lookup_color("theme_bg_color")
        if ok:
            luminance = 0.2126 * rgba.red + 0.7152 * rgba.green + 0.0722 * rgba.blue
            return luminance < 0.5
    except Exception:
        pass
    finally:
        if probe is not None:
            probe.destroy()
    return False


def _read_custom_css(path_str: str) -> str:
    if not path_str or not path_str.strip():
        return ""
    p = Path(path_str).expanduser()
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


class MarkdownViewerApp(Gtk.Application):
    """Multi-tab native GTK3 + WebKit2 Markdown Studio application."""

    def __init__(
        self,
        launch_options: LaunchOptions | None = None,
        *,
        application_id: str | None = "dev.abby.markveil",
    ) -> None:
        super().__init__(
            application_id=application_id,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.launch_options: LaunchOptions = launch_options or LaunchOptions(files=[])
        self.config: AppConfig = load_config()
        if self.launch_options.theme:
            self.config.theme = self.launch_options.theme

        self.quick_mode: bool = bool(self.launch_options.quick)
        self.system_dark: bool = False
        self.resolved_theme: str = "folio"
        self.custom_css: str = _read_custom_css(self.config.custom_css_path)

        self.window: Gtk.ApplicationWindow | None = None
        self.notebook: Gtk.Notebook | None = None
        self.sidebar: DocumentSidebar | None = None
        self.welcome_view: WelcomeView | None = None

        self._css_provider: Gtk.CssProvider | None = None
        self._suppress_ui_signals: bool = False
        self._status_toast_timer: int = 0
        self._config_save_timer: int = 0
        self._config_dirty: bool = False
        self._pending_clipboard_tab: DocumentTab | None = None
        self._pending_clipboard_attempts: int = 0
        self._pending_clipboard_timer: int = 0
        self._pending_clipboard_focus_hid: int = 0
        self._tab_labels: dict[DocumentTab, list[tuple[Gtk.Label, Gtk.Label]]] = {}
        self._document_rows: dict[DocumentTab, Gtk.ListBoxRow] = {}

    # ------------------------------------------------------------------
    # Gtk.Application Lifecycle
    # ------------------------------------------------------------------
    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        self.system_dark = _detect_system_dark()
        self.resolved_theme = resolve_theme_id(
            self.config.theme, system_dark=self.system_dark
        )

        self._build_window()
        self._apply_theme_css()

        assert self.window is not None
        self.window.show_all()
        self._process_launch_options()
        self._sync_chrome_visibility()
        self._sync_ui_for_active_tab()

    # ------------------------------------------------------------------
    # Window & Chrome Construction
    # ------------------------------------------------------------------
    def _build_window(self) -> None:
        win = Gtk.ApplicationWindow(application=self)
        win.get_style_context().add_class("markveil-window")
        win.set_default_size(self.config.window_width, self.config.window_height)
        win.set_position(Gtk.WindowPosition.CENTER)
        icon_candidates = (
            Path(__file__).resolve().parent.parent / "assets" / "icons" / "markveil-128.png",
            Path(__file__).resolve().parent.parent / "assets" / "icons" / "markveil.svg",
        )
        icon_loaded = False
        for icon_path in icon_candidates:
            if icon_path.is_file():
                try:
                    Gtk.Window.set_default_icon_from_file(str(icon_path))
                    win.set_icon_from_file(str(icon_path))
                    icon_loaded = True
                    break
                except Exception:
                    continue
        if not icon_loaded:
            win.set_icon_name("markveil")
        win.connect("delete-event", self._on_window_delete)
        win.connect("key-press-event", self._on_key_press)
        win.connect("configure-event", self._on_window_configure)

        # Drag-and-drop URIs onto window
        win.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        win.connect("drag-data-received", self._on_drag_data_received)

        self.window = win

        # HeaderBar
        self._build_headerbar(win)

        # Root container
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("main-root")

        # Main paned: Sidebar (left) + Content Stack (right)
        self._main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._main_paned.set_position(self.config.sidebar_width)
        self._main_paned.connect("notify::position", self._on_sidebar_width_changed)

        initial_sidebar_tab = self.config.sidebar_tab
        self.sidebar = DocumentSidebar(
            on_heading_clicked=self._on_sidebar_heading_clicked,
            on_section_clicked=self._on_sidebar_section_clicked,
            on_add_comment=self.action_add_comment,
            on_comment_clicked=self._on_sidebar_comment_clicked,
            on_edit_comment=self._on_sidebar_edit_comment,
            on_delete_comment=self._on_sidebar_delete_comment,
            on_comments_exported=self._on_sidebar_comments_exported,
            on_open_agentic_file=self.open_file,
            on_tab_changed=self._on_sidebar_tab_changed,
            on_status_message=self.show_status_toast,
        )
        self.sidebar.show_all()
        self.sidebar.set_active_tab(initial_sidebar_tab)
        self.sidebar.set_no_show_all(True)
        self.sidebar.hide()

        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        self.welcome_view = WelcomeView(
            recent_files=self.config.recent_files,
            on_open_file=self.action_open_file,
            on_new_document=self.action_new_tab,
            on_open_clipboard=self.action_open_clipboard,
            on_open_clipboard_entry=self._open_clipboard_history_entry,
            on_open_recent=self.open_file,
        )
        self._content_stack.add_named(self.welcome_view, "welcome")

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.set_show_tabs(False)
        self.notebook.connect_after("switch-page", self._on_notebook_switch_page)
        self.notebook.connect("page-reordered", lambda *_: self.sidebar.documents.invalidate_sort())
        self.sidebar.documents.set_sort_func(self._compare_document_rows)
        self.sidebar.documents.connect("row-activated", self._activate_document)
        self._content_stack.add_named(self.notebook, "tabs")

        self._main_paned.pack1(self.sidebar, False, False)
        self._main_paned.pack2(self._content_stack, True, False)
        root.pack_start(self._main_paned, True, True, 0)

        # Bottom StatusBar
        self._build_statusbar(root)

        win.add(root)

    def _build_headerbar(self, win: Gtk.ApplicationWindow) -> None:
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.get_style_context().add_class("main-headerbar")
        hb.set_title("Markveil")
        hb.set_subtitle("")
        self._headerbar = hb

        # The window manager still receives the full title; the bar uses one line.
        hb.set_has_subtitle(False)
        self._location = Gtk.Label()
        self._location.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._location.set_max_width_chars(24)
        self._location.get_style_context().add_class("location")
        hb.set_custom_title(self._location)
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        mark_path = Path(__file__).resolve().parent.parent / "assets" / "icons" / "folio-mark.svg"
        symbol = Gtk.Image.new_from_file(str(mark_path))
        brand.pack_start(symbol, False, False, 0)
        wordmark = Gtk.Label(label="Markveil")
        wordmark.get_style_context().add_class("wordmark")
        brand.pack_start(wordmark, False, False, 0)
        hb.pack_start(brand)

        # --- Start controls ---
        self._sidebar_btn = Gtk.ToggleButton()
        self._sidebar_btn.set_image(
            Gtk.Image.new_from_icon_name("view-dual-symbolic", Gtk.IconSize.BUTTON)
        )
        self._sidebar_btn.set_tooltip_text("Toggle Sidebar (Ctrl+B / F9)")
        self._sidebar_btn.set_active(self.config.sidebar_visible and not self.quick_mode)
        self._sidebar_btn.connect("toggled", self._on_sidebar_btn_toggled)
        self._sidebar_btn.show_all()
        self._sidebar_btn.set_no_show_all(True)
        hb.pack_start(self._sidebar_btn)

        self._open_btn = Gtk.Button.new_from_icon_name(
            "document-open-symbolic", Gtk.IconSize.BUTTON
        )
        self._open_btn.set_tooltip_text("Open File (Ctrl+O)")
        self._open_btn.connect("clicked", lambda _b: self.action_open_file())
        hb.pack_start(self._open_btn)

        self._save_btn = Gtk.Button.new_from_icon_name(
            "document-save-symbolic", Gtk.IconSize.BUTTON
        )
        self._save_btn.set_tooltip_text("Save (Ctrl+S)")
        self._save_btn.connect("clicked", lambda _b: self.action_save())
        self._save_btn.show_all()
        self._save_btn.set_no_show_all(True)
        hb.pack_start(self._save_btn)

        # Hidden dummy stack powering styled Gtk.StackSwitcher.mode-switcher
        self._mode_dummy_stack = Gtk.Stack()
        for key, label in (("preview", "Preview"), ("split", "Split"), ("edit", "Edit")):
            child = Gtk.Box()
            child.show()
            self._mode_dummy_stack.add_titled(child, key, label)
        self._mode_dummy_stack.connect(
            "notify::visible-child-name", self._on_mode_switcher_changed
        )

        self._mode_switcher = Gtk.StackSwitcher()
        self._mode_switcher.set_stack(self._mode_dummy_stack)
        self._mode_switcher.get_style_context().add_class("mode-switcher")
        self._mode_switcher.show_all()
        self._mode_switcher.set_no_show_all(True)

        # --- End controls (packed right-to-left) ---
        self._menu_btn = Gtk.MenuButton()
        self._menu_btn.set_image(
            Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        )
        self._menu_btn.set_tooltip_text("Menu")
        self._menu_popover = self._build_menu_popover(self._menu_btn)
        self._menu_btn.set_popover(self._menu_popover)
        hb.pack_end(self._menu_btn)

        hb.pack_end(self._mode_switcher)

        self._watch_btn = Gtk.ToggleButton(label="Watch")
        self._watch_btn.set_tooltip_text("Toggle Agent Watch Mode (Ctrl+Shift+W)")
        self._watch_btn.connect("toggled", self._on_watch_btn_toggled)
        self._watch_btn.show_all()
        self._watch_btn.set_no_show_all(True)
        hb.pack_end(self._watch_btn)

        self._search_btn = Gtk.Button.new_from_icon_name(
            "edit-find-symbolic", Gtk.IconSize.BUTTON
        )
        self._search_btn.set_tooltip_text("Find (Ctrl+F)")
        self._search_btn.connect("clicked", lambda _b: self.action_open_search(False))
        hb.pack_start(self._search_btn)

        win.set_titlebar(hb)

    def _build_menu_popover(self, relative_to: Gtk.Widget) -> Gtk.Popover:
        pop = Gtk.Popover.new(relative_to)
        pop.get_style_context().add_class("markveil-popover")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_size_request(240, -1)

        def add_item(label: str, callback: object) -> Gtk.ModelButton:
            btn = Gtk.ModelButton()
            btn.set_label(label)
            btn.connect("clicked", lambda _b: (pop.popdown(), callback()))
            box.pack_start(btn, False, False, 0)
            return btn

        def add_sep() -> None:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(3)
            sep.set_margin_bottom(3)
            box.pack_start(sep, False, False, 0)

        add_item("New Tab   (Ctrl+N)", self.action_new_tab)
        add_item("Open Clipboard   (Ctrl+Shift+V)", self.action_open_clipboard)
        self._menu_save_as = add_item("Save As…   (Ctrl+Shift+S)", self.action_save_as)

        add_sep()
        rec_hdr = Gtk.Label(label="Recent files")
        rec_hdr.get_style_context().add_class("sidebar-section-title")
        rec_hdr.set_xalign(0.0)
        rec_hdr.set_margin_start(8)
        rec_hdr.set_margin_top(2)
        box.pack_start(rec_hdr, False, False, 0)

        self._menu_recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.pack_start(self._menu_recent_box, False, False, 0)

        add_sep()
        self._agent_btn = add_item("Ask local agent…   (Ctrl+Shift+A)", self.action_ask_agent)
        self._theme_btn = add_item("Cycle theme   (Ctrl+T)", self.cycle_theme)
        add_item("Compare / Visual Diff…   (Ctrl+D)", self.action_open_diff_picker)
        add_item("Add Review Comment   (Ctrl+Shift+M)", self.action_add_comment)
        add_item("Export Review Comments…", self.action_export_reviews)
        add_item("Print / Export PDF…   (Ctrl+P)", self.action_print)
        add_item("Copy File Path   (Ctrl+Shift+C)", self.action_copy_file_path)

        add_sep()
        self._menu_status_bar_btn = Gtk.CheckButton(label="Show Status Bar")
        self._menu_status_bar_btn.set_active(self.config.status_bar_visible)
        self._menu_status_bar_btn.set_margin_start(6)
        self._menu_status_bar_btn.connect("toggled", self._on_status_bar_menu_toggled)
        box.pack_start(self._menu_status_bar_btn, False, False, 0)

        add_item("Preferences…", self.action_preferences)
        add_item("Keyboard Shortcuts   (F1)", self.action_shortcuts)

        box.show_all()
        pop.add(box)
        pop.connect("show", self._refresh_recent_menu)
        return pop

    def _refresh_recent_menu(self, _popover: Gtk.Popover) -> None:
        for child in list(self._menu_recent_box.get_children()):
            self._menu_recent_box.remove(child)

        existing = [p for p in self.config.recent_files if Path(p).is_file()][:6]
        if not existing:
            lbl = Gtk.Label(label="No recent files")
            lbl.get_style_context().add_class("muted-label")
            lbl.set_xalign(0.0)
            lbl.set_margin_start(10)
            self._menu_recent_box.pack_start(lbl, False, False, 0)
        else:
            for file_path in existing:
                btn = Gtk.ModelButton()
                btn.set_label(Path(file_path).name)
                btn.set_tooltip_text(file_path)
                btn.connect(
                    "clicked",
                    lambda _b, fp=file_path: (
                        self._menu_popover.popdown(),
                        self.open_file(fp),
                    ),
                )
                self._menu_recent_box.pack_start(btn, False, False, 0)

        self._menu_recent_box.show_all()

    def _build_statusbar(self, root: Gtk.Box) -> None:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.get_style_context().add_class("mdv-statusbar")
        bar.set_size_request(-1, 26)
        self._statusbar = bar

        self._cursor_lbl = Gtk.Label(label="")
        bar.pack_start(self._cursor_lbl, False, False, 0)

        self._stats_lbl = Gtk.Label(label="")
        self._stats_lbl.get_style_context().add_class("doc-stats-label")
        bar.pack_start(self._stats_lbl, False, False, 0)

        self._toast_lbl = Gtk.Label(label="")
        bar.pack_start(self._toast_lbl, True, True, 4)

        # Right side badges & zoom
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        zoom_box.get_style_context().add_class("linked")
        zoom_box.get_style_context().add_class("zoom-controls")

        z_out = Gtk.Button(label="-")
        z_out.set_tooltip_text("Zoom Out (Ctrl+-)")
        z_out.connect("clicked", lambda _b: self.adjust_zoom(-0.1))
        zoom_box.pack_start(z_out, False, False, 0)

        self._zoom_reset_btn = Gtk.Button(
            label=f"{int(round(self.config.zoom_level * 100))}%"
        )
        self._zoom_reset_btn.set_tooltip_text("Reset Zoom (Ctrl+0)")
        self._zoom_reset_btn.connect("clicked", lambda _b: self.set_zoom(1.0))
        zoom_box.pack_start(self._zoom_reset_btn, False, False, 0)

        z_in = Gtk.Button(label="+")
        z_in.set_tooltip_text("Zoom In (Ctrl++)")
        z_in.connect("clicked", lambda _b: self.adjust_zoom(0.1))
        zoom_box.pack_start(z_in, False, False, 0)
        bar.pack_end(zoom_box, False, False, 0)

        self._readonly_badge = Gtk.Label(label="Read only")
        self._readonly_badge.get_style_context().add_class("readonly-badge")
        bar.pack_end(self._readonly_badge, False, False, 0)

        self._watch_badge = Gtk.Label(label="● WATCH")
        self._watch_badge.get_style_context().add_class("watch-badge")
        bar.pack_end(self._watch_badge, False, False, 0)

        bar.show_all()
        self._readonly_badge.set_no_show_all(True)
        self._readonly_badge.hide()
        self._watch_badge.set_no_show_all(True)
        self._watch_badge.hide()
        bar.set_no_show_all(True)

        root.pack_end(bar, False, False, 0)

    # ------------------------------------------------------------------
    # Launch Options Dispatch & Wayland Deferred Clipboard
    # ------------------------------------------------------------------
    def _process_launch_options(self) -> None:
        opts = self.launch_options

        if opts.diff_files:
            file_a, file_b = opts.diff_files
            tab = self.open_file(file_b, mode="preview", readonly=opts.readonly)
            if tab is None:
                tab = self.open_text_tab(
                    text="",
                    display_name=f"Diff: {Path(file_a).name} ↔ {Path(file_b).name}",
                    readonly=True,
                )
            self._apply_file_diff(tab, file_a, file_b, "unified")
            return

        if opts.git_diff_file:
            tab = self.open_file(
                opts.git_diff_file,
                mode="preview",
                watch=opts.watch,
                readonly=opts.readonly,
            )
            if tab is not None:
                self._apply_git_diff(tab, "unified")
            return

        if opts.clipboard:
            self._start_deferred_clipboard_launch()
            return

        if opts.stdin_text is not None:
            self.open_text_tab(
                text=opts.stdin_text,
                display_name=opts.stdin_label,
                mode=opts.mode,
                readonly=opts.readonly,
                line=opts.line,
                section=opts.section,
            )
            return

        if opts.files:
            for idx, file_path in enumerate(opts.files):
                self.open_file(
                    file_path,
                    mode=opts.mode,
                    watch=opts.watch,
                    readonly=opts.readonly,
                    line=opts.line if idx == 0 else None,
                    section=opts.section if idx == 0 else None,
                )
            return

        self._content_stack.set_visible_child_name("welcome")

    def _start_deferred_clipboard_launch(self) -> None:
        """Open Clipboard Studio cleanly under Wayland by deferring read until focus/map."""
        tab = self.open_text_tab(
            text="",
            display_name="Clipboard.md",
            mode="preview",
            clipboard_mode=True,
            clipboard_was_html=False,
        )
        self._cancel_pending_clipboard()
        self._pending_clipboard_tab = tab
        self._pending_clipboard_attempts = 0

        if self.window is not None:
            self._pending_clipboard_focus_hid = self.window.connect(
                "focus-in-event", self._on_startup_clipboard_focus
            )
        GLib.idle_add(self._attempt_startup_clipboard_read)

    def _cancel_pending_clipboard(self) -> None:
        if self._pending_clipboard_timer:
            GLib.source_remove(self._pending_clipboard_timer)
            self._pending_clipboard_timer = 0
        if self._pending_clipboard_focus_hid and self.window is not None:
            try:
                self.window.disconnect(self._pending_clipboard_focus_hid)
            except Exception:
                pass
        self._pending_clipboard_focus_hid = 0
        self._pending_clipboard_tab = None

    def _on_startup_clipboard_focus(
        self, _win: Gtk.Window, _event: Gdk.EventFocus
    ) -> bool:
        GLib.idle_add(self._attempt_startup_clipboard_read)
        return False

    def _attempt_startup_clipboard_read(self) -> bool:
        self._pending_clipboard_timer = 0
        tab = self._pending_clipboard_tab
        if tab is None or tab._cleaned_up:
            self._cancel_pending_clipboard()
            return False

        # If user already typed or loaded content into the tab, stop retrying
        if tab.get_text().strip():
            self._cancel_pending_clipboard()
            return False

        self._pending_clipboard_attempts += 1
        payload = read_clipboard_smart(prefer_html_convert=True)
        if payload.text:
            self._cancel_pending_clipboard()
            tab.load_clipboard_payload(
                payload.text, payload.was_html, record_history=True, mark_dirty=False
            )
            return False

        # Under Wayland seat focus can arrive slightly after map; retry briefly.
        if self._pending_clipboard_attempts < 4:
            delay_ms = 90 * self._pending_clipboard_attempts
            self._pending_clipboard_timer = GLib.timeout_add(
                delay_ms, self._attempt_startup_clipboard_read
            )
            return False

        self._cancel_pending_clipboard()
        tab.show_empty_clipboard_prompt()
        return False

    # ------------------------------------------------------------------
    # Tab Management
    # ------------------------------------------------------------------
    def get_active_tab(self) -> DocumentTab | None:
        if self.notebook is None or self.notebook.get_n_pages() == 0:
            return None
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        return page if isinstance(page, DocumentTab) else None

    def get_all_tabs(self) -> list[DocumentTab]:
        if self.notebook is None:
            return []
        tabs: list[DocumentTab] = []
        for idx in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(idx)
            if isinstance(page, DocumentTab):
                tabs.append(page)
        return tabs

    def _compare_document_rows(self, left: Gtk.ListBoxRow, right: Gtk.ListBoxRow) -> int:
        return self.notebook.page_num(left.document) - self.notebook.page_num(right.document)

    def _activate_document(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.notebook.set_current_page(self.notebook.page_num(row.document))

    def _document_label(self, tab: DocumentTab, *, in_sidebar: bool) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if in_sidebar:
            icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic", Gtk.IconSize.MENU)
            box.pack_start(icon, False, False, 0)
        title = Gtk.Label(xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(26)
        box.pack_start(title, True, True, 0)
        dot = Gtk.Label(label="•")
        dot.set_tooltip_text("Unsaved changes")
        dot.set_no_show_all(True)
        box.pack_start(dot, False, False, 0)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.get_style_context().add_class("document-close")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Close document (Ctrl+W)")
        close.set_focus_on_click(False)
        close.connect("clicked", lambda _button: self.close_tab(tab))
        box.pack_end(close, False, False, 0)
        self._tab_labels.setdefault(tab, []).append((title, dot))
        box.show_all()
        return box

    def _add_tab(self, tab: DocumentTab) -> DocumentTab:
        assert self.notebook is not None and self.sidebar is not None
        label_box = self._document_label(tab, in_sidebar=False)
        page_idx = self.notebook.append_page(tab, label_box)
        row = Gtk.ListBoxRow()
        row.document = tab
        row.add(self._document_label(tab, in_sidebar=True))
        self._document_rows[tab] = row
        self.sidebar.documents.add(row)
        row.show_all()
        self.notebook.set_tab_reorderable(tab, True)
        tab.show_all()
        # Preserve single-render guarantee: sync pane visibility without re-rendering
        tab.set_view_mode(tab.view_mode, rerender=False, notify=False)
        self.notebook.set_current_page(page_idx)
        self._content_stack.set_visible_child_name("tabs")
        self._update_notebook_tab_bar()
        self._update_tab_label(tab)
        self._sync_chrome_visibility()
        self._sync_ui_for_active_tab()
        return tab

    def _update_notebook_tab_bar(self) -> None:
        if self.notebook is not None:
            use_strip = self.quick_mode or not self.config.sidebar_visible
            self.notebook.set_show_tabs(use_strip and self.notebook.get_n_pages() > 1)

    def _update_tab_label(self, tab: DocumentTab) -> None:
        for title, dot in self._tab_labels.get(tab, ()):
            title.set_text(tab.display_name)
            title.set_tooltip_text(tab.current_file or tab.display_name)
            dot.set_visible(tab.dirty)

    def open_file(
        self,
        file_path: str,
        *,
        mode: str = "preview",
        watch: bool = False,
        readonly: bool = False,
        line: int | None = None,
        section: str | None = None,
    ) -> DocumentTab | None:
        resolved = str(Path(file_path).expanduser().resolve())
        if not Path(resolved).is_file():
            self.show_status_toast(f"File not found: {file_path}")
            return None

        # Focus existing tab if already open
        if self.notebook is not None:
            for idx, existing in enumerate(self.get_all_tabs()):
                if existing.current_file == resolved:
                    self.notebook.set_current_page(idx)
                    if section:
                        existing.scroll_to_slug(section)
                    if line:
                        existing.scroll_to_line(line)
                    if watch and not existing.watch_enabled:
                        existing.set_watch_enabled(True)
                    return existing

        tab = DocumentTab(
            file_path=resolved,
            theme_id=self.resolved_theme,
            zoom_level=self.config.zoom_level,
            view_mode=mode,
            readonly=readonly,
            watch_enabled=watch,
            allow_remote_images=self.config.allow_remote_images,
            vim_enabled=self.config.vim_navigation,
            custom_css=self.custom_css,
            split_ratio=self.config.split_ratio,
            initial_line=line,
            initial_section=section,
            on_state_changed=self._on_tab_state_changed,
            on_cursor_changed=self._on_tab_cursor_changed,
            on_open_file_request=self._on_tab_open_file_request,
            on_always_allow_remote=self._on_always_allow_remote,
            on_save_as_request=self._on_tab_save_as_request,
            on_comment_added=self._on_tab_comment_added,
            on_status_message=self.show_status_toast,
            on_confirm_leave=self._confirm_leave_tab,
            on_file_navigated=self._on_tab_file_navigated,
        )
        self._record_recent_file(resolved)
        return self._add_tab(tab)

    def open_text_tab(
        self,
        *,
        text: str,
        display_name: str = "Untitled.md",
        mode: str = "preview",
        readonly: bool = False,
        clipboard_mode: bool = False,
        clipboard_was_html: bool = False,
        line: int | None = None,
        section: str | None = None,
    ) -> DocumentTab:
        tab = DocumentTab(
            file_path=None,
            initial_text=text,
            display_name=display_name,
            theme_id=self.resolved_theme,
            zoom_level=self.config.zoom_level,
            view_mode=mode,
            readonly=readonly,
            allow_remote_images=self.config.allow_remote_images,
            vim_enabled=self.config.vim_navigation,
            custom_css=self.custom_css,
            split_ratio=self.config.split_ratio,
            clipboard_mode=clipboard_mode,
            clipboard_was_html=clipboard_was_html,
            initial_line=line,
            initial_section=section,
            on_state_changed=self._on_tab_state_changed,
            on_cursor_changed=self._on_tab_cursor_changed,
            on_open_file_request=self._on_tab_open_file_request,
            on_always_allow_remote=self._on_always_allow_remote,
            on_save_as_request=self._on_tab_save_as_request,
            on_comment_added=self._on_tab_comment_added,
            on_status_message=self.show_status_toast,
            on_confirm_leave=self._confirm_leave_tab,
            on_file_navigated=self._on_tab_file_navigated,
        )
        return self._add_tab(tab)

    def _record_recent_file(self, resolved_path: str) -> None:
        add_recent_file(self.config, resolved_path)
        self._schedule_config_save()
        if self.welcome_view is not None:
            self.welcome_view.set_recent_files(self.config.recent_files)

    def _confirm_leave_tab(self, tab: DocumentTab, *, closing: bool = False) -> bool:
        """Confirm discarding/saving unsaved edits or unexported review comments."""
        if tab.dirty:
            resp = self._confirm_unsaved_dialog(tab.display_name, closing=closing)
            if resp == Gtk.ResponseType.CANCEL:
                return False
            if resp == Gtk.ResponseType.YES:
                if not self._save_tab(tab):
                    return False

        if tab.has_unexported_comments():
            resp = self._confirm_unexported_comments_dialog(
                tab.display_name, closing=closing
            )
            if resp == Gtk.ResponseType.CANCEL:
                return False
            if resp == Gtk.ResponseType.YES:
                if self.sidebar is None:
                    return False
                self.sidebar.update_comments(
                    tab.review_session.list(),
                    tab.current_file,
                    has_active_document=True,
                )
                saved = self.sidebar.export_review_dialog(self.window)
                if not saved:
                    return False
                tab.mark_comments_exported()
        return True

    def close_tab(self, tab: DocumentTab, *, force: bool = False) -> bool:
        if self.notebook is None:
            return False
        if not force and (tab.dirty or tab.has_unexported_comments()):
            if not self._confirm_leave_tab(tab, closing=True):
                return False

        page_num = self.notebook.page_num(tab)
        if page_num < 0:
            return False
        if tab is self._pending_clipboard_tab:
            self._cancel_pending_clipboard()
        tab.cleanup()
        self._tab_labels.pop(tab, None)
        self.sidebar.documents.remove(self._document_rows.pop(tab))
        self.notebook.remove_page(page_num)
        self._update_notebook_tab_bar()

        if self.notebook.get_n_pages() == 0:
            self._content_stack.set_visible_child_name("welcome")

        self._sync_chrome_visibility()
        self._sync_ui_for_active_tab()
        return True

    def _confirm_unsaved_dialog(self, title: str, *, closing: bool = True) -> int:
        verb = "closing" if closing else "navigating away"
        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Save changes to “{title}” before {verb}?",
        )
        dlg.get_style_context().add_class("markveil-window")
        dlg.format_secondary_text(
            "Your unsaved edits will be lost if you continue without saving."
        )
        dlg.add_button("Discard", Gtk.ResponseType.NO)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        save_btn = dlg.add_button("Save", Gtk.ResponseType.YES)
        save_btn.get_style_context().add_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.YES)
        resp = dlg.run()
        dlg.destroy()
        return resp

    def _confirm_unexported_comments_dialog(
        self, title: str, *, closing: bool = True
    ) -> int:
        verb = "closing" if closing else "navigating away"
        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Export review comments for “{title}” before {verb}?",
        )
        dlg.get_style_context().add_class("markveil-window")
        dlg.format_secondary_text(
            "You have unexported review comments that will be lost if discarded."
        )
        dlg.add_button("Discard", Gtk.ResponseType.NO)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        exp_btn = dlg.add_button("Export…", Gtk.ResponseType.YES)
        exp_btn.get_style_context().add_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.YES)
        resp = dlg.run()
        dlg.destroy()
        return resp

    # ------------------------------------------------------------------
    # Theme & Zoom
    # ------------------------------------------------------------------
    @staticmethod
    def _on_css_parsing_error(
        _provider: Gtk.CssProvider, section: Gtk.CssSection, error: GLib.Error
    ) -> None:
        line = section.get_start_line() + 1 if section is not None else 0
        print(
            f"[markveil] GTK CSS parse warning (line {line}): {error.message}",
            file=sys.stderr,
        )

    def _apply_theme_css(self) -> None:
        css = build_gtk_css(self.resolved_theme, self.config.zoom_level)
        if self._css_provider is None:
            self._css_provider = Gtk.CssProvider()
            self._css_provider.connect("parsing-error", self._on_css_parsing_error)
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen,
                    self._css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_USER,
                )
        try:
            self._css_provider.load_from_data(css.encode("utf-8"))
        except Exception as exc:
            print(f"[markveil] Failed to load GTK CSS: {exc}", file=sys.stderr)

        if hasattr(self, "_theme_btn"):
            self._theme_btn.set_label(
                f"Cycle theme  ·  {THEMES[self.resolved_theme].name}   (Ctrl+T)"
            )

    def set_theme(self, theme_id: str) -> None:
        self.config.theme = theme_id
        self.resolved_theme = resolve_theme_id(theme_id, system_dark=self.system_dark)
        self._apply_theme_css()
        for tab in self.get_all_tabs():
            tab.apply_theme(self.resolved_theme, rerender=True)
        self._schedule_config_save()

    def cycle_theme(self) -> None:
        try:
            idx = THEME_ORDER.index(self.resolved_theme)
        except ValueError:
            idx = -1
        next_theme = THEME_ORDER[(idx + 1) % len(THEME_ORDER)]
        self.set_theme(next_theme)
        self.show_status_toast(f"Theme: {THEMES[next_theme].name}")

    def set_zoom(self, zoom: float) -> None:
        clamped = round(max(0.5, min(3.0, float(zoom))), 2)
        self.config.zoom_level = clamped
        self._zoom_reset_btn.set_label(f"{int(round(clamped * 100))}%")
        self._apply_theme_css()
        for tab in self.get_all_tabs():
            tab.set_zoom_level(clamped)
        self._schedule_config_save()

    def adjust_zoom(self, delta: float) -> None:
        self.set_zoom(self.config.zoom_level + delta)

    # ------------------------------------------------------------------
    # Chrome & State Synchronization
    # ------------------------------------------------------------------
    def _sync_chrome_visibility(self) -> None:
        tab = self.get_active_tab()
        has_tab = tab is not None
        self._update_notebook_tab_bar()
        self._search_btn.set_sensitive(has_tab)
        self._agent_btn.set_sensitive(has_tab and not self.quick_mode)
        self._menu_save_as.set_sensitive(has_tab and not tab.readonly)

        if self.quick_mode:
            self._sidebar_btn.hide()
            self._save_btn.hide()
            self._mode_switcher.hide()
            self._watch_btn.hide()
            self._statusbar.hide()
            if self.sidebar is not None:
                self.sidebar.hide()
            return

        self._sidebar_btn.show_all()
        self._sidebar_btn.show()
        self._sidebar_btn.set_sensitive(has_tab)

        if has_tab:
            self._watch_btn.show_all()
            self._watch_btn.show()
            if tab.readonly:
                self._save_btn.hide()
                self._mode_switcher.hide()
            else:
                self._save_btn.show_all()
                self._save_btn.show()
                self._mode_switcher.show_all()
                self._mode_switcher.show()
        else:
            self._save_btn.hide()
            self._mode_switcher.hide()
            self._watch_btn.hide()

        if self.sidebar is not None:
            if has_tab and self.config.sidebar_visible:
                self.sidebar.show_all()
                self.sidebar.show()
            else:
                self.sidebar.hide()

        if has_tab and self.config.status_bar_visible:
            self._statusbar.show_all()
            self._statusbar.show()
        else:
            self._statusbar.hide()

    def _sync_cursor_label(self, tab: DocumentTab | None) -> None:
        if tab is not None and tab.view_mode in ("edit", "split") and not tab.diff_active:
            self._cursor_lbl.set_text(f"Ln {tab.cursor_line}, Col {tab.cursor_col}")
            self._cursor_lbl.show()
        else:
            self._cursor_lbl.set_text("")

    def _sync_ui_for_active_tab(self) -> None:
        tab = self.get_active_tab()
        self._suppress_ui_signals = True
        try:
            if tab is None:
                self._headerbar.set_title("Markveil")
                self._location.set_text("")
                self._cursor_lbl.set_text("")
                self._stats_lbl.set_text("")
                self._watch_badge.hide()
                self._readonly_badge.hide()
                self._save_btn.get_style_context().remove_class("suggested-action")
                self._watch_btn.set_active(False)
                if self.sidebar is not None:
                    self.sidebar.update_outline([], None)
                    self.sidebar.update_context(None)
                    self.sidebar.update_comments(
                        [], None, has_active_document=False
                    )
                return

            # HeaderBar title & subtitle
            dirty_prefix = "• " if tab.dirty else ""
            self._headerbar.set_title(f"{dirty_prefix}{tab.display_name}")

            location = tab.display_name
            if tab.diff_active:
                location = f"Diff  /  {location}"
            elif tab.current_file:
                parent = Path(tab.current_file).parent.name
                if parent:
                    location = f"{parent}  /  {location}"
            self._location.set_text(location)
            self._location.set_tooltip_text(tab.current_file or tab.display_name)
            row = self._document_rows.get(tab)
            if row is not None:
                self.sidebar.documents.select_row(row)

            # Save button emphasis
            save_ctx = self._save_btn.get_style_context()
            if tab.dirty and not tab.readonly:
                save_ctx.add_class("suggested-action")
            else:
                save_ctx.remove_class("suggested-action")

            # Mode switcher
            if self._mode_dummy_stack.get_visible_child_name() != tab.view_mode:
                self._mode_dummy_stack.set_visible_child_name(tab.view_mode)

            # Watch button
            watch_label = "Watch"
            if tab.watch_enabled:
                watch_label = "Paused" if tab.watch_paused else "● Watching"
            self._watch_btn.set_label(watch_label)
            self._watch_btn.set_active(tab.watch_enabled)
            self._watch_btn.set_sensitive(bool(tab.current_file))

            # StatusBar metrics
            self._sync_cursor_label(tab)

            report = tab.context_report
            if report is not None:
                mins = f"{report.reading_minutes} min" if report.reading_minutes else "<1 min"
                self._stats_lbl.set_text(
                    f"{report.words:,} words · ~{report.est_tokens:,} est. tokens · {mins}"
                )
            else:
                self._stats_lbl.set_text("")

            if tab.watch_enabled:
                self._watch_badge.set_text(f"Revision {max(1, tab.revision_count)}")
                if tab.watch_paused:
                    self._watch_badge.get_style_context().remove_class("active")
                else:
                    self._watch_badge.get_style_context().add_class("active")
                self._watch_badge.show()
            else:
                self._watch_badge.hide()

            if tab.readonly:
                self._readonly_badge.show()
            else:
                self._readonly_badge.hide()

            # Sidebar updates
            if self.sidebar is not None:
                self.sidebar.update_outline(tab.headings, tab.current_file)
                self.sidebar.set_active_heading(tab.active_heading_slug)
                self.sidebar.update_context(tab.context_report)
                self.sidebar.update_comments(
                    tab.review_session.list(),
                    tab.current_file,
                    has_active_document=True,
                )
                self.sidebar.set_project_context(tab.current_file)
        finally:
            self._suppress_ui_signals = False

    def show_status_toast(self, message: str) -> None:
        if not hasattr(self, "_toast_lbl"):
            return
        self._toast_lbl.set_text(message)
        if self._status_toast_timer:
            GLib.source_remove(self._status_toast_timer)
        self._status_toast_timer = GLib.timeout_add(3000, self._clear_status_toast)

    def _clear_status_toast(self) -> bool:
        self._status_toast_timer = 0
        if hasattr(self, "_toast_lbl"):
            self._toast_lbl.set_text("")
        return False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_new_tab(self) -> None:
        self.open_text_tab(text="# New Document\n\n", display_name="Untitled.md", mode="split")

    def action_open_file(self) -> None:
        fc = Gtk.FileChooserNative.new(
            "Open Markdown or Technical File",
            self.window,
            Gtk.FileChooserAction.OPEN,
            "_Open",
            "_Cancel",
        )
        fc.set_select_multiple(True)

        md_filter = Gtk.FileFilter()
        md_filter.set_name("Markdown & Technical Files")
        for pat in (
            "*.md",
            "*.markdown",
            "*.mdown",
            "*.mkd",
            "*.mdx",
            "*.mdc",
            "*.rules",
            "*.json",
            "*.jsonc",
            "*.yaml",
            "*.yml",
            "*.toml",
            "*.diff",
            "*.patch",
            "*.mmd",
            "*.mermaid",
            "*.txt",
            "*.py",
            "*.sh",
            "*.js",
            "*.ts",
            "*.tsx",
        ):
            md_filter.add_pattern(pat)
        fc.add_filter(md_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All Files")
        all_filter.add_pattern("*")
        fc.add_filter(all_filter)

        tab = self.get_active_tab()
        if tab and tab.current_file:
            parent = Path(tab.current_file).parent
            if parent.is_dir():
                fc.set_current_folder(str(parent))

        if fc.run() == Gtk.ResponseType.ACCEPT:
            for fname in fc.get_filenames():
                self.open_file(fname)
        fc.destroy()

    def action_open_clipboard(self) -> None:
        payload = read_clipboard_smart(prefer_html_convert=True)
        if payload.text:
            _record_clipboard_history(payload.text, was_html=payload.was_html)
            self.open_text_tab(
                text=payload.text,
                display_name="Clipboard.md",
                mode="preview",
                clipboard_mode=True,
                clipboard_was_html=payload.was_html,
            )
        else:
            tab = self.open_text_tab(
                text="",
                display_name="Clipboard.md",
                mode="split",
                clipboard_mode=True,
                clipboard_was_html=False,
            )
            tab.show_empty_clipboard_prompt()

    def _open_clipboard_history_entry(self, text: str, was_html: bool) -> None:
        self.open_text_tab(
            text=text,
            display_name="Clipboard.md",
            mode="preview" if text else "split",
            clipboard_mode=True,
            clipboard_was_html=was_html,
        )

    def _save_tab(self, tab: DocumentTab) -> bool:
        if tab.readonly:
            return False
        if tab.current_file:
            return tab.save()
        return self._save_tab_as(tab)

    def _save_tab_as(self, tab: DocumentTab) -> bool:
        if tab.readonly:
            return False
        fc = Gtk.FileChooserNative.new(
            "Save Document As",
            self.window,
            Gtk.FileChooserAction.SAVE,
            "_Save",
            "_Cancel",
        )
        fc.set_do_overwrite_confirmation(True)
        if tab.current_file:
            p = Path(tab.current_file)
            fc.set_current_folder(str(p.parent))
            fc.set_current_name(p.name)
        else:
            fc.set_current_name(tab.display_name or "Untitled.md")

        saved = False
        if fc.run() == Gtk.ResponseType.ACCEPT:
            fname = fc.get_filename()
            if fname:
                saved = tab.save(fname)
                if saved:
                    self._record_recent_file(str(Path(fname).resolve()))
        fc.destroy()
        return saved

    def action_save(self) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            self._save_tab(tab)

    def action_save_as(self) -> None:
        tab = self.get_active_tab()
        if tab is not None and not tab.readonly:
            self._save_tab_as(tab)

    def action_close_active_tab(self) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            self.close_tab(tab)

    def action_cycle_view_mode(self) -> None:
        tab = self.get_active_tab()
        if tab is None or tab.readonly:
            return
        if tab.diff_active:
            tab.hide_diff_overlay()
            return
        idx = _VIEW_MODE_CYCLE.index(tab.view_mode)
        next_mode = _VIEW_MODE_CYCLE[(idx + 1) % len(_VIEW_MODE_CYCLE)]
        tab.set_view_mode(next_mode)

    def action_toggle_split(self) -> None:
        tab = self.get_active_tab()
        if tab is None or tab.readonly:
            return
        if tab.diff_active:
            tab.hide_diff_overlay()
        tab.set_view_mode("preview" if tab.view_mode == "split" else "split")

    def action_reload(self) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.reload_from_disk(highlight_changes=tab.watch_enabled)

    def action_toggle_sidebar(self) -> None:
        if self.quick_mode:
            return
        self.config.sidebar_visible = not self.config.sidebar_visible
        self._suppress_ui_signals = True
        self._sidebar_btn.set_active(self.config.sidebar_visible)
        self._suppress_ui_signals = False
        self._sync_chrome_visibility()
        self._schedule_config_save()

    def action_open_search(self, replace: bool = False) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.open_search(replace=replace)

    def action_toggle_watch(self) -> None:
        tab = self.get_active_tab()
        if tab is None:
            return
        tab.set_watch_enabled(not tab.watch_enabled)

    def action_add_comment(self) -> None:
        tab = self.get_active_tab()
        if tab is None:
            self.show_status_toast("Open a document first to add a review comment.")
            return
        tab.request_add_comment()

    def action_open_diff_picker(self) -> None:
        tab = self.get_active_tab()
        dlg = DiffPickerDialog(
            self.window,
            has_revisions=bool(tab and len(tab.revisions) >= 2),
            current_file=tab.current_file if tab else None,
        )
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            sel = dlg.get_selection()
            source = sel["source"]
            mode = sel["mode"] or "unified"
            if source == "revision" and tab is not None:
                tab.show_last_revision_diff(mode=mode)
            elif source == "git" and tab is not None:
                self._apply_git_diff(tab, mode)
            elif source == "files":
                fa = sel["file_a"]
                fb = sel["file_b"]
                if fa and fb:
                    target_tab = tab or self.open_text_tab(
                        text="",
                        display_name=f"Diff: {Path(fa).name} ↔ {Path(fb).name}",
                        readonly=True,
                    )
                    self._apply_file_diff(target_tab, fa, fb, mode)
        dlg.destroy()

    def _apply_git_diff(self, tab: DocumentTab, mode: str) -> None:
        if not tab.current_file:
            tab.show_notice("Save the file first to compare against Git HEAD.")
            return
        fp = tab.current_file

        def _regen(m: str):
            return diff_git_head(fp, revision="HEAD", mode=m)

        tab.show_diff_report(_regen(mode), "git", mode=mode, regenerate_fn=_regen)

    def _apply_file_diff(
        self, tab: DocumentTab, file_a: str, file_b: str, mode: str
    ) -> None:
        def _regen(m: str):
            return diff_files(file_a, file_b, mode=m)

        tab.show_diff_report(_regen(mode), "files", mode=mode, regenerate_fn=_regen)

    def action_ask_agent(self) -> None:
        if self.quick_mode:
            return
        tab = self.get_active_tab()
        if tab is None:
            self.show_status_toast("Open a document first to ask a local agent.")
            return
        AskAgentDialog(
            self.window,
            document_text=tab.get_text(),
            file_path=tab.current_file,
            theme_id=self.resolved_theme,
            preferred_agent=self.config.preferred_agent,
            on_open_in_tab=lambda name, md: self.open_text_tab(
                text=md, display_name=name, mode="preview"
            ),
            on_agent_selected=self._on_preferred_agent_selected,
        )

    def _on_preferred_agent_selected(self, backend_id: str) -> None:
        if backend_id and backend_id != self.config.preferred_agent:
            self.config.preferred_agent = backend_id
            self._schedule_config_save()

    def action_export_reviews(self) -> None:
        tab = self.get_active_tab()
        if tab is None or self.sidebar is None:
            return
        if len(tab.review_session) == 0:
            self.show_status_toast("No review comments to export yet.")
            return
        self.sidebar.export_review_dialog(self.window)

    def action_print(self) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.print_document(self.window)

    def action_copy_file_path(self) -> None:
        tab = self.get_active_tab()
        if tab and tab.current_file:
            ok = write_clipboard_text(tab.current_file)
            self.show_status_toast(
                f"Copied path: {tab.current_file}"
                if ok
                else "Failed to copy file path to clipboard"
            )
        else:
            self.show_status_toast("Current tab has no file path yet.")

    def action_preferences(self) -> None:
        dlg = PreferencesDialog(self.window, self.config)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            vals = dlg.get_values()
            prev_resolved = self.resolved_theme
            self.config.theme = str(vals["theme"])
            self.config.preferred_agent = str(vals.get("preferred_agent", "auto"))
            self.config.vim_navigation = bool(vals["vim_navigation"])
            self.config.allow_remote_images = bool(vals["allow_remote_images"])
            self.config.status_bar_visible = bool(vals["status_bar_visible"])
            self.config.custom_css_path = str(vals["custom_css_path"])
            self.custom_css = _read_custom_css(self.config.custom_css_path)

            self.resolved_theme = resolve_theme_id(
                self.config.theme, system_dark=self.system_dark
            )
            theme_changed = self.resolved_theme != prev_resolved
            self._apply_theme_css()

            self._suppress_ui_signals = True
            try:
                self._menu_status_bar_btn.set_active(self.config.status_bar_visible)
            finally:
                self._suppress_ui_signals = False

            self._sync_chrome_visibility()

            for tab in self.get_all_tabs():
                tab.apply_theme(self.resolved_theme, rerender=False)
                prefs_changed = tab.apply_preferences(
                    vim_enabled=self.config.vim_navigation,
                    allow_remote_images=self.config.allow_remote_images,
                    custom_css=self.custom_css,
                    rerender=False,
                )
                if theme_changed or prefs_changed:
                    tab.rerender_active_view()

            self._schedule_config_save()
        dlg.destroy()

    def action_shortcuts(self) -> None:
        dlg = ShortcutsDialog(self.window)
        dlg.run()
        dlg.destroy()

    def action_switch_tab(self, delta: int) -> None:
        if self.notebook is None:
            return
        n = self.notebook.get_n_pages()
        if n <= 1:
            return
        cur = self.notebook.get_current_page()
        self.notebook.set_current_page((cur + delta) % n)

    # ------------------------------------------------------------------
    # Signal Callbacks
    # ------------------------------------------------------------------
    def _on_sidebar_btn_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._suppress_ui_signals:
            return
        self.config.sidebar_visible = btn.get_active()
        self._sync_chrome_visibility()
        self._schedule_config_save()

    def _on_mode_switcher_changed(self, stack: Gtk.Stack, _pspec: object) -> None:
        if self._suppress_ui_signals:
            return
        mode = stack.get_visible_child_name()
        tab = self.get_active_tab()
        if tab is not None and mode in ("preview", "split", "edit"):
            if tab.diff_active:
                tab.hide_diff_overlay()
            tab.set_view_mode(mode)

    def _on_watch_btn_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._suppress_ui_signals:
            return
        tab = self.get_active_tab()
        if tab is not None:
            tab.set_watch_enabled(btn.get_active())

    def _on_status_bar_menu_toggled(self, btn: Gtk.CheckButton) -> None:
        if self._suppress_ui_signals:
            return
        self.config.status_bar_visible = btn.get_active()
        self._sync_chrome_visibility()
        self._schedule_config_save()

    def _on_notebook_switch_page(
        self, _nb: Gtk.Notebook, _page: Gtk.Widget, _page_num: int
    ) -> None:
        self._sync_chrome_visibility()
        self._sync_ui_for_active_tab()

    def _on_tab_state_changed(self, tab: DocumentTab) -> None:
        self._update_tab_label(tab)
        if tab is self.get_active_tab():
            self._sync_chrome_visibility()
            self._sync_ui_for_active_tab()

    def _on_tab_cursor_changed(self, tab: DocumentTab) -> None:
        if tab is self.get_active_tab():
            self._sync_cursor_label(tab)

    def _on_tab_file_navigated(self, resolved_path: str) -> None:
        self._record_recent_file(resolved_path)

    def _on_tab_open_file_request(
        self, file_path: str, _new_tab: bool, section: str | None
    ) -> None:
        self.open_file(file_path, section=section)

    def _on_always_allow_remote(self) -> None:
        self.config.allow_remote_images = True
        self._schedule_config_save()

    def _on_tab_save_as_request(self, tab: DocumentTab) -> None:
        self._save_tab_as(tab)

    def _on_tab_comment_added(self, _tab: DocumentTab) -> None:
        if not self.quick_mode and self.sidebar is not None:
            if not self.config.sidebar_visible:
                self.action_toggle_sidebar()
            self.sidebar.set_active_tab("comments")

    def _on_sidebar_heading_clicked(self, heading: HeadingItem) -> None:
        tab = self.get_active_tab()
        if tab is None:
            return
        tab.scroll_to_slug(heading.slug)
        if heading.line > 0:
            tab.jump_to_line(heading.line)

    def _on_sidebar_section_clicked(self, section: SectionStats) -> None:
        tab = self.get_active_tab()
        if tab is None:
            return
        title = (section.title or "").strip()
        if title == "(Preamble)" or section.line <= 1:
            tab.scroll_to_top()
            return

        # Resolve to exact HeadingItem slug by line first, then text
        matched: HeadingItem | None = None
        for h in tab.headings:
            if h.line == section.line:
                matched = h
                break
        if matched is None:
            needle = title.lower()
            for h in tab.headings:
                if h.text.strip().lower() == needle:
                    matched = h
                    break

        if matched is not None:
            tab.scroll_to_slug(matched.slug)
        else:
            tab.scroll_to_heading(title)

        if section.line > 0:
            tab.jump_to_line(section.line)

    def _on_sidebar_comment_clicked(self, comment: ReviewComment) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.scroll_to_comment(comment)

    def _on_sidebar_edit_comment(self, comment: ReviewComment) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.edit_review_comment(comment)

    def _on_sidebar_delete_comment(self, comment_id: str) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.delete_review_comment(comment_id)

    def _on_sidebar_comments_exported(self, _filepath: str) -> None:
        tab = self.get_active_tab()
        if tab is not None:
            tab.mark_comments_exported()

    def _on_sidebar_tab_changed(self, tab_name: str) -> None:
        if tab_name != self.config.sidebar_tab:
            self.config.sidebar_tab = tab_name
            self._schedule_config_save()

    def _on_sidebar_width_changed(self, paned: Gtk.Paned, _pspec: object) -> None:
        pos = paned.get_position()
        if 140 <= pos <= 700 and pos != self.config.sidebar_width:
            self.config.sidebar_width = pos
            self._schedule_config_save()

    def _on_window_configure(
        self, win: Gtk.Window, _event: Gdk.EventConfigure
    ) -> bool:
        w, h = win.get_size()
        if (
            w >= 400
            and h >= 300
            and (w != self.config.window_width or h != self.config.window_height)
        ):
            self.config.window_width = w
            self.config.window_height = h
            self._schedule_config_save()
        return False

    def _on_drag_data_received(
        self,
        _widget: Gtk.Widget,
        _context: Gdk.DragContext,
        _x: int,
        _y: int,
        selection_data: Gtk.SelectionData,
        _info: int,
        _timestamp: int,
    ) -> None:
        uris = selection_data.get_uris()
        for uri in uris:
            parsed = urlparse(uri)
            if parsed.scheme == "file":
                try:
                    path, _host = GLib.filename_from_uri(uri)
                except Exception:
                    path = url2pathname(unquote(parsed.path))
                if path and Path(path).is_file():
                    self.open_file(path)

    def _on_window_delete(self, _win: Gtk.Window, _event: Gdk.Event) -> bool:
        for tab in list(self.get_all_tabs()):
            if not self.close_tab(tab):
                return True  # User cancelled quit
        self._cleanup_and_save()
        return False

    def do_shutdown(self) -> None:
        self._cleanup_and_save()
        Gtk.Application.do_shutdown(self)

    def _cleanup_and_save(self) -> None:
        self._cancel_pending_clipboard()
        if self._status_toast_timer:
            GLib.source_remove(self._status_toast_timer)
            self._status_toast_timer = 0
        if self._config_save_timer:
            GLib.source_remove(self._config_save_timer)
            self._config_save_timer = 0
        for tab in list(self.get_all_tabs()):
            tab.cleanup()
        self._save_config_safe()
        self._config_dirty = False

    def _schedule_config_save(self, delay_ms: int = _CONFIG_SAVE_DEBOUNCE_MS) -> None:
        """Debounce disk writes so interactive toggles/resizes never stall on fsync."""
        self._config_dirty = True
        if self._config_save_timer:
            GLib.source_remove(self._config_save_timer)
        self._config_save_timer = GLib.timeout_add(delay_ms, self._flush_config_save)

    def _flush_config_save(self) -> bool:
        self._config_save_timer = 0
        if self._config_dirty:
            self._config_dirty = False
            self._save_config_safe()
        return False

    def _save_config_safe(self) -> None:
        try:
            save_config(self.config)
        except Exception as exc:
            print(f"[markveil] Failed to save config: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Keyboard Shortcuts
    # ------------------------------------------------------------------
    def _on_key_press(self, _win: Gtk.Window, event: Gdk.EventKey) -> bool:
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.MOD1_MASK)
        keyval = event.keyval
        key_lower = Gdk.keyval_to_lower(keyval)

        # Function keys (no modifier)
        if not ctrl and not alt:
            if keyval == Gdk.KEY_F9:
                self.action_toggle_sidebar()
                return True
            if keyval == Gdk.KEY_F1:
                self.action_shortcuts()
                return True

        # Alt + Left / Right -> link history
        if alt and not ctrl:
            tab = self.get_active_tab()
            if tab is not None:
                if keyval == Gdk.KEY_Left:
                    tab.go_back()
                    return True
                if keyval == Gdk.KEY_Right:
                    tab.go_forward()
                    return True

        if not ctrl or alt:
            return False

        # Ctrl + Shift shortcuts (checked first to avoid shadowing Ctrl+<key>)
        if shift:
            if key_lower == Gdk.KEY_s:
                self.action_save_as()
                return True
            if key_lower == Gdk.KEY_w:
                self.action_toggle_watch()
                return True
            if key_lower == Gdk.KEY_a:
                self.action_ask_agent()
                return True
            if key_lower == Gdk.KEY_c:
                self.action_copy_file_path()
                return True
            if key_lower == Gdk.KEY_m:
                self.action_add_comment()
                return True
            if key_lower == Gdk.KEY_v:
                self.action_open_clipboard()
                return True
            if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
                self.action_switch_tab(-1)
                return True
            if keyval == Gdk.KEY_question:
                self.action_shortcuts()
                return True

        # Ctrl + <key> shortcuts (no Shift, or symbol keys like + / ?)
        if keyval == Gdk.KEY_question:
            self.action_shortcuts()
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.adjust_zoom(0.1)
            return True
        if keyval in (Gdk.KEY_minus, Gdk.KEY_underscore, Gdk.KEY_KP_Subtract):
            self.adjust_zoom(-0.1)
            return True
        if keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.set_zoom(1.0)
            return True
        if keyval == Gdk.KEY_Tab:
            self.action_switch_tab(1)
            return True
        if keyval == Gdk.KEY_backslash:
            self.action_toggle_split()
            return True

        if not shift:
            if key_lower == Gdk.KEY_n:
                self.action_new_tab()
                return True
            if key_lower == Gdk.KEY_o:
                self.action_open_file()
                return True
            if key_lower == Gdk.KEY_w:
                self.action_close_active_tab()
                return True
            if key_lower == Gdk.KEY_s:
                self.action_save()
                return True
            if key_lower == Gdk.KEY_e:
                self.action_cycle_view_mode()
                return True
            if key_lower == Gdk.KEY_r:
                self.action_reload()
                return True
            if key_lower == Gdk.KEY_b:
                self.action_toggle_sidebar()
                return True
            if key_lower == Gdk.KEY_f:
                self.action_open_search(replace=False)
                return True
            if key_lower == Gdk.KEY_h:
                self.action_open_search(replace=True)
                return True
            if key_lower == Gdk.KEY_p:
                self.action_print()
                return True
            if key_lower == Gdk.KEY_t:
                self.cycle_theme()
                return True
            if key_lower == Gdk.KEY_d:
                self.action_open_diff_picker()
                return True
            if key_lower == Gdk.KEY_q:
                if self.window is not None and not self._on_window_delete(
                    self.window, Gdk.Event.new(Gdk.EventType.DELETE)
                ):
                    self.quit()
                return True

        return False
