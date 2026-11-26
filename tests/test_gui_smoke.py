"""Real GTK3 + WebKit2 GUI smoke and regression tests for Markveil."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

try:
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    gi.require_version("GtkSource", "300")
    from gi.repository import Gdk, GLib, Gtk

    _GTK_AVAILABLE = bool(Gtk.init_check([])[0])
except Exception:  # pragma: no cover
    _GTK_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _GTK_AVAILABLE,
    reason="GTK3 display unavailable (Gtk.init_check failed)",
)


def _pump_events(duration_s: float = 0.12) -> None:
    """Drain pending GLib/GTK main-loop events for duration_s seconds."""
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.015)
    while ctx.pending():
        ctx.iteration(False)


def _run_app_scenario(app, scenario: Callable[[object], None]) -> None:
    """Run MarkdownViewerApp through its real app.run() lifecycle and execute scenario."""
    errors: list[BaseException] = []
    orig_excepthook = sys.excepthook

    def _capture_hook(exc_type, exc_value, exc_tb) -> None:
        errors.append(exc_value)
        orig_excepthook(exc_type, exc_value, exc_tb)

    def _runner() -> bool:
        try:
            _pump_events(0.25)
            scenario(app)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            try:
                for tab in list(app.get_all_tabs()):
                    tab.cleanup()
                if app.window is not None:
                    app.window.destroy()
            finally:
                app.quit()
        return False

    def _on_activate(_app) -> None:
        GLib.idle_add(_runner)

    app.connect_after("activate", _on_activate)
    sys.excepthook = _capture_hook
    try:
        app.run(["md-viewer"])
    finally:
        sys.excepthook = orig_excepthook

    if errors:
        raise errors[0]


def _relative_luminance(r: float, g: float, b: float) -> float:
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _blend_rgba(fg: Gdk.RGBA, bg: tuple[float, float, float]) -> tuple[float, float, float]:
    a = max(0.0, min(1.0, float(fg.alpha)))
    return (
        fg.red * a + bg[0] * (1.0 - a),
        fg.green * a + bg[1] * (1.0 - a),
        fg.blue * a + bg[2] * (1.0 - a),
    )


def _contrast_ratio(
    fg_rgb: tuple[float, float, float], bg_rgb: tuple[float, float, float]
) -> float:
    l1 = _relative_luminance(*fg_rgb)
    l2 = _relative_luminance(*bg_rgb)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    cleaned = hex_color.lstrip("#")
    return (
        int(cleaned[0:2], 16) / 255.0,
        int(cleaned[2:4], 16) / 255.0,
        int(cleaned[4:6], 16) / 255.0,
    )


def _sample_markdown() -> str:
    return """\
---
title: Smoke Studio Document
tags: [gtk3, webkit2, watch-mode]
---

# Smoke Studio

Introductory paragraph for **Markveil** verification.

## Task & Table

| Feature | Status |
| --- | --- |
| Multi-tab | Ready |
| Watch Mode | Active |

- [ ] First unchecked task
- [x] Completed task

## Math & Diagrams

Inline math $E = mc^2$ and block math:

$$
\\int_0^1 x\\,dx = \\frac{1}{2}
$$

```mermaid
graph LR
    A[Agent] --> B[Watch Mode]
    B --> C[Live Preview]
```

## Security Fence

```html
<script>alert("xss-in-code-fence")</script>
```
"""


def test_gui_studio_full_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify window, rendering, themes, modes, search, sidebar, watch reload, diff, and clean quit."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    doc = tmp_path / "studio_smoke.md"
    doc.write_text(_sample_markdown(), encoding="utf-8")

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.tab import DocumentTab

    opts = LaunchOptions(files=[str(doc)], watch=True)
    app = MarkdownViewerApp(launch_options=opts)

    def _verify(a: MarkdownViewerApp) -> None:
        assert a.window is not None
        assert a.notebook is not None
        assert a._content_stack.get_visible_child_name() == "tabs"
        assert a.notebook.get_n_pages() == 1
        assert not a.notebook.get_show_tabs()

        tab = a.get_active_tab()
        assert isinstance(tab, DocumentTab)
        assert tab.current_file == str(doc.resolve())
        assert tab.watch_enabled is True
        assert tab.dirty is False
        # P1-2: Opening a tab must render exactly once (not 3x!)
        assert tab.render_count == 1

        # Verify extracted headings & safe code fence rendering
        heading_texts = [h.text for h in tab.headings]
        assert heading_texts == [
            "Smoke Studio",
            "Task & Table",
            "Math & Diagrams",
            "Security Fence",
        ]
        assert tab.last_render_result is not None
        rendered_html = tab.last_render_result.html
        assert '<script>alert("xss-in-code-fence")</script>' not in rendered_html
        assert "xss-in-code-fence" in rendered_html

        # Theme switching across all curated themes
        for theme_id in ("folio", "paper", "obsidian", "sepia", "nordic"):
            a.set_theme(theme_id)
            _pump_events(0.06)
            assert a.resolved_theme == theme_id
            assert tab.theme_id == theme_id

        # View mode switching: preview -> split -> edit -> preview
        for mode in ("split", "edit", "preview"):
            tab.set_view_mode(mode)
            _pump_events(0.06)
            assert tab.view_mode == mode

        # Search bar open, query, and close
        tab.open_search(replace=False)
        _pump_events(0.05)
        assert tab.is_search_open() is True
        tab._search_entry.set_text("Watch Mode")
        _pump_events(0.06)
        tab.close_search()
        _pump_events(0.05)
        assert tab.is_search_open() is False

        # Sidebar toggle & tab cycling (all 4 tabs including Agentic Env)
        assert a.sidebar is not None
        a.action_toggle_sidebar()
        _pump_events(0.05)
        for stab in ("outline", "context", "comments", "env"):
            a.sidebar.set_active_tab(stab)
            _pump_events(0.04)
            assert a.sidebar.get_active_tab() == stab
        assert tab.context_report is not None
        assert tab.context_report.words > 20
        assert tab.context_report.est_tokens > 20

        # Watch Mode reload on external disk modification
        initial_rev = tab.revision_count
        updated_text = (
            _sample_markdown()
            + "\n## Live Agent Update\n\nAppended cleanly by agent.\n"
        )
        doc.write_text(updated_text, encoding="utf-8")

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and tab.revision_count <= initial_rev:
            _pump_events(0.08)

        assert tab.revision_count >= initial_rev + 1
        assert "Live Agent Update" in tab.get_text()
        assert tab.dirty is False

        # Visual Diff overlay & return to document
        tab.show_last_revision_diff(mode="unified")
        _pump_events(0.06)
        assert tab.diff_active is True
        tab.hide_diff_overlay()
        _pump_events(0.06)
        assert tab.diff_active is False

    _run_app_scenario(app, _verify)


def test_gui_multi_tab_and_readonly_quick_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify multi-tab notebook visibility, readonly enforcement, Save As sync, and quick mode."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    file_a = tmp_path / "a.md"
    file_b = tmp_path / "b.md"
    file_a.write_text("# Doc A\n\nAlpha content.\n", encoding="utf-8")
    file_b.write_text("# Doc B\n\nBeta content.\n", encoding="utf-8")

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions

    opts = LaunchOptions(files=[str(file_a)], quick=True, readonly=True)
    app = MarkdownViewerApp(launch_options=opts)

    def _verify(a: MarkdownViewerApp) -> None:
        assert a.notebook is not None
        assert a.notebook.get_n_pages() == 1
        assert not a.notebook.get_show_tabs()
        assert a.quick_mode is True
        assert a._menu_save_as.get_sensitive() is False
        assert a._agent_btn.get_sensitive() is False

        tab_a = a.get_active_tab()
        assert tab_a is not None
        assert tab_a.readonly is True
        assert tab_a.render_count == 1
        tab_a.set_view_mode("edit")
        assert tab_a.view_mode == "preview"

        # Opening second tab reveals tab bar
        tab_b = a.open_file(str(file_b), readonly=True)
        _pump_events(0.1)
        assert tab_b is not None
        assert tab_b.render_count == 1
        assert a.notebook.get_n_pages() == 2
        assert a.notebook.get_show_tabs() is True

        # Closing second tab hides tab bar again
        assert a.close_tab(tab_b, force=True) is True
        _pump_events(0.08)
        assert a.notebook.get_n_pages() == 1
        assert a.notebook.get_show_tabs() is False

    _run_app_scenario(app, _verify)


def test_folio_document_navigation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions

    source = tmp_path / "notes.md"
    source.write_text("# Field notes", encoding="utf-8")
    app = MarkdownViewerApp(LaunchOptions(files=[str(source)]))

    def verify(a: MarkdownViewerApp) -> None:
        first = a.get_active_tab()
        assert a.resolved_theme == "folio"
        assert first.render_count == 1
        assert first.source_buffer.get_style_scheme().get_id() == "markveil-folio"
        assert a._menu_save_as.get_sensitive() is True

        draft = a.open_text_tab(text="# Draft", display_name="notes.md", mode="edit")
        assert draft.render_count == 1
        rail = a.sidebar.documents
        assert rail.get_selected_row().document is draft
        assert not a.notebook.get_show_tabs()
        draft.source_buffer.insert_at_cursor(" changed")
        assert draft.dirty
        assert all(dot.get_visible() for _, dot in a._tab_labels[draft])

        rail.emit("row-activated", rail.get_row_at_index(0))
        assert a.get_active_tab() is first
        assert rail.get_selected_row().document is first
        assert a.sidebar._folder.get_visible()
        a.action_toggle_sidebar()
        assert a.notebook.get_show_tabs()
        a.notebook.reorder_child(draft, 0)
        a.action_toggle_sidebar()
        assert rail.get_row_at_index(0).document is draft
        assert rail.get_selected_row().document is first

        a.close_tab(first, force=True)
        assert rail.get_selected_row().document is draft
        assert not a.sidebar._folder.get_visible()
        a.close_tab(draft, force=True)
        assert a._content_stack.get_visible_child_name() == "welcome"
        assert not a.sidebar.get_visible()
        assert not a._statusbar.get_visible()

    _run_app_scenario(app, verify)


def test_dark_user_css_override_contrast_all_themes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0-1: Hostile dark PRIORITY_USER gtk.css must never create invisible sidebar buttons."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    hostile_css = b"""
    button { background-color: #111827; color: #ffffff; }
    button:disabled, button:disabled label { color: rgba(255, 255, 255, 0.5); }
    button:checked { background-color: #38bdf8; color: #ffffff; }
    row:selected, row:selected label { background-color: #0f172a; color: #ffffff; }
    """
    screen = Gdk.Screen.get_default()
    assert screen is not None
    hostile_provider = Gtk.CssProvider()
    hostile_provider.load_from_data(hostile_css)
    Gtk.StyleContext.add_provider_for_screen(
        screen, hostile_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )

    doc = tmp_path / "contrast.md"
    doc.write_text("# Contrast Test\n\nBody text.\n", encoding="utf-8")

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.themes import THEMES, THEME_ORDER

    app = MarkdownViewerApp(LaunchOptions(files=[str(doc)]))

    def _verify(a: MarkdownViewerApp) -> None:
        assert a.sidebar is not None
        a.sidebar.set_active_tab("comments")
        _pump_events(0.08)

        export_btn = a.sidebar._export_review_btn
        copy_btn = a.sidebar._copy_review_btn
        add_btn = a.sidebar._add_comment_btn

        for theme_id in THEME_ORDER:
            a.set_theme(theme_id)
            _pump_events(0.08)
            spec = THEMES[theme_id]
            surface_rgb = _hex_to_rgb(spec.surface)
            bg_rgb = _hex_to_rgb(spec.bg)
            accent_rgb = _hex_to_rgb(spec.accent)

            # Disabled state for Export… and Copy (no comments yet)
            assert export_btn.get_sensitive() is False
            assert copy_btn.get_sensitive() is False
            for btn in (export_btn, copy_btn):
                lbl = btn.get_child()
                assert lbl is not None
                fg = lbl.get_style_context().get_color(Gtk.StateFlags.INSENSITIVE)
                fg_rgb = _blend_rgba(fg, surface_rgb)
                ratio = _contrast_ratio(fg_rgb, surface_rgb)
                assert ratio >= 3.0, (
                    f"{theme_id} disabled {btn.get_label()!r} contrast {ratio:.2f} < 3.0"
                )

            # Enabled state for Export… and Copy
            export_btn.set_sensitive(True)
            copy_btn.set_sensitive(True)
            _pump_events(0.04)
            for btn in (export_btn, copy_btn):
                lbl = btn.get_child()
                assert lbl is not None
                fg = lbl.get_style_context().get_color(Gtk.StateFlags.NORMAL)
                fg_rgb = _blend_rgba(fg, bg_rgb)
                ratio = _contrast_ratio(fg_rgb, bg_rgb)
                assert ratio >= 4.5, (
                    f"{theme_id} enabled {btn.get_label()!r} contrast {ratio:.2f} < 4.5"
                )
            export_btn.set_sensitive(False)
            copy_btn.set_sensitive(False)

            # Primary "+ Add" button contrast on accent background
            add_lbl = add_btn.get_child()
            assert add_lbl is not None
            add_fg = add_lbl.get_style_context().get_color(Gtk.StateFlags.NORMAL)
            add_ratio = _contrast_ratio(_blend_rgba(add_fg, accent_rgb), accent_rgb)
            assert add_ratio >= 4.5, (
                f"{theme_id} '+ Add' button contrast {add_ratio:.2f} < 4.5"
            )

    try:
        _run_app_scenario(app, _verify)
    finally:
        Gtk.StyleContext.remove_provider_for_screen(screen, hostile_provider)


def test_comments_flow_dialog_validation_and_dirty_nav_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0-2 & P0-5: Verify + Add button, CommentEditorDialog validation, and dirty navigate guard."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    doc_a = tmp_path / "doc_a.md"
    doc_b = tmp_path / "doc_b.md"
    doc_a.write_text("# Doc A\n\n## Details\n\nOriginal A.\n", encoding="utf-8")
    doc_b.write_text("# Doc B\n\nTarget B.\n", encoding="utf-8")

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.dialogs import CommentEditorDialog, PreferencesDialog

    app = MarkdownViewerApp(LaunchOptions(files=[str(doc_a)]))

    def _verify(a: MarkdownViewerApp) -> None:
        tab = a.get_active_tab()
        assert tab is not None
        assert a.sidebar is not None

        # Comments sidebar + Add button exists and is enabled for active doc
        a.sidebar.set_active_tab("comments")
        _pump_events(0.05)
        assert a.sidebar._add_comment_btn.get_visible() is True
        assert a.sidebar._add_comment_btn.get_sensitive() is True

        # CommentEditorDialog validation: empty feedback disables Save, non-empty enables it
        dlg = CommentEditorDialog(
            a.window, heading="Details", quote="Original A.", initial_feedback=""
        )
        try:
            assert dlg._save_btn is not None
            assert dlg._save_btn.get_sensitive() is False
            assert dlg._validation_lbl.get_visible() is True
            dlg._heading_entry.set_text("Updated Details")
            dlg._textview.get_buffer().set_text("Clarify edge case.")
            _pump_events(0.04)
            assert dlg._save_btn.get_sensitive() is True
            assert dlg._validation_lbl.get_visible() is False
            assert dlg.get_heading() == "Updated Details"
            assert dlg.get_quote() == "Original A."
            assert dlg.get_feedback() == "Clarify edge case."
        finally:
            dlg.destroy()

        # PreferencesDialog includes preferred_agent
        prefs = PreferencesDialog(a.window, a.config)
        try:
            vals = prefs.get_values()
            assert "preferred_agent" in vals
            assert vals["preferred_agent"] == "auto"
        finally:
            prefs.destroy()

        # Add a comment and verify unexported tracking + sidebar updates
        tab.review_session.add(
            heading="Details", quote="Original A.", feedback="Tighten wording."
        )
        tab._local_comments_dirty = True
        tab._notify_state_changed()
        _pump_events(0.05)
        assert tab.has_unexported_comments() is True
        assert a.sidebar._export_review_btn.get_sensitive() is True
        assert a.sidebar._copy_review_btn.get_sensitive() is True
        assert a.sidebar._comments_count_label.get_text() == "1 comment"

        # Dirty-navigation guard: if confirm returns False, edits & comments stay intact!
        tab.source_buffer.insert_at_cursor("\nUnsaved edit")
        assert tab.dirty is True
        prompted = []

        def _deny_leave(_t):
            prompted.append(True)
            return False

        tab._on_confirm_leave = _deny_leave
        nav_ok = tab.navigate_to_file(str(doc_b))
        assert nav_ok is False
        assert prompted == [True]
        assert tab.current_file == str(doc_a.resolve())
        assert "Unsaved edit" in tab.get_text()
        assert len(tab.review_session) == 1

        # When leave is confirmed, navigation succeeds, resets review_session, and updates recents
        tab._on_confirm_leave = lambda _t: True
        nav_ok = tab.navigate_to_file(str(doc_b))
        assert nav_ok is True
        assert tab.current_file == str(doc_b.resolve())
        assert len(tab.review_session) == 0
        assert str(doc_b.resolve()) in a.config.recent_files

    _run_app_scenario(app, _verify)


def test_agentic_env_sidebar_filtering_and_empty_clipboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-1, P0-3, & R2-P0-2: Verify Agentic Env sidebar filtering, async race guard, & empty clipboard Split UX."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    skill_file = tmp_path / "SKILL.md"
    rule_file = tmp_path / "AGENTS.md"
    skill_file.write_text("# My Skill\n\nInstructions.\n", encoding="utf-8")
    rule_file.write_text("# Project Rules\n\nConventions.\n", encoding="utf-8")

    @dataclass(frozen=True)
    class _StubArtifact:
        path: str
        rel_path: str
        env_source: str
        scope: str
        kind: str
        name: str
        description: str

    from mdviewer.agentic_env import clear_catalog_cache
    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.clipboard import ClipboardPayload

    clear_catalog_cache()

    pending_sidebar_callbacks: list[Callable[[object], None]] = []
    pending_welcome_callbacks: list[Callable[[object], None]] = []

    def _deferred_sidebar_scan(callback, **_kwargs):
        pending_sidebar_callbacks.append(callback)

    def _deferred_welcome_scan(callback, **_kwargs):
        pending_welcome_callbacks.append(callback)

    monkeypatch.setattr(
        "mdviewer.sidebar.discover_agentic_catalog_async", _deferred_sidebar_scan
    )
    monkeypatch.setattr(
        "mdviewer.dialogs.discover_agentic_catalog_async", _deferred_welcome_scan
    )
    monkeypatch.setattr(
        "mdviewer.app.read_clipboard_smart",
        lambda prefer_html_convert=True: ClipboardPayload(text="", was_html=False),
    )

    app = MarkdownViewerApp(LaunchOptions(files=[str(rule_file)]))

    def _verify(a: MarkdownViewerApp) -> None:
        assert a.sidebar is not None
        assert a.welcome_view is not None
        a.sidebar.set_active_tab("env")
        _pump_events(0.05)

        # In-flight async scans were queued before manual set_agentic_artifacts()
        assert len(pending_sidebar_callbacks) >= 1

        manual_artifacts = [
            _StubArtifact(
                path=str(skill_file),
                rel_path="skills/demo/SKILL.md",
                env_source="claude",
                scope="global",
                kind="skill",
                name="demo-skill",
                description="Demo global skill",
            ),
            _StubArtifact(
                path=str(rule_file),
                rel_path="AGENTS.md",
                env_source="project",
                scope="project",
                kind="rule",
                name="AGENTS.md",
                description="Repo instructions",
            ),
        ]
        a.sidebar.set_agentic_artifacts(manual_artifacts)
        a.welcome_view.set_agentic_artifacts([manual_artifacts[0]])
        _pump_events(0.05)
        assert a.sidebar._env_count_label.get_text() == "2"
        assert a.welcome_view._welcome_env_count.get_text() == "1"

        # Now deliver stale in-flight async callbacks with 15 bogus artifacts: must be ignored!
        stale_catalog = [
            _StubArtifact(
                path=str(tmp_path / f"stale_{i}.md"),
                rel_path=f"stale_{i}.md",
                env_source="gemini",
                scope="global",
                kind="skill",
                name=f"stale-{i}",
                description="Stale background result",
            )
            for i in range(15)
        ]
        for cb in list(pending_sidebar_callbacks):
            cb(stale_catalog)
        for cb in list(pending_welcome_callbacks):
            cb(stale_catalog)
        _pump_events(0.08)
        assert a.sidebar._env_count_label.get_text() == "2"
        assert a.welcome_view._welcome_env_count.get_text() == "1"

        # Filter by scope: project
        a.sidebar._env_scope_buttons["project"].set_active(True)
        _pump_events(0.04)
        assert a.sidebar._env_count_label.get_text() == "1"

        # Reset scope to all and filter by search query
        a.sidebar._env_scope_buttons["all"].set_active(True)
        a.sidebar._env_search_entry.set_text("demo-skill")
        _pump_events(0.04)
        assert a.sidebar._env_count_label.get_text() == "1"

        # Empty clipboard opens in Split mode with visible InfoBar prompt
        a.action_open_clipboard()
        _pump_events(0.06)
        clip_tab = a.get_active_tab()
        assert clip_tab is not None
        assert clip_tab.clipboard_mode is True
        assert clip_tab.view_mode == "split"
        assert clip_tab._notice_infobar.get_visible() is True

        # Loading clipboard payload hides notice and records history
        clip_tab.load_clipboard_payload("# Captured\n\nFrom clipboard.", was_html=False)
        _pump_events(0.05)
        assert clip_tab._notice_infobar.get_visible() is False
        assert "Captured" in clip_tab.get_text()

    _run_app_scenario(app, _verify)


def test_preview_selection_request_add_comment_prefills_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R2-P0-1: Selecting preview text in WebKit2 must prefill exact quote and heading."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    doc = tmp_path / "selection_test.md"
    doc.write_text(
        "# Overview\n\nIntro paragraph.\n\n## Architecture\n\n"
        "Markveil preserves exact preview selection quotes cleanly.\n",
        encoding="utf-8",
    )

    import mdviewer.tab as tab_mod
    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.dialogs import CommentEditorDialog

    captured: list[tuple[str, str]] = []

    class _CapturingCommentDialog(CommentEditorDialog):
        def run(self) -> int:
            captured.append((self.get_heading(), self.get_quote()))
            return Gtk.ResponseType.CANCEL

    monkeypatch.setattr(tab_mod, "CommentEditorDialog", _CapturingCommentDialog)

    app = MarkdownViewerApp(LaunchOptions(files=[str(doc)]))

    def _verify(a: MarkdownViewerApp) -> None:
        tab = a.get_active_tab()
        assert tab is not None

        # Wait until WebKit2 finishes loading the rendered preview and JS bridge
        ready: list[bool] = []
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not ready:
            done_flag: list[str | None] = []
            tab._eval_js(
                "typeof window.__markveilGetSelectionPayload === 'function' ? 'ok' : ''",
                callback=lambda val: done_flag.append(val),
            )
            _pump_events(0.08)
            if done_flag and done_flag[0] == "ok":
                ready.append(True)
        assert ready, "WebKit2 preview JS bridge did not initialize in time"

        # Select the exact paragraph text inside .markdown-container under ## Architecture
        selected_text: list[str | None] = []
        tab._eval_js(
            "(function(){"
            "var ps = document.querySelectorAll('.markdown-container p');"
            "var target = null;"
            "for (var i = 0; i < ps.length; i++) {"
            "  if (ps[i].textContent.indexOf('Markveil preserves exact preview selection') !== -1) {"
            "    target = ps[i]; break;"
            "  }"
            "}"
            "if (!target) return '';"
            "var range = document.createRange();"
            "range.selectNodeContents(target);"
            "var sel = window.getSelection();"
            "sel.removeAllRanges();"
            "sel.addRange(range);"
            "return sel.toString().trim();"
            "})();",
            callback=lambda val: selected_text.append(val),
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not selected_text:
            _pump_events(0.05)
        assert selected_text == [
            "Markveil preserves exact preview selection quotes cleanly."
        ]

        tab.request_add_comment()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not captured:
            _pump_events(0.05)

        assert captured == [
            (
                "Architecture",
                "Markveil preserves exact preview selection quotes cleanly.",
            )
        ]

    _run_app_scenario(app, _verify)
    stderr = capsys.readouterr().err
    assert "Failed to parse selection payload" not in stderr


def test_html_clipboard_history_badge_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R2-P1-1: HTML clipboard captures record cleanly and display [HTML → MD] in popovers."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions
    from mdviewer.clipboard import ClipboardPayload, get_clipboard_history

    get_clipboard_history().clear()
    monkeypatch.setattr(
        "mdviewer.app.read_clipboard_smart",
        lambda prefer_html_convert=True: ClipboardPayload(text="", was_html=False),
    )

    app = MarkdownViewerApp(LaunchOptions(files=[]))

    def _verify(a: MarkdownViewerApp) -> None:
        a.action_open_clipboard()
        _pump_events(0.05)
        clip_tab = a.get_active_tab()
        assert clip_tab is not None
        assert a.welcome_view is not None

        clip_tab.load_clipboard_payload("Plain snippet line", was_html=False, record_history=True)
        clip_tab.load_clipboard_payload(
            "# Converted Heading\n\nRich HTML body.", was_html=True, record_history=True
        )
        _pump_events(0.05)

        entries = get_clipboard_history().entries()
        assert len(entries) == 2
        assert entries[0].source == "html"
        assert entries[1].source == "text"

        # Tab clipboard history popover labels
        clip_tab._refresh_clipboard_history_popover(clip_tab._clip_history_popover)
        tab_labels = [
            child.get_label()
            for child in clip_tab._clip_history_box.get_children()
            if isinstance(child, Gtk.ModelButton)
        ]
        assert "[HTML → MD] # Converted Heading" in tab_labels
        assert "[Text] Plain snippet line" in tab_labels

        # WelcomeView clipboard history popover labels
        a.welcome_view._refresh_clipboard_history_popover(
            a.welcome_view._clip_history_popover
        )
        welcome_labels = [
            child.get_label()
            for child in a.welcome_view._clip_history_box.get_children()
            if isinstance(child, Gtk.ModelButton)
        ]
        assert "[HTML → MD] # Converted Heading" in welcome_labels
        assert "[Text] Plain snippet line" in welcome_labels

    _run_app_scenario(app, _verify)
    get_clipboard_history().clear()
    stderr = capsys.readouterr().err
    assert "Failed to record clipboard history" not in stderr


def test_context_inspector_agentic_card_sibling_links_and_live_meta_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2-P2-1 & R2-P2-2: Context Inspector shows AgenticArtifact card, clickable siblings, & live meta sync."""
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    repo = tmp_path / "demo_repo"
    (repo / ".git").mkdir(parents=True)
    skill_dir = repo / "skills" / "demo-skill"
    refs_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    refs_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)

    guide_file = refs_dir / "guide.md"
    guide_file.write_text("# Sibling Guide\n\nHelpful reference.\n", encoding="utf-8")
    script_file = scripts_dir / "check.py"
    script_file.write_text("print('ok')\n", encoding="utf-8")

    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: demo-skill\n"
        "description: Initial skill summary\n"
        "triggers: [deploy, audit]\n"
        'globs: ["**/*.py"]\n'
        "alwaysApply: true\n"
        "---\n\n"
        "# Demo Skill\n\n"
        "Follow these verification instructions carefully.\n",
        encoding="utf-8",
    )

    from mdviewer.app import MarkdownViewerApp
    from mdviewer.cli import LaunchOptions

    def _collect_label_texts(widget: Gtk.Widget) -> list[str]:
        texts: list[str] = []
        if isinstance(widget, Gtk.Label):
            texts.append(widget.get_text())
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                texts.extend(_collect_label_texts(child))
        return texts

    app = MarkdownViewerApp(LaunchOptions(files=[str(skill_file)]))

    def _verify(a: MarkdownViewerApp) -> None:
        tab = a.get_active_tab()
        assert tab is not None
        assert a.sidebar is not None
        assert tab.context_report is not None
        assert tab.context_report.agentic_artifact is not None

        # R2-P2-2: Initial token_estimate synced with ContextReport.est_tokens
        assert tab._agentic_meta is not None
        assert tab._agentic_meta["token_estimate"] == tab.context_report.est_tokens
        assert tab.last_render_result is not None
        assert f"~{tab.context_report.est_tokens:,} tok" in tab.last_render_result.html

        # R2-P2-1: Context Inspector renders Agentic Artifact card with metadata & sibling links
        a.sidebar.set_active_tab("context")
        _pump_events(0.05)
        assert a.sidebar._agentic_context_card is not None
        card_texts = _collect_label_texts(a.sidebar._agentic_context_card)
        joined_card = " | ".join(card_texts)
        assert "project" in joined_card
        assert "skill" in joined_card
        assert "Always Apply" in joined_card
        assert "deploy, audit" in joined_card
        assert "**/*.py" in joined_card

        sibling_labels = [btn.get_label() for btn in a.sidebar._context_sibling_buttons]
        assert "references/guide.md" in sibling_labels
        assert "scripts/check.py" in sibling_labels

        # Clicking a sibling link button opens the sibling file directly in a tab
        guide_btn = next(
            btn
            for btn in a.sidebar._context_sibling_buttons
            if btn.get_label() == "references/guide.md"
        )
        guide_btn.clicked()
        _pump_events(0.08)
        opened = a.get_active_tab()
        assert opened is not None
        assert opened.current_file == str(guide_file.resolve())

        # Switch back to SKILL.md tab and verify live in-memory frontmatter + token sync
        a.open_file(str(skill_file))
        _pump_events(0.05)
        skill_tab = a.get_active_tab()
        assert skill_tab is tab

        updated_buffer = (
            "---\n"
            "name: live-renamed-skill\n"
            "description: Live edited description\n"
            "triggers: [live-trigger]\n"
            'globs: ["src/*.ts"]\n'
            "alwaysApply: false\n"
            "---\n\n"
            "# Demo Skill\n\n"
            + ("Expanded live documentation body text. " * 25)
            + "\n"
        )
        skill_tab.source_buffer.set_text(updated_buffer)
        skill_tab.render_preview()
        _pump_events(0.06)

        assert skill_tab.context_report is not None
        assert skill_tab._agentic_meta is not None
        assert skill_tab._agentic_meta["token_estimate"] == skill_tab.context_report.est_tokens
        assert skill_tab._agentic_meta["name"] == "live-renamed-skill"
        assert skill_tab._agentic_meta["description"] == "Live edited description"
        assert skill_tab._agentic_meta["triggers"] == ["live-trigger"]
        assert skill_tab._agentic_meta["globs"] == ["src/*.ts"]
        assert skill_tab._agentic_meta["always_apply"] is False
        assert skill_tab.last_render_result is not None
        assert "live-renamed-skill" in skill_tab.last_render_result.html
        assert f"~{skill_tab.context_report.est_tokens:,} tok" in skill_tab.last_render_result.html

    _run_app_scenario(app, _verify)


def test_cold_gi_imports_require_gdk3() -> None:
    """Importing GUI modules in a fresh interpreter must bind Gdk 3.0 without GTK4 conflicts."""
    import subprocess

    for mod in ("mdviewer.app", "mdviewer.tab", "mdviewer.dialogs", "mdviewer.clipboard"):
        proc = subprocess.run(
            [sys.executable, "-W", "error::Warning", "-c", f"import {mod}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, f"Cold import of {mod} failed: {proc.stderr}"
