"""Minimal, native-respecting GTK3 chrome CSS, WebView background matching, and GtkSourceView schemes.

Markveil leaves window chrome, HeaderBar, Notebook tabs, buttons, entries, and
popovers to the user's active GTK3 desktop theme (Yaru, Adwaita, Obsidian-Glass,
Catppuccin, Breeze, etc.) so there are no mismatched double-frames or theme clashes.
Only subtle alpha-blended utility accents, editor typography/zoom, and the WebView
preview container background (zero white flash) are styled here.
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
    """Build minimal GTK3 CSS that harmonizes with any system GTK3 theme."""
    t = THEMES[resolve_theme_id(theme_id)]
    clamped_zoom = max(0.5, min(3.0, float(zoom_level)))
    editor_pt = max(8, min(28, int(round(11 * clamped_zoom))))

    return f"""\
/* Markveil native-respecting GTK3 utilities (document theme: {t.id}) */

.markveil-window headerbar.main-headerbar {{
    min-height: 42px;
    padding-left: 8px;
    padding-right: 8px;
}}

.markveil-window stackswitcher.mode-switcher button {{
    padding-left: 10px;
    padding-right: 10px;
    font-size: 0.88em;
}}

.markveil-window .sidebar-section-title {{
    color: alpha(currentColor, 0.58);
    font-size: 0.76em;
    font-weight: 600;
    letter-spacing: 0.04em;
}}

.markveil-window .muted-label {{
    color: alpha(currentColor, 0.65);
}}

.markveil-window .mdv-sidebar {{
    border-right: 1px solid alpha(currentColor, 0.12);
}}

.markveil-window .mdv-sidebar list row {{
    padding: 5px 10px;
    border-radius: 5px;
    margin: 1px 4px;
}}

.markveil-window .mdv-sidebar list row.outline-row-active {{
    background-color: alpha(currentColor, 0.08);
    border-left: 2px solid {t.accent};
    font-weight: 600;
}}

.markveil-window .review-comment-card,
.markveil-window .context-metric-card {{
    background-color: alpha(currentColor, 0.04);
    border: 1px solid alpha(currentColor, 0.12);
    border-radius: 6px;
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
}}

.markveil-window .search-bar {{
    border-bottom: 1px solid alpha(currentColor, 0.12);
    padding: 5px 10px;
}}

.markveil-window .search-match-label {{
    color: alpha(currentColor, 0.65);
    font-size: 0.82em;
    padding: 0 6px;
}}

.markveil-window .mdv-statusbar {{
    border-top: 1px solid alpha(currentColor, 0.12);
    padding: 3px 12px;
    font-size: 0.8em;
}}

.markveil-window .mdv-statusbar label {{
    color: alpha(currentColor, 0.7);
}}

.markveil-window .mdv-statusbar .zoom-controls button {{
    padding: 1px 6px;
    min-height: 20px;
}}

.markveil-window .watch-badge {{
    color: alpha(currentColor, 0.72);
    border: 1px solid alpha(currentColor, 0.18);
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
    border: 1px solid alpha(currentColor, 0.18);
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 0.78em;
    font-weight: 600;
}}

/* Match WebKit2 preview container background to document theme (zero white flash) */
.markveil-window scrolledwindow.preview-scrolled,
.markveil-window scrolledwindow.preview-scrolled viewport {{
    background-color: {t.bg};
}}

/* GtkSourceView editor typography and zoom */
.markveil-window textview.editor-source,
.markveil-window textview.editor-source text {{
    font-family: "JetBrains Mono", "IBM Plex Mono", "Fira Code", "Ubuntu Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: {editor_pt}pt;
}}

/* Token budget progress bars */
.markveil-window progressbar trough {{
    border-radius: 3px;
    min-height: 6px;
}}

.markveil-window progressbar progress {{
    background-color: {t.accent};
    border-radius: 3px;
    min-height: 6px;
}}
"""
