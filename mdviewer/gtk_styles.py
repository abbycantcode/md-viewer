"""Scoped Folio studio chrome, editor schemes, and WebKit background colors."""

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
        "folio": ("markveil-folio", "classic"),
        "paper": ("Yaru", "Adwaita", "kate", "tango", "classic", "solarized-light"),
        "sepia": ("solarized-light", "Yaru", "tango", "classic", "kate"),
        "obsidian": ("Yaru-dark", "Adwaita-dark", "oblivion", "solarized-dark", "classic-dark"),
        "nordic": ("oblivion", "Yaru-dark", "solarized-dark", "Adwaita-dark", "cobalt"),
    }
    return candidates[resolved]


def build_gtk_css(theme_id: str, zoom_level: float = 1.0) -> str:
    """Build application-scoped GTK3 chrome for the selected document palette."""
    t = THEMES[resolve_theme_id(theme_id)]
    clamped_zoom = max(0.5, min(3.0, float(zoom_level)))
    editor_pt = max(8, min(28, int(round(11 * clamped_zoom))))

    return f"""
.markveil-window, .markveil-window .main-root {{
    background-color: {t.bg};
    color: {t.text};
    font-family: "IBM Plex Sans", "Cantarell", sans-serif;
}}
.markveil-window button, .markveil-popover button {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 4px; box-shadow: none; text-shadow: none;
}}
.markveil-window button:hover, .markveil-popover button:hover {{ background: {t.surface_alt}; }}
.markveil-window button:checked {{ background: {t.selection_bg}; color: {t.selection_text}; }}
.markveil-window button:disabled {{ color: {t.muted}; opacity: 0.65; }}
.markveil-window button label, .markveil-window button image,
.markveil-window row:selected label, .markveil-window row:selected image,
.markveil-popover button label {{ color: inherit; }}
.markveil-window entry, .markveil-window textview:not(.editor-source) text {{
    background: {t.bg}; color: {t.text}; caret-color: {t.text};
}}
.markveil-window entry {{ border: 1px solid {t.border_strong}; box-shadow: none; }}
.markveil-window entry placeholder {{ color: {t.muted}; }}
.markveil-window entry:focus {{ border-color: {t.accent}; }}
.markveil-window switch {{ background: {t.border_strong}; border: none; }}
.markveil-window switch:checked {{ background: {t.accent}; }}
.markveil-window switch slider {{ background: {t.bg}; border: 1px solid {t.border_strong}; }}
.markveil-window .sidebar-header stackswitcher {{ background: transparent; box-shadow: none; }}
.markveil-window .workspace-location {{
    color: {t.muted}; border-top: 1px solid {t.border}; padding: 10px 16px; font-size: 0.9em;
}}
.markveil-popover, .markveil-popover.background {{ background: {t.bg}; color: {t.text}; }}
.markveil-popover button {{ border: none; background: transparent; }}
.markveil-popover modelbutton, .markveil-popover modelbutton label,
.markveil-window headerbar.main-headerbar .markveil-popover button,
.markveil-window headerbar.main-headerbar .markveil-popover button label {{
    color: {t.text}; background: transparent; text-shadow: none;
}}
.markveil-popover modelbutton:hover,
.markveil-window headerbar.main-headerbar .markveil-popover button:hover {{
    background: {t.surface_alt};
}}
.markveil-popover .muted-label {{ color: {t.muted}; }}
.markveil-window headerbar.main-headerbar {{
    background-image: none;
    background-color: #253f32;
    color: #f5f6e6;
    border: none;
    box-shadow: none;
    padding: 5px 12px;
    min-height: 42px;
}}
.markveil-window headerbar .wordmark, .markveil-window .welcome-title {{
    font-family: "Bitstream Charter", Georgia, serif;
    font-size: 23px;
    font-weight: bold;
}}
.markveil-window .welcome-title {{ font-size: 36px; font-weight: normal; }}
.markveil-window headerbar .location {{ color: #dce6d5; font-size: 0.92em; }}
.markveil-window headerbar.main-headerbar button,
.markveil-window .mdv-sidebar button,
.markveil-window .mdv-statusbar button,
.markveil-window .search-bar button,
.markveil-window .document-close {{
    background-image: none;
    background-color: transparent;
    color: inherit;
    border: none;
    box-shadow: none;
    text-shadow: none;
    border-radius: 4px;
    min-height: 24px;
    min-width: 18px;
    padding: 3px 6px;
}}
.markveil-window headerbar.main-headerbar button {{ color: #f5f6e6; }}
.markveil-window headerbar.main-headerbar button:disabled {{ color: #9aae9d; }}
.markveil-window headerbar.main-headerbar button:hover,
.markveil-window headerbar.main-headerbar button:checked {{ background-color: #3a5544; }}
.markveil-window headerbar.main-headerbar button.suggested-action {{ background-color: #dae5bd; color: #253f32; }}
.markveil-window headerbar.main-headerbar .mode-switcher {{
    background-color: #395343;
    padding: 3px;
    border-radius: 6px;
}}
.markveil-window headerbar.main-headerbar .mode-switcher button {{ padding: 2px 10px; }}
.markveil-window headerbar.main-headerbar .mode-switcher button:checked {{
    background-color: #f5f6e6;
    color: #253f32;
}}
.markveil-window .mdv-sidebar, .markveil-window .mdv-statusbar,
.markveil-window .search-bar {{ background-color: {t.surface}; color: {t.text}; }}
.markveil-window .mdv-sidebar list, .markveil-window .mdv-sidebar viewport,
.markveil-window .context-metric-card, .markveil-window .preview-scrolled viewport {{
    background-color: transparent; color: {t.text};
}}
.markveil-window .mdv-sidebar list {{ padding: 0 10px; }}
.markveil-window .mdv-sidebar list row {{
    padding: 3px 8px;
    border-radius: 3px;
    color: {t.muted};
    min-height: 24px;
}}
.markveil-window .mdv-sidebar row:hover,
.markveil-window .mdv-sidebar button:hover, .markveil-window .search-bar button:hover,
.markveil-window .mdv-statusbar button:hover {{ background-color: {t.surface_alt}; }}
.markveil-window .mdv-sidebar list row:selected,
.markveil-window .mdv-sidebar list row.outline-row-active,
.markveil-window .sidebar-header button:checked, .markveil-window .search-bar button:checked {{
    background-color: {t.selection_bg}; color: {t.selection_text};
}}
.markveil-window .open-documents row:selected {{ font-weight: bold; }}
.markveil-window .mdv-sidebar list row:selected label,
.markveil-window .mdv-sidebar list row:selected image {{ color: {t.selection_text}; }}
.markveil-window .mdv-sidebar stackswitcher button image {{ color: {t.text}; }}
.markveil-window .mdv-sidebar .document-close, .markveil-window .mdv-sidebar .anchor-copy {{
    padding: 1px 3px; min-width: 16px; min-height: 19px; opacity: 0;
}}
.markveil-window .mdv-sidebar row:hover button, .markveil-window .mdv-sidebar row:focus button,
.markveil-window .mdv-sidebar button:focus {{ opacity: 1; }}
.markveil-window .rail-title {{
    padding: 15px 18px 8px; font-size: 0.9em; font-weight: bold; color: {t.muted};
}}
.markveil-window .sidebar-header {{
    margin: 16px 12px 0; padding: 10px 0 0; border-top: 1px solid {t.border};
}}
.markveil-window .sidebar-header button {{ padding: 4px 11px; }}
.markveil-window .sidebar-section-title {{ font-weight: bold; font-size: 0.92em; color: {t.heading}; }}
.markveil-window .muted-label, .markveil-window .search-match-label {{ color: {t.muted}; }}
.markveil-window .review-comment-card, .markveil-window .context-metric-card {{
    padding: 8px 6px; margin: 1px 10px; border-bottom: 1px solid {t.border};
}}
.markveil-window .search-bar {{ padding: 5px 10px; border-bottom: 1px solid {t.border}; }}
.markveil-window .mdv-statusbar {{
    border-top: 1px solid {t.border}; padding: 1px 12px; font-size: 0.85em; color: {t.muted};
}}
.markveil-window .mdv-statusbar button {{ min-height: 19px; padding: 1px 5px; }}
.markveil-window .watch-badge.active {{ color: {t.accent}; font-weight: bold; }}
.markveil-window .readonly-badge {{ color: {t.warning_fg}; background: {t.warning_bg}; padding: 0 5px; }}
.markveil-window paned > separator {{ min-width: 1px; background: {t.border}; }}
.markveil-window notebook > header {{ background: {t.surface}; border: 0; }}
.markveil-window notebook > header tab {{ background: transparent; color: {t.muted}; }}
.markveil-window notebook > header tab:checked {{ color: {t.heading}; box-shadow: inset 0 -2px {t.accent}; }}
.markveil-window .preview-scrolled {{ background-color: {t.bg}; }}
.markveil-window textview.editor-source, .markveil-window textview.editor-source text {{
    font-family: "IBM Plex Mono", "Ubuntu Mono", monospace;
    font-size: {editor_pt}pt;
}}
.markveil-window progressbar trough {{ background: {t.surface_alt}; min-height: 4px; border: 0; }}
.markveil-window progressbar progress {{ background: {t.accent}; min-height: 4px; border: 0; }}
.markveil-window button:focus, .markveil-window row:focus {{
    outline-style: solid; outline-width: 1px; outline-offset: -2px; outline-color: {t.accent};
}}
.markveil-window headerbar.main-headerbar button:focus {{ outline-color: #a5ba8f; }}
.markveil-window .preview-scrolled button.suggested-action,
dialog.markveil-window button.suggested-action {{
    background: {t.accent}; color: {t.accent_contrast}; border: none; box-shadow: none;
}}
"""
