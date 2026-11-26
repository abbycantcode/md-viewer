"""Welcome view and modal/utility dialogs for Markveil."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, WebKit2  # noqa: E402

from mdviewer.agent_cli import (  # noqa: E402
    PROMPT_PRESETS,
    AgentTaskHandle,
    detect_available_agents,
    run_agent_async,
)
from mdviewer.clipboard import write_clipboard_text  # noqa: E402
from mdviewer.config import AppConfig  # noqa: E402
from mdviewer.gtk_styles import get_webview_bg_rgba  # noqa: E402
from mdviewer.markdown_engine import render_document  # noqa: E402
from mdviewer.themes import THEMES, THEME_ORDER  # noqa: E402

try:
    from mdviewer.agent_cli import (  # noqa: E402
        SUPPORTED_AGENT_IDS,
        detect_installed_agents,
    )
except ImportError:  # pragma: no cover - fallback before backend-core merges
    SUPPORTED_AGENT_IDS = ("claude", "codex", "agy")
    detect_installed_agents = detect_available_agents

try:
    from mdviewer.clipboard import get_clipboard_history  # noqa: E402
except ImportError:  # pragma: no cover - fallback before backend-core merges
    get_clipboard_history = None  # type: ignore[assignment]

try:
    from mdviewer.agentic_env import (  # noqa: E402
        discover_agentic_catalog_async,
        find_project_root,
    )
except ImportError:  # pragma: no cover - fallback before backend-core merges
    discover_agentic_catalog_async = None  # type: ignore[assignment]
    find_project_root = None  # type: ignore[assignment]


_WELCOME_ENV_SOURCES: tuple[tuple[str, str], ...] = (
    ("all", "All envs"),
    ("claude", "claude"),
    ("codex", "codex"),
    ("gemini", "gemini"),
    ("agents", "agents"),
    ("cursor", "cursor"),
    ("opencode", "opencode"),
    ("grok", "grok"),
    ("project", "project"),
)

_WELCOME_ENV_KINDS: tuple[tuple[str, str], ...] = (
    ("all", "All kinds"),
    ("skill", "Skill"),
    ("agent", "Agent"),
    ("rule", "Rule"),
    ("command", "Command"),
    ("reference", "Reference"),
    ("prompt", "Prompt"),
    ("memory", "Memory"),
    ("config", "Config"),
)

_AGENT_LABELS: dict[str, str] = {
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "agy": "Antigravity CLI",
    "cursor-agent": "Cursor Agent",
    "opencode": "OpenCode",
    "kimi": "Kimi Code",
    "gemini": "Gemini CLI",
    "cline": "Cline",
    "devin": "Devin CLI",
}


def _extract_catalog_artifacts(catalog: Any) -> list[Any]:
    if catalog is None:
        return []
    artifacts = getattr(catalog, "artifacts", None)
    if artifacts is not None:
        return list(artifacts)
    if isinstance(catalog, (list, tuple)):
        return list(catalog)
    return []


def _entry_is_html(entry: Any) -> bool:
    return (
        str(getattr(entry, "source", "text") or "text").strip().lower() == "html"
        or bool(getattr(entry, "was_html", False))
    )


def _format_clipboard_entry_label(entry: Any) -> str:
    text = str(getattr(entry, "text", entry) or "")
    was_html = _entry_is_html(entry)
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "(empty)")
    if len(first_line) > 48:
        first_line = first_line[:45] + "…"
    tag = "HTML → MD" if was_html else "Text"
    return f"[{tag}] {first_line}"


# ---------------------------------------------------------------------------
# WelcomeView (empty / home state)
# ---------------------------------------------------------------------------
class WelcomeView(Gtk.ScrolledWindow):
    """Clean editorial home view shown when no documents are open."""

    def __init__(
        self,
        *,
        recent_files: list[str] | None = None,
        on_open_file: Callable[[], None] | None = None,
        on_new_document: Callable[[], None] | None = None,
        on_open_clipboard: Callable[[], None] | None = None,
        on_open_clipboard_entry: Callable[[str, bool], None] | None = None,
        on_open_recent: Callable[[str], None] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.get_style_context().add_class("preview-scrolled")

        self._on_open_recent = on_open_recent
        self._on_open_clipboard_entry = on_open_clipboard_entry
        self._project_root: Path | None = (
            Path(project_root) if project_root is not None else None
        )
        self._env_artifacts: list[Any] = []
        self._env_scan_seq: int = 0
        self._env_scope_filter: str = "all"
        self._destroyed: bool = False
        self.connect("destroy", self._on_destroy)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)
        outer.set_margin_top(36)
        outer.set_margin_bottom(36)
        outer.set_margin_start(32)
        outer.set_margin_end(32)
        outer.set_size_request(520, -1)

        # Header with Markveil logo
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "icons" / "markveil-128.png"
        if not icon_path.is_file():
            icon_path = Path(__file__).resolve().parent.parent / "assets" / "icons" / "markveil.svg"
        if icon_path.is_file():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(icon_path), 56, 56, True
                )
                logo_img = Gtk.Image.new_from_pixbuf(pixbuf)
                header_row.pack_start(logo_img, False, False, 0)
            except Exception:
                pass

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label()
        title.set_text("Open a document")
        title.get_style_context().add_class("welcome-title")
        title.set_xalign(0.0)
        title_col.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(
            label="Choose a file, start a draft, open your clipboard, or browse agentic environments."
        )
        subtitle.get_style_context().add_class("muted-label")
        subtitle.set_xalign(0.0)
        subtitle.set_line_wrap(True)
        title_col.pack_start(subtitle, False, False, 0)

        header_row.pack_start(title_col, True, True, 0)
        header_row.set_margin_bottom(20)
        outer.pack_start(header_row, False, False, 0)

        # Action row
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_btn = Gtk.Button(label="Open File…")
        open_btn.get_style_context().add_class("suggested-action")
        if on_open_file:
            open_btn.connect("clicked", lambda _b: on_open_file())
        actions.pack_start(open_btn, False, False, 0)

        new_btn = Gtk.Button(label="New Document")
        if on_new_document:
            new_btn.connect("clicked", lambda _b: on_new_document())
        actions.pack_start(new_btn, False, False, 0)

        clip_btn = Gtk.Button(label="Open Clipboard")
        clip_btn.set_tooltip_text("Open Clipboard Studio (Ctrl+Shift+V)")
        if on_open_clipboard:
            clip_btn.connect("clicked", lambda _b: on_open_clipboard())
        actions.pack_start(clip_btn, False, False, 0)

        self._clip_history_btn = Gtk.MenuButton(label="History ▾")
        self._clip_history_btn.set_tooltip_text("Recent clipboard captures")
        self._clip_history_popover = self._build_clipboard_history_popover(
            self._clip_history_btn
        )
        self._clip_history_btn.set_popover(self._clip_history_popover)
        actions.pack_start(self._clip_history_btn, False, False, 0)

        actions.set_margin_bottom(22)
        outer.pack_start(actions, False, False, 0)

        # Recent files
        recent_title = Gtk.Label(label="Recent files")
        recent_title.get_style_context().add_class("sidebar-section-title")
        recent_title.set_xalign(0.0)
        recent_title.set_margin_bottom(6)
        outer.pack_start(recent_title, False, False, 0)

        self._recent_list = Gtk.ListBox()
        self._recent_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._recent_list.set_activate_on_single_click(True)
        self._recent_list.connect("row-activated", self._handle_recent_activated)
        self._recent_list.get_style_context().add_class("context-metric-card")
        self._recent_list.set_margin_bottom(20)
        outer.pack_start(self._recent_list, False, False, 0)

        # Agentic Environments quick-browse section
        self._build_agentic_env_section(outer)

        self.add(outer)
        self.set_recent_files(recent_files or [])
        GLib.idle_add(self._kickoff_env_scan)

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        self._destroyed = True

    def _build_clipboard_history_popover(self, relative_to: Gtk.Widget) -> Gtk.Popover:
        pop = Gtk.Popover.new(relative_to)
        pop.get_style_context().add_class("markveil-popover")
        self._clip_history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._clip_history_box.set_margin_top(6)
        self._clip_history_box.set_margin_bottom(6)
        self._clip_history_box.set_margin_start(6)
        self._clip_history_box.set_margin_end(6)
        self._clip_history_box.set_size_request(260, -1)
        pop.add(self._clip_history_box)
        pop.connect("show", self._refresh_clipboard_history_popover)
        return pop

    def _refresh_clipboard_history_popover(self, _pop: Gtk.Popover) -> None:
        for child in list(self._clip_history_box.get_children()):
            self._clip_history_box.remove(child)

        entries: list[Any] = []
        if get_clipboard_history is not None:
            try:
                hist = get_clipboard_history()
                raw = hist.entries() if callable(getattr(hist, "entries", None)) else getattr(hist, "entries", [])
                entries = list(raw)
            except Exception:
                entries = []

        if not entries:
            lbl = Gtk.Label(label="No clipboard captures yet.")
            lbl.get_style_context().add_class("muted-label")
            lbl.set_xalign(0.0)
            lbl.set_margin_start(6)
            lbl.set_margin_end(6)
            lbl.set_margin_top(4)
            lbl.set_margin_bottom(4)
            self._clip_history_box.pack_start(lbl, False, False, 0)
        else:
            for entry in entries[:10]:
                text = str(getattr(entry, "text", entry) or "")
                was_html = _entry_is_html(entry)
                btn = Gtk.ModelButton()
                btn.set_label(_format_clipboard_entry_label(entry))
                btn.connect(
                    "clicked",
                    lambda _b, t=text, h=was_html: (
                        self._clip_history_popover.popdown(),
                        self._on_open_clipboard_entry(t, h)
                        if self._on_open_clipboard_entry
                        else None,
                    ),
                )
                self._clip_history_box.pack_start(btn, False, False, 0)

        self._clip_history_box.show_all()

    def _build_agentic_env_section(self, outer: Gtk.Box) -> None:
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.set_margin_bottom(6)

        env_title = Gtk.Label(label="Agentic Environments", xalign=0.0)
        env_title.get_style_context().add_class("sidebar-section-title")
        hdr.pack_start(env_title, True, True, 0)

        self._welcome_env_count = Gtk.Label(label="0")
        self._welcome_env_count.get_style_context().add_class("env-badge")
        hdr.pack_start(self._welcome_env_count, False, False, 0)

        refresh_btn = Gtk.Button.new_from_icon_name(
            "view-refresh-symbolic", Gtk.IconSize.MENU
        )
        refresh_btn.set_tooltip_text("Refresh agentic environments")
        refresh_btn.connect(
            "clicked", lambda _b: self.refresh_agentic_catalog(force_refresh=True)
        )
        hdr.pack_end(refresh_btn, False, False, 0)
        outer.pack_start(hdr, False, False, 0)

        # Filter bar
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_margin_bottom(8)

        scope_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        scope_box.get_style_context().add_class("linked")
        scope_box.get_style_context().add_class("env-scope-group")
        first_rb: Gtk.RadioButton | None = None
        for scope_key, scope_label in (
            ("all", "All"),
            ("project", "Project"),
            ("global", "Global"),
        ):
            rb = (
                Gtk.RadioButton.new_with_label(None, scope_label)
                if first_rb is None
                else Gtk.RadioButton.new_with_label_from_widget(first_rb, scope_label)
            )
            if first_rb is None:
                first_rb = rb
            rb.set_mode(False)
            rb.connect("toggled", self._on_env_scope_toggled, scope_key)
            scope_box.pack_start(rb, False, False, 0)
        controls.pack_start(scope_box, False, False, 0)

        self._welcome_env_combo = Gtk.ComboBoxText()
        for key, label in _WELCOME_ENV_SOURCES:
            self._welcome_env_combo.append(key, label)
        self._welcome_env_combo.set_active_id("all")
        self._welcome_env_combo.connect("changed", lambda _c: self._render_welcome_env_list())
        controls.pack_start(self._welcome_env_combo, False, False, 0)

        self._welcome_kind_combo = Gtk.ComboBoxText()
        for key, label in _WELCOME_ENV_KINDS:
            self._welcome_kind_combo.append(key, label)
        self._welcome_kind_combo.set_active_id("all")
        self._welcome_kind_combo.connect("changed", lambda _c: self._render_welcome_env_list())
        controls.pack_start(self._welcome_kind_combo, False, False, 0)

        self._welcome_env_search = Gtk.Entry()
        self._welcome_env_search.set_placeholder_text("Search…")
        self._welcome_env_search.set_width_chars(14)
        self._welcome_env_search.connect("changed", lambda _e: self._render_welcome_env_list())
        controls.pack_start(self._welcome_env_search, True, True, 0)

        outer.pack_start(controls, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(240)
        scrolled.set_propagate_natural_height(True)

        self._welcome_env_list = Gtk.ListBox()
        self._welcome_env_list.get_style_context().add_class("env-welcome-list")
        self._welcome_env_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._welcome_env_list.set_activate_on_single_click(True)
        self._welcome_env_list.connect("row-activated", self._handle_recent_activated)

        self._welcome_env_placeholder = Gtk.Label(label="Scanning agentic environments…")
        self._welcome_env_placeholder.get_style_context().add_class("muted-label")
        self._welcome_env_placeholder.set_margin_top(12)
        self._welcome_env_placeholder.set_margin_bottom(12)
        self._welcome_env_list.set_placeholder(self._welcome_env_placeholder)
        self._welcome_env_placeholder.show()

        scrolled.add(self._welcome_env_list)
        outer.pack_start(scrolled, False, False, 0)

    def _kickoff_env_scan(self) -> bool:
        if not self._destroyed and self._env_scan_seq == 0:
            self.refresh_agentic_catalog(force_refresh=False)
        return False

    def set_project_context(self, file_path: str | None) -> None:
        """Update active project root and refresh catalog if changed."""
        new_root: Path | None = None
        if find_project_root is not None:
            try:
                new_root = find_project_root(file_path)
            except Exception:
                new_root = None
        elif file_path:
            new_root = Path(file_path).parent

        if new_root != self._project_root:
            self._env_scan_seq += 1
            self._project_root = new_root
            self.refresh_agentic_catalog(force_refresh=False)

    def set_agentic_artifacts(self, artifacts: list[Any]) -> None:
        """Directly supply artifacts and invalidate any in-flight async scan."""
        self._env_scan_seq += 1
        self._env_artifacts = list(artifacts)
        self._render_welcome_env_list()

    def refresh_agentic_catalog(self, *, force_refresh: bool = False) -> None:
        if self._destroyed:
            return
        self._env_scan_seq += 1
        scan_seq = self._env_scan_seq

        if discover_agentic_catalog_async is None:
            self._welcome_env_placeholder.set_text("No agentic environments detected.")
            self._render_welcome_env_list()
            return

        root = self._project_root
        if root is None and find_project_root is not None:
            try:
                root = find_project_root(None)
            except Exception:
                root = None

        self._welcome_env_placeholder.set_text("Scanning agentic environments…")

        def _on_catalog(catalog: Any) -> None:
            def _apply() -> bool:
                if self._destroyed or scan_seq != self._env_scan_seq:
                    return False
                self._env_artifacts = _extract_catalog_artifacts(catalog)
                self._render_welcome_env_list()
                return False

            GLib.idle_add(_apply)

        try:
            discover_agentic_catalog_async(
                _on_catalog,
                project_root=root,
                include_global=True,
                force_refresh=force_refresh,
            )
        except Exception:
            if scan_seq == self._env_scan_seq:
                self._welcome_env_placeholder.set_text("No agentic environments detected.")

    refresh_agentic_env = refresh_agentic_catalog

    def _on_env_scope_toggled(self, btn: Gtk.RadioButton, scope_key: str) -> None:
        if btn.get_active():
            self._env_scope_filter = scope_key
            self._render_welcome_env_list()

    def _render_welcome_env_list(self) -> None:
        for child in list(self._welcome_env_list.get_children()):
            self._welcome_env_list.remove(child)

        query = self._welcome_env_search.get_text().strip().lower()
        scope = self._env_scope_filter
        env_src = self._welcome_env_combo.get_active_id() or "all"
        kind = self._welcome_kind_combo.get_active_id() or "all"

        filtered: list[Any] = []
        for art in self._env_artifacts:
            art_scope = str(getattr(art, "scope", "") or "").lower()
            art_env = str(getattr(art, "env_source", "") or "").lower()
            art_kind = str(getattr(art, "kind", "") or "").lower()
            if scope != "all" and art_scope != scope:
                continue
            if env_src != "all" and art_env != env_src:
                continue
            if kind != "all" and art_kind != kind:
                continue
            if query:
                haystack = " ".join(
                    (
                        str(getattr(art, "name", "") or ""),
                        str(getattr(art, "description", "") or ""),
                        str(getattr(art, "rel_path", "") or ""),
                        art_env,
                        art_kind,
                    )
                ).lower()
                if query not in haystack:
                    continue
            filtered.append(art)

        self._welcome_env_count.set_text(str(len(filtered)))
        if not filtered:
            self._welcome_env_placeholder.set_text(
                "No matching agentic artifacts."
                if self._env_artifacts
                else "No agentic artifacts found in this workspace or home directory."
            )
            return

        for art in filtered[:50]:
            file_path = str(getattr(art, "path", "") or "")
            row = Gtk.ListBoxRow()
            row.file_path = file_path  # type: ignore[attr-defined]
            row.set_tooltip_text(file_path)

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name = str(getattr(art, "name", "") or Path(file_path).name)
            name_lbl = Gtk.Label(label=name, xalign=0.0)
            name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            hbox.pack_start(name_lbl, False, False, 0)

            env_source = str(getattr(art, "env_source", "") or "")
            art_kind = str(getattr(art, "kind", "") or "")
            art_scope = str(getattr(art, "scope", "") or "")
            if env_source:
                eb = Gtk.Label(label=env_source)
                eb.get_style_context().add_class("env-badge-accent")
                hbox.pack_start(eb, False, False, 0)
            if art_kind:
                kb = Gtk.Label(label=art_kind)
                kb.get_style_context().add_class("env-badge")
                hbox.pack_start(kb, False, False, 0)
            if art_scope:
                sb = Gtk.Label(label=art_scope)
                sb.get_style_context().add_class("env-badge")
                hbox.pack_start(sb, False, False, 0)

            desc = str(getattr(art, "description", "") or getattr(art, "rel_path", "") or "")
            if desc:
                desc_lbl = Gtk.Label(label=desc, xalign=1.0)
                desc_lbl.get_style_context().add_class("muted-label")
                desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                hbox.pack_end(desc_lbl, True, True, 0)

            row.add(hbox)
            self._welcome_env_list.add(row)

        if len(filtered) > 50:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            lbl = Gtk.Label(
                label=f"Showing 50 of {len(filtered)} — refine search or filters.",
                xalign=0.0,
            )
            lbl.get_style_context().add_class("muted-label")
            row.add(lbl)
            self._welcome_env_list.add(row)

        self._welcome_env_list.show_all()

    def set_recent_files(self, paths: list[str]) -> None:
        for child in list(self._recent_list.get_children()):
            self._recent_list.remove(child)

        existing = [p for p in paths if Path(p).is_file()]
        if not existing:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            lbl = Gtk.Label(label="No recent files yet. Open a Markdown file or drag one here.")
            lbl.get_style_context().add_class("muted-label")
            lbl.set_xalign(0.0)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            lbl.set_margin_start(6)
            row.add(lbl)
            self._recent_list.add(row)
        else:
            for file_path in existing[:8]:
                p = Path(file_path)
                row = Gtk.ListBoxRow()
                row.file_path = file_path  # type: ignore[attr-defined]

                hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                hbox.set_margin_top(4)
                hbox.set_margin_bottom(4)
                hbox.set_margin_start(6)
                hbox.set_margin_end(6)

                name_lbl = Gtk.Label(label=p.name)
                name_lbl.set_xalign(0.0)
                hbox.pack_start(name_lbl, False, False, 0)

                parent_lbl = Gtk.Label(label=str(p.parent))
                parent_lbl.get_style_context().add_class("muted-label")
                parent_lbl.set_xalign(1.0)
                parent_lbl.set_ellipsize(Pango.EllipsizeMode.START)
                hbox.pack_end(parent_lbl, True, True, 0)

                row.add(hbox)
                self._recent_list.add(row)

        self._recent_list.show_all()

    def _handle_recent_activated(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        if row is None:
            return
        file_path = getattr(row, "file_path", None)
        if file_path and self._on_open_recent:
            self._on_open_recent(file_path)


# ---------------------------------------------------------------------------
# AskAgentDialog
# ---------------------------------------------------------------------------
class AskAgentDialog(Gtk.Dialog):
    """Query a local coding agent CLI about the active document."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        *,
        document_text: str,
        file_path: str | None,
        theme_id: str,
        preferred_agent: str = "auto",
        on_open_in_tab: Callable[[str, str], None] | None = None,
        on_agent_selected: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            title="Ask Local Agent",
            transient_for=parent,
            modal=False,
        )
        self.get_style_context().add_class("markveil-window")
        self.set_default_size(760, 560)
        self._document_text = document_text
        self._file_path = file_path
        self._theme_id = theme_id
        self._on_open_in_tab = on_open_in_tab
        self._on_agent_selected = on_agent_selected
        self._active_handle: AgentTaskHandle | None = None
        self._last_answer: str = ""
        self._destroyed = False

        self.connect("destroy", self._on_destroy)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(12)
        content.set_margin_end(12)

        self._backends = list(detect_installed_agents())

        # Backend selector + preset buttons
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        agent_lbl = Gtk.Label(label="Agent:")
        agent_lbl.get_style_context().add_class("muted-label")
        top_row.pack_start(agent_lbl, False, False, 0)

        self._backend_combo = Gtk.ComboBoxText()
        selected_idx = 0
        for idx, backend in enumerate(self._backends):
            self._backend_combo.append(backend.id, f"{backend.name} ({backend.id})")
            if backend.id == preferred_agent:
                selected_idx = idx
        if self._backends:
            self._backend_combo.set_active(selected_idx)
            self._backend_combo.connect("changed", self._on_backend_changed)
        else:
            self._backend_combo.append("none", "No local agent CLI found")
            self._backend_combo.set_active(0)
            self._backend_combo.set_sensitive(False)
        top_row.pack_start(self._backend_combo, False, False, 0)

        self._spinner = Gtk.Spinner()
        top_row.pack_end(self._spinner, False, False, 0)

        supported_list = ", ".join(SUPPORTED_AGENT_IDS)
        self._status_lbl = Gtk.Label(
            label=(
                "Ready"
                if self._backends
                else f"Install a supported CLI ({supported_list}) to enable."
            )
        )
        self._status_lbl.get_style_context().add_class("muted-label")
        self._status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        top_row.pack_end(self._status_lbl, True, True, 4)
        content.pack_start(top_row, False, False, 0)

        # Preset prompt buttons
        presets_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for _preset_key, (label, prompt_text) in PROMPT_PRESETS.items():
            btn = Gtk.Button(label=label)
            btn.set_sensitive(bool(self._backends))
            btn.connect("clicked", self._on_preset_clicked, prompt_text)
            presets_row.pack_start(btn, False, False, 0)
        content.pack_start(presets_row, False, False, 0)

        # Custom question row
        q_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._question_entry = Gtk.Entry()
        self._question_entry.set_placeholder_text(
            "Ask a question about this document…"
        )
        self._question_entry.set_sensitive(bool(self._backends))
        self._question_entry.connect("activate", lambda _e: self._run_query())
        q_row.pack_start(self._question_entry, True, True, 0)

        self._ask_btn = Gtk.Button(label="Ask")
        self._ask_btn.get_style_context().add_class("suggested-action")
        self._ask_btn.set_sensitive(bool(self._backends))
        self._ask_btn.connect("clicked", lambda _b: self._run_query())
        q_row.pack_start(self._ask_btn, False, False, 0)

        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.set_sensitive(False)
        self._cancel_btn.connect("clicked", lambda _b: self._cancel_active())
        q_row.pack_start(self._cancel_btn, False, False, 0)
        content.pack_start(q_row, False, False, 0)

        # Hardened WebKit2 answer preview
        self._webview = WebKit2.WebView()
        settings = self._webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_allow_universal_access_from_file_urls(False)
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_enable_page_cache(False)

        rgba = Gdk.RGBA(*get_webview_bg_rgba(theme_id))
        self._webview.set_background_color(rgba)
        self._webview.connect("decide-policy", self._on_decide_policy)

        scrolled = Gtk.ScrolledWindow()
        scrolled.get_style_context().add_class("preview-scrolled")
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.add(self._webview)
        content.pack_start(scrolled, True, True, 0)

        # Bottom action buttons
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._copy_btn = Gtk.Button(label="Copy Answer")
        self._copy_btn.set_sensitive(False)
        self._copy_btn.connect("clicked", self._on_copy_answer)
        bottom.pack_start(self._copy_btn, False, False, 0)

        self._new_tab_btn = Gtk.Button(label="Open in New Tab")
        self._new_tab_btn.set_sensitive(False)
        self._new_tab_btn.connect("clicked", self._on_open_new_tab)
        bottom.pack_start(self._new_tab_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _b: self.destroy())
        bottom.pack_end(close_btn, False, False, 0)
        content.pack_start(bottom, False, False, 0)

        supported_md = ", ".join(f"`{a}`" for a in SUPPORTED_AGENT_IDS)
        self._render_markdown(
            "_Choose a preset or enter a question to query a local agent CLI._"
            if self._backends
            else f"> [!NOTE]\n> No supported local agent CLI ({supported_md}) was detected."
        )
        self.show_all()

    def _on_backend_changed(self, combo: Gtk.ComboBoxText) -> None:
        backend_id = combo.get_active_id()
        if backend_id and backend_id != "none" and self._on_agent_selected:
            self._on_agent_selected(backend_id)

    def _render_markdown(self, md_text: str) -> None:
        result = render_document(
            md_text,
            file_path="agent-response.md",
            theme=self._theme_id,
            allow_remote_images=False,
            vim_enabled=False,
        )
        self._webview.load_html(result.html, "about:blank")

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
        if nav_type == WebKit2.NavigationType.OTHER and (
            not uri or uri == "about:blank"
        ):
            decision.use()
            return True
        parsed = urlparse(uri)
        if parsed.scheme in ("http", "https", "mailto"):
            decision.ignore()
            try:
                Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
            except Exception:
                pass
            return True
        decision.ignore()
        return True

    def _on_preset_clicked(self, _btn: Gtk.Button, prompt_text: str) -> None:
        self._question_entry.set_text(prompt_text)
        self._run_query()

    def _run_query(self) -> None:
        backend_id = self._backend_combo.get_active_id()
        if not backend_id or backend_id == "none":
            return
        if self._on_agent_selected:
            self._on_agent_selected(backend_id)
        question = self._question_entry.get_text().strip()
        if not question:
            question = PROMPT_PRESETS["summarize"][1]
            self._question_entry.set_text(question)

        self._cancel_active()
        self._set_running(True, f"Running {backend_id}…")

        def _dispatch(fn: Callable[[], None]) -> None:
            def _idle() -> bool:
                if not self._destroyed:
                    fn()
                return False

            GLib.idle_add(_idle)

        self._active_handle = run_agent_async(
            backend_id=backend_id,
            document_text=self._document_text,
            file_path=self._file_path,
            question=question,
            on_done=self._handle_done,
            on_error=self._handle_error,
            timeout_sec=90,
            dispatch=_dispatch,
        )

    def _set_running(self, running: bool, status: str) -> None:
        self._status_lbl.set_text(status)
        self._ask_btn.set_sensitive((not running) and bool(self._backends))
        self._cancel_btn.set_sensitive(running)
        if running:
            self._spinner.start()
        else:
            self._spinner.stop()

    def _handle_done(self, output: str) -> None:
        self._active_handle = None
        self._last_answer = output or "_Agent returned an empty response._"
        self._set_running(False, "Done")
        self._copy_btn.set_sensitive(bool(output))
        self._new_tab_btn.set_sensitive(bool(output) and self._on_open_in_tab is not None)
        self._render_markdown(self._last_answer)

    def _handle_error(self, message: str) -> None:
        self._active_handle = None
        self._set_running(False, "Error")
        self._render_markdown(f"> [!CAUTION]\n> **Agent Error**\n>\n> {message}")

    def _cancel_active(self) -> None:
        if self._active_handle is not None:
            self._active_handle.cancel()
            self._active_handle = None
            self._set_running(False, "Cancelled")

    def _on_copy_answer(self, _btn: Gtk.Button) -> None:
        if self._last_answer:
            ok = write_clipboard_text(self._last_answer)
            self._status_lbl.set_text(
                "Copied answer to clipboard"
                if ok
                else "Failed to copy answer to clipboard"
            )

    def _on_open_new_tab(self, _btn: Gtk.Button) -> None:
        if self._last_answer and self._on_open_in_tab:
            stem = Path(self._file_path).stem if self._file_path else "document"
            self._on_open_in_tab(f"{stem}-agent.md", self._last_answer)

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        self._destroyed = True
        if self._active_handle is not None:
            self._active_handle.cancel()
            self._active_handle = None


# ---------------------------------------------------------------------------
# DiffPickerDialog
# ---------------------------------------------------------------------------
class DiffPickerDialog(Gtk.Dialog):
    """Choose diff source (Last Revision, Git HEAD, or Two Files) and layout."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        *,
        has_revisions: bool,
        current_file: str | None,
    ) -> None:
        super().__init__(
            title="Compare / Visual Diff",
            transient_for=parent,
            modal=True,
        )
        self.get_style_context().add_class("markveil-window")
        self.add_buttons(
            "_Cancel",
            Gtk.ResponseType.CANCEL,
            "Show Diff",
            Gtk.ResponseType.ACCEPT,
        )
        self.set_default_response(Gtk.ResponseType.ACCEPT)
        self.set_default_size(460, -1)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(14)
        content.set_margin_end(14)

        self._radio_rev = Gtk.RadioButton.new_with_label_from_widget(
            None, "Compare with Last Watched Revision"
        )
        self._radio_rev.set_sensitive(has_revisions)
        content.pack_start(self._radio_rev, False, False, 0)

        self._radio_git = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_rev, "Compare Current File with Git HEAD"
        )
        self._radio_git.set_sensitive(bool(current_file))
        content.pack_start(self._radio_git, False, False, 0)

        self._radio_files = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_rev, "Compare Two Files…"
        )
        content.pack_start(self._radio_files, False, False, 0)

        if has_revisions:
            self._radio_rev.set_active(True)
        elif current_file:
            self._radio_git.set_active(True)
        else:
            self._radio_files.set_active(True)

        self._files_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self._files_grid.set_margin_start(22)

        lbl_a = Gtk.Label(label="Before (A):")
        lbl_a.set_xalign(0.0)
        self._chooser_a = Gtk.FileChooserButton(
            title="Select Base File (Before)",
            action=Gtk.FileChooserAction.OPEN,
        )
        self._chooser_a.set_hexpand(True)

        lbl_b = Gtk.Label(label="After (B):")
        lbl_b.set_xalign(0.0)
        self._chooser_b = Gtk.FileChooserButton(
            title="Select Target File (After)",
            action=Gtk.FileChooserAction.OPEN,
        )
        self._chooser_b.set_hexpand(True)
        if current_file and Path(current_file).is_file():
            self._chooser_b.set_filename(current_file)

        self._files_grid.attach(lbl_a, 0, 0, 1, 1)
        self._files_grid.attach(self._chooser_a, 1, 0, 1, 1)
        self._files_grid.attach(lbl_b, 0, 1, 1, 1)
        self._files_grid.attach(self._chooser_b, 1, 1, 1, 1)
        content.pack_start(self._files_grid, False, False, 0)

        # Layout mode
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_row.set_margin_top(6)
        mode_lbl = Gtk.Label(label="Layout:")
        mode_lbl.get_style_context().add_class("muted-label")
        mode_row.pack_start(mode_lbl, False, False, 0)

        self._mode_combo = Gtk.ComboBoxText()
        self._mode_combo.append("unified", "Unified Diff")
        self._mode_combo.append("split", "Side-by-Side")
        self._mode_combo.set_active(0)
        mode_row.pack_start(self._mode_combo, True, True, 0)
        content.pack_start(mode_row, False, False, 0)

        for rb in (self._radio_rev, self._radio_git, self._radio_files):
            rb.connect("toggled", self._sync_file_pickers)
        self._sync_file_pickers()
        self.show_all()

    def _sync_file_pickers(self, *_args: object) -> None:
        self._files_grid.set_sensitive(self._radio_files.get_active())

    def get_selection(self) -> dict[str, str | None]:
        if self._radio_rev.get_active():
            source = "revision"
        elif self._radio_git.get_active():
            source = "git"
        else:
            source = "files"
        return {
            "source": source,
            "mode": self._mode_combo.get_active_id() or "unified",
            "file_a": self._chooser_a.get_filename(),
            "file_b": self._chooser_b.get_filename(),
        }


# ---------------------------------------------------------------------------
# PreferencesDialog
# ---------------------------------------------------------------------------
class PreferencesDialog(Gtk.Dialog):
    """Application preferences editor synced with AppConfig."""

    def __init__(self, parent: Gtk.Window | None, config: AppConfig) -> None:
        super().__init__(
            title="Preferences",
            transient_for=parent,
            modal=True,
        )
        self.get_style_context().add_class("markveil-window")
        self.add_buttons(
            "_Cancel",
            Gtk.ResponseType.CANCEL,
            "Apply",
            Gtk.ResponseType.ACCEPT,
        )
        self.set_default_response(Gtk.ResponseType.ACCEPT)
        self.set_default_size(480, -1)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(16)
        content.set_margin_end(16)

        grid = Gtk.Grid(column_spacing=16, row_spacing=12)

        # Theme
        row = 0
        grid.attach(self._make_label("Theme"), 0, row, 1, 1)
        self._theme_combo = Gtk.ComboBoxText()
        self._theme_combo.append("auto", "Auto (Follow System)")
        for tid in THEME_ORDER:
            self._theme_combo.append(tid, THEMES[tid].name)
        self._theme_combo.set_active_id(config.theme)
        self._theme_combo.set_hexpand(True)
        grid.attach(self._theme_combo, 1, row, 1, 1)

        # Preferred local agent
        row += 1
        grid.attach(self._make_label("Preferred local agent"), 0, row, 1, 1)
        self._agent_combo = Gtk.ComboBoxText()
        self._agent_combo.append("auto", "Auto (First Available)")
        installed_by_id = {b.id: b for b in detect_installed_agents()}
        seen_ids: set[str] = {"auto"}
        for b in installed_by_id.values():
            self._agent_combo.append(b.id, f"{b.name} ({b.id}) · installed")
            seen_ids.add(b.id)
        for aid in SUPPORTED_AGENT_IDS:
            if aid not in seen_ids:
                label = _AGENT_LABELS.get(aid, aid)
                self._agent_combo.append(aid, f"{label} ({aid})")
                seen_ids.add(aid)
        if config.preferred_agent and config.preferred_agent not in seen_ids:
            self._agent_combo.append(config.preferred_agent, config.preferred_agent)
        if not self._agent_combo.set_active_id(config.preferred_agent or "auto"):
            self._agent_combo.set_active_id("auto")
        self._agent_combo.set_hexpand(True)
        grid.attach(self._agent_combo, 1, row, 1, 1)

        # Vim navigation
        row += 1
        grid.attach(self._make_label("Vim navigation (j/k/d/u/gg/G)"), 0, row, 1, 1)
        self._vim_switch = Gtk.Switch()
        self._vim_switch.set_active(config.vim_navigation)
        self._vim_switch.set_halign(Gtk.Align.END)
        grid.attach(self._vim_switch, 1, row, 1, 1)

        # Remote images
        row += 1
        grid.attach(self._make_label("Allow remote images by default"), 0, row, 1, 1)
        self._remote_img_switch = Gtk.Switch()
        self._remote_img_switch.set_active(config.allow_remote_images)
        self._remote_img_switch.set_halign(Gtk.Align.END)
        grid.attach(self._remote_img_switch, 1, row, 1, 1)

        # Status bar
        row += 1
        grid.attach(self._make_label("Show bottom status bar"), 0, row, 1, 1)
        self._status_bar_switch = Gtk.Switch()
        self._status_bar_switch.set_active(config.status_bar_visible)
        self._status_bar_switch.set_halign(Gtk.Align.END)
        grid.attach(self._status_bar_switch, 1, row, 1, 1)

        # Custom CSS file
        row += 1
        grid.attach(self._make_label("Custom CSS file"), 0, row, 1, 1)
        css_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._css_path_entry = Gtk.Entry()
        self._css_path_entry.set_text(config.custom_css_path or "")
        self._css_path_entry.set_placeholder_text("Optional .css path…")
        css_box.pack_start(self._css_path_entry, True, True, 0)

        browse_btn = Gtk.Button(label="Browse…")
        browse_btn.connect("clicked", self._browse_css)
        css_box.pack_start(browse_btn, False, False, 0)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", lambda _b: self._css_path_entry.set_text(""))
        css_box.pack_start(clear_btn, False, False, 0)

        grid.attach(css_box, 1, row, 1, 1)
        content.pack_start(grid, True, True, 0)
        self.show_all()

    @staticmethod
    def _make_label(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        return lbl

    def _browse_css(self, _btn: Gtk.Button) -> None:
        fc = Gtk.FileChooserNative.new(
            "Select Custom CSS",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Open",
            "_Cancel",
        )
        css_filter = Gtk.FileFilter()
        css_filter.set_name("CSS stylesheets (*.css)")
        css_filter.add_pattern("*.css")
        fc.add_filter(css_filter)

        if fc.run() == Gtk.ResponseType.ACCEPT:
            fname = fc.get_filename()
            if fname:
                self._css_path_entry.set_text(fname)
        fc.destroy()

    def get_values(self) -> dict[str, object]:
        return {
            "theme": self._theme_combo.get_active_id() or "auto",
            "preferred_agent": self._agent_combo.get_active_id() or "auto",
            "vim_navigation": self._vim_switch.get_active(),
            "allow_remote_images": self._remote_img_switch.get_active(),
            "status_bar_visible": self._status_bar_switch.get_active(),
            "custom_css_path": self._css_path_entry.get_text().strip(),
        }


# ---------------------------------------------------------------------------
# ShortcutsDialog
# ---------------------------------------------------------------------------
class ShortcutsDialog(Gtk.Dialog):
    """Clean grouped keyboard shortcut reference."""

    _GROUPS: tuple[tuple[str, list[tuple[str, str]]], ...] = (
        (
            "FILES & TABS",
            [
                ("Ctrl+N", "New document tab"),
                ("Ctrl+O", "Open file"),
                ("Ctrl+W", "Close current tab"),
                ("Ctrl+S", "Save document"),
                ("Ctrl+Shift+S", "Save document as…"),
                ("Ctrl+P", "Print / Export PDF"),
                ("Ctrl+Shift+C", "Copy current file path"),
                ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"),
                ("Ctrl+Q", "Quit Markveil"),
            ],
        ),
        (
            "VIEWS & NAVIGATION",
            [
                ("Ctrl+E", "Cycle Preview / Split / Edit"),
                ("Ctrl+\\", "Toggle Split view"),
                ("Ctrl+R", "Reload from disk / refresh"),
                ("Ctrl+B / F9", "Toggle sidebar"),
                ("Ctrl++ / Ctrl+- / Ctrl+0", "Zoom in / out / reset"),
                ("Alt+Left / Alt+Right", "Back / forward link history"),
                ("j / k / d / u / gg / G", "Vim scroll in Preview"),
                ("[ / ]  and  /", "Prev / next heading & search"),
            ],
        ),
        (
            "AGENT STUDIO & SEARCH",
            [
                ("Ctrl+F", "Find in document"),
                ("Ctrl+H", "Find & Replace (Edit / Split)"),
                ("Ctrl+Shift+M", "Add review comment"),
                ("Ctrl+Shift+V", "Open Clipboard Studio"),
                ("Ctrl+Shift+W", "Toggle Agent Watch Mode"),
                ("Ctrl+D", "Open Visual Diff picker"),
                ("Ctrl+Shift+A", "Ask Local Agent"),
                ("Ctrl+T", "Cycle Theme (Folio / Paper / Obsidian / Sepia / Nordic)"),
                ("Super+Shift+M", "Global Clipboard Studio launcher"),
                ("Ctrl+? / F1", "Show keyboard shortcuts"),
            ],
        ),
    )

    def __init__(self, parent: Gtk.Window | None) -> None:
        super().__init__(
            title="Keyboard Shortcuts",
            transient_for=parent,
            modal=True,
        )
        self.get_style_context().add_class("markveil-window")
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.set_default_size(560, 540)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        for group_title, items in self._GROUPS:
            hdr = Gtk.Label(label=group_title)
            hdr.get_style_context().add_class("sidebar-section-title")
            hdr.set_xalign(0.0)
            box.pack_start(hdr, False, False, 0)

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.get_style_context().add_class("context-metric-card")
            grid = Gtk.Grid(column_spacing=18, row_spacing=6)
            for idx, (keys, desc) in enumerate(items):
                kl = Gtk.Label()
                kl.set_markup(f"<tt><b>{GLib.markup_escape_text(keys)}</b></tt>")
                kl.set_xalign(0.0)
                dl = Gtk.Label(label=desc)
                dl.set_xalign(0.0)
                dl.set_hexpand(True)
                grid.attach(kl, 0, idx, 1, 1)
                grid.attach(dl, 1, idx, 1, 1)
            card.pack_start(grid, False, False, 0)
            box.pack_start(card, False, False, 0)

        scrolled.add(box)
        self.get_content_area().pack_start(scrolled, True, True, 0)
        self.show_all()


# ---------------------------------------------------------------------------
# Quick Comment Input Dialog (used by add-comment & edit-comment)
# ---------------------------------------------------------------------------
class CommentEditorDialog(Gtk.Dialog):
    """Compact modal dialog to add or edit an anchored review comment."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        *,
        heading: str,
        quote: str,
        initial_feedback: str = "",
        title: str = "Add Review Comment",
    ) -> None:
        super().__init__(title=title, transient_for=parent, modal=True)
        self.get_style_context().add_class("markveil-window")
        self.add_buttons(
            "_Cancel",
            Gtk.ResponseType.CANCEL,
            "Save Comment",
            Gtk.ResponseType.ACCEPT,
        )
        self.set_default_response(Gtk.ResponseType.ACCEPT)
        self.set_default_size(480, 340)

        self._save_btn = self.get_widget_for_response(Gtk.ResponseType.ACCEPT)
        if self._save_btn is not None:
            self._save_btn.get_style_context().add_class("suggested-action")

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(14)
        content.set_margin_end(14)

        # Editable Section / Heading
        sec_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sec_lbl = Gtk.Label(label="Section:", xalign=0.0)
        sec_lbl.get_style_context().add_class("sidebar-section-title")
        sec_row.pack_start(sec_lbl, False, False, 0)

        self._heading_entry = Gtk.Entry()
        self._heading_entry.set_text((heading or "").strip() or "Document")
        self._heading_entry.set_placeholder_text("Section or heading name…")
        sec_row.pack_start(self._heading_entry, True, True, 0)
        content.pack_start(sec_row, False, False, 0)

        # Optional Quote field
        quote_lbl = Gtk.Label(label="Quote (optional):", xalign=0.0)
        quote_lbl.get_style_context().add_class("muted-label")
        content.pack_start(quote_lbl, False, False, 0)

        quote_scrolled = Gtk.ScrolledWindow()
        quote_scrolled.set_shadow_type(Gtk.ShadowType.IN)
        quote_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        quote_scrolled.set_min_content_height(46)
        quote_scrolled.set_max_content_height(78)

        self._quote_view = Gtk.TextView()
        self._quote_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._quote_view.get_buffer().set_text((quote or "").strip())
        quote_scrolled.add(self._quote_view)
        content.pack_start(quote_scrolled, False, False, 0)

        # Feedback field
        fb_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        fb_lbl = Gtk.Label(label="Feedback:", xalign=0.0)
        fb_lbl.get_style_context().add_class("sidebar-section-title")
        fb_hdr.pack_start(fb_lbl, True, True, 0)

        shortcut_lbl = Gtk.Label(label="Ctrl+Enter to save", xalign=1.0)
        shortcut_lbl.get_style_context().add_class("muted-label")
        fb_hdr.pack_end(shortcut_lbl, False, False, 0)
        content.pack_start(fb_hdr, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(100)

        self._textview = Gtk.TextView()
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.get_buffer().set_text(initial_feedback)
        self._textview.get_buffer().connect("changed", self._sync_validation)
        scrolled.add(self._textview)
        content.pack_start(scrolled, True, True, 0)

        self._validation_lbl = Gtk.Label(
            label="Enter review feedback to enable saving.",
            xalign=0.0,
        )
        self._validation_lbl.get_style_context().add_class("muted-label")
        content.pack_start(self._validation_lbl, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self.show_all()
        self._sync_validation()
        self._textview.grab_focus()

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if (
            bool(state & Gdk.ModifierType.CONTROL_MASK)
            and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
        ):
            if self.get_feedback():
                self.response(Gtk.ResponseType.ACCEPT)
            return True
        return False

    def _sync_validation(self, *_args: object) -> None:
        valid = bool(self.get_feedback())
        if self._save_btn is not None:
            self._save_btn.set_sensitive(valid)
        self._validation_lbl.set_visible(not valid)

    def get_heading(self) -> str:
        return self._heading_entry.get_text().strip() or "Document"

    def get_quote(self) -> str:
        buf = self._quote_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()

    def get_feedback(self) -> str:
        buf = self._textview.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
