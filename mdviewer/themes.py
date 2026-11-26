"""Curated editorial themes and document CSS generation for Markveil.

Design direction: "Editorial Ink & Technical Precision" — high-craft native Linux
reading and technical review typography, 72ch prose measure, 1px hairline borders,
WCAG AA (>= 4.5:1) contrast across all four themes, and reduced-motion support.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from urllib.parse import quote


@dataclass(frozen=True)
class ThemeSpec:
    """Complete semantic color and rendering token specification for a theme."""

    id: str
    name: str
    is_dark: bool
    pygments_style: str

    # Core surfaces & typography
    bg: str
    surface: str
    surface_alt: str
    text: str
    heading: str
    muted: str
    border: str
    border_subtle: str
    border_strong: str

    # Primary accent & selection
    accent: str
    accent_hover: str
    accent_soft: str
    accent_border: str
    accent_contrast: str
    selection_bg: str
    selection_text: str

    # Code, blockquote, kbd
    code_inline_bg: str
    code_bg: str
    code_header_bg: str
    blockquote_bg: str
    kbd_bg: str
    kbd_border: str
    mark_bg: str
    mark_text: str

    # Watch mode changed-block highlight
    watch_bg_peak: str
    watch_bg_rest: str

    # Admonition semantic ink colors (WCAG AA >= 4.5:1 on bg & alert bg)
    note_fg: str
    note_bg: str
    tip_fg: str
    tip_bg: str
    important_fg: str
    important_bg: str
    warning_fg: str
    warning_bg: str
    caution_fg: str
    caution_bg: str

    # Diff view semantic colors
    diff_add_bg: str
    diff_add_word_bg: str
    diff_add_fg: str
    diff_add_gutter: str
    diff_del_bg: str
    diff_del_word_bg: str
    diff_del_fg: str
    diff_del_gutter: str
    diff_hunk_bg: str
    diff_hunk_fg: str

    # Technical validation badges
    valid_fg: str
    valid_bg: str
    valid_border: str
    invalid_fg: str
    invalid_bg: str
    invalid_border: str

    # JSON tree syntax ink
    json_key: str
    json_string: str
    json_number: str
    json_bool: str
    json_null: str

    # Subtle elevation & scrollbars
    shadow_sm: str
    shadow_md: str
    scrollbar_thumb: str
    scrollbar_thumb_hover: str


THEME_ORDER: tuple[str, ...] = ("folio", "paper", "obsidian", "sepia", "nordic")

THEMES: dict[str, ThemeSpec] = {
    "paper": ThemeSpec(
        id="paper",
        name="Paper",
        is_dark=False,
        pygments_style="friendly",
        bg="#FCFCFA",
        surface="#F4F3EE",
        surface_alt="#ECEAE3",
        text="#18181B",
        heading="#09090B",
        muted="#52525B",
        border="#E4E3DD",
        border_subtle="#EEEDE8",
        border_strong="#C9C7BE",
        accent="#0F52BA",
        accent_hover="#0B3D8C",
        accent_soft="rgba(15, 82, 186, 0.08)",
        accent_border="rgba(15, 82, 186, 0.24)",
        accent_contrast="#FFFFFF",
        selection_bg="rgba(15, 82, 186, 0.16)",
        selection_text="#09090B",
        code_inline_bg="#F1F0EA",
        code_bg="#F4F3EE",
        code_header_bg="#ECEAE3",
        blockquote_bg="rgba(15, 82, 186, 0.04)",
        kbd_bg="#F4F3EE",
        kbd_border="#D4D2C8",
        mark_bg="#FEF3C7",
        mark_text="#18181B",
        watch_bg_peak="rgba(15, 82, 186, 0.14)",
        watch_bg_rest="rgba(15, 82, 186, 0.045)",
        note_fg="#0F52BA",
        note_bg="#F1F5FC",
        tip_fg="#166534",
        tip_bg="#F0F8F3",
        important_fg="#5B3782",
        important_bg="#F6F2FA",
        warning_fg="#8A4B08",
        warning_bg="#FCF6EC",
        caution_fg="#B42318",
        caution_bg="#FDF2F1",
        diff_add_bg="#EAF6EE",
        diff_add_word_bg="#C6EBD1",
        diff_add_fg="#14532D",
        diff_add_gutter="#DCF0E3",
        diff_del_bg="#FBECEB",
        diff_del_word_bg="#F5C9C6",
        diff_del_fg="#991B1B",
        diff_del_gutter="#F7DDDB",
        diff_hunk_bg="#EEF2F8",
        diff_hunk_fg="#0F52BA",
        valid_fg="#166534",
        valid_bg="#EAF6EE",
        valid_border="#B7DFC5",
        invalid_fg="#B42318",
        invalid_bg="#FBECEB",
        invalid_border="#F2C0BC",
        json_key="#0F52BA",
        json_string="#166534",
        json_number="#9A3412",
        json_bool="#5B3782",
        json_null="#52525B",
        shadow_sm="0 1px 2px rgba(24, 24, 27, 0.04)",
        shadow_md="0 6px 18px rgba(24, 24, 27, 0.08)",
        scrollbar_thumb="rgba(82, 82, 91, 0.25)",
        scrollbar_thumb_hover="rgba(82, 82, 91, 0.45)",
    ),
    "obsidian": ThemeSpec(
        id="obsidian",
        name="Obsidian",
        is_dark=True,
        pygments_style="github-dark",
        bg="#0E1116",
        surface="#151921",
        surface_alt="#1C222D",
        text="#E6EDF3",
        heading="#F3F7FB",
        muted="#8B949E",
        border="#262C36",
        border_subtle="#1D222B",
        border_strong="#3B4352",
        accent="#58A6FF",
        accent_hover="#79B8FF",
        accent_soft="rgba(88, 166, 255, 0.12)",
        accent_border="rgba(88, 166, 255, 0.32)",
        accent_contrast="#090C10",
        selection_bg="rgba(88, 166, 255, 0.26)",
        selection_text="#F3F7FB",
        code_inline_bg="#181D26",
        code_bg="#151921",
        code_header_bg="#1B202B",
        blockquote_bg="rgba(88, 166, 255, 0.07)",
        kbd_bg="#1C222D",
        kbd_border="#363E4D",
        mark_bg="#3B2E12",
        mark_text="#F3F7FB",
        watch_bg_peak="rgba(88, 166, 255, 0.20)",
        watch_bg_rest="rgba(88, 166, 255, 0.07)",
        note_fg="#58A6FF",
        note_bg="#121C2A",
        tip_fg="#4CC36A",
        tip_bg="#112118",
        important_fg="#C297FF",
        important_bg="#1D1629",
        warning_fg="#E3AE3D",
        warning_bg="#241D11",
        caution_fg="#FF7B72",
        caution_bg="#271517",
        diff_add_bg="#12241B",
        diff_add_word_bg="#1F4A33",
        diff_add_fg="#6EE787",
        diff_add_gutter="#163022",
        diff_del_bg="#2B1619",
        diff_del_word_bg="#57262B",
        diff_del_fg="#FFA198",
        diff_del_gutter="#381B1F",
        diff_hunk_bg="#141E2E",
        diff_hunk_fg="#79B8FF",
        valid_fg="#56D364",
        valid_bg="#12241B",
        valid_border="#234D35",
        invalid_fg="#FF7B72",
        invalid_bg="#2B1619",
        invalid_border="#5C282D",
        json_key="#79B8FF",
        json_string="#7EE787",
        json_number="#F0B36B",
        json_bool="#C297FF",
        json_null="#8B949E",
        shadow_sm="0 1px 2px rgba(0, 0, 0, 0.35)",
        shadow_md="0 8px 24px rgba(0, 0, 0, 0.48)",
        scrollbar_thumb="rgba(139, 148, 158, 0.28)",
        scrollbar_thumb_hover="rgba(139, 148, 158, 0.48)",
    ),
    "sepia": ThemeSpec(
        id="sepia",
        name="Sepia",
        is_dark=False,
        pygments_style="friendly",
        bg="#F8F3E6",
        surface="#EFE8D6",
        surface_alt="#E7DEC8",
        text="#2C241B",
        heading="#1E1710",
        muted="#6E5F4F",
        border="#DED5C0",
        border_subtle="#E8E0CD",
        border_strong="#C3B69C",
        accent="#A14A0B",
        accent_hover="#7E3807",
        accent_soft="rgba(161, 74, 11, 0.09)",
        accent_border="rgba(161, 74, 11, 0.26)",
        accent_contrast="#FDFBF6",
        selection_bg="rgba(161, 74, 11, 0.18)",
        selection_text="#1E1710",
        code_inline_bg="#EDE5D2",
        code_bg="#EFE8D6",
        code_header_bg="#E7DEC8",
        blockquote_bg="rgba(161, 74, 11, 0.05)",
        kbd_bg="#EFE8D6",
        kbd_border="#CEC2A9",
        mark_bg="#F3DE9D",
        mark_text="#2C241B",
        watch_bg_peak="rgba(161, 74, 11, 0.16)",
        watch_bg_rest="rgba(161, 74, 11, 0.055)",
        note_fg="#1F568B",
        note_bg="#ECEEEB",
        tip_fg="#255E36",
        tip_bg="#EBEFE2",
        important_fg="#693870",
        important_bg="#F2EAEB",
        warning_fg="#8C490A",
        warning_bg="#F5E9D3",
        caution_fg="#9E2A22",
        caution_bg="#F6E5DE",
        diff_add_bg="#E6EEDB",
        diff_add_word_bg="#C9DCBA",
        diff_add_fg="#1F512E",
        diff_add_gutter="#DCE7CE",
        diff_del_bg="#F4E2DB",
        diff_del_word_bg="#E8C0B4",
        diff_del_fg="#8E231B",
        diff_del_gutter="#EED6CD",
        diff_hunk_bg="#EAE5D8",
        diff_hunk_fg="#8A4209",
        valid_fg="#255E36",
        valid_bg="#E6EEDB",
        valid_border="#B9CEAC",
        invalid_fg="#9E2A22",
        invalid_bg="#F4E2DB",
        invalid_border="#DEB5A9",
        json_key="#8C410A",
        json_string="#255E36",
        json_number="#1F568B",
        json_bool="#693870",
        json_null="#6E5F4F",
        shadow_sm="0 1px 2px rgba(44, 36, 27, 0.05)",
        shadow_md="0 6px 18px rgba(44, 36, 27, 0.10)",
        scrollbar_thumb="rgba(110, 95, 79, 0.28)",
        scrollbar_thumb_hover="rgba(110, 95, 79, 0.48)",
    ),
    "nordic": ThemeSpec(
        id="nordic",
        name="Nordic",
        is_dark=True,
        pygments_style="github-dark",
        bg="#1A1F29",
        surface="#222936",
        surface_alt="#293142",
        text="#DCE3EC",
        heading="#EDF2F8",
        muted="#8E9BB0",
        border="#2F384A",
        border_subtle="#262E3D",
        border_strong="#445069",
        accent="#7AA2F7",
        accent_hover="#99B8FA",
        accent_soft="rgba(122, 162, 247, 0.13)",
        accent_border="rgba(122, 162, 247, 0.34)",
        accent_contrast="#11151C",
        selection_bg="rgba(122, 162, 247, 0.26)",
        selection_text="#EDF2F8",
        code_inline_bg="#252D3C",
        code_bg="#222936",
        code_header_bg="#283141",
        blockquote_bg="rgba(122, 162, 247, 0.08)",
        kbd_bg="#283141",
        kbd_border="#414D65",
        mark_bg="#423A24",
        mark_text="#EDF2F8",
        watch_bg_peak="rgba(122, 162, 247, 0.22)",
        watch_bg_rest="rgba(122, 162, 247, 0.08)",
        note_fg="#7AA2F7",
        note_bg="#1F293B",
        tip_fg="#7EC997",
        tip_bg="#1E2E2B",
        important_fg="#C0A8F5",
        important_bg="#28243A",
        warning_fg="#E5BE73",
        warning_bg="#2F2B22",
        caution_fg="#F28B8B",
        caution_bg="#322229",
        diff_add_bg="#1E2F2C",
        diff_add_word_bg="#2C4D44",
        diff_add_fg="#8CD6A4",
        diff_add_gutter="#223834",
        diff_del_bg="#332229",
        diff_del_word_bg="#57313C",
        diff_del_fg="#F7A0A0",
        diff_del_gutter="#402832",
        diff_hunk_bg="#212B3E",
        diff_hunk_fg="#99B8FA",
        valid_fg="#7EC997",
        valid_bg="#1E2F2C",
        valid_border="#34564C",
        invalid_fg="#F28B8B",
        invalid_bg="#332229",
        invalid_border="#603843",
        json_key="#8EB2FA",
        json_string="#8CD6A4",
        json_number="#E5BE73",
        json_bool="#C0A8F5",
        json_null="#8E9BB0",
        shadow_sm="0 1px 2px rgba(8, 10, 15, 0.35)",
        shadow_md="0 8px 24px rgba(8, 10, 15, 0.45)",
        scrollbar_thumb="rgba(142, 155, 176, 0.28)",
        scrollbar_thumb_hover="rgba(142, 155, 176, 0.48)",
    ),
}

# Keep the existing light palette's semantic warning and diff colors.
THEMES["folio"] = replace(
    THEMES["paper"], id="folio", name="Folio",
    bg="#FAFAF2", surface="#EDF0E3", surface_alt="#E2E9CE",
    text="#304736", heading="#23392D", muted="#526454",
    border="#CDD3C1", border_subtle="#E1E5D7", border_strong="#91A185",
    accent="#395B40", accent_hover="#203F2B", accent_soft="#DFE8D6",
    accent_border="#869A78", selection_bg="#D6DEC8", selection_text="#23392D",
    code_inline_bg="#E9EDDF", code_bg="#EFF2E8", code_header_bg="#E6EBDB",
    blockquote_bg="#EFF2E7", kbd_bg="#EDF0E3", kbd_border="#CCD3C1",
    watch_bg_peak="#DCE7C8", watch_bg_rest="#F0F3E6",
    note_fg="#355142", note_bg="#EAF0E3",
    diff_hunk_bg="#E2E9D8", diff_hunk_fg="#35563F", json_key="#395B40",
)

_FONT_SANS = (
    '"IBM Plex Sans", "Inter", "Ubuntu", "Cantarell", -apple-system, '
    'BlinkMacSystemFont, "Segoe UI", "Noto Sans", sans-serif'
)
_FONT_MONO = (
    '"JetBrains Mono", "IBM Plex Mono", "Fira Code", "Ubuntu Mono", '
    '"Cascadia Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
)


def resolve_theme_id(theme_id: str | None, system_dark: bool = False) -> str:
    """Resolve user/config theme identifier to one of a curated theme ID."""
    key = (theme_id or "auto").strip().lower()
    if key in ("auto", "system", ""):
        return "obsidian" if system_dark else "folio"
    if key == "dark":
        return "obsidian"
    if key == "light":
        return "paper"
    if key in THEMES:
        return key
    return "obsidian" if system_dark else "folio"


def is_dark_theme(theme_id: str) -> bool:
    """Return True if the resolved theme uses a dark palette."""
    return THEMES[resolve_theme_id(theme_id)].is_dark


def get_pygments_style(theme_id: str) -> str:
    """Return the Pygments style name paired with the resolved theme."""
    return THEMES[resolve_theme_id(theme_id)].pygments_style


def get_bg_hex(theme_id: str) -> str:
    """Return the primary page background hex color for the resolved theme."""
    return THEMES[resolve_theme_id(theme_id)].bg


def get_mermaid_theme_vars(theme_id: str) -> dict[str, object]:
    """Return Mermaid themeVariables matched tightly to the resolved theme."""
    t = THEMES[resolve_theme_id(theme_id)]
    return {
        "darkMode": t.is_dark,
        "fontFamily": _FONT_SANS,
        "fontSize": "14px",
        "background": t.bg,
        "mainBkg": t.surface,
        "primaryColor": t.surface,
        "primaryTextColor": t.text,
        "primaryBorderColor": t.border_strong,
        "secondaryColor": t.surface_alt,
        "secondaryTextColor": t.text,
        "secondaryBorderColor": t.border,
        "tertiaryColor": t.bg,
        "tertiaryTextColor": t.text,
        "tertiaryBorderColor": t.border,
        "lineColor": t.muted,
        "textColor": t.text,
        "nodeBkg": t.surface,
        "nodeBorder": t.border_strong,
        "nodeTextColor": t.text,
        "clusterBkg": t.bg,
        "clusterBorder": t.border_strong,
        "titleColor": t.heading,
        "edgeLabelBackground": t.bg,
        "actorBkg": t.surface,
        "actorBorder": t.border_strong,
        "actorTextColor": t.text,
        "actorLineColor": t.border_strong,
        "signalColor": t.muted,
        "signalTextColor": t.text,
        "labelBoxBkgColor": t.surface,
        "labelBoxBorderColor": t.border,
        "labelTextColor": t.text,
        "noteBkgColor": t.surface_alt,
        "noteBorderColor": t.accent,
        "noteTextColor": t.text,
        "activationBkgColor": t.surface_alt,
        "activationBorderColor": t.accent,
        "sectionBkgColor": t.surface,
        "altSectionBkgColor": t.bg,
        "gridColor": t.border,
    }


def _svg_icon_uri(svg_inner: str, stroke_hex: str) -> str:
    """Encode a crisp inline SVG data URI for admonition headings."""
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        f"stroke='{stroke_hex}' stroke-width='2' stroke-linecap='round' "
        f"stroke-linejoin='round'>{svg_inner}</svg>"
    )
    return f"data:image/svg+xml,{quote(svg, safe='')}"


def get_document_css(theme_id: str, custom_css: str = "") -> str:
    """Generate the complete editorial document stylesheet for the given theme."""
    t = THEMES[resolve_theme_id(theme_id)]
    scheme = "dark" if t.is_dark else "light"

    note_icon = _svg_icon_uri(
        "<circle cx='12' cy='12' r='10'/><path d='M12 16v-4'/><path d='M12 8h.01'/>",
        t.note_fg,
    )
    tip_icon = _svg_icon_uri(
        "<path d='M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5'/>"
        "<path d='M9 18h6'/><path d='M10 22h4'/>",
        t.tip_fg,
    )
    warning_icon = _svg_icon_uri(
        "<path d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z'/>"
        "<path d='M12 9v4'/><path d='M12 17h.01'/>",
        t.warning_fg,
    )
    caution_icon = _svg_icon_uri(
        "<polygon points='7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2'/>"
        "<path d='m15 9-6 6'/><path d='m9 9 6 6'/>",
        t.caution_fg,
    )
    important_icon = _svg_icon_uri(
        "<circle cx='12' cy='12' r='10'/><path d='M12 8v4'/><path d='M12 16h.01'/>",
        t.important_fg,
    )

    css = f"""\
:root {{
    color-scheme: {scheme};
    --bg-color: {t.bg};
    --surface-bg: {t.surface};
    --surface-alt: {t.surface_alt};
    --text-color: {t.text};
    --heading-color: {t.heading};
    --muted-color: {t.muted};
    --border-color: {t.border};
    --border-subtle: {t.border_subtle};
    --border-strong: {t.border_strong};
    --accent-color: {t.accent};
    --accent-hover: {t.accent_hover};
    --accent-soft: {t.accent_soft};
    --accent-border: {t.accent_border};
    --accent-contrast: {t.accent_contrast};
    --selection-bg: {t.selection_bg};
    --selection-text: {t.selection_text};
    --inline-code-bg: {t.code_inline_bg};
    --pre-bg: {t.code_bg};
    --code-header-bg: {t.code_header_bg};
    --blockquote-bg: {t.blockquote_bg};
    --kbd-bg: {t.kbd_bg};
    --kbd-border: {t.kbd_border};
    --mark-bg: {t.mark_bg};
    --mark-text: {t.mark_text};
    --watch-bg-peak: {t.watch_bg_peak};
    --watch-bg-rest: {t.watch_bg_rest};
    --note-fg: {t.note_fg};
    --note-bg: {t.note_bg};
    --tip-fg: {t.tip_fg};
    --tip-bg: {t.tip_bg};
    --important-fg: {t.important_fg};
    --important-bg: {t.important_bg};
    --warning-fg: {t.warning_fg};
    --warning-bg: {t.warning_bg};
    --caution-fg: {t.caution_fg};
    --caution-bg: {t.caution_bg};
    --diff-add-bg: {t.diff_add_bg};
    --diff-add-word-bg: {t.diff_add_word_bg};
    --diff-add-fg: {t.diff_add_fg};
    --diff-add-gutter: {t.diff_add_gutter};
    --diff-del-bg: {t.diff_del_bg};
    --diff-del-word-bg: {t.diff_del_word_bg};
    --diff-del-fg: {t.diff_del_fg};
    --diff-del-gutter: {t.diff_del_gutter};
    --diff-hunk-bg: {t.diff_hunk_bg};
    --diff-hunk-fg: {t.diff_hunk_fg};
    --valid-fg: {t.valid_fg};
    --valid-bg: {t.valid_bg};
    --valid-border: {t.valid_border};
    --invalid-fg: {t.invalid_fg};
    --invalid-bg: {t.invalid_bg};
    --invalid-border: {t.invalid_border};
    --json-key: {t.json_key};
    --json-string: {t.json_string};
    --json-number: {t.json_number};
    --json-bool: {t.json_bool};
    --json-null: {t.json_null};
    --shadow-sm: {t.shadow_sm};
    --shadow-md: {t.shadow_md};
    --scrollbar-thumb: {t.scrollbar_thumb};
    --scrollbar-thumb-hover: {t.scrollbar_thumb_hover};
    --font-serif: "Bitstream Charter", Charter, Georgia, "Noto Serif", serif;
    --font-sans: {_FONT_SANS};
    --font-mono: {_FONT_MONO};
}}

*, *::before, *::after {{
    box-sizing: border-box;
}}

html {{
    background-color: var(--bg-color);
    scroll-behavior: smooth;
}}

body {{
    font-family: var(--font-sans);
    font-size: 16px;
    line-height: 1.72;
    color: var(--text-color);
    background-color: var(--bg-color);
    margin: 0;
    padding: 0;
    overflow-wrap: break-word;
    word-wrap: break-word;
    font-feature-settings: "kern" 1, "liga" 1;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}}

::selection {{
    background-color: var(--selection-bg);
    color: var(--selection-text);
}}

/* Editorial prose container — 72ch measure with generous breathing room */
.markdown-container {{
    max-width: 54rem;
    margin: 0 auto;
    padding: clamp(1.5rem, 4vw, 3.5rem) clamp(1.25rem, 5vw, 4rem) 5.5rem;
}}

.markdown-container:has(.diff-container),
.markdown-container:has(.diff-view) {{
    max-width: min(76rem, 100%);
}}

.markdown-container:has(.diff-split) {{
    max-width: min(96rem, 100%);
}}

.markdown-container > :first-child {{
    margin-top: 0;
}}

/* Headings & hover anchor copy control */
h1, h2, h3, h4, h5, h6 {{
    position: relative;
    color: var(--heading-color);
    font-weight: 650;
    line-height: 1.3;
    margin-top: 2rem;
    margin-bottom: 0.75rem;
    letter-spacing: -0.02em;
    scroll-margin-top: 1.5rem;
}}

h1, h2 {{
    font-family: var(--font-serif);
    font-weight: normal;
    line-height: 1.12;
    letter-spacing: -0.04em;
}}

h1 {{
    font-size: clamp(2.25rem, 5.2vw, 4rem);
    margin: 0.25rem 0 1rem;
}}

h2 {{
    font-size: clamp(1.55rem, 3.2vw, 2.05rem);
    margin-top: 2rem;
}}

.markdown-container > h1:first-of-type + p {{
    font: 1.24rem/1.5 var(--font-serif);
    color: var(--muted-color);
    padding-bottom: 1.25rem;
    border-bottom: 1px solid var(--border-color);
}}

h3 {{
    font-size: 1.2rem;
    margin-top: 1.75rem;
}}

h4 {{
    font-size: 1.04rem;
    margin-top: 1.45rem;
}}

h5 {{
    font-size: 0.94rem;
    margin-top: 1.25rem;
}}

h6 {{
    font-size: 0.84rem;
    color: var(--muted-color);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 1.25rem;
}}

.heading-anchor {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-left: 0.42rem;
    padding: 0 0.28rem;
    border: 1px solid transparent;
    border-radius: 4px;
    background: transparent;
    color: var(--muted-color);
    font-family: var(--font-mono);
    font-size: 0.76em;
    font-weight: 500;
    line-height: 1.3;
    vertical-align: middle;
    cursor: pointer;
    opacity: 0;
    user-select: none;
    transition: opacity 0.14s ease, color 0.14s ease, border-color 0.14s ease, background-color 0.14s ease;
}}

h1:hover .heading-anchor,
h2:hover .heading-anchor,
h3:hover .heading-anchor,
h4:hover .heading-anchor,
h5:hover .heading-anchor,
h6:hover .heading-anchor,
.heading-anchor:focus-visible,
.heading-anchor.copied {{
    opacity: 1;
}}

.heading-anchor:hover {{
    color: var(--accent-color);
    background-color: var(--accent-soft);
    border-color: var(--accent-border);
}}

.heading-anchor:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 2px;
}}

.heading-anchor.copied {{
    color: var(--valid-fg);
    background-color: var(--valid-bg);
    border-color: var(--valid-border);
}}

/* Prose */
p {{
    margin-top: 0;
    margin-bottom: 1.1rem;
}}

strong, b {{
    color: var(--heading-color);
    font-weight: 640;
}}

del, s {{
    color: var(--muted-color);
    text-decoration: line-through;
    text-decoration-thickness: 1.25px;
}}

mark {{
    background-color: var(--mark-bg);
    color: var(--mark-text);
    padding: 0.08em 0.3em;
    border-radius: 3px;
}}

abbr[title] {{
    text-decoration: underline dotted var(--border-strong);
    text-underline-offset: 3px;
    cursor: help;
}}

/* Links */
a {{
    color: var(--accent-color);
    text-decoration: underline;
    text-decoration-color: var(--accent-border);
    text-decoration-thickness: 1px;
    text-underline-offset: 3px;
    transition: color 0.14s ease, text-decoration-color 0.14s ease;
}}

a:hover {{
    color: var(--accent-hover);
    text-decoration-color: var(--accent-hover);
}}

a:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 2px;
    border-radius: 2px;
}}

/* Inline & Fenced Code */
code {{
    font-family: var(--font-mono);
    font-size: 0.87em;
    background-color: var(--inline-code-bg);
    color: var(--text-color);
    border: none;
    padding: 0.14em 0.4em;
    border-radius: 4px;
}}

.markdown-container pre {{
    margin: 1.35rem 0;
    padding: 1rem 1.2rem;
    border-radius: 3px;
    border: none;
    background-color: var(--pre-bg);
    color: var(--text-color);
    font-family: var(--font-mono);
    font-size: 0.875rem;
    line-height: 1.56;
    overflow-x: auto;
    tab-size: 4;
}}

.markdown-container pre code {{
    background: transparent;
    border: none;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
    color: inherit;
}}

/* Pygments highlight wrapper — beats Pygments default background */
.markdown-container .highlight {{
    margin: 1.4rem 0;
    border-radius: 3px;
    border: none;
    background-color: var(--pre-bg);
    color: var(--text-color);
    overflow: hidden;
}}

.markdown-container .highlight pre {{
    margin: 0;
    border: none;
    border-radius: 0;
    background-color: transparent;
    padding: 0.95rem 1.2rem;
    line-height: 1.56;
}}

.code-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.42rem 0.9rem;
    background-color: var(--code-header-bg);
    border-bottom: 1px solid var(--border-color);
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--muted-color);
    user-select: none;
}}

.code-lang {{
    text-transform: uppercase;
}}

.code-copy-btn {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.18rem 0.52rem;
    border: none;
    border-radius: 4px;
    background-color: var(--bg-color);
    color: var(--muted-color);
    font-family: var(--font-sans);
    font-size: 0.73rem;
    font-weight: 500;
    cursor: pointer;
    transition: color 0.14s ease, border-color 0.14s ease, background-color 0.14s ease;
}}

.code-copy-btn:hover {{
    color: var(--text-color);
    border-color: var(--border-strong);
}}

.code-copy-btn:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 1px;
}}

.code-copy-btn.copied {{
    color: var(--valid-fg);
    background-color: var(--valid-bg);
    border-color: var(--valid-border);
}}

/* Tables */
.table-wrapper {{
    width: 100%;
    overflow-x: auto;
    margin: 1.45rem 0;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--bg-color);
}}

table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0;
    text-align: left;
    font-size: 0.92rem;
    font-variant-numeric: tabular-nums;
}}

th, td {{
    padding: 0.65rem 0.95rem;
    border-bottom: 1px solid var(--border-color);
    vertical-align: top;
}}

th {{
    background-color: var(--surface-bg);
    color: var(--heading-color);
    font-weight: 620;
    letter-spacing: -0.01em;
    border-bottom: 1px solid var(--border-strong);
}}

tr:last-child td {{
    border-bottom: none;
}}

tbody tr:hover {{
    background-color: var(--surface-bg);
}}

/* Blockquotes */
blockquote {{
    margin: 1.35rem 0;
    padding: 0.7rem 1.15rem;
    border-left: 3px solid var(--accent-color);
    background-color: var(--blockquote-bg);
    border-radius: 0 5px 5px 0;
    color: var(--text-color);
}}

blockquote > :last-child {{
    margin-bottom: 0;
}}

blockquote blockquote {{
    margin: 0.75rem 0 0 0;
    border-left-color: var(--border-strong);
    background-color: transparent;
}}

/* Horizontal rule */
hr {{
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 2.25rem 0;
}}

/* Lists & Definition lists */
ul, ol {{
    padding-left: 1.75rem;
    margin: 0 0 1.15rem 0;
}}

li {{
    margin: 0.32rem 0;
}}

li > p {{
    margin-bottom: 0.4rem;
}}

li > ul, li > ol {{
    margin-top: 0.25rem;
    margin-bottom: 0.35rem;
}}

dl {{
    margin: 1.25rem 0;
}}

dt {{
    font-weight: 640;
    color: var(--heading-color);
    margin-top: 0.85rem;
}}

dd {{
    margin: 0.25rem 0 0.5rem 1.4rem;
    color: var(--text-color);
}}

/* Interactive Task Lists */
.task-list-item {{
    list-style-type: none;
    margin-left: -1.45rem;
}}

.task-list-item input[type="checkbox"],
.task-checkbox {{
    appearance: none;
    -webkit-appearance: none;
    width: 1.08em;
    height: 1.08em;
    border: 1.5px solid var(--border-strong);
    border-radius: 3.5px;
    margin: 0 0.55em 0 0;
    vertical-align: -0.18em;
    position: relative;
    cursor: pointer;
    background-color: var(--bg-color);
    transition: background-color 0.12s ease, border-color 0.12s ease;
}}

.task-checkbox:hover:not(:disabled) {{
    border-color: var(--accent-color);
}}

.task-checkbox:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 2px;
}}

.task-checkbox:disabled {{
    cursor: default;
    opacity: 0.75;
}}

.task-list-item input[type="checkbox"]:checked,
.task-checkbox:checked {{
    background-color: var(--accent-color);
    border-color: var(--accent-color);
}}

.task-list-item input[type="checkbox"]:checked::after,
.task-checkbox:checked::after {{
    content: "";
    position: absolute;
    top: 1.5px;
    left: 4.5px;
    width: 3.5px;
    height: 7.5px;
    border: solid var(--accent-contrast);
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
}}

/* Keyboard keys */
kbd {{
    display: inline-block;
    padding: 0.1em 0.45em;
    font-family: var(--font-mono);
    font-size: 0.8em;
    font-weight: 500;
    line-height: 1.4;
    color: var(--text-color);
    background-color: var(--kbd-bg);
    border: 1px solid var(--kbd-border);
    border-bottom-width: 2px;
    border-radius: 4px;
    vertical-align: baseline;
}}

/* Images & Blocked Remote Images */
img {{
    max-width: 100%;
    height: auto;
    border-radius: 5px;
    border: 1px solid var(--border-subtle);
}}

figure {{
    margin: 1.5rem 0;
}}

figcaption {{
    margin-top: 0.5rem;
    font-size: 0.85rem;
    color: var(--muted-color);
}}

img.blocked-remote-img,
.blocked-remote-img {{
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 16rem;
    min-height: 2.6rem;
    padding: 0.55rem 0.9rem;
    margin: 0.4rem 0;
    border: 1px dashed var(--border-strong);
    border-radius: 6px;
    background-color: var(--surface-bg);
    color: var(--muted-color);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    line-height: 1.4;
    vertical-align: middle;
}}

/* Footnotes */
.footnote {{
    margin-top: 2.5rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
    font-size: 0.88rem;
    color: var(--muted-color);
}}

/* Front-matter metadata card */
details.front-matter-card {{
    border: none;
    border-radius: 3px;
    background-color: var(--bg-color);
    margin: 0 0 1.25rem;
    overflow: hidden;
}}

summary.front-matter-summary {{
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.65rem;
    user-select: none;
    font-size: 0.85rem;
    color: var(--muted-color);
}}

.front-matter-summary::after {{
    content: "▸";
    font-size: 0.8em;
}}

details[open] > .front-matter-summary::after {{ content: "▾"; }}

.front-matter-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
}}

.front-matter-doc-title {{
    font-size: 0.94rem;
    color: var(--heading-color);
    font-weight: 600;
}}

.front-matter-content {{
    padding: 0.75rem 1rem;
}}

.front-matter-tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.65rem;
}}

.front-matter-tag {{
    font-family: var(--font-mono);
    font-size: 0.76rem;
    padding: 0.14rem 0.52rem;
    background-color: var(--surface-bg);
    color: var(--text-color);
    border: 1px solid var(--border-color);
    border-radius: 4px;
}}

.front-matter-table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 0.86rem;
}}

.front-matter-table th,
.front-matter-table td {{
    padding: 0.36rem 0.6rem;
    border-bottom: 1px solid var(--border-subtle);
}}

.front-matter-table th {{
    background: transparent;
    border-bottom: 1px solid var(--border-subtle);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: var(--muted-color);
    width: 24%;
    font-weight: 500;
}}

.front-matter-table td {{
    color: var(--text-color);
}}

.front-matter-table tr:last-child th,
.front-matter-table tr:last-child td {{
    border-bottom: none;
}}

/* GitHub Alert Admonitions */
.admonition {{
    padding: 0.85rem 1.15rem;
    border: 1px solid var(--border-color);
    border-left-width: 3px;
    margin: 1.35rem 0;
    border-radius: 0 6px 6px 0;
    font-size: 0.95rem;
    color: var(--text-color);
}}

.admonition > :last-child {{
    margin-bottom: 0;
}}

.admonition-title {{
    font-weight: 650;
    margin: 0 0 0.4rem 0;
    font-size: 0.92rem;
    letter-spacing: 0.01em;
    display: flex;
    align-items: center;
    gap: 0.45rem;
}}

.admonition-title::before {{
    content: "";
    display: inline-block;
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    background-repeat: no-repeat;
    background-size: contain;
}}

.admonition.note {{
    border-left-color: var(--note-fg);
    background-color: var(--note-bg);
}}
.admonition.note .admonition-title {{ color: var(--note-fg); }}
.admonition.note .admonition-title::before {{
    background-image: url("{note_icon}");
}}

.admonition.tip {{
    border-left-color: var(--tip-fg);
    background-color: var(--tip-bg);
}}
.admonition.tip .admonition-title {{ color: var(--tip-fg); }}
.admonition.tip .admonition-title::before {{
    background-image: url("{tip_icon}");
}}

.admonition.warning {{
    border-left-color: var(--warning-fg);
    background-color: var(--warning-bg);
}}
.admonition.warning .admonition-title {{ color: var(--warning-fg); }}
.admonition.warning .admonition-title::before {{
    background-image: url("{warning_icon}");
}}

.admonition.caution,
.admonition.danger {{
    border-left-color: var(--caution-fg);
    background-color: var(--caution-bg);
}}
.admonition.caution .admonition-title,
.admonition.danger .admonition-title {{ color: var(--caution-fg); }}
.admonition.caution .admonition-title::before,
.admonition.danger .admonition-title::before {{
    background-image: url("{caution_icon}");
}}

.admonition.important {{
    border-left-color: var(--important-fg);
    background-color: var(--important-bg);
}}
.admonition.important .admonition-title {{ color: var(--important-fg); }}
.admonition.important .admonition-title::before {{
    background-image: url("{important_icon}");
}}

/* Mermaid Diagrams & Hover Zoom Toolbar */
.mermaid-container {{
    position: relative;
    margin: 1.5rem 0;
    border-radius: 3px;
    border: none;
    background-color: var(--surface-alt);
    overflow: hidden;
}}

.mermaid-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.42rem 0.9rem;
    font-family: var(--font-sans);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;

    color: var(--muted-color);
    border-bottom: 0;
    background-color: transparent;
}}

.mermaid-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--text-color);
}}

.mermaid-type {{
    font-size: 0.71rem;
    color: var(--muted-color);
}}

.mermaid-toolbar {{
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    margin-left: auto;
    opacity: 0.85;
    transition: opacity 0.15s ease;
}}

.mermaid-container:hover .mermaid-toolbar,
.mermaid-container:focus-within .mermaid-toolbar {{
    opacity: 1;
}}

.mermaid-toolbar-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.7rem;
    height: 1.55rem;
    padding: 0 0.45rem;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background-color: var(--bg-color);
    color: var(--muted-color);
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 500;
    text-transform: none;
    letter-spacing: 0;
    cursor: pointer;
    transition: color 0.12s ease, border-color 0.12s ease, background-color 0.12s ease;
}}

.mermaid-toolbar-btn:hover {{
    color: var(--text-color);
    border-color: var(--border-strong);
}}

.mermaid-toolbar-btn:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 1px;
}}

.mermaid-toolbar-btn.copied {{
    color: var(--valid-fg);
    background-color: var(--valid-bg);
    border-color: var(--valid-border);
}}

.mermaid-viewport {{
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding: 1.5rem 1.25rem;
    overflow: auto;
    min-height: 80px;
}}

.mermaid-viewport .mermaid {{
    display: flex;
    justify-content: center;
    width: 100%;
}}

.mermaid-viewport svg {{
    max-width: 100%;
    height: auto !important;
    transition: width 0.14s ease;
}}

.mermaid-error {{
    width: 100%;
    padding: 0.9rem 1.1rem;
    color: var(--invalid-fg);
    font-size: 0.86rem;
    text-align: left;
}}

.mermaid-error-header {{
    font-weight: 650;
    margin-bottom: 0.4rem;
}}

.mermaid-error-msg {{
    margin-bottom: 0.65rem;
    font-family: var(--font-mono);
    font-size: 0.8rem;
    background-color: var(--invalid-bg);
    color: var(--invalid-fg);
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    border: 1px solid var(--invalid-border);
}}

.mermaid-error-details summary {{
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--muted-color);
    margin-bottom: 0.4rem;
}}

.mermaid-error-code {{
    font-family: var(--font-mono);
    font-size: 0.8rem;
    background-color: var(--pre-bg);
    color: var(--text-color);
    border: 1px solid var(--border-color);
    padding: 0.65rem 0.8rem;
    border-radius: 4px;
    margin: 0;
    overflow-x: auto;
}}

/* KaTeX Math Equations */
.katex-block {{
    margin: 1.45rem 0;
    padding: 1.1rem 1.35rem;
    border-radius: 6px;
    background-color: var(--surface-bg);
    border: 1px solid var(--border-color);
    overflow-x: auto;
    overflow-y: hidden;
    display: flex;
    justify-content: center;
    align-items: center;
}}

.katex-display-math,
.katex-display {{
    margin: 0 !important;
    text-align: center;
}}

.katex-inline-math {{
    display: inline;
    padding: 0 0.12em;
}}

/* Watch Mode Changed-Block Highlights */
@keyframes mdvWatchFade {{
    0% {{
        background-color: var(--watch-bg-peak);
    }}
    100% {{
        background-color: var(--watch-bg-rest);
    }}
}}

[data-changed="true"] {{
    position: relative;
    border-left: 3px solid var(--accent-color);
    padding: 0.22rem 0.65rem 0.22rem 0.85rem;
    margin-left: -0.95rem;
    border-radius: 0 4px 4px 0;
    background-color: var(--watch-bg-rest);
    animation: mdvWatchFade 2.4s ease-out forwards;
}}

.mermaid-container[data-changed="true"],
.katex-block[data-changed="true"],
details.front-matter-card[data-changed="true"],
.plain-text-line[data-changed="true"] {{
    margin-left: 0;
}}

.mermaid-container[data-changed="true"],
details.front-matter-card[data-changed="true"] {{
    padding: 0;
}}

/* Diff View (diff_engine.py unified & split tables) */
.diff-container {{
    margin: 0.5rem 0 2rem 0;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--bg-color);
    overflow: hidden;
}}

.diff-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.7rem 1rem;
    background-color: var(--surface-bg);
    border-bottom: 1px solid var(--border-color);
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--heading-color);
}}

.diff-labels {{
    font-weight: 600;
    color: var(--heading-color);
    overflow-wrap: anywhere;
}}

.diff-empty {{
    margin: 0;
    padding: 2rem 1.25rem;
    text-align: center;
    color: var(--muted-color);
    font-size: 0.92rem;
}}

.diff-stats {{
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    font-family: var(--font-mono);
    font-size: 0.8rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}}

.diff-stats .diff-stat-add,
.diff-stat-add {{
    color: var(--diff-add-fg);
}}

.diff-stats .diff-stat-del,
.diff-stat-del {{
    color: var(--diff-del-fg);
}}

.diff-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: 0.82rem;
    line-height: 1.5;
    table-layout: fixed;
}}

.diff-table th,
.diff-table td {{
    padding: 0.16rem 0.6rem;
    border-bottom: none;
    vertical-align: top;
    white-space: pre-wrap;
    word-break: break-word;
}}

.diff-table tbody tr:hover {{
    background-color: transparent;
}}

.diff-table .diff-ln,
.diff-table .diff-lineno,
.diff-table .diff-gutter {{
    width: 3.4rem;
    text-align: right;
    color: var(--muted-color);
    user-select: none;
    border-right: 1px solid var(--border-subtle);
    font-variant-numeric: tabular-nums;
    padding-right: 0.55rem;
}}

.diff-table .diff-sign {{
    width: 1.7rem;
    text-align: center;
    color: var(--muted-color);
    user-select: none;
    padding-left: 0.2rem;
    padding-right: 0.2rem;
}}

.diff-table:not(.diff-split) .diff-code {{
    width: auto;
}}

.diff-split {{
    width: 100%;
}}

.diff-split td.diff-code {{
    width: calc(50% - 3.4rem);
}}

.diff-split td:nth-child(3),
.diff-split td.diff-split-divider {{
    border-left: 1px solid var(--border-color);
}}

.diff-hunk-heading {{
    background-color: var(--diff-hunk-bg);
    color: var(--diff-hunk-fg);
    font-family: var(--font-mono);
    font-size: 0.78rem;
    font-weight: 600;
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}}

.diff-hunk-heading td {{
    padding: 0.35rem 0.8rem;
}}

.diff-line-add {{
    background-color: var(--diff-add-bg);
    color: var(--text-color);
}}

.diff-line-add .diff-ln,
.diff-line-add .diff-lineno,
.diff-line-add .diff-gutter {{
    background-color: var(--diff-add-gutter);
    color: var(--diff-add-fg);
}}

.diff-line-add .diff-sign {{
    color: var(--diff-add-fg);
    font-weight: 600;
}}

.diff-line-del {{
    background-color: var(--diff-del-bg);
    color: var(--text-color);
}}

.diff-line-del .diff-ln,
.diff-line-del .diff-lineno,
.diff-line-del .diff-gutter {{
    background-color: var(--diff-del-gutter);
    color: var(--diff-del-fg);
}}

.diff-line-del .diff-sign {{
    color: var(--diff-del-fg);
    font-weight: 600;
}}

.diff-line-ctx {{
    background-color: var(--bg-color);
    color: var(--text-color);
}}

/* Split-diff paired replace rows: left side red, right side green */
.diff-split tr.diff-line-del.diff-line-add > td:nth-child(1) {{
    background-color: var(--diff-del-gutter);
    color: var(--diff-del-fg);
}}

.diff-split tr.diff-line-del.diff-line-add > td:nth-child(2) {{
    background-color: var(--diff-del-bg);
}}

.diff-split tr.diff-line-del.diff-line-add > td:nth-child(3) {{
    background-color: var(--diff-add-gutter);
    color: var(--diff-add-fg);
}}

.diff-split tr.diff-line-del.diff-line-add > td:nth-child(4) {{
    background-color: var(--diff-add-bg);
}}

/* Split-diff empty half-rows use neutral surface tint */
.diff-split tr.diff-line-del:not(.diff-line-add) > td:nth-child(3),
.diff-split tr.diff-line-del:not(.diff-line-add) > td:nth-child(4),
.diff-split tr.diff-line-add:not(.diff-line-del) > td:nth-child(1),
.diff-split tr.diff-line-add:not(.diff-line-del) > td:nth-child(2) {{
    background-color: var(--surface-bg);
    color: var(--muted-color);
}}

ins.diff-word,
.diff-table ins {{
    background-color: var(--diff-add-word-bg);
    color: var(--text-color);
    text-decoration: none;
    border-radius: 2px;
    padding: 0 1px;
}}

del.diff-word,
.diff-table del {{
    background-color: var(--diff-del-word-bg);
    color: var(--text-color);
    text-decoration: none;
    border-radius: 2px;
    padding: 0 1px;
}}

/* Standalone .diff / .patch file viewer */
.diff-view {{
    margin: 0.5rem 0 2rem 0;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--bg-color);
    font-family: var(--font-mono);
    font-size: 0.83rem;
    line-height: 1.5;
    overflow-x: auto;
}}

.diff-view > .diff-stats {{
    display: flex;
    padding: 0.55rem 0.9rem;
    background-color: var(--surface-bg);
    border-bottom: 1px solid var(--border-color);
}}

.diff-line {{
    padding: 0.08rem 0.9rem;
    white-space: pre-wrap;
    word-break: break-word;
}}

.diff-file-header {{
    background-color: var(--surface-alt);
    color: var(--heading-color);
    font-weight: 600;
    padding-top: 0.25rem;
    padding-bottom: 0.25rem;
    border-top: 1px solid var(--border-subtle);
}}

.diff-hunk-header {{
    background-color: var(--diff-hunk-bg);
    color: var(--diff-hunk-fg);
    font-weight: 600;
    padding-top: 0.24rem;
    padding-bottom: 0.24rem;
}}

.diff-add {{
    background-color: var(--diff-add-bg);
    color: var(--diff-add-fg);
}}

.diff-del {{
    background-color: var(--diff-del-bg);
    color: var(--diff-del-fg);
}}

.diff-ctx {{
    color: var(--text-color);
}}

/* Technical File Viewer (JSON / YAML / TOML / Diff / Plain Text) */
.tech-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.7rem 1rem;
    margin: 0 0 1.25rem 0;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--surface-bg);
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--heading-color);
}}

.file-status-badge,
.validation-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.22rem 0.65rem;
    margin-bottom: 0.9rem;
    border-radius: 4px;
    border: 1px solid var(--border-color);
    font-family: var(--font-mono);
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}}

.tech-header .validation-badge {{
    margin-bottom: 0;
}}

.validation-badge.valid,
.file-status-badge.status-valid {{
    color: var(--valid-fg);
    background-color: var(--valid-bg);
    border-color: var(--valid-border);
}}

.validation-badge.invalid,
.file-status-badge.status-invalid {{
    color: var(--invalid-fg);
    background-color: var(--invalid-bg);
    border-color: var(--invalid-border);
}}

.structured-tree,
.json-tree {{
    margin: 0 0 1.35rem 0;
    padding: 0.85rem 1.05rem;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--surface-bg);
    font-family: var(--font-mono);
    font-size: 0.83rem;
    line-height: 1.55;
    overflow-x: auto;
}}

.json-tree-root {{
    margin-top: 0.55rem;
}}

.json-tree details.json-node,
.json-tree details {{
    margin: 0.14rem 0;
}}

.json-tree .json-children {{
    padding-left: 1.05rem;
    margin-left: 0.32rem;
    border-left: 1px solid var(--border-color);
}}

.json-tree .json-leaf {{
    padding: 0.06rem 0;
}}

.json-tree summary {{
    cursor: pointer;
    color: var(--heading-color);
    font-weight: 550;
    user-select: none;
}}

.json-tree .json-meta {{
    color: var(--muted-color);
    font-weight: 450;
}}

.json-tree .json-key {{ color: var(--json-key); }}
.json-tree .json-string,
.json-tree .json-str {{ color: var(--json-string); }}
.json-tree .json-number,
.json-tree .json-num {{ color: var(--json-number); }}
.json-tree .json-bool {{ color: var(--json-bool); }}
.json-tree .json-null {{ color: var(--json-null); font-style: italic; }}

/* Plain Text File Viewer */
.plain-text-view {{
    margin: 0.25rem 0 2rem 0;
    padding: 1.1rem 1.3rem;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background-color: var(--surface-bg);
    color: var(--text-color);
    font-family: var(--font-mono);
    font-size: 0.87rem;
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-x: auto;
}}

.plain-text-line {{
    min-height: 1.5em;
    white-space: pre-wrap;
}}

/* Selection Review Comment Pill */
.mdv-comment-pill {{
    position: fixed;
    z-index: 9999;
    display: none;
    align-items: center;
    gap: 0.38rem;
    padding: 0.32rem 0.72rem;
    border: 1px solid var(--border-strong);
    border-radius: 5px;
    background-color: var(--heading-color);
    color: var(--bg-color);
    font-family: var(--font-sans);
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.3;
    cursor: pointer;
    box-shadow: var(--shadow-md);
    user-select: none;
}}

.mdv-comment-pill:hover {{
    background-color: var(--accent-color);
    border-color: var(--accent-color);
    color: var(--accent-contrast);
}}

.mdv-comment-pill:focus-visible {{
    outline: 2px solid var(--accent-color);
    outline-offset: 2px;
}}

/* WebKit Scrollbars */
::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}

::-webkit-scrollbar-track {{
    background: transparent;
}}

::-webkit-scrollbar-thumb {{
    background: var(--scrollbar-thumb);
    border-radius: 4px;
}}

::-webkit-scrollbar-thumb:hover {{
    background: var(--scrollbar-thumb-hover);
}}

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {{
    html {{
        scroll-behavior: auto;
    }}
    *, *::before, *::after {{
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
    }}
    [data-changed="true"] {{
        animation: none;
        background-color: var(--watch-bg-rest);
    }}
}}

/* Print Stylesheet — Crisp White-Paper Ink */
@media print {{
    :root {{
        color-scheme: light;
        --bg-color: #FFFFFF;
        --surface-bg: #F6F6F6;
        --surface-alt: #EFEFEF;
        --text-color: #111111;
        --heading-color: #000000;
        --muted-color: #444444;
        --border-color: #D0D0D0;
        --border-subtle: #E2E2E2;
        --border-strong: #999999;
        --accent-color: #111111;
        --accent-hover: #000000;
        --inline-code-bg: #F3F3F3;
        --pre-bg: #F7F7F7;
        --code-header-bg: #EFEFEF;
        --blockquote-bg: #FAFAFA;
        --shadow-sm: none;
        --shadow-md: none;
    }}

    html, body {{
        background-color: #FFFFFF !important;
        color: #111111 !important;
        font-size: 11pt;
        line-height: 1.55;
    }}

    .markdown-container {{
        max-width: 100% !important;
        padding: 0 !important;
        margin: 0 !important;
    }}

    .code-copy-btn,
    .heading-anchor,
    .mermaid-toolbar,
    .mdv-comment-pill {{
        display: none !important;
    }}

    [data-changed="true"] {{
        animation: none !important;
        background-color: transparent !important;
        border-left-color: #666666 !important;
    }}

    h1, h2, h3, h4, h5, h6 {{
        break-after: avoid;
        page-break-after: avoid;
    }}

    .highlight,
    pre,
    .mermaid-container,
    .katex-block,
    .table-wrapper,
    table,
    .admonition,
    blockquote,
    details.front-matter-card,
    figure {{
        break-inside: avoid;
        page-break-inside: avoid;
        box-shadow: none !important;
    }}

    a {{
        color: #111111 !important;
        text-decoration: underline !important;
    }}
}}
"""
    if custom_css and custom_css.strip():
        css = f"{css}\n/* User Custom CSS */\n{custom_css.strip()}\n"
    return css
