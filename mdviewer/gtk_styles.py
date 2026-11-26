"""GTK3 chrome styling, WebView background matching, and GtkSourceView schemes.

Keeps GTK3 window chrome, HeaderBar, Notebook tabs, Sidebar, SearchBar,
StatusBar, InfoBar, and GtkSourceView tightly harmonized with THEMES[theme_id]
so opening files or switching themes produces zero white flash.
"""

from __future__ import annotations

from mdviewer.themes import THEMES, resolve_theme_id


def _hex_to_rgb_floats(hex_color: str) -> tuple[float, float, float]:
    """Convert a #RRGGBB hex string into normalized (r, g, b) floats in [0.0, 1.0]."""
    cleaned = hex_color.lstrip("#")
    if len(cleaned) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {hex_color!r}")
    r = int(cleaned[0:2], 16) / 255.0
    g = int(cleaned[2:4], 16) / 255.0
    b = int(cleaned[4:6], 16) / 255.0
    return (r, g, b)


def get_webview_bg_rgba(theme_id: str) -> tuple[float, float, float, float]:
    """Return an opaque (r, g, b, a) tuple matching THEMES[theme_id].bg for WebKit2."""
    spec = THEMES[resolve_theme_id(theme_id)]
    r, g, b = _hex_to_rgb_floats(spec.bg)
    return (r, g, b, 1.0)


def get_gtksource_scheme_candidates(theme_id: str) -> tuple[str, ...]:
    """Return ordered GtkSourceView style scheme IDs best matching the theme."""
    resolved = resolve_theme_id(theme_id)
    candidates: dict[str, tuple[str, ...]] = {
        "paper": ("Yaru", "Adwaita", "kate", "tango", "classic", "solarized-light"),
        "sepia": ("solarized-light", "Yaru", "tango", "classic", "kate"),
        "obsidian": ("Yaru-dark", "Adwaita-dark", "oblivion", "solarized-dark", "classic-dark"),
        "nordic": ("oblivion", "Yaru-dark", "solarized-dark", "Adwaita-dark", "cobalt"),
    }
    return candidates[resolved]


def build_gtk_css(theme_id: str, zoom_level: float = 1.0) -> str:
    """Build valid GTK3 CSS matched to THEMES[theme_id] and current editor zoom."""
    t = THEMES[resolve_theme_id(theme_id)]
    clamped_zoom = max(0.5, min(3.0, float(zoom_level)))
    editor_pt = max(8, min(28, int(round(11 * clamped_zoom))))

    return f"""\
/* md-viewer v2 GTK3 theme: {t.id} */

window,
window.background,
box.main-root,
stack,
paned {{
    background-color: {t.bg};
    color: {t.text};
}}

paned > separator {{
    min-width: 1px;
    min-height: 1px;
    background-color: {t.border};
    background-image: none;
}}

/* HeaderBar */
headerbar,
headerbar.main-headerbar {{
    min-height: 44px;
    padding: 0 8px;
    background-color: {t.surface};
    background-image: none;
    color: {t.text};
    border-bottom: 1px solid {t.border};
    box-shadow: none;
}}

headerbar .title,
headerbar.main-headerbar .title {{
    color: {t.heading};
    font-weight: 600;
}}

headerbar .subtitle,
headerbar.main-headerbar .subtitle {{
    color: {t.muted};
    font-size: 0.82em;
}}

headerbar separator,
headerbar.main-headerbar separator {{
    background-color: {t.border};
}}

headerbar button,
headerbar.main-headerbar button {{
    background-color: transparent;
    background-image: none;
    color: {t.text};
    border: 1px solid transparent;
    border-radius: 5px;
    box-shadow: none;
    text-shadow: none;
    -gtk-icon-shadow: none;
    padding: 4px 8px;
    transition: background-color 120ms ease, border-color 120ms ease;
}}

headerbar button:hover,
headerbar.main-headerbar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border};
}}

headerbar button:active,
headerbar button:checked,
headerbar.main-headerbar button:active,
headerbar.main-headerbar button:checked {{
    background-color: {t.bg};
    border-color: {t.border_strong};
    color: {t.heading};
}}

headerbar button.suggested-action,
headerbar.main-headerbar button.suggested-action {{
    background-image: none;
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

headerbar button.suggested-action:hover,
headerbar.main-headerbar button.suggested-action:hover {{
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
}}

headerbar .linked > button,
headerbar.main-headerbar .linked > button {{
    border-color: {t.border};
    background-color: {t.bg};
}}

headerbar .linked > button:hover,
headerbar.main-headerbar .linked > button:hover {{
    background-color: {t.surface_alt};
}}

stackswitcher.mode-switcher button {{
    border-radius: 5px;
    padding: 4px 11px;
    font-size: 0.88em;
    font-weight: 500;
}}

stackswitcher.mode-switcher button:checked {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
    color: {t.heading};
    font-weight: 600;
}}

.zoom-controls button {{
    padding: 3px 7px;
    font-size: 0.84em;
}}

.doc-stats-label {{
    font-size: 0.78em;
    color: {t.muted};
    background-color: {t.bg};
    border: 1px solid {t.border};
    padding: 2px 9px;
    border-radius: 4px;
    font-weight: 500;
    margin-right: 4px;
}}

/* Document Tabs (Notebook) */
notebook,
notebook > stack {{
    background-color: {t.bg};
    color: {t.text};
    border: none;
}}

notebook > header {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 0 4px;
}}

notebook > header tabs tab {{
    background-color: transparent;
    background-image: none;
    color: {t.muted};
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 5px 10px;
    margin: 0 1px;
    box-shadow: none;
}}

notebook > header tabs tab:hover {{
    color: {t.text};
    background-color: {t.surface_alt};
}}

notebook > header tabs tab:checked {{
    background-color: {t.bg};
    color: {t.heading};
    border-left: 1px solid {t.border};
    border-right: 1px solid {t.border};
    border-bottom: 2px solid {t.accent};
    font-weight: 600;
}}

notebook > header tabs tab button {{
    padding: 1px 3px;
    min-width: 18px;
    min-height: 18px;
    border-radius: 4px;
    background: transparent;
    border: none;
    color: {t.muted};
}}

notebook > header tabs tab button:hover {{
    background-color: {t.surface_alt};
    color: {t.text};
}}

/* Sidebar (Outline, Context Inspector, Review Comments, Ask Agent) */
.sidebar,
.mdv-sidebar {{
    background-color: {t.surface};
    color: {t.text};
    border-right: 1px solid {t.border};
}}

.sidebar header,
.mdv-sidebar .sidebar-header {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 6px 8px;
}}

.sidebar-section-title {{
    color: {t.muted};
    font-size: 0.78em;
    font-weight: 600;
    letter-spacing: 0.04em;
}}

.sidebar list,
.mdv-sidebar list,
.sidebar treeview,
.mdv-sidebar treeview {{
    background-color: {t.surface};
    color: {t.text};
}}

.sidebar list row,
.mdv-sidebar list row {{
    padding: 5px 10px;
    border-radius: 4px;
    margin: 1px 4px;
    color: {t.text};
}}

.sidebar list row:hover,
.mdv-sidebar list row:hover {{
    background-color: {t.surface_alt};
}}

.sidebar list row:selected,
.mdv-sidebar list row:selected,
.sidebar list row.outline-row-active,
.mdv-sidebar list row.outline-row-active {{
    background-color: {t.bg};
    color: {t.accent};
    border-left: 2px solid {t.accent};
    font-weight: 600;
}}

.sidebar button,
.mdv-sidebar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 5px;
    box-shadow: none;
    padding: 4px 9px;
}}

.sidebar button:hover,
.mdv-sidebar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

.sidebar button.suggested-action,
.mdv-sidebar button.suggested-action {{
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

.review-comment-card,
.context-metric-card {{
    background-color: {t.bg};
    border: 1px solid {t.border};
    border-radius: 5px;
    padding: 8px 10px;
    margin: 4px 6px;
}}

list.context-metric-card {{
    padding: 4px;
    margin: 0;
}}

list.context-metric-card row {{
    padding: 4px 6px;
    border-radius: 4px;
    color: {t.text};
}}

list.context-metric-card row:hover {{
    background-color: {t.surface};
}}

.muted-label {{
    color: {t.muted};
}}

/* SearchBar, WatchBar, DiffBar, ClipboardBar & Entries */
searchbar,
searchbar > revealer > box,
.search-bar {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 5px 10px;
    color: {t.text};
}}

.search-bar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 4px;
    box-shadow: none;
    padding: 3px 9px;
}}

.search-bar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

.search-bar button:checked {{
    background-color: {t.surface_alt};
    border-color: {t.accent};
    color: {t.accent};
    font-weight: 600;
}}

.search-bar button.suggested-action {{
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

entry {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    caret-color: {t.accent};
    border: 1px solid {t.border_strong};
    border-radius: 5px;
    padding: 4px 8px;
    box-shadow: none;
}}

entry:focus {{
    border-color: {t.accent};
}}

entry selection {{
    background-color: {t.accent};
    color: {t.accent_contrast};
}}

.search-match-label {{
    color: {t.muted};
    font-size: 0.82em;
    padding: 0 6px;
}}

/* InfoBar (Remote images blocked, external change notice, git diff error) */
infobar,
infobar > revealer > box {{
    background-color: {t.surface};
    background-image: none;
    color: {t.text};
    border-bottom: 1px solid {t.border};
    box-shadow: none;
    padding: 4px 10px;
}}

infobar.info > revealer > box {{
    background-color: {t.note_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

infobar.warning > revealer > box {{
    background-color: {t.warning_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

infobar.error > revealer > box {{
    background-color: {t.caution_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

infobar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    padding: 3px 9px;
    box-shadow: none;
}}

infobar button:hover {{
    background-color: {t.surface_alt};
}}

/* StatusBar */
.status-bar,
.mdv-statusbar {{
    background-color: {t.surface};
    color: {t.muted};
    border-top: 1px solid {t.border};
    padding: 3px 12px;
    font-size: 0.8em;
}}

.status-bar label,
.mdv-statusbar label {{
    color: {t.muted};
}}

.mdv-statusbar .doc-stats-label {{
    background-color: transparent;
    border: none;
    padding: 0;
    margin-right: 0;
    font-size: 1em;
    color: {t.muted};
}}

.mdv-statusbar .zoom-controls button {{
    background-color: transparent;
    background-image: none;
    border: 1px solid transparent;
    color: {t.muted};
    padding: 1px 6px;
    min-height: 20px;
    box-shadow: none;
}}

.mdv-statusbar .zoom-controls button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border};
    color: {t.text};
}}

.watch-badge {{
    color: {t.muted};
    background-color: {t.bg};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 0.78em;
    font-weight: 600;
}}

.watch-badge.active {{
    color: {t.valid_fg};
    background-color: {t.valid_bg};
    border-color: {t.valid_border};
}}

.readonly-badge {{
    color: {t.warning_fg};
    background-color: {t.warning_bg};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 0.78em;
    font-weight: 600;
}}

/* Preview & Source Scrolled Containers — Zero White Flash */
scrolledwindow,
scrolledwindow viewport,
scrolledwindow.preview-scrolled,
scrolledwindow.preview-scrolled viewport,
scrolledwindow.source-scrolled,
scrolledwindow.source-scrolled viewport {{
    background-color: {t.bg};
}}

/* General TextViews (e.g., CommentEditorDialog) & GtkSourceView Editor */
textview,
textview text {{
    background-color: {t.bg};
    color: {t.text};
    caret-color: {t.accent};
}}

textview.editor-source,
textview.editor-source text {{
    background-color: {t.bg};
    color: {t.text};
    caret-color: {t.accent};
    font-family: "JetBrains Mono", "IBM Plex Mono", "Fira Code", "Ubuntu Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: {editor_pt}pt;
}}

textview.editor-source border {{
    background-color: {t.surface};
    color: {t.muted};
}}

textview.editor-source text selection {{
    background-color: {t.accent};
    color: {t.accent_contrast};
}}

/* Popovers & Menus */
popover,
popover.background,
menu {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 6px;
}}

popover modelbutton,
menu menuitem {{
    color: {t.text};
    padding: 5px 10px;
    border-radius: 4px;
}}

popover modelbutton:hover,
menu menuitem:hover {{
    background-color: {t.surface_alt};
    color: {t.heading};
}}

/* Progress / Token budget bars */
progressbar trough {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 3px;
    min-height: 6px;
}}

progressbar progress {{
    background-color: {t.accent};
    border-radius: 3px;
    min-height: 6px;
}}
"""
