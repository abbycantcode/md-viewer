"""Real GTK3 + WebKit2 GUI smoke tests for Markveil."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

import pytest

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    gi.require_version("GtkSource", "300")
    from gi.repository import GLib, Gtk

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

        # Theme switching across all 4 curated themes
        for theme_id in ("paper", "obsidian", "sepia", "nordic"):
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

        # Sidebar toggle & tab cycling
        assert a.sidebar is not None
        a.action_toggle_sidebar()
        _pump_events(0.05)
        for stab in ("outline", "context", "comments"):
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
    """Verify multi-tab notebook visibility, readonly enforcement, and --quick chrome hiding."""
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

        tab_a = a.get_active_tab()
        assert tab_a is not None
        assert tab_a.readonly is True
        tab_a.set_view_mode("edit")
        assert tab_a.view_mode == "preview"

        # Opening second tab reveals tab bar
        tab_b = a.open_file(str(file_b), readonly=True)
        _pump_events(0.1)
        assert tab_b is not None
        assert a.notebook.get_n_pages() == 2
        assert a.notebook.get_show_tabs() is True

        # Closing second tab hides tab bar again
        assert a.close_tab(tab_b, force=True) is True
        _pump_events(0.08)
        assert a.notebook.get_n_pages() == 1
        assert a.notebook.get_show_tabs() is False

    _run_app_scenario(app, _verify)
