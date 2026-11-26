"""Document sidebar with Outline, Context Inspector, and Review Comments tabs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Pango  # noqa: E402

from mdviewer.clipboard import write_clipboard_text  # noqa: E402
from mdviewer.context_inspector import DocumentContextReport, SectionStats  # noqa: E402
from mdviewer.markdown_engine import HeadingItem  # noqa: E402
from mdviewer.review_comments import (  # noqa: E402
    ReviewComment,
    default_review_path,
    export_markdown,
)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


class DocumentSidebar(Gtk.Box):
    """Three-tab document sidebar: Outline, Context Inspector, and Review Comments."""

    def __init__(
        self,
        *,
        on_heading_clicked: Callable[[HeadingItem], None] | None = None,
        on_section_clicked: Callable[[SectionStats], None] | None = None,
        on_edit_comment: Callable[[ReviewComment], None] | None = None,
        on_delete_comment: Callable[[str], None] | None = None,
        on_tab_changed: Callable[[str], None] | None = None,
        on_status_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("mdv-sidebar")
        self.set_size_request(200, -1)

        self._on_heading_clicked = on_heading_clicked
        self._on_section_clicked = on_section_clicked
        self._on_edit_comment = on_edit_comment
        self._on_delete_comment = on_delete_comment
        self._on_tab_changed = on_tab_changed
        self._on_status_message = on_status_message

        self._current_file: str | None = None
        self._current_comments: list[ReviewComment] = []
        self._outline_rows: dict[str, Gtk.ListBoxRow] = {}
        self._shown_headings: list[HeadingItem] | None = None
        self._shown_report: DocumentContextReport | None = None
        self._active_slug: str = ""
        self._suppress_outline_select = False

        section = Gtk.Label(label="Open documents", xalign=0)
        section.get_style_context().add_class("rail-title")
        self.pack_start(section, False, False, 0)
        self.documents = Gtk.ListBox()
        self.documents.get_style_context().add_class("open-documents")
        self.documents.set_selection_mode(Gtk.SelectionMode.SINGLE)
        files = Gtk.ScrolledWindow()
        files.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        files.set_max_content_height(156)
        files.set_propagate_natural_height(True)
        files.add(self.documents)
        self.pack_start(files, False, False, 0)

        # Header with 3-tab StackSwitcher
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.get_style_context().add_class("sidebar-header")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.connect("notify::visible-child-name", self._handle_stack_changed)

        self.switcher = Gtk.StackSwitcher()
        self.switcher.set_stack(self.stack)
        self.switcher.set_homogeneous(False)
        self.switcher.set_hexpand(True)
        header.pack_start(self.switcher, True, True, 0)
        self.pack_start(header, False, False, 0)

        # Build the 3 tabs
        self._build_outline_tab()
        self._build_context_tab()
        self._build_comments_tab()

        self.pack_start(self.stack, True, True, 0)
        self._folder = Gtk.Box(spacing=7)
        self._folder.get_style_context().add_class("workspace-location")
        self._folder.pack_start(
            Gtk.Image.new_from_icon_name("folder-symbolic", Gtk.IconSize.MENU), False, False, 0
        )
        self._folder_name = Gtk.Label(xalign=0)
        self._folder_name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._folder.pack_start(self._folder_name, True, True, 0)
        self._folder.show_all()
        self._folder.set_no_show_all(True)
        self.pack_end(self._folder, False, False, 0)
        for button, name in zip(self.switcher.get_children(), ("Outline", "Context", "Comments")):
            button.set_tooltip_text(name)
            button.get_accessible().set_name(name)

    # ------------------------------------------------------------------
    # Tab Builders
    # ------------------------------------------------------------------
    def _build_outline_tab(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._outline_list = Gtk.ListBox()
        self._outline_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._outline_list.set_activate_on_single_click(True)
        self._outline_list.connect("row-activated", self._handle_outline_activated)

        self._outline_empty = Gtk.Label(label="No headings in this document.")
        self._outline_empty.get_style_context().add_class("muted-label")
        self._outline_empty.set_margin_top(20)
        self._outline_empty.set_margin_start(12)
        self._outline_empty.set_margin_end(12)
        self._outline_empty.set_line_wrap(True)
        self._outline_list.set_placeholder(self._outline_empty)
        self._outline_empty.show()

        caption = Gtk.Label(label="In this document", xalign=0)
        caption.get_style_context().add_class("rail-title")
        box.pack_start(caption, False, False, 0)
        scrolled.add(self._outline_list)
        box.pack_start(scrolled, True, True, 0)
        self.stack.add_titled(box, "outline", "Outline")
        self.stack.child_set_property(box, "icon-name", "view-list-symbolic")

    def _build_context_tab(self) -> None:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._context_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._context_box.set_margin_top(6)
        self._context_box.set_margin_bottom(10)
        scrolled.add(self._context_box)

        self.stack.add_titled(scrolled, "context", "Context")
        self.stack.child_set_property(scrolled, "icon-name", "dialog-information-symbolic")

    def _build_comments_tab(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_margin_top(6)
        actions.set_margin_start(8)
        actions.set_margin_end(8)

        self._comments_count_label = Gtk.Label(label="0 comments")
        self._comments_count_label.get_style_context().add_class("sidebar-section-title")
        self._comments_count_label.set_halign(Gtk.Align.START)
        actions.pack_start(self._comments_count_label, True, True, 0)

        self._copy_review_btn = Gtk.Button(label="Copy")
        self._copy_review_btn.set_tooltip_text("Copy Review Markdown to clipboard")
        self._copy_review_btn.connect("clicked", self._handle_copy_review)
        actions.pack_end(self._copy_review_btn, False, False, 0)

        self._export_review_btn = Gtk.Button(label="Export…")
        self._export_review_btn.set_tooltip_text("Export Review Comments as Markdown file")
        self._export_review_btn.connect("clicked", self._handle_export_review)
        actions.pack_end(self._export_review_btn, False, False, 0)

        outer.pack_start(actions, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._comments_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._comments_box.set_margin_bottom(10)
        scrolled.add(self._comments_box)
        outer.pack_start(scrolled, True, True, 0)

        self.stack.add_titled(outer, "comments", "Comments")
        self.stack.child_set_property(outer, "icon-name", "mail-message-new-symbolic")

    # ------------------------------------------------------------------
    # Tab Selection API
    # ------------------------------------------------------------------
    def set_active_tab(self, tab_name: str) -> None:
        if tab_name in ("outline", "context", "comments"):
            self.stack.set_visible_child_name(tab_name)

    def get_active_tab(self) -> str:
        return self.stack.get_visible_child_name() or "outline"

    def _handle_stack_changed(self, stack: Gtk.Stack, _pspec: object) -> None:
        name = stack.get_visible_child_name()
        if name and self._on_tab_changed:
            self._on_tab_changed(name)

    # ------------------------------------------------------------------
    # Outline Updates
    # ------------------------------------------------------------------
    def update_outline(
        self, headings: list[HeadingItem], file_path: str | None = None
    ) -> None:
        if self._current_file != file_path or self._shown_headings is None:
            parent = Path(file_path).parent if file_path else None
            self._folder.set_visible(parent is not None)
            self._folder_name.set_text((parent.name or str(parent)) if parent else "")
            self._folder.set_tooltip_text(str(parent) if parent else None)
        self._current_file = file_path
        if headings == self._shown_headings:
            return
        self._shown_headings = headings
        self._outline_rows.clear()
        for child in list(self._outline_list.get_children()):
            self._outline_list.remove(child)

        for heading in headings:
            row = Gtk.ListBoxRow()
            row.heading_item = heading  # type: ignore[attr-defined]

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            indent = max(0, (heading.level - 1) * 12)
            hbox.set_margin_start(indent)

            lbl = Gtk.Label(label=heading.text)
            lbl.set_xalign(0.0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_tooltip_text(f"H{heading.level}: {heading.text} (line {heading.line})")
            hbox.pack_start(lbl, True, True, 0)

            copy_btn = Gtk.Button(label="#")
            copy_btn.get_style_context().add_class("anchor-copy")
            copy_btn.set_relief(Gtk.ReliefStyle.NONE)
            copy_btn.set_tooltip_text("Copy heading anchor link")
            copy_btn.set_focus_on_click(False)
            copy_btn.connect("clicked", self._handle_copy_heading_link, heading)
            hbox.pack_end(copy_btn, False, False, 0)

            row.add(hbox)
            self._outline_list.add(row)
            if heading.slug and heading.slug not in self._outline_rows:
                self._outline_rows[heading.slug] = row

        self._outline_list.show_all()
        if self._active_slug:
            self.set_active_heading(self._active_slug)

    def set_active_heading(self, slug: str) -> None:
        self._active_slug = slug or ""
        for row_slug, row in self._outline_rows.items():
            ctx = row.get_style_context()
            if row_slug == self._active_slug:
                ctx.add_class("outline-row-active")
            else:
                ctx.remove_class("outline-row-active")

    def _handle_outline_activated(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if self._suppress_outline_select or row is None:
            return
        heading = getattr(row, "heading_item", None)
        if heading is not None and self._on_heading_clicked:
            self._on_heading_clicked(heading)

    def _handle_copy_heading_link(self, _btn: Gtk.Button, heading: HeadingItem) -> None:
        prefix = Path(self._current_file).name if self._current_file else ""
        ref = f"{prefix}#{heading.slug}" if prefix else f"#{heading.slug}"
        write_clipboard_text(ref)
        if self._on_status_message:
            self._on_status_message(f"Copied {ref}")

    # ------------------------------------------------------------------
    # Context Inspector Updates
    # ------------------------------------------------------------------
    def update_context(self, report: DocumentContextReport | None) -> None:
        if report is not None and report is self._shown_report:
            return
        self._shown_report = report
        for child in list(self._context_box.get_children()):
            self._context_box.remove(child)

        if report is None:
            lbl = Gtk.Label(label="Open a document to inspect context metrics.")
            lbl.get_style_context().add_class("muted-label")
            lbl.set_margin_top(20)
            lbl.set_line_wrap(True)
            self._context_box.pack_start(lbl, False, False, 0)
            self._context_box.show_all()
            return

        # Primary metrics card
        metrics_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        metrics_card.get_style_context().add_class("context-metric-card")

        title = Gtk.Label(label="Document metrics")
        title.get_style_context().add_class("sidebar-section-title")
        title.set_xalign(0.0)
        metrics_card.pack_start(title, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        rows_data = [
            ("Words", f"{report.words:,}"),
            ("Characters", f"{report.chars:,}"),
            ("Size", _format_bytes(report.bytes_size)),
            ("Lines", f"{report.lines:,}"),
            (
                "Reading time",
                f"~{report.reading_minutes} min" if report.reading_minutes else "< 1 min",
            ),
        ]
        for idx, (k, v) in enumerate(rows_data):
            kl = Gtk.Label(label=k)
            kl.get_style_context().add_class("muted-label")
            kl.set_xalign(0.0)
            vl = Gtk.Label(label=v)
            vl.set_xalign(1.0)
            vl.set_hexpand(True)
            grid.attach(kl, 0, idx, 1, 1)
            grid.attach(vl, 1, idx, 1, 1)
        metrics_card.pack_start(grid, False, False, 0)
        self._context_box.pack_start(metrics_card, False, False, 0)

        # Heuristic token budget card
        token_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        token_card.get_style_context().add_class("context-metric-card")

        tok_title = Gtk.Label(label="Estimated tokens")
        tok_title.get_style_context().add_class("sidebar-section-title")
        tok_title.set_xalign(0.0)
        token_card.pack_start(tok_title, False, False, 0)

        tok_total = Gtk.Label(label=f"~{report.est_tokens:,} est. tokens")
        tok_total.set_xalign(0.0)
        token_card.pack_start(tok_total, False, False, 0)

        tok_split = Gtk.Label(
            label=f"Prose: ~{report.prose_tokens:,}  ·  Code: ~{report.code_tokens:,}"
        )
        tok_split.get_style_context().add_class("muted-label")
        tok_split.set_xalign(0.0)
        tok_split.set_line_wrap(True)
        token_card.pack_start(tok_split, False, False, 0)

        if report.est_tokens > 0:
            code_bar = Gtk.ProgressBar()
            code_bar.set_fraction(
                max(0.0, min(1.0, report.prose_tokens / max(1, report.est_tokens)))
            )
            code_bar.set_tooltip_text("Prose share of estimated tokens")
            token_card.pack_start(code_bar, False, False, 0)

        if report.is_skill_doc:
            fm_info = (
                "Front-matter keys: " + ", ".join(report.front_matter_keys)
                if report.front_matter_keys
                else "No YAML front-matter keys found."
            )
            skill_lbl = Gtk.Label(label=f"Agent instruction doc · {fm_info}")
            skill_lbl.get_style_context().add_class("muted-label")
            skill_lbl.set_xalign(0.0)
            skill_lbl.set_line_wrap(True)
            token_card.pack_start(skill_lbl, False, False, 0)

        self._context_box.pack_start(token_card, False, False, 0)

        # Warnings card (SKILL.md / oversized section checks)
        if report.warnings:
            warn_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            warn_card.get_style_context().add_class("context-metric-card")
            w_hdr = Gtk.Label(label=f"Checks and warnings ({len(report.warnings)})")
            w_hdr.get_style_context().add_class("sidebar-section-title")
            w_hdr.set_xalign(0.0)
            warn_card.pack_start(w_hdr, False, False, 0)

            for warning in report.warnings:
                wl = Gtk.Label(label=f"• {warning}")
                wl.set_xalign(0.0)
                wl.set_line_wrap(True)
                wl.set_max_width_chars(30)
                warn_card.pack_start(wl, False, False, 0)

            self._context_box.pack_start(warn_card, False, False, 0)

        # Per-section breakdown
        if report.sections:
            sec_hdr = Gtk.Label(label="Tokens by section")
            sec_hdr.get_style_context().add_class("sidebar-section-title")
            sec_hdr.set_xalign(0.0)
            sec_hdr.set_margin_start(8)
            sec_hdr.set_margin_top(4)
            self._context_box.pack_start(sec_hdr, False, False, 0)

            sec_list = Gtk.ListBox()
            sec_list.set_selection_mode(Gtk.SelectionMode.NONE)
            sec_list.set_activate_on_single_click(True)
            sec_list.connect("row-activated", self._handle_section_activated)

            for sec in report.sections:
                row = Gtk.ListBoxRow()
                row.section_stats = sec  # type: ignore[attr-defined]

                sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

                name_lbl = Gtk.Label(label=sec.title)
                name_lbl.set_xalign(0.0)
                name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                top.pack_start(name_lbl, True, True, 0)

                meta_lbl = Gtk.Label(label=f"~{sec.est_tokens:,} ({sec.pct_of_total:.0f}%)")
                meta_lbl.get_style_context().add_class("muted-label")
                top.pack_end(meta_lbl, False, False, 0)
                sbox.pack_start(top, False, False, 0)

                bar = Gtk.ProgressBar()
                bar.set_fraction(max(0.0, min(1.0, sec.pct_of_total / 100.0)))
                sbox.pack_start(bar, False, False, 0)

                row.add(sbox)
                sec_list.add(row)

            self._context_box.pack_start(sec_list, False, False, 0)

        self._context_box.show_all()

    def _handle_section_activated(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if row is None:
            return
        sec = getattr(row, "section_stats", None)
        if sec is not None and self._on_section_clicked:
            self._on_section_clicked(sec)

    # ------------------------------------------------------------------
    # Review Comments Updates
    # ------------------------------------------------------------------
    def update_comments(
        self, comments: list[ReviewComment], source_path: str | None = None
    ) -> None:
        self._current_file = source_path
        if self._comments_box.get_children() and comments == self._current_comments:
            return
        # The review session edits its comment objects in place.
        self._current_comments = [replace(comment) for comment in comments]

        count = len(comments)
        self._comments_count_label.set_text(
            f"{count} comment" if count == 1 else f"{count} comments"
        )
        self._copy_review_btn.set_sensitive(count > 0)
        self._export_review_btn.set_sensitive(count > 0)

        for child in list(self._comments_box.get_children()):
            self._comments_box.remove(child)

        if not comments:
            empty = Gtk.Label(
                label="Select text in Preview and click \"Add comment\" to attach review feedback."
            )
            empty.get_style_context().add_class("muted-label")
            empty.set_margin_top(18)
            empty.set_margin_start(10)
            empty.set_margin_end(10)
            empty.set_line_wrap(True)
            empty.set_xalign(0.0)
            self._comments_box.pack_start(empty, False, False, 0)
            self._comments_box.show_all()
            return

        for comment in comments:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            card.get_style_context().add_class("review-comment-card")

            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            heading_lbl = Gtk.Label(label=comment.heading)
            heading_lbl.get_style_context().add_class("sidebar-section-title")
            heading_lbl.set_xalign(0.0)
            heading_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            hdr.pack_start(heading_lbl, True, True, 0)

            edit_btn = Gtk.Button(label="Edit")
            edit_btn.connect("clicked", self._handle_edit_comment_clicked, comment)
            hdr.pack_end(edit_btn, False, False, 0)

            del_btn = Gtk.Button(label="×")
            del_btn.set_tooltip_text("Delete comment")
            del_btn.connect("clicked", self._handle_delete_comment_clicked, comment.id)
            hdr.pack_end(del_btn, False, False, 0)
            card.pack_start(hdr, False, False, 0)

            if comment.quote:
                snippet = comment.quote.replace("\n", " ")
                if len(snippet) > 140:
                    snippet = snippet[:137] + "…"
                quote_lbl = Gtk.Label(label=f'"{snippet}"')
                quote_lbl.get_style_context().add_class("muted-label")
                quote_lbl.set_xalign(0.0)
                quote_lbl.set_line_wrap(True)
                quote_lbl.set_max_width_chars(28)
                card.pack_start(quote_lbl, False, False, 0)

            fb_lbl = Gtk.Label(label=comment.feedback)
            fb_lbl.set_xalign(0.0)
            fb_lbl.set_line_wrap(True)
            fb_lbl.set_max_width_chars(28)
            card.pack_start(fb_lbl, False, False, 0)

            self._comments_box.pack_start(card, False, False, 0)

        self._comments_box.show_all()

    def _handle_edit_comment_clicked(
        self, _btn: Gtk.Button, comment: ReviewComment
    ) -> None:
        if self._on_edit_comment:
            self._on_edit_comment(comment)

    def _handle_delete_comment_clicked(self, _btn: Gtk.Button, comment_id: str) -> None:
        if self._on_delete_comment:
            self._on_delete_comment(comment_id)

    def _handle_copy_review(self, _btn: Gtk.Button) -> None:
        source_name = self._current_file or "Document"
        md = export_markdown(source_name, self._current_comments)
        write_clipboard_text(md)
        if self._on_status_message:
            self._on_status_message("Copied review comments as Markdown")

    def _handle_export_review(self, _btn: Gtk.Button) -> None:
        self.export_review_dialog()

    def export_review_dialog(self, parent_window: Gtk.Window | None = None) -> str | None:
        """Open a Save dialog prefilled with <stem>.review.md and write exported Markdown."""
        toplevel = parent_window or self.get_toplevel()
        if not isinstance(toplevel, Gtk.Window):
            toplevel = None

        suggested = Path(default_review_path(self._current_file))
        dialog = Gtk.FileChooserNative.new(
            "Export Review Comments",
            toplevel,
            Gtk.FileChooserAction.SAVE,
            "_Save",
            "_Cancel",
        )
        dialog.set_do_overwrite_confirmation(True)
        if suggested.parent.is_dir():
            dialog.set_current_folder(str(suggested.parent))
        dialog.set_current_name(suggested.name)

        md_filter = Gtk.FileFilter()
        md_filter.set_name("Markdown files (*.md)")
        md_filter.add_pattern("*.md")
        dialog.add_filter(md_filter)

        saved_path: str | None = None
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            if filename:
                content = export_markdown(
                    self._current_file or "Document", self._current_comments
                )
                try:
                    Path(filename).write_text(content, encoding="utf-8")
                    saved_path = filename
                    if self._on_status_message:
                        self._on_status_message(f"Exported review to {Path(filename).name}")
                except OSError as exc:
                    if self._on_status_message:
                        self._on_status_message(f"Export failed: {exc}")
        dialog.destroy()
        return saved_path
