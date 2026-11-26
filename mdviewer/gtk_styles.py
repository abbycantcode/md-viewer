"""GTK3 chrome styling, WebView background matching, and GtkSourceView schemes.

All GTK3 rules are scoped strictly to `.markveil-window` and `.markveil-popover`
so native system dialogs (FileChooser, Print, MessageDialog) keep pure OS styling
with zero CSS leakage, while Markveil's own windows and dialogs match THEMES[theme_id]
with zero white flash.
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
    """Build valid GTK3 CSS scoped strictly to Markveil windows and popovers."""
    t = THEMES[resolve_theme_id(theme_id)]
    clamped_zoom = max(0.5, min(3.0, float(zoom_level)))
    editor_pt = max(8, min(28, int(round(11 * clamped_zoom))))

    return f"""\
/* Markveil GTK3 theme: {t.id} (strictly scoped to .markveil-window) */

window.markveil-window,
window.markveil-window.background,
.markveil-window box.main-root,
.markveil-window stack,
.markveil-window paned {{
    background-color: {t.bg};
    color: {t.text};
}}

.markveil-window paned > separator {{
    min-width: 1px;
    min-height: 1px;
    background-color: {t.border};
    background-image: none;
}}

/* HeaderBar */
.markveil-window headerbar,
.markveil-window headerbar.main-headerbar {{
    min-height: 44px;
    padding: 0 8px;
    background-color: {t.surface};
    background-image: none;
    color: {t.text};
    border-bottom: 1px solid {t.border};
    box-shadow: none;
}}

.markveil-window headerbar .title,
.markveil-window headerbar.main-headerbar .title {{
    color: {t.heading};
    font-weight: 600;
}}

.markveil-window headerbar .subtitle,
.markveil-window headerbar.main-headerbar .subtitle {{
    color: {t.muted};
    font-size: 0.82em;
}}

.markveil-window headerbar separator,
.markveil-window headerbar.main-headerbar separator {{
    background-color: {t.border};
}}

.markveil-window headerbar button,
.markveil-window headerbar.main-headerbar button {{
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

.markveil-window headerbar button:hover,
.markveil-window headerbar.main-headerbar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border};
}}

.markveil-window headerbar button:active,
.markveil-window headerbar button:checked,
.markveil-window headerbar.main-headerbar button:active,
.markveil-window headerbar.main-headerbar button:checked {{
    background-color: {t.bg};
    border-color: {t.border_strong};
    color: {t.heading};
}}

.markveil-window headerbar button.suggested-action,
.markveil-window headerbar.main-headerbar button.suggested-action {{
    background-image: none;
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

.markveil-window headerbar button.suggested-action:hover,
.markveil-window headerbar.main-headerbar button.suggested-action:hover {{
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
}}

.markveil-window headerbar .linked > button,
.markveil-window headerbar.main-headerbar .linked > button {{
    border-color: {t.border};
    background-color: {t.bg};
}}

.markveil-window headerbar .linked > button:hover,
.markveil-window headerbar.main-headerbar .linked > button:hover {{
    background-color: {t.surface_alt};
}}

.markveil-window stackswitcher.mode-switcher button {{
    border-radius: 5px;
    padding: 4px 11px;
    font-size: 0.88em;
    font-weight: 500;
}}

.markveil-window stackswitcher.mode-switcher button:checked {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
    color: {t.heading};
    font-weight: 600;
}}

.markveil-window .zoom-controls button {{
    padding: 3px 7px;
    font-size: 0.84em;
}}

.markveil-window .doc-stats-label {{
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
.markveil-window notebook,
.markveil-window notebook > stack {{
    background-color: {t.bg};
    color: {t.text};
    border: none;
}}

.markveil-window notebook > header {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 0 4px;
}}

.markveil-window notebook > header tabs tab {{
    background-color: transparent;
    background-image: none;
    color: {t.muted};
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 5px 10px;
    margin: 0 1px;
    box-shadow: none;
}}

.markveil-window notebook > header tabs tab:hover {{
    color: {t.text};
    background-color: {t.surface_alt};
}}

.markveil-window notebook > header tabs tab:checked {{
    background-color: {t.bg};
    color: {t.heading};
    border-left: 1px solid {t.border};
    border-right: 1px solid {t.border};
    border-bottom: 2px solid {t.accent};
    font-weight: 600;
}}

.markveil-window notebook > header tabs tab button {{
    padding: 1px 3px;
    min-width: 18px;
    min-height: 18px;
    border-radius: 4px;
    background: transparent;
    border: none;
    color: {t.muted};
}}

.markveil-window notebook > header tabs tab button:hover {{
    background-color: {t.surface_alt};
    color: {t.text};
}}

/* Sidebar (Outline, Context Inspector, Review Comments) */
.markveil-window .sidebar,
.markveil-window .mdv-sidebar {{
    background-color: {t.surface};
    color: {t.text};
    border-right: 1px solid {t.border};
}}

.markveil-window .sidebar header,
.markveil-window .mdv-sidebar .sidebar-header {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 6px 8px;
}}

.markveil-window .sidebar-section-title {{
    color: {t.muted};
    font-size: 0.78em;
    font-weight: 600;
    letter-spacing: 0.04em;
}}

.markveil-window .sidebar list,
.markveil-window .mdv-sidebar list,
.markveil-window .sidebar treeview,
.markveil-window .mdv-sidebar treeview {{
    background-color: {t.surface};
    color: {t.text};
}}

.markveil-window .sidebar list row,
.markveil-window .mdv-sidebar list row {{
    padding: 5px 10px;
    border-radius: 4px;
    margin: 1px 4px;
    color: {t.text};
}}

.markveil-window .sidebar list row:hover,
.markveil-window .mdv-sidebar list row:hover {{
    background-color: {t.surface_alt};
}}

.markveil-window .sidebar list row:selected,
.markveil-window .mdv-sidebar list row:selected,
.markveil-window .sidebar list row.outline-row-active,
.markveil-window .mdv-sidebar list row.outline-row-active {{
    background-color: {t.bg};
    color: {t.accent};
    border-left: 2px solid {t.accent};
    font-weight: 600;
}}

.markveil-window .sidebar button,
.markveil-window .mdv-sidebar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 5px;
    box-shadow: none;
    padding: 4px 9px;
}}

.markveil-window .sidebar button:hover,
.markveil-window .mdv-sidebar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

.markveil-window .sidebar button.suggested-action,
.markveil-window .mdv-sidebar button.suggested-action {{
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

.markveil-window .review-comment-card,
.markveil-window .context-metric-card {{
    background-color: {t.bg};
    border: 1px solid {t.border};
    border-radius: 5px;
    padding: 8px 10px;
    margin: 4px 6px;
}}

.markveil-window list.context-metric-card {{
    padding: 4px;
    margin: 0;
}}

.markveil-window list.context-metric-card row {{
    padding: 4px 6px;
    border-radius: 4px;
    color: {t.text};
}}

.markveil-window list.context-metric-card row:hover {{
    background-color: {t.surface};
}}

.markveil-window .muted-label {{
    color: {t.muted};
}}

/* SearchBar, WatchBar, DiffBar, ClipboardBar & Entries */
.markveil-window searchbar,
.markveil-window searchbar > revealer > box,
.markveil-window .search-bar {{
    background-color: {t.surface};
    border-bottom: 1px solid {t.border};
    padding: 5px 10px;
    color: {t.text};
}}

.markveil-window .search-bar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 4px;
    box-shadow: none;
    padding: 3px 9px;
}}

.markveil-window .search-bar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

.markveil-window .search-bar button:checked {{
    background-color: {t.surface_alt};
    border-color: {t.accent};
    color: {t.accent};
    font-weight: 600;
}}

.markveil-window .search-bar button.suggested-action {{
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
    font-weight: 600;
}}

.markveil-window entry {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    caret-color: {t.accent};
    border: 1px solid {t.border_strong};
    border-radius: 5px;
    padding: 4px 8px;
    box-shadow: none;
}}

.markveil-window entry:focus {{
    border-color: {t.accent};
}}

.markveil-window entry selection {{
    background-color: {t.accent};
    color: {t.accent_contrast};
}}

.markveil-window .search-match-label {{
    color: {t.muted};
    font-size: 0.82em;
    padding: 0 6px;
}}

/* InfoBar */
.markveil-window infobar,
.markveil-window infobar > revealer > box {{
    background-color: {t.surface};
    background-image: none;
    color: {t.text};
    border-bottom: 1px solid {t.border};
    box-shadow: none;
    padding: 4px 10px;
}}

.markveil-window infobar.info > revealer > box {{
    background-color: {t.note_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

.markveil-window infobar.warning > revealer > box {{
    background-color: {t.warning_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

.markveil-window infobar.error > revealer > box {{
    background-color: {t.caution_bg};
    border-bottom-color: {t.border};
    color: {t.text};
}}

.markveil-window infobar button {{
    background-color: {t.bg};
    background-image: none;
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    padding: 3px 9px;
    box-shadow: none;
}}

.markveil-window infobar button:hover {{
    background-color: {t.surface_alt};
}}

/* StatusBar */
.markveil-window .status-bar,
.markveil-window .mdv-statusbar {{
    background-color: {t.surface};
    color: {t.muted};
    border-top: 1px solid {t.border};
    padding: 3px 12px;
    font-size: 0.8em;
}}

.markveil-window .status-bar label,
.markveil-window .mdv-statusbar label {{
    color: {t.muted};
}}

.markveil-window .mdv-statusbar .doc-stats-label {{
    background-color: transparent;
    border: none;
    padding: 0;
    margin-right: 0;
    font-size: 1em;
    color: {t.muted};
}}

.markveil-window .mdv-statusbar .zoom-controls button {{
    background-color: transparent;
    background-image: none;
    border: 1px solid transparent;
    color: {t.muted};
    padding: 1px 6px;
    min-height: 20px;
    box-shadow: none;
}}

.markveil-window .mdv-statusbar .zoom-controls button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border};
    color: {t.text};
}}

.markveil-window .watch-badge {{
    color: {t.muted};
    background-color: {t.bg};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 0.78em;
    font-weight: 600;
}}

.markveil-window .watch-badge.active {{
    color: {t.valid_fg};
    background-color: {t.valid_bg};
    border-color: {t.valid_border};
}}

.markveil-window .readonly-badge {{
    color: {t.warning_fg};
    background-color: {t.warning_bg};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 0.78em;
    font-weight: 600;
}}

/* Preview & Source Scrolled Containers */
.markveil-window scrolledwindow,
.markveil-window scrolledwindow viewport,
.markveil-window scrolledwindow.preview-scrolled,
.markveil-window scrolledwindow.preview-scrolled viewport,
.markveil-window scrolledwindow.source-scrolled,
.markveil-window scrolledwindow.source-scrolled viewport {{
    background-color: {t.bg};
}}

/* TextViews & GtkSourceView Editor */
.markveil-window textview,
.markveil-window textview text {{
    background-color: {t.bg};
    color: {t.text};
    caret-color: {t.accent};
}}

.markveil-window textview.editor-source,
.markveil-window textview.editor-source text {{
    background-color: {t.bg};
    color: {t.text};
    caret-color: {t.accent};
    font-family: "JetBrains Mono", "IBM Plex Mono", "Fira Code", "Ubuntu Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: {editor_pt}pt;
}}

.markveil-window textview.editor-source border {{
    background-color: {t.surface};
    color: {t.muted};
}}

.markveil-window textview.editor-source text selection {{
    background-color: {t.accent};
    color: {t.accent_contrast};
}}

/* Markveil App Popover */
popover.markveil-popover,
popover.markveil-popover.background {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 6px;
}}

popover.markveil-popover modelbutton {{
    color: {t.text};
    padding: 5px 10px;
    border-radius: 4px;
}}

popover.markveil-popover modelbutton:hover {{
    background-color: {t.surface_alt};
    color: {t.heading};
}}

/* Progress / Token budget bars */
.markveil-window progressbar trough {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 3px;
    min-height: 6px;
}}

.markveil-window progressbar progress {{
    background-color: {t.accent};
    border-radius: 3px;
    min-height: 6px;
}}
"""
