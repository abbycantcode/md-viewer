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
    """Build application-scoped GTK3 chrome immune to hostile dark user themes.

    Registered at Gtk.STYLE_PROVIDER_PRIORITY_USER (800) with explicit state rules
    (enabled, :hover, :checked, :disabled) using strictly THEMES[theme_id] tokens.
    """
    t = THEMES[resolve_theme_id(theme_id)]
    clamped_zoom = max(0.5, min(3.0, float(zoom_level)))
    editor_pt = max(8, min(28, int(round(11 * clamped_zoom))))

    return f"""
window.markveil-window,
window.markveil-window.background,
dialog.markveil-window,
dialog.markveil-window.background,
messagedialog.markveil-window,
messagedialog.markveil-window.background,
.markveil-window .main-root,
dialog.markveil-window .dialog-vbox,
messagedialog.markveil-window .dialog-vbox {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    font-family: "IBM Plex Sans", "Cantarell", sans-serif;
    text-shadow: none;
}}

.markveil-window label,
dialog.markveil-window label,
messagedialog.markveil-window label,
.markveil-popover label {{
    color: {t.text};
    text-shadow: none;
}}

.markveil-window .muted-label,
dialog.markveil-window .muted-label,
.markveil-window .search-match-label,
.markveil-popover .muted-label {{
    color: {t.muted};
}}

.markveil-window .sidebar-section-title,
dialog.markveil-window .sidebar-section-title,
.markveil-popover .sidebar-section-title {{
    font-weight: bold;
    font-size: 0.92em;
    color: {t.heading};
}}

/* General buttons inside windows and dialogs (explicit states beat user gtk.css) */
window.markveil-window button,
dialog.markveil-window button,
messagedialog.markveil-window button {{
    background-image: none;
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    box-shadow: none;
    text-shadow: none;
    opacity: 1.0;
}}
window.markveil-window button label,
window.markveil-window button image,
dialog.markveil-window button label,
dialog.markveil-window button image,
messagedialog.markveil-window button label,
messagedialog.markveil-window button image {{
    color: {t.text};
    text-shadow: none;
    opacity: 1.0;
}}
window.markveil-window button:hover,
dialog.markveil-window button:hover,
messagedialog.markveil-window button:hover {{
    background-image: none;
    background-color: {t.surface_alt};
    color: {t.heading};
    border-color: {t.accent};
}}
window.markveil-window button:hover label,
dialog.markveil-window button:hover label,
messagedialog.markveil-window button:hover label {{
    color: {t.heading};
}}
window.markveil-window button:checked,
window.markveil-window button:active,
dialog.markveil-window button:checked,
dialog.markveil-window button:active {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
    border-color: {t.accent};
}}
window.markveil-window button:checked label,
window.markveil-window button:checked image,
dialog.markveil-window button:checked label {{
    color: {t.selection_text};
}}
window.markveil-window button:disabled,
dialog.markveil-window button:disabled,
messagedialog.markveil-window button:disabled {{
    background-image: none;
    background-color: {t.surface};
    color: {t.muted};
    border-color: {t.border};
    box-shadow: none;
    text-shadow: none;
    opacity: 1.0;
}}
window.markveil-window button:disabled label,
window.markveil-window button:disabled image,
dialog.markveil-window button:disabled label,
dialog.markveil-window button:disabled image,
messagedialog.markveil-window button:disabled label,
messagedialog.markveil-window button:disabled image {{
    color: {t.muted};
    text-shadow: none;
    opacity: 1.0;
}}

/* Suggested / primary action buttons */
window.markveil-window button.suggested-action,
dialog.markveil-window button.suggested-action,
messagedialog.markveil-window button.suggested-action {{
    background-image: none;
    background-color: {t.accent};
    color: {t.accent_contrast};
    border: 1px solid {t.accent};
    box-shadow: none;
    text-shadow: none;
}}
window.markveil-window button.suggested-action label,
window.markveil-window button.suggested-action image,
dialog.markveil-window button.suggested-action label,
messagedialog.markveil-window button.suggested-action label {{
    color: {t.accent_contrast};
    text-shadow: none;
}}
window.markveil-window button.suggested-action:hover,
dialog.markveil-window button.suggested-action:hover,
messagedialog.markveil-window button.suggested-action:hover {{
    background-image: none;
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
    color: {t.accent_contrast};
}}
window.markveil-window button.suggested-action:disabled,
dialog.markveil-window button.suggested-action:disabled,
messagedialog.markveil-window button.suggested-action:disabled {{
    background-image: none;
    background-color: {t.surface_alt};
    color: {t.muted};
    border-color: {t.border};
    opacity: 1.0;
}}
window.markveil-window button.suggested-action:disabled label,
dialog.markveil-window button.suggested-action:disabled label {{
    color: {t.muted};
    opacity: 1.0;
}}

/* Entries, TextViews, Switches */
window.markveil-window entry,
dialog.markveil-window entry,
window.markveil-window textview:not(.editor-source),
window.markveil-window textview:not(.editor-source) text,
dialog.markveil-window textview:not(.editor-source),
dialog.markveil-window textview:not(.editor-source) text {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    caret-color: {t.text};
}}
window.markveil-window entry,
dialog.markveil-window entry {{
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    box-shadow: none;
}}
window.markveil-window entry placeholder,
dialog.markveil-window entry placeholder {{
    color: {t.muted};
}}
window.markveil-window entry:focus,
dialog.markveil-window entry:focus {{
    border-color: {t.accent};
}}
window.markveil-window entry:disabled,
dialog.markveil-window entry:disabled {{
    background-color: {t.surface};
    color: {t.muted};
    border-color: {t.border};
}}
window.markveil-window switch,
dialog.markveil-window switch {{
    background-image: none;
    background-color: {t.border_strong};
    border: 1px solid {t.border_strong};
    border-radius: 12px;
    box-shadow: none;
}}
window.markveil-window switch:checked,
dialog.markveil-window switch:checked {{
    background-image: none;
    background-color: {t.accent};
    border-color: {t.accent};
}}
window.markveil-window switch slider,
dialog.markveil-window switch slider {{
    background-image: none;
    background-color: {t.bg};
    border: 1px solid {t.border_strong};
}}

/* ComboBox, CheckButton, RadioButton, Menus */
window.markveil-window combobox button.combo,
dialog.markveil-window combobox button.combo {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    box-shadow: none;
    padding: 3px 8px;
}}
window.markveil-window combobox button.combo cellview,
window.markveil-window combobox button.combo label,
window.markveil-window combobox button.combo arrow,
dialog.markveil-window combobox button.combo cellview,
dialog.markveil-window combobox button.combo label,
dialog.markveil-window combobox button.combo arrow {{
    color: {t.text};
}}
window.markveil-window combobox button.combo:hover,
dialog.markveil-window combobox button.combo:hover {{
    background-color: {t.surface_alt};
    border-color: {t.accent};
}}
window.markveil-window combobox button.combo:disabled,
dialog.markveil-window combobox button.combo:disabled {{
    background-color: {t.surface};
    color: {t.muted};
    border-color: {t.border};
    opacity: 1.0;
}}
window.markveil-window combobox button.combo:disabled cellview,
window.markveil-window combobox button.combo:disabled label,
dialog.markveil-window combobox button.combo:disabled cellview,
dialog.markveil-window combobox button.combo:disabled label {{
    color: {t.muted};
}}

window.markveil-window menu,
dialog.markveil-window menu {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border_strong};
}}
window.markveil-window menu menuitem,
dialog.markveil-window menu menuitem {{
    background-image: none;
    background-color: transparent;
    color: {t.text};
}}
window.markveil-window menu menuitem:hover,
dialog.markveil-window menu menuitem:hover {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
}}

window.markveil-window checkbutton,
dialog.markveil-window checkbutton,
.markveil-popover checkbutton,
window.markveil-window radiobutton,
dialog.markveil-window radiobutton {{
    background-image: none;
    background-color: transparent;
    color: {t.text};
}}
window.markveil-window checkbutton label,
dialog.markveil-window checkbutton label,
.markveil-popover checkbutton label,
window.markveil-window radiobutton label,
dialog.markveil-window radiobutton label {{
    color: {t.text};
}}
window.markveil-window checkbutton:disabled label,
dialog.markveil-window checkbutton:disabled label,
window.markveil-window radiobutton:disabled label,
dialog.markveil-window radiobutton:disabled label {{
    color: {t.muted};
}}
window.markveil-window checkbutton check,
dialog.markveil-window checkbutton check,
.markveil-popover checkbutton check,
window.markveil-window radiobutton radio,
dialog.markveil-window radiobutton radio {{
    background-image: none;
    background-color: {t.bg};
    border: 1px solid {t.border_strong};
    color: {t.accent_contrast};
    box-shadow: none;
}}
window.markveil-window checkbutton check:checked,
dialog.markveil-window checkbutton check:checked,
.markveil-popover checkbutton check:checked,
window.markveil-window radiobutton radio:checked,
dialog.markveil-window radiobutton radio:checked {{
    background-image: none;
    background-color: {t.accent};
    border-color: {t.accent};
    color: {t.accent_contrast};
}}

/* InfoBars */
window.markveil-window infobar,
window.markveil-window infobar > revealer > box {{
    background-image: none;
    background-color: {t.note_bg};
    color: {t.text};
    border-bottom: 1px solid {t.border};
    box-shadow: none;
}}
window.markveil-window infobar.warning,
window.markveil-window infobar.warning > revealer > box {{
    background-color: {t.warning_bg};
    color: {t.warning_fg};
}}
window.markveil-window infobar.error,
window.markveil-window infobar.error > revealer > box {{
    background-color: {t.caution_bg};
    color: {t.caution_fg};
}}
window.markveil-window infobar label {{
    color: {t.text};
}}
window.markveil-window infobar.warning label {{
    color: {t.warning_fg};
}}
window.markveil-window infobar.error label {{
    color: {t.caution_fg};
}}
window.markveil-window infobar button {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    padding: 3px 9px;
}}
window.markveil-window infobar button label {{
    color: {t.text};
}}
window.markveil-window infobar button:hover {{
    background-color: {t.surface_alt};
    border-color: {t.accent};
}}

/* Popovers */
popover.markveil-popover,
popover.markveil-popover.background {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border_strong};
    box-shadow: none;
}}
popover.markveil-popover button,
popover.markveil-popover modelbutton,
window.markveil-window headerbar.main-headerbar popover.markveil-popover button,
window.markveil-window headerbar.main-headerbar popover.markveil-popover modelbutton {{
    background-image: none;
    background-color: transparent;
    color: {t.text};
    border: none;
    box-shadow: none;
    text-shadow: none;
}}
popover.markveil-popover button label,
popover.markveil-popover modelbutton label,
window.markveil-window headerbar.main-headerbar popover.markveil-popover button label,
window.markveil-window headerbar.main-headerbar popover.markveil-popover modelbutton label {{
    color: {t.text};
    text-shadow: none;
}}
popover.markveil-popover button:hover,
popover.markveil-popover modelbutton:hover,
window.markveil-window headerbar.main-headerbar popover.markveil-popover button:hover,
window.markveil-window headerbar.main-headerbar popover.markveil-popover modelbutton:hover {{
    background-image: none;
    background-color: {t.surface_alt};
    color: {t.heading};
}}
popover.markveil-popover button:disabled,
popover.markveil-popover modelbutton:disabled,
popover.markveil-popover modelbutton:disabled label {{
    color: {t.muted};
    opacity: 1.0;
}}

/* HeaderBar (Folio botanical green editorial chrome) */
window.markveil-window headerbar.main-headerbar {{
    background-image: none;
    background-color: #253f32;
    color: #f5f6e6;
    border: none;
    box-shadow: none;
    padding: 5px 12px;
    min-height: 42px;
}}
window.markveil-window headerbar.main-headerbar label {{
    color: #f5f6e6;
}}
window.markveil-window headerbar .wordmark,
window.markveil-window .welcome-title {{
    font-family: "Bitstream Charter", Georgia, serif;
    font-size: 23px;
    font-weight: bold;
}}
window.markveil-window .welcome-title {{
    font-size: 36px;
    font-weight: normal;
    color: {t.heading};
}}
window.markveil-window headerbar.main-headerbar .location {{
    color: #dce6d5;
    font-size: 0.92em;
}}
window.markveil-window headerbar.main-headerbar button {{
    background-image: none;
    background-color: transparent;
    color: #f5f6e6;
    border: none;
    box-shadow: none;
    text-shadow: none;
    border-radius: 4px;
    min-height: 24px;
    min-width: 18px;
    padding: 3px 6px;
}}
window.markveil-window headerbar.main-headerbar button label,
window.markveil-window headerbar.main-headerbar button image {{
    color: #f5f6e6;
}}
window.markveil-window headerbar.main-headerbar button:disabled,
window.markveil-window headerbar.main-headerbar button:disabled label,
window.markveil-window headerbar.main-headerbar button:disabled image {{
    color: #9aae9d;
    opacity: 1.0;
}}
window.markveil-window headerbar.main-headerbar button:hover,
window.markveil-window headerbar.main-headerbar button:checked {{
    background-image: none;
    background-color: #3a5544;
    color: #f5f6e6;
}}
window.markveil-window headerbar.main-headerbar button.suggested-action {{
    background-image: none;
    background-color: #dae5bd;
    color: #253f32;
    border: none;
}}
window.markveil-window headerbar.main-headerbar button.suggested-action label,
window.markveil-window headerbar.main-headerbar button.suggested-action image {{
    color: #253f32;
}}
window.markveil-window headerbar.main-headerbar .mode-switcher {{
    background-color: #395343;
    padding: 3px;
    border-radius: 6px;
}}
window.markveil-window headerbar.main-headerbar .mode-switcher button {{
    padding: 2px 10px;
}}
window.markveil-window headerbar.main-headerbar .mode-switcher button:checked {{
    background-image: none;
    background-color: #f5f6e6;
    color: #253f32;
}}
window.markveil-window headerbar.main-headerbar .mode-switcher button:checked label {{
    color: #253f32;
}}

/* Sidebar, StatusBar, Search/Tool Bars */
window.markveil-window .mdv-sidebar,
window.markveil-window .mdv-statusbar,
window.markveil-window .search-bar {{
    background-image: none;
    background-color: {t.surface};
    color: {t.text};
}}
window.markveil-window .mdv-sidebar list,
window.markveil-window .mdv-sidebar viewport,
window.markveil-window .context-metric-card,
window.markveil-window .preview-scrolled viewport {{
    background-image: none;
    background-color: transparent;
    color: {t.text};
}}
window.markveil-window .mdv-sidebar list {{
    padding: 0 10px;
}}
window.markveil-window .mdv-sidebar list row {{
    background-image: none;
    background-color: transparent;
    padding: 3px 8px;
    border-radius: 4px;
    color: {t.muted};
    min-height: 24px;
}}
window.markveil-window .mdv-sidebar list row label {{
    color: {t.text};
}}
window.markveil-window .mdv-sidebar list row .muted-label {{
    color: {t.muted};
}}
window.markveil-window .mdv-sidebar list row:hover {{
    background-image: none;
    background-color: {t.surface_alt};
}}
window.markveil-window .mdv-sidebar list row:selected,
window.markveil-window .mdv-sidebar list row.outline-row-active {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
}}
window.markveil-window .open-documents row:selected {{
    font-weight: bold;
}}
window.markveil-window .mdv-sidebar list row:selected label,
window.markveil-window .mdv-sidebar list row:selected image,
window.markveil-window .mdv-sidebar list row.outline-row-active label,
window.markveil-window .mdv-sidebar list row.outline-row-active image {{
    color: {t.selection_text};
}}

/* Sidebar & Bar Flat Buttons (with explicit enabled/hover/checked/disabled states) */
window.markveil-window .mdv-sidebar button,
window.markveil-window .mdv-statusbar button,
window.markveil-window .search-bar button,
window.markveil-window .document-close {{
    background-image: none;
    background-color: transparent;
    color: {t.text};
    border: 1px solid transparent;
    box-shadow: none;
    text-shadow: none;
    border-radius: 4px;
    min-height: 24px;
    min-width: 18px;
    padding: 3px 6px;
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button label,
window.markveil-window .mdv-sidebar button image,
window.markveil-window .mdv-statusbar button label,
window.markveil-window .mdv-statusbar button image,
window.markveil-window .search-bar button label,
window.markveil-window .search-bar button image {{
    color: {t.text};
    text-shadow: none;
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button:hover,
window.markveil-window .mdv-statusbar button:hover,
window.markveil-window .search-bar button:hover {{
    background-image: none;
    background-color: {t.surface_alt};
    color: {t.heading};
}}
window.markveil-window .mdv-sidebar button:checked,
window.markveil-window .sidebar-header stackswitcher button:checked,
window.markveil-window .search-bar button:checked {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
    border-color: {t.border_strong};
}}
window.markveil-window .mdv-sidebar button:checked label,
window.markveil-window .mdv-sidebar button:checked image,
window.markveil-window .sidebar-header stackswitcher button:checked label,
window.markveil-window .sidebar-header stackswitcher button:checked image,
window.markveil-window .search-bar button:checked label {{
    color: {t.selection_text};
}}
window.markveil-window .mdv-sidebar button:disabled,
window.markveil-window .mdv-statusbar button:disabled,
window.markveil-window .search-bar button:disabled {{
    background-image: none;
    background-color: transparent;
    color: {t.muted};
    border-color: transparent;
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button:disabled label,
window.markveil-window .mdv-sidebar button:disabled image,
window.markveil-window .mdv-statusbar button:disabled label,
window.markveil-window .mdv-statusbar button:disabled image,
window.markveil-window .search-bar button:disabled label,
window.markveil-window .search-bar button:disabled image {{
    color: {t.muted};
    opacity: 1.0;
}}

/* Refined editorial bordered pill buttons for sidebar actions (+ Add, Export…, Copy) */
window.markveil-window .mdv-sidebar button.sidebar-action-btn {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 0.88em;
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-action-btn label {{
    color: {t.text};
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-action-btn:hover {{
    background-image: none;
    background-color: {t.surface_alt};
    border-color: {t.accent};
    color: {t.heading};
}}
window.markveil-window .mdv-sidebar button.sidebar-action-btn:hover label {{
    color: {t.heading};
}}
window.markveil-window .mdv-sidebar button.sidebar-action-btn:disabled {{
    background-image: none;
    background-color: {t.surface};
    color: {t.muted};
    border: 1px solid {t.border};
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-action-btn:disabled label {{
    color: {t.muted};
    opacity: 1.0;
}}

window.markveil-window .mdv-sidebar button.sidebar-primary-btn {{
    background-image: none;
    background-color: {t.accent};
    color: {t.accent_contrast};
    border: 1px solid {t.accent};
    border-radius: 5px;
    padding: 3px 10px;
    font-size: 0.88em;
    font-weight: bold;
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-primary-btn label {{
    color: {t.accent_contrast};
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-primary-btn:hover {{
    background-image: none;
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
    color: {t.accent_contrast};
}}
window.markveil-window .mdv-sidebar button.sidebar-primary-btn:disabled {{
    background-image: none;
    background-color: {t.surface_alt};
    color: {t.muted};
    border: 1px solid {t.border};
    opacity: 1.0;
}}
window.markveil-window .mdv-sidebar button.sidebar-primary-btn:disabled label {{
    color: {t.muted};
    opacity: 1.0;
}}

/* Sidebar header StackSwitcher */
window.markveil-window .sidebar-header {{
    margin: 14px 12px 0;
    padding: 10px 0 0;
    border-top: 1px solid {t.border};
}}
window.markveil-window .sidebar-header stackswitcher {{
    background-image: none;
    background-color: transparent;
    box-shadow: none;
}}
window.markveil-window .sidebar-header stackswitcher button {{
    padding: 4px 9px;
    background-image: none;
    background-color: transparent;
    color: {t.text};
    border: 1px solid transparent;
    border-radius: 5px;
}}
window.markveil-window .sidebar-header stackswitcher button:hover {{
    background-color: {t.surface_alt};
}}
window.markveil-window .sidebar-header stackswitcher button:checked {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
    border-color: {t.border};
}}

window.markveil-window .mdv-sidebar .document-close,
window.markveil-window .mdv-sidebar .anchor-copy {{
    padding: 1px 3px;
    min-width: 16px;
    min-height: 19px;
    opacity: 0;
}}
window.markveil-window .mdv-sidebar row:hover button,
window.markveil-window .mdv-sidebar row:focus button,
window.markveil-window .mdv-sidebar button:focus {{
    opacity: 1;
}}

window.markveil-window .rail-title {{
    padding: 15px 18px 8px;
    font-size: 0.9em;
    font-weight: bold;
    color: {t.muted};
}}
window.markveil-window .workspace-location {{
    color: {t.muted};
    border-top: 1px solid {t.border};
    padding: 10px 16px;
    font-size: 0.9em;
}}

/* Agentic Environment Badges & Filter Pills (strictly Markveil palette) */
window.markveil-window .env-scope-group button {{
    background-image: none;
    background-color: {t.bg};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 0.84em;
    min-height: 22px;
}}
window.markveil-window .env-scope-group button label {{
    color: {t.text};
}}
window.markveil-window .env-scope-group button:checked {{
    background-image: none;
    background-color: {t.selection_bg};
    color: {t.selection_text};
    border-color: {t.accent};
    font-weight: bold;
}}
window.markveil-window .env-scope-group button:checked label {{
    color: {t.selection_text};
}}
window.markveil-window .env-badge {{
    background-color: {t.surface_alt};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 0px 5px;
    font-family: "IBM Plex Mono", "Ubuntu Mono", monospace;
    font-size: 0.76em;
}}
window.markveil-window .env-badge-accent {{
    background-color: {t.accent_soft};
    color: {t.accent};
    border: 1px solid {t.accent_border};
    border-radius: 3px;
    padding: 0px 5px;
    font-family: "IBM Plex Mono", "Ubuntu Mono", monospace;
    font-size: 0.76em;
}}
window.markveil-window .env-welcome-list {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 4px;
}}
window.markveil-window .env-welcome-list row {{
    background-image: none;
    background-color: transparent;
    border-radius: 4px;
    padding: 4px 6px;
}}
window.markveil-window .env-welcome-list row:hover {{
    background-color: {t.surface_alt};
}}

/* Cards, Search Bar, StatusBar, Notebook, Editor, Progress */
window.markveil-window .review-comment-card,
window.markveil-window .context-metric-card {{
    padding: 8px 6px;
    margin: 1px 10px;
    border-bottom: 1px solid {t.border};
}}
window.markveil-window .search-bar {{
    padding: 5px 10px;
    border-bottom: 1px solid {t.border};
}}
window.markveil-window .mdv-statusbar {{
    border-top: 1px solid {t.border};
    padding: 1px 12px;
    font-size: 0.85em;
    color: {t.muted};
}}
window.markveil-window .mdv-statusbar label {{
    color: {t.muted};
}}
window.markveil-window .mdv-statusbar button {{
    min-height: 19px;
    padding: 1px 5px;
}}
window.markveil-window .watch-badge.active {{
    color: {t.accent};
    font-weight: bold;
}}
window.markveil-window .readonly-badge {{
    color: {t.warning_fg};
    background-color: {t.warning_bg};
    padding: 0 5px;
    border-radius: 3px;
}}
window.markveil-window paned > separator {{
    min-width: 1px;
    background-color: {t.border};
}}
window.markveil-window notebook > header {{
    background-image: none;
    background-color: {t.surface};
    border: 0;
}}
window.markveil-window notebook > header tab {{
    background-image: none;
    background-color: transparent;
    color: {t.muted};
}}
window.markveil-window notebook > header tab label {{
    color: {t.muted};
}}
window.markveil-window notebook > header tab:checked {{
    color: {t.heading};
    box-shadow: inset 0 -2px {t.accent};
}}
window.markveil-window notebook > header tab:checked label {{
    color: {t.heading};
}}
window.markveil-window .preview-scrolled {{
    background-color: {t.bg};
}}
window.markveil-window textview.editor-source,
window.markveil-window textview.editor-source text {{
    font-family: "IBM Plex Mono", "Ubuntu Mono", monospace;
    font-size: {editor_pt}pt;
}}
window.markveil-window progressbar trough {{
    background-color: {t.surface_alt};
    min-height: 4px;
    border: 0;
}}
window.markveil-window progressbar progress {{
    background-color: {t.accent};
    min-height: 4px;
    border: 0;
}}
window.markveil-window button:focus,
window.markveil-window row:focus {{
    outline-style: solid;
    outline-width: 1px;
    outline-offset: -2px;
    outline-color: {t.accent};
}}
window.markveil-window headerbar.main-headerbar button:focus {{
    outline-color: #a5ba8f;
}}
"""
