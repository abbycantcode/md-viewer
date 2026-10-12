#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "markdown",
#     "pyyaml",
# ]
# ///
"""md-viewer: Markdown viewer and editor for Ubuntu."""

import sys
import os
import re
import html
import subprocess

import markdown
from pygments.formatters import HtmlFormatter

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkSource", "300")

from gi.repository import Gtk, Gdk, WebKit2, GtkSource, Gio, GLib  # noqa: E402


class CustomHtmlFormatter(HtmlFormatter):
    """Custom Pygments HTML formatter that preserves language tags on code containers."""

    def __init__(self, lang_str: str = "", **options):
        super().__init__(**options)
        self.raw_lang = lang_str.removeprefix("language-") if lang_str else ""
        self.lang_str = lang_str

    def _wrap_div(self, inner):
        cls = (self.cssclass + " " + self.lang_str).strip()
        data_attr = f' data-lang="{self.raw_lang}"' if self.raw_lang else ""
        yield 0, f'<div class="{cls}"{data_attr}>'
        for tup in inner:
            yield tup
        yield 0, "</div>\n"


try:
    import yaml
except ImportError:
    yaml = None


# ---------------------------------------------------------------------------
# Bundled Vendor Assets (KaTeX & Mermaid for 100% offline rendering)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets", "vendor")
KATEX_CSS_PATH = os.path.join(ASSETS_DIR, "katex", "katex.min.css")
KATEX_JS_PATH = os.path.join(ASSETS_DIR, "katex", "katex.min.js")
KATEX_AUTO_PATH = os.path.join(ASSETS_DIR, "katex", "contrib", "auto-render.min.js")
MERMAID_JS_PATH = os.path.join(ASSETS_DIR, "mermaid", "mermaid.min.js")


# ---------------------------------------------------------------------------
# Front-matter and GitHub Alert Helpers
# ---------------------------------------------------------------------------
FRONT_MATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n(?:---|\.\.\.)\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict | None, str]:
    """Extract and parse YAML front-matter from document head if present."""
    match = FRONT_MATTER_REGEX.match(text)
    if not match:
        return None, text
    raw_yaml = match.group(1)
    body = text[match.end():]
    if yaml is not None:
        try:
            data = yaml.safe_load(raw_yaml)
            if isinstance(data, dict):
                return data, body
        except Exception:
            pass
    # Fallback parser for simple key-value lines
    meta = {}
    for line in raw_yaml.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return (meta, body) if meta else (None, body)


def render_front_matter_html(meta: dict | None) -> str:
    """Format parsed metadata into a collapsible metadata card."""
    if not meta:
        return ""

    title = meta.get("title")
    tags = meta.get("tags") or meta.get("categories") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.strip("[]").split(",") if t.strip()]

    rows = []
    for k, v in meta.items():
        if k in ("title", "tags", "categories"):
            continue
        if isinstance(v, list):
            val_str = ", ".join(html.escape(str(item)) for item in v)
        elif isinstance(v, dict):
            val_str = html.escape(str(v))
        else:
            val_str = html.escape(str(v))
        k_str = html.escape(str(k))
        rows.append(f"<tr><th>{k_str}</th><td>{val_str}</td></tr>")

    tag_pills = "".join(f'<span class="front-matter-tag">{html.escape(str(t))}</span>' for t in tags)
    tag_html = f'<div class="front-matter-tags">{tag_pills}</div>' if tag_pills else ""
    title_html = f'<span class="front-matter-doc-title">{html.escape(str(title))}</span>' if title else ""
    table_html = f'<table class="front-matter-table"><tbody>{"".join(rows)}</tbody></table>' if rows else ""

    return (
        '<details class="front-matter-card" open>\n'
        '  <summary class="front-matter-summary">\n'
        '    <span class="front-matter-badge">\n'
        '      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">\n'
        '        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>\n'
        '      </svg>\n'
        '      Metadata\n'
        '    </span>\n'
        f'    {title_html}\n'
        '  </summary>\n'
        '  <div class="front-matter-content">\n'
        f'    {tag_html}\n'
        f'    {table_html}\n'
        '  </div>\n'
        '</details>\n'
    )


def transform_github_alerts(text: str) -> str:
    """Transform GitHub-style blockquote alerts (> [!NOTE]) into admonition blocks."""
    pattern = re.compile(
        r"^(> ?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*\n(?:> ?.*(?:\n|$))+)",
        re.MULTILINE | re.IGNORECASE,
    )

    def repl(m):
        raw = m.group(1)
        alert_type = m.group(2).lower()
        lines = raw.split("\n")
        content_lines = []
        for line in lines[1:]:
            if line.startswith("> "):
                content_lines.append(line[2:])
            elif line.startswith(">"):
                content_lines.append(line[1:])
            elif line:
                content_lines.append(line)
        content = "\n".join(content_lines).strip()
        indented = "\n    ".join(content.split("\n"))
        return f'!!! {alert_type} "{alert_type.capitalize()}"\n    {indented}\n\n'

    return pattern.sub(repl, text)


# ---------------------------------------------------------------------------
# Pre-processing for Mermaid diagrams & KaTeX math
# ---------------------------------------------------------------------------
def preprocess_markdown(text: str) -> tuple[str, dict[str, str]]:
    """Extract and protect math formulas and Mermaid diagrams prior to markdown parsing."""
    placeholders: dict[str, str] = {}
    counter = 0

    def new_token(tag: str) -> str:
        nonlocal counter
        counter += 1
        return f"KMD_{tag}_{counter}_KMD"

    # 1. Defensive sanitization: disarm raw script tags and on* event attributes
    text = re.sub(
        r"<\s*script\b[^>]*>[\s\S]*?<\s*/\s*script\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    while re.search(r'(<[a-zA-Z][^>]*?)\s+on[a-zA-Z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', text, flags=re.IGNORECASE):
        text = re.sub(
            r'(<[a-zA-Z][^>]*?)\s+on[a-zA-Z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
            r"\1",
            text,
            flags=re.IGNORECASE,
        )

    # 2. Extract fenced Mermaid diagrams: ```mermaid ... ``` or ~~~mermaid ... ~~~
    def repl_mermaid(m):
        code = m.group(1).strip()
        tok = new_token("MERMAID")
        escaped = html.escape(code)
        placeholders[tok] = (
            '<div class="mermaid-container">\n'
            '  <div class="mermaid-header">\n'
            '    <span class="mermaid-badge">\n'
            '      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">\n'
            '        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>\n'
            '        <polyline points="2 17 12 22 22 17"></polyline>\n'
            '        <polyline points="2 12 12 17 22 12"></polyline>\n'
            '      </svg>\n'
            '      Diagram\n'
            '    </span>\n'
            '    <span class="mermaid-type">Mermaid</span>\n'
            '  </div>\n'
            '  <div class="mermaid-viewport">\n'
            f'    <div class="mermaid" data-source="{escaped}">{escaped}</div>\n'
            '  </div>\n'
            '</div>'
        )
        return f"\n\n{tok}\n\n"

    text = re.sub(
        r"(?:```|~~~)(?:mermaid)[ \t]*\n([\s\S]*?)(?:\n[ \t]*(?:```|~~~)|[ \t]*(?:```|~~~))[ \t]*(?:\n|$)",
        repl_mermaid,
        text,
        flags=re.IGNORECASE,
    )

    # 3. Extract fenced math blocks: ```math ... ```, ```katex ... ```, ```latex ... ```
    def repl_math_fence(m):
        code = m.group(1).strip()
        tok = new_token("MATHBLOCK")
        escaped = html.escape(code)
        placeholders[tok] = (
            '<div class="katex-block">\n'
            f'  <div class="katex-display-math" data-math="{escaped}">$${escaped}$$</div>\n'
            '</div>'
        )
        return f"\n\n{tok}\n\n"

    text = re.sub(
        r"(?:```|~~~)(?:math|katex|latex)[ \t]*\n([\s\S]*?)(?:\n[ \t]*(?:```|~~~)|[ \t]*(?:```|~~~))[ \t]*(?:\n|$)",
        repl_math_fence,
        text,
        flags=re.IGNORECASE,
    )

    # 4. Protect remaining code blocks (``` ... ``` or ~~~ ... ~~~)
    protected_code_blocks: dict[str, str] = {}
    cb_idx = 0

    def protect_code(m):
        nonlocal cb_idx
        cb_idx += 1
        tok = f"KMD_PROTECTED_CODE_{cb_idx}_KMD"
        protected_code_blocks[tok] = m.group(0)
        return tok

    text = re.sub(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", protect_code, text)

    # 5. Extract display math blocks: $$ ... $$ and \[ ... \]
    def repl_display_math(m):
        code = m.group(1).strip()
        tok = new_token("MATHBLOCK")
        escaped = html.escape(code)
        placeholders[tok] = (
            '<div class="katex-block">\n'
            f'  <div class="katex-display-math" data-math="{escaped}">$${escaped}$$</div>\n'
            '</div>'
        )
        return f"\n\n{tok}\n\n"

    text = re.sub(
        r"(?<!\\)\$\$\n?([\s\S]*?)\n?(?<!\\)\$\$",
        repl_display_math,
        text,
    )
    text = re.sub(
        r"(?<!\\)\\\[\n?([\s\S]*?)\n?(?<!\\)\\\]",
        repl_display_math,
        text,
    )

    # 6. Protect inline code spans `...`
    protected_inline: dict[str, str] = {}
    in_idx = 0

    def protect_inline(m):
        nonlocal in_idx
        in_idx += 1
        tok = f"KMD_PROTECTED_INLINE_{in_idx}_KMD"
        protected_inline[tok] = m.group(0)
        return tok

    text = re.sub(r"(?<!\\)(`+)(.+?)(?<!`)\1(?!`)", protect_inline, text)

    # 7. Extract inline math: $...$ and \(...\)
    def repl_inline_math(m):
        code = m.group(1).strip()
        tok = new_token("MATHINLINE")
        escaped = html.escape(code)
        placeholders[tok] = (
            f'<span class="katex-inline-math" data-math="{escaped}">${escaped}$</span>'
        )
        return tok

    text = re.sub(
        r"(?<!\\)\$(?!\s)([^\$\n]+?)(?<!\s)(?<!\\)\$(?!\d)",
        repl_inline_math,
        text,
    )
    text = re.sub(
        r"(?<!\\)\\\((.+?)(?<!\\)\\\)",
        repl_inline_math,
        text,
    )

    # 8. Restore protected inline code and code blocks
    for tok, original in protected_inline.items():
        text = text.replace(tok, original)
    for tok, original in protected_code_blocks.items():
        text = text.replace(tok, original)

    return text, placeholders


# ---------------------------------------------------------------------------
# CSS for rendered HTML view
# ---------------------------------------------------------------------------
RENDER_CSS = """\
:root {
    color-scheme: light dark;
    --bg-color: #ffffff;
    --surface-bg: #f8fafc;
    --card-bg: #ffffff;
    --card-header-bg: #f8fafc;
    --math-bg: #f8fafc;
    --text-color: #0f172a;
    --heading-color: #020617;
    --muted-color: #64748b;
    --border-color: #e2e8f0;
    --border-subtle: #f1f5f9;
    --border-hover: #cbd5e1;
    --link-color: #2563eb;
    --link-hover: #1d4ed8;
    --accent-color: #3b82f6;
    --inline-code-bg: #f1f5f9;
    --inline-code-color: #0f172a;
    --inline-code-border: #e2e8f0;
    --pre-bg: #0f172a;
    --pre-color: #f8fafc;
    --pre-border: #1e293b;
    --code-header-bg: #1e293b;
    --code-header-color: #94a3b8;
    --table-th-bg: #f8fafc;
    --table-hover-bg: #f1f5f9;
    --blockquote-bg: rgba(59, 130, 246, 0.05);
    --blockquote-border: #3b82f6;
    --tag-bg: #eff6ff;
    --tag-color: #2563eb;
    --tag-border: #bfdbfe;
    --kbd-bg: #f8fafc;
    --kbd-border: #cbd5e1;
    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Noto Sans", Ubuntu, Cantarell, sans-serif;
    --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro", SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

body.dark {
    --bg-color: #0d1117;
    --surface-bg: #161b22;
    --card-bg: #161b22;
    --card-header-bg: #1c2128;
    --math-bg: #161b22;
    --text-color: #e6edf3;
    --heading-color: #f0f6fc;
    --muted-color: #8b949e;
    --border-color: #30363d;
    --border-subtle: #21262d;
    --border-hover: #484f58;
    --link-color: #58a6ff;
    --link-hover: #79c0ff;
    --accent-color: #58a6ff;
    --inline-code-bg: #1f242c;
    --inline-code-color: #e6edf3;
    --inline-code-border: #30363d;
    --pre-bg: #161b22;
    --pre-color: #e6edf3;
    --pre-border: #30363d;
    --code-header-bg: #1c2128;
    --code-header-color: #8b949e;
    --table-th-bg: #161b22;
    --table-hover-bg: #1f242c;
    --blockquote-bg: rgba(88, 166, 255, 0.08);
    --blockquote-border: #58a6ff;
    --tag-bg: rgba(56, 139, 253, 0.15);
    --tag-color: #58a6ff;
    --tag-border: rgba(56, 139, 253, 0.3);
    --kbd-bg: #21262d;
    --kbd-border: #484f58;
    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.3);
    --shadow-md: 0 4px 12px 0 rgba(0, 0, 0, 0.4);
}

html {
    background-color: var(--bg-color);
    scroll-behavior: smooth;
}

body {
    font-family: var(--font-sans);
    font-size: 15.5px;
    line-height: 1.72;
    color: var(--text-color);
    background-color: var(--bg-color);
    word-wrap: break-word;
    overflow-wrap: break-word;
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}

.markdown-container {
    max-width: 56rem;
    margin: 0 auto;
    padding: 2.75rem 3.25rem 5rem 3.25rem;
    box-sizing: border-box;
}

/* Headings */
h1, h2, h3, h4, h5, h6 {
    color: var(--heading-color);
    font-weight: 650;
    line-height: 1.3;
    margin-top: 1.8rem;
    margin-bottom: 0.75rem;
    letter-spacing: -0.015em;
}

h1 {
    font-size: 2.15rem;
    font-weight: 750;
    letter-spacing: -0.025em;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid var(--border-color);
    margin-top: 2rem;
}

h2 {
    font-size: 1.55rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--border-color);
    margin-top: 1.65rem;
}

h3 {
    font-size: 1.28rem;
    margin-top: 1.4rem;
}

h4 {
    font-size: 1.08rem;
}

h5 {
    font-size: 0.95rem;
}

h6 {
    font-size: 0.86rem;
    color: var(--muted-color);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

p {
    margin-top: 0;
    margin-bottom: 1.05rem;
}

/* Links */
a {
    color: var(--link-color);
    text-decoration: none;
    text-underline-offset: 3px;
    transition: color 0.15s ease, text-decoration 0.15s ease;
}

a:hover {
    color: var(--link-hover);
    text-decoration: underline;
}

/* Code & Syntax */
code {
    font-family: var(--font-mono);
    font-size: 0.88em;
    background-color: var(--inline-code-bg);
    color: var(--inline-code-color);
    border: 1px solid var(--inline-code-border);
    padding: 0.2em 0.45em;
    border-radius: 6px;
}

pre {
    margin: 1.25rem 0;
    border-radius: 9px;
    overflow-x: auto;
    line-height: 1.5;
    background-color: var(--pre-bg);
    border: 1px solid var(--border-color);
    padding: 1.1rem 1.35rem;
}

pre code {
    background: none;
    border: none;
    padding: 0;
    color: inherit;
    font-size: 0.9em;
}

/* Pygments highlight wrappers with header */
.highlight {
    margin: 1.35rem 0;
    border-radius: 9px;
    border: 1px solid var(--border-color);
    overflow: hidden;
    background-color: var(--pre-bg);
    box-shadow: var(--shadow-sm);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.highlight:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
}

.highlight pre {
    margin: 0;
    border: none;
    border-radius: 0;
    background: transparent;
    padding: 1rem 1.25rem;
}

.code-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.45rem 0.95rem;
    background-color: var(--code-header-bg);
    border-bottom: 1px solid var(--border-color);
    font-size: 0.74rem;
    font-weight: 600;
    color: var(--code-header-color);
    letter-spacing: 0.05em;
    user-select: none;
}

.code-lang {
    text-transform: uppercase;
}

.code-copy-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 3px 8px;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--code-header-color);
    font-size: 0.75rem;
    font-family: inherit;
    cursor: pointer;
    transition: all 0.15s ease;
}

.code-copy-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-color);
}

.code-copy-btn.copied {
    color: #10b981;
}

/* Tables */
.table-wrapper {
    width: 100%;
    overflow-x: auto;
    margin: 1.4rem 0;
    border-radius: 9px;
    border: 1px solid var(--border-color);
    background-color: var(--card-bg);
    box-shadow: var(--shadow-sm);
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 0;
    text-align: left;
    font-size: 0.94em;
}

th, td {
    padding: 0.72rem 1.1rem;
    border-bottom: 1px solid var(--border-color);
}

th {
    background-color: var(--table-th-bg);
    color: var(--heading-color);
    font-weight: 650;
    letter-spacing: -0.01em;
}

tr:last-child td {
    border-bottom: none;
}

tbody tr {
    transition: background-color 0.12s ease;
}

tbody tr:hover {
    background-color: var(--table-hover-bg);
}

/* Blockquotes */
blockquote {
    border-left: 4px solid var(--blockquote-border);
    background-color: var(--blockquote-bg);
    margin: 1.35rem 0;
    padding: 0.75rem 1.3rem;
    border-radius: 0 8px 8px 0;
    color: var(--muted-color);
}

blockquote p:last-child {
    margin-bottom: 0;
}

/* Horizontal rule */
hr {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 2.25rem 0;
}

/* Lists */
ul, ol {
    padding-left: 2rem;
    margin: 0 0 1.15rem 0;
}

li {
    margin: 0.35rem 0;
}

li > p {
    margin-bottom: 0.35rem;
}

/* Images */
img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    box-shadow: var(--shadow-md);
    transition: transform 0.2s ease;
}

/* Task lists */
.task-list-item {
    list-style-type: none;
    margin-left: -1.5rem;
}

.task-list-item input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 1.15em;
    height: 1.15em;
    border: 1.6px solid var(--muted-color);
    border-radius: 4px;
    margin-right: 0.6em;
    vertical-align: -0.2em;
    position: relative;
    cursor: default;
    transition: all 0.15s ease;
    background-color: transparent;
}

.task-list-item input[type="checkbox"]:checked {
    background-color: var(--accent-color);
    border-color: var(--accent-color);
}

.task-list-item input[type="checkbox"]:checked::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 4px;
    width: 3px;
    height: 7px;
    border: solid white;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
}

/* Keyboard badge */
kbd {
    display: inline-block;
    padding: 2px 7px;
    font-family: var(--font-mono);
    font-size: 0.82em;
    font-weight: 500;
    color: var(--text-color);
    background-color: var(--kbd-bg);
    border: 1px solid var(--kbd-border);
    border-radius: 5px;
    box-shadow: 0 1px 0 var(--kbd-border), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

/* Front-matter card */
details.front-matter-card {
    border: 1px solid var(--border-color);
    border-radius: 10px;
    background-color: var(--card-bg);
    margin: 0 0 2rem 0;
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

details.front-matter-card:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
}

summary.front-matter-summary {
    padding: 0.75rem 1.15rem;
    cursor: pointer;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.85rem;
    user-select: none;
    border-bottom: 1px solid transparent;
    background-color: var(--card-header-bg);
    transition: background-color 0.15s ease;
}

details.front-matter-card[open] summary.front-matter-summary {
    border-bottom: 1px solid var(--border-color);
}

.front-matter-badge {
    font-size: 0.73rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 9px;
    background-color: var(--tag-bg);
    color: var(--tag-color);
    border: 1px solid var(--tag-border);
    border-radius: 999px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
}

.front-matter-doc-title {
    font-size: 0.98rem;
    color: var(--heading-color);
    font-weight: 600;
}

.front-matter-content {
    padding: 0.85rem 1.15rem;
}

.front-matter-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-bottom: 0.75rem;
}

.front-matter-tag {
    font-size: 0.8rem;
    padding: 2px 10px;
    background-color: var(--tag-bg);
    color: var(--tag-color);
    border: 1px solid var(--tag-border);
    border-radius: 999px;
    font-weight: 500;
}

.front-matter-table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.88rem;
}

.front-matter-table th, .front-matter-table td {
    padding: 0.4rem 0.7rem;
    border-bottom: 1px solid var(--border-subtle);
}

.front-matter-table th {
    background: transparent;
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--muted-color);
    width: 24%;
    font-weight: 500;
}

.front-matter-table td {
    color: var(--text-color);
}

.front-matter-table tr:last-child th,
.front-matter-table tr:last-child td {
    border-bottom: none;
}

/* GitHub alert callouts */
.admonition {
    padding: 0.9rem 1.25rem;
    border-left: 4px solid;
    margin: 1.35rem 0;
    border-radius: 8px;
    font-size: 0.96em;
    box-shadow: var(--shadow-sm);
}

.admonition-title {
    font-weight: 650;
    margin-bottom: 0.4rem;
    font-size: 0.98em;
    display: flex;
    align-items: center;
    gap: 0.45rem;
}

.admonition.note {
    border-color: #0969da;
    background-color: rgba(9, 105, 218, 0.08);
}
.admonition.note .admonition-title { color: #0969da; }
.admonition.note .admonition-title::before {
    content: "";
    display: inline-block;
    width: 16px;
    height: 16px;
    background-repeat: no-repeat;
    background-size: contain;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230969da' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M12 16v-4'/%3E%3Cpath d='M12 8h.01'/%3E%3C/svg%3E");
}

.admonition.tip {
    border-color: #1a7f37;
    background-color: rgba(26, 127, 55, 0.08);
}
.admonition.tip .admonition-title { color: #1a7f37; }
.admonition.tip .admonition-title::before {
    content: "";
    display: inline-block;
    width: 16px;
    height: 16px;
    background-repeat: no-repeat;
    background-size: contain;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231a7f37' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5'/%3E%3Cpath d='M9 18h6'/%3E%3Cpath d='M10 22h4'/%3E%3C/svg%3E");
}

.admonition.warning {
    border-color: #9a6700;
    background-color: rgba(154, 103, 0, 0.08);
}
.admonition.warning .admonition-title { color: #9a6700; }
.admonition.warning .admonition-title::before {
    content: "";
    display: inline-block;
    width: 16px;
    height: 16px;
    background-repeat: no-repeat;
    background-size: contain;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239a6700' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z'/%3E%3Cpath d='M12 9v4'/%3E%3Cpath d='M12 17h.01'/%3E%3C/svg%3E");
}

.admonition.caution, .admonition.danger {
    border-color: #cf222e;
    background-color: rgba(207, 34, 46, 0.08);
}
.admonition.caution .admonition-title, .admonition.danger .admonition-title { color: #cf222e; }
.admonition.caution .admonition-title::before, .admonition.danger .admonition-title::before {
    content: "";
    display: inline-block;
    width: 16px;
    height: 16px;
    background-repeat: no-repeat;
    background-size: contain;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23cf222e' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2'/%3E%3Cpath d='m15 9-6 6'/%3E%3Cpath d='m9 9 6 6'/%3E%3C/svg%3E");
}

.admonition.important {
    border-color: #8250df;
    background-color: rgba(130, 80, 223, 0.08);
}
.admonition.important .admonition-title { color: #8250df; }
.admonition.important .admonition-title::before {
    content: "";
    display: inline-block;
    width: 16px;
    height: 16px;
    background-repeat: no-repeat;
    background-size: contain;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238250df' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M12 8v4'/%3E%3Cpath d='M12 16h.01'/%3E%3C/svg%3E");
}

body.dark .admonition.note { border-color: #58a6ff; background-color: rgba(88, 166, 255, 0.12); }
body.dark .admonition.note .admonition-title { color: #58a6ff; }
body.dark .admonition.note .admonition-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2358a6ff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M12 16v-4'/%3E%3Cpath d='M12 8h.01'/%3E%3C/svg%3E");
}

body.dark .admonition.tip { border-color: #3fb950; background-color: rgba(63, 185, 80, 0.12); }
body.dark .admonition.tip .admonition-title { color: #3fb950; }
body.dark .admonition.tip .admonition-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233fb950' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5'/%3E%3Cpath d='M9 18h6'/%3E%3Cpath d='M10 22h4'/%3E%3C/svg%3E");
}

body.dark .admonition.warning { border-color: #d29922; background-color: rgba(210, 153, 34, 0.12); }
body.dark .admonition.warning .admonition-title { color: #d29922; }
body.dark .admonition.warning .admonition-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23d29922' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z'/%3E%3Cpath d='M12 9v4'/%3E%3Cpath d='M12 17h.01'/%3E%3C/svg%3E");
}

body.dark .admonition.caution, body.dark .admonition.danger { border-color: #f85149; background-color: rgba(248, 81, 73, 0.12); }
body.dark .admonition.caution .admonition-title, body.dark .admonition.danger .admonition-title { color: #f85149; }
body.dark .admonition.caution .admonition-title::before, body.dark .admonition.danger .admonition-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f85149' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2'/%3E%3Cpath d='m15 9-6 6'/%3E%3Cpath d='m9 9 6 6'/%3E%3C/svg%3E");
}

body.dark .admonition.important { border-color: #bc8cff; background-color: rgba(188, 140, 255, 0.12); }
body.dark .admonition.important .admonition-title { color: #bc8cff; }
body.dark .admonition.important .admonition-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23bc8cff' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M12 8v4'/%3E%3Cpath d='M12 16h.01'/%3E%3C/svg%3E");
}

/* Mermaid Diagrams Container */
.mermaid-container {
    margin: 1.6rem 0;
    border-radius: 10px;
    border: 1px solid var(--border-color);
    background-color: var(--card-bg);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.mermaid-container:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
}

.mermaid-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.45rem 0.95rem;
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted-color);
    border-bottom: 1px solid var(--border-color);
    background-color: var(--card-header-bg);
}

.mermaid-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--accent-color);
}

.mermaid-type {
    font-size: 0.72rem;
    color: var(--muted-color);
}

.mermaid-viewport {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 1.75rem 1.25rem;
    overflow-x: auto;
    min-height: 80px;
}

.mermaid-viewport .mermaid {
    width: 100%;
    display: flex;
    justify-content: center;
}

.mermaid-viewport svg {
    max-width: 100%;
    height: auto !important;
}

.mermaid-error {
    width: 100%;
    padding: 1rem 1.25rem;
    color: #ef4444;
    font-size: 0.88rem;
    text-align: left;
}

.mermaid-error-header {
    font-weight: 600;
    margin-bottom: 0.35rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.mermaid-error-msg {
    margin-bottom: 0.65rem;
    font-family: var(--font-mono);
    font-size: 0.82rem;
    background: rgba(239, 68, 68, 0.08);
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    border: 1px solid rgba(239, 68, 68, 0.2);
}

.mermaid-error-details summary {
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--muted-color);
    margin-bottom: 0.4rem;
}

.mermaid-error-code {
    font-family: var(--font-mono);
    font-size: 0.8rem;
    background: var(--pre-bg);
    color: var(--pre-color);
    padding: 0.65rem;
    border-radius: 6px;
    margin: 0;
}

/* KaTeX Math Equations */
.katex-block {
    margin: 1.5rem 0;
    padding: 1.2rem 1.5rem;
    border-radius: 9px;
    background-color: var(--math-bg);
    border: 1px solid var(--border-color);
    overflow-x: auto;
    overflow-y: hidden;
    display: flex;
    justify-content: center;
    align-items: center;
    box-shadow: var(--shadow-sm);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.katex-block:hover {
    border-color: var(--border-hover);
    box-shadow: var(--shadow-md);
}

.katex-display-math {
    margin: 0;
    text-align: center;
}

.katex-display {
    margin: 0 !important;
    text-align: center;
}

.katex-inline-math {
    display: inline;
    padding: 0 0.15em;
}

/* WebKit Scrollbars */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: rgba(140, 150, 165, 0.3);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: rgba(140, 150, 165, 0.5);
}
"""


# ---------------------------------------------------------------------------
# Client-side JavaScript for interactive enhancements (offline)
# ---------------------------------------------------------------------------
RENDER_JS = """\
(function() {
    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatLangName(lang) {
        if (!lang || lang === "code" || lang === "text" || lang === "plain") return "CODE";
        var map = {
            "js": "JavaScript", "javascript": "JavaScript",
            "ts": "TypeScript", "typescript": "TypeScript",
            "py": "Python", "python": "Python",
            "rb": "Ruby", "ruby": "Ruby",
            "sh": "Bash", "bash": "Bash", "zsh": "Zsh", "shell": "Shell",
            "cpp": "C++", "c++": "C++", "c": "C",
            "cs": "C#", "csharp": "C#",
            "rs": "Rust", "rust": "Rust",
            "go": "Go", "golang": "Go",
            "html": "HTML", "css": "CSS", "scss": "SCSS",
            "json": "JSON", "yaml": "YAML", "yml": "YAML",
            "md": "Markdown", "markdown": "Markdown",
            "sql": "SQL", "xml": "XML", "diff": "Diff",
            "dockerfile": "Dockerfile", "docker": "Docker"
        };
        var lower = lang.toLowerCase();
        return map[lower] || lang.toUpperCase();
    }

    function renderMath() {
        if (window.katex) {
            document.querySelectorAll(".katex-display-math:not(.rendered)").forEach(function(el) {
                var tex = el.getAttribute("data-math") || el.textContent;
                tex = tex.replace(/^\\$\\$|\\$\\$$/g, "").trim();
                try {
                    katex.render(tex, el, { displayMode: true, throwOnError: false });
                    el.classList.add("rendered");
                } catch (e) {}
            });
            document.querySelectorAll(".katex-inline-math:not(.rendered)").forEach(function(el) {
                var tex = el.getAttribute("data-math") || el.textContent;
                tex = tex.replace(/^\\$|\\$$/g, "").trim();
                try {
                    katex.render(tex, el, { displayMode: false, throwOnError: false });
                    el.classList.add("rendered");
                } catch (e) {}
            });
        }
        if (window.renderMathInElement) {
            try {
                renderMathInElement(document.body, {
                    delimiters: [
                        { left: "$$", right: "$$", display: true },
                        { left: "\\\\[", right: "\\\\]", display: true },
                        { left: "$", right: "$", display: false },
                        { left: "\\\\(", right: "\\\\)", display: false }
                    ],
                    throwOnError: false,
                    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
                    ignoredClasses: ["katex", "katex-block", "katex-display-math", "katex-inline-math", "mermaid"]
                });
            } catch (err) {
                console.error("KaTeX auto-render error:", err);
            }
        }
    }

    function renderMermaidError(el, code, err) {
        el.classList.add("has-error");
        var msg = (err && err.message) ? err.message : String(err);
        var rogue = document.querySelectorAll('svg[id^="dmermaid"], [id^="dmermaid"]');
        rogue.forEach(function(r) { r.remove(); });
        el.innerHTML = '<div class="mermaid-error">' +
            '<div class="mermaid-error-header">⚠️ Diagram Syntax Error</div>' +
            '<div class="mermaid-error-msg">' + escapeHtml(msg) + '</div>' +
            '<details class="mermaid-error-details"><summary>Diagram Source</summary><pre class="mermaid-error-code">' + escapeHtml(code) + '</pre></details>' +
            '</div>';
    }

    function renderMermaidDiagrams() {
        if (!window.mermaid) return;
        var isDark = document.body.classList.contains("dark");
        mermaid.initialize({
            startOnLoad: false,
            theme: isDark ? "dark" : "default",
            securityLevel: "loose",
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Noto Sans", sans-serif',
            themeVariables: isDark ? {
                darkMode: true,
                background: "#161b22",
                primaryColor: "#1f6feb",
                primaryTextColor: "#f0f6fc",
                primaryBorderColor: "#30363d",
                lineColor: "#8b949e",
                secondaryColor: "#21262d",
                tertiaryColor: "#161b22",
                mainBkg: "#161b22",
                nodeBorder: "#30363d",
                clusterBkg: "#0d1117",
                titleColor: "#f0f6fc",
                edgeLabelBackground: "#161b22",
                nodeTextColor: "#f0f6fc"
            } : {
                darkMode: false,
                background: "#ffffff",
                primaryColor: "#0969da",
                primaryTextColor: "#1f2328",
                primaryBorderColor: "#d0d7de",
                lineColor: "#57606a",
                secondaryColor: "#f6f8fa",
                tertiaryColor: "#ffffff",
                mainBkg: "#ffffff",
                nodeBorder: "#d0d7de",
                clusterBkg: "#f8fafc",
                titleColor: "#1f2328",
                edgeLabelBackground: "#ffffff",
                nodeTextColor: "#1f2328"
            }
        });

        var items = document.querySelectorAll(".mermaid:not(.rendered)");
        items.forEach(function(el, idx) {
            var rawCode = el.getAttribute("data-source") || el.textContent.trim();
            var id = "mermaid-chart-" + Date.now() + "-" + idx;
            try {
                mermaid.render(id, rawCode).then(function(res) {
                    el.innerHTML = res.svg;
                    el.classList.add("rendered");
                }).catch(function(err) {
                    console.error("Mermaid render error:", err);
                    renderMermaidError(el, rawCode, err);
                });
            } catch (syncErr) {
                console.error("Mermaid sync error:", syncErr);
                renderMermaidError(el, rawCode, syncErr);
            }
        });
    }

    function setupCodeBlocks() {
        document.querySelectorAll("div.highlight").forEach(function(block) {
            if (block.querySelector(".code-header")) return;
            var pre = block.querySelector("pre");
            if (!pre) return;

            var code = pre.querySelector("code");
            var lang = block.getAttribute("data-lang") || "";
            if (!lang && code && code.className) {
                var m = code.className.match(/(?:language-|lang-)(\\w+)/);
                if (m) lang = m[1];
            }
            if (!lang) {
                var m2 = block.className.match(/(?:language-|highlight-)(\\w+)/);
                if (m2) lang = m2[1];
            }

            var header = document.createElement("div");
            header.className = "code-header";

            var badge = document.createElement("span");
            badge.className = "code-lang";
            badge.textContent = formatLangName(lang);
            header.appendChild(badge);

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "code-copy-btn";
            btn.title = "Copy code to clipboard";
            btn.setAttribute("aria-label", "Copy code to clipboard");
            var copyIconSvg = '<svg class="copy-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
            var checkIconSvg = '<svg class="copy-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
            btn.innerHTML = copyIconSvg + '<span class="copy-label">Copy</span>';

            btn.addEventListener("click", function(e) {
                e.preventDefault();
                var text = (code ? code.innerText : pre.innerText) || "";
                function markCopied() {
                    btn.classList.add("copied");
                    btn.innerHTML = checkIconSvg + '<span class="copy-label">Copied!</span>';
                    setTimeout(function() {
                        btn.classList.remove("copied");
                        btn.innerHTML = copyIconSvg + '<span class="copy-label">Copy</span>';
                    }, 1600);
                }
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(markCopied).catch(function() {
                        fallbackCopy(text);
                        markCopied();
                    });
                } else {
                    fallbackCopy(text);
                    markCopied();
                }
            });
            header.appendChild(btn);
            block.insertBefore(header, pre);
        });
    }

    function fallbackCopy(text) {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "0";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(ta);
    }

    function init() {
        renderMath();
        renderMermaidDiagrams();
        setupCodeBlocks();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
"""


# ---------------------------------------------------------------------------
# Markdown rendering configuration
# ---------------------------------------------------------------------------
MARKDOWN_EXTENSIONS = [
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.toc",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "markdown.extensions.codehilite",
    "markdown.extensions.admonition",
    "markdown.extensions.def_list",
    "markdown.extensions.footnotes",
]

MARKDOWN_EXTENSION_CONFIGS = {
    "markdown.extensions.codehilite": {
        "css_class": "highlight",
        "guess_lang": True,
        "pygments_formatter": CustomHtmlFormatter,
    },
    "markdown.extensions.toc": {
        "permalink": False,
    },
}


def render_markdown(text: str, dark: bool) -> str:
    """Convert markdown text to a complete HTML document with KaTeX and Mermaid support."""
    meta, body = parse_front_matter(text)
    fm_html = render_front_matter_html(meta)
    transformed_body = transform_github_alerts(body)

    # Preprocess Mermaid diagrams and math equations
    preprocessed_body, placeholders = preprocess_markdown(transformed_body)

    pygments_style = "github-dark" if dark else "friendly"
    extension_configs = {
        "markdown.extensions.codehilite": {
            "css_class": "highlight",
            "guess_lang": True,
            "pygments_style": pygments_style,
            "pygments_formatter": CustomHtmlFormatter,
        },
        "markdown.extensions.toc": {
            "permalink": False,
        },
    }

    html_body = markdown.markdown(
        preprocessed_body,
        extensions=MARKDOWN_EXTENSIONS,
        extension_configs=extension_configs,
    )

    # Unwrap paragraphs around block-level placeholders
    html_body = re.sub(
        r"<p>\s*(KMD_(?:MERMAID|MATHBLOCK)_[0-9]+_KMD)\s*</p>",
        r"\1",
        html_body,
    )

    # Restore placeholders
    for tok, markup in placeholders.items():
        html_body = html_body.replace(tok, markup)

    # Wrap tables in overflow container for horizontal scroll responsiveness
    html_body = re.sub(
        r"(<table>[\s\S]*?</table>)",
        r'<div class="table-wrapper">\1</div>',
        html_body,
    )

    pygments_css = HtmlFormatter(style=pygments_style).get_style_defs(".highlight")
    theme_class = "dark" if dark else ""
    bg_hex = "#0d1117" if dark else "#ffffff"
    scheme = "dark" if dark else "light"

    # Bundle asset URIs
    katex_css_uri = GLib.filename_to_uri(KATEX_CSS_PATH, None) if os.path.isfile(KATEX_CSS_PATH) else ""
    katex_js_uri = GLib.filename_to_uri(KATEX_JS_PATH, None) if os.path.isfile(KATEX_JS_PATH) else ""
    katex_auto_uri = GLib.filename_to_uri(KATEX_AUTO_PATH, None) if os.path.isfile(KATEX_AUTO_PATH) else ""
    mermaid_js_uri = GLib.filename_to_uri(MERMAID_JS_PATH, None) if os.path.isfile(MERMAID_JS_PATH) else ""

    asset_tags = []
    if katex_css_uri:
        asset_tags.append(f'<link rel="stylesheet" href="{katex_css_uri}">')
    if katex_js_uri:
        asset_tags.append(f'<script src="{katex_js_uri}"></script>')
    if katex_auto_uri:
        asset_tags.append(f'<script src="{katex_auto_uri}"></script>')
    if mermaid_js_uri:
        asset_tags.append(f'<script src="{mermaid_js_uri}"></script>')
    assets_html = "\n".join(asset_tags)

    csp = (
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline' file:; "
        "style-src 'self' 'unsafe-inline' file:; "
        "font-src 'self' file: data:; "
        "img-src * file: data: blob:; "
        "connect-src 'none'; "
        "media-src 'none'; "
        "object-src 'none'; "
        "frame-src 'none';"
    )

    return (
        f'<!DOCTYPE html>\n'
        f'<html style="background-color: {bg_hex}; color-scheme: {scheme};"><head>'
        f'<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{assets_html}\n'
        f'<style>\n{RENDER_CSS}\n{pygments_css}\n</style>\n'
        f'</head><body class="{theme_class}">\n'
        f'<div class="markdown-container">\n'
        f'{fm_html}{html_body}\n'
        f'</div>\n'
        f'<script>\n{RENDER_JS}\n</script>\n'
        f'</body></html>'
    )


# ---------------------------------------------------------------------------
# GTK Application
# ---------------------------------------------------------------------------
class MarkdownViewerApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="dev.abby.md-viewer",
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.dark_mode = self._detect_system_theme()
        self.zoom_level: float = 1.0
        self.current_file: str | None = None
        self._file_monitor_id: int | None = None
        self._file_mtime: float = 0.0
        self._dirty: bool = False
        self._loading: bool = False
        self._clipboard_mode: bool = False
        self._clipboard_text: str | None = None
        self.win: Gtk.ApplicationWindow | None = None

        # GTK CSS provider for widget styling and dynamic font zoom
        self.css_provider = Gtk.CssProvider()
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    # -- Lifecycle ----------------------------------------------------------

    def do_activate(self):
        """Launched with no file argument (or --clipboard mode)."""
        if self.win:
            self.win.present()
            return
        self._build_window()
        self.win.present()
        if self._clipboard_mode and self._clipboard_text is not None:
            self._load_clipboard_content(self._clipboard_text)
        else:
            self._open_file_dialog()

    def do_open(self, files, n_files, hint):
        """Launched with a file argument."""
        self.current_file = files[0].get_path()
        if not self.win:
            self._build_window()
        self._load_file()
        self.win.present()

    # -- UI Construction ----------------------------------------------------

    def _build_window(self):
        self.win = Gtk.ApplicationWindow(application=self, title="md-viewer")
        self.win.set_default_size(980, 740)
        self.win.set_icon_name("text-x-markdown")

        # --- Content stack ---
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        # Rendered view (WebKit2)
        self.webview = WebKit2.WebView()
        ws = self.webview.get_settings()
        ws.set_enable_javascript(True)
        ws.set_allow_file_access_from_file_urls(True)
        ws.set_allow_universal_access_from_file_urls(True)
        ws.set_enable_page_cache(False)
        self.webview.connect("decide-policy", self._on_decide_policy)

        scroll_web = Gtk.ScrolledWindow()
        scroll_web.get_style_context().add_class("preview-scrolled")
        scroll_web.add(self.webview)
        self.stack.add_titled(scroll_web, "rendered", "Preview")

        # Source view (GtkSourceView)
        self.source_buffer = GtkSource.Buffer()
        lm = GtkSource.LanguageManager.get_default()
        md_lang = lm.get_language("markdown")
        if md_lang:
            self.source_buffer.set_language(md_lang)
        self.source_view = GtkSource.View(buffer=self.source_buffer)
        self.source_view.get_style_context().add_class("editor-source")
        self.source_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.source_view.set_show_line_numbers(True)
        self.source_view.set_highlight_current_line(True)
        self.source_view.set_auto_indent(True)
        self.source_view.set_indent_on_tab(True)
        self.source_view.set_indent_width(4)
        self.source_view.set_tab_width(4)
        self.source_view.set_insert_spaces_instead_of_tabs(True)
        self.source_view.set_editable(True)
        self.source_view.set_monospace(True)
        self.source_view.set_top_margin(16)
        self.source_view.set_bottom_margin(16)
        self.source_view.set_left_margin(16)
        self.source_view.set_right_margin(16)
        self.source_buffer.set_highlight_matching_brackets(True)
        self.source_buffer.set_highlight_syntax(True)
        self.source_buffer.connect("changed", self._on_buffer_changed)

        scroll_src = Gtk.ScrolledWindow()
        scroll_src.get_style_context().add_class("source-scrolled")
        scroll_src.add(self.source_view)
        self.stack.add_titled(scroll_src, "source", "Edit")

        self.stack.connect("notify::visible-child-name", self._on_stack_child_changed)
        self.stack.set_visible_child_name("rendered")

        # --- Header bar ---
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("md-viewer")
        header.get_style_context().add_class("main-headerbar")

        # Linked file actions box (Open, Save, Save As)
        file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        file_box.get_style_context().add_class("linked")
        file_box.get_style_context().add_class("file-actions")

        # Open button
        open_btn = Gtk.Button.new_from_icon_name(
            "document-open-symbolic", Gtk.IconSize.BUTTON
        )
        open_btn.set_tooltip_text("Open file  (Ctrl+O)")
        open_btn.connect("clicked", lambda _b: self._open_file_dialog())
        file_box.pack_start(open_btn, False, False, 0)

        # Save button with dynamic dirty state indicator
        self.save_btn = Gtk.Button.new_from_icon_name(
            "document-save-symbolic", Gtk.IconSize.BUTTON
        )
        self.save_btn.set_tooltip_text("Save  (Ctrl+S)")
        self.save_btn.connect("clicked", lambda _b: self._save_file())
        file_box.pack_start(self.save_btn, False, False, 0)

        # Save As button
        save_as_btn = Gtk.Button.new_from_icon_name(
            "document-save-as-symbolic", Gtk.IconSize.BUTTON
        )
        save_as_btn.set_tooltip_text("Save As  (Ctrl+Shift+S)")
        save_as_btn.connect("clicked", lambda _b: self._save_file_as())
        file_box.pack_start(save_as_btn, False, False, 0)

        header.pack_start(file_box)

        # Separator between file actions and view switcher
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        header.pack_start(sep1)

        # Segmented Preview/Edit switcher with clear text labels
        self.switcher = Gtk.StackSwitcher()
        self.switcher.set_stack(self.stack)
        self.switcher.get_style_context().add_class("linked")
        self.switcher.get_style_context().add_class("mode-switcher")
        header.pack_start(self.switcher)

        # Theme toggle icon button
        self.theme_btn = Gtk.Button.new_from_icon_name(
            self._get_theme_icon_name(), Gtk.IconSize.BUTTON
        )
        self.theme_btn.set_tooltip_text(
            "Switch to light theme  (Ctrl+T)" if self.dark_mode else "Switch to dark theme  (Ctrl+T)"
        )
        self.theme_btn.connect("clicked", self._on_toggle_theme)
        header.pack_end(self.theme_btn)

        # Separator before zoom controls
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        header.pack_end(sep2)

        # Zoom controls (linked box: [-] [100%] [+])
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        zoom_box.get_style_context().add_class("linked")
        zoom_box.get_style_context().add_class("zoom-controls")

        zoom_out_btn = Gtk.Button.new_from_icon_name(
            "zoom-out-symbolic", Gtk.IconSize.BUTTON
        )
        zoom_out_btn.set_tooltip_text("Zoom out  (Ctrl+-)")
        zoom_out_btn.connect("clicked", lambda _b: self._zoom_out())
        zoom_box.pack_start(zoom_out_btn, False, False, 0)

        self.zoom_label_btn = Gtk.Button(label="100%")
        self.zoom_label_btn.set_tooltip_text("Reset zoom  (Ctrl+0)")
        self.zoom_label_btn.connect("clicked", lambda _b: self._zoom_reset())
        zoom_box.pack_start(self.zoom_label_btn, False, False, 0)

        zoom_in_btn = Gtk.Button.new_from_icon_name(
            "zoom-in-symbolic", Gtk.IconSize.BUTTON
        )
        zoom_in_btn.set_tooltip_text("Zoom in  (Ctrl++)")
        zoom_in_btn.connect("clicked", lambda _b: self._zoom_in())
        zoom_box.pack_start(zoom_in_btn, False, False, 0)

        header.pack_end(zoom_box)

        # Document reading stats label (subtle pill badge, hidden by default until calculated)
        self.stats_label = Gtk.Label()
        self.stats_label.get_style_context().add_class("doc-stats-label")
        self.stats_label.set_no_show_all(True)
        header.pack_end(self.stats_label)

        self.win.set_titlebar(header)
        self.win.add(self.stack)

        # --- Keyboard shortcuts ---
        accel = Gtk.AccelGroup()
        shortcuts = {
            "<Control>o": lambda *_a: self._open_file_dialog(),
            "<Control>s": lambda *_a: self._save_file(),
            "<Control><Shift>s": lambda *_a: self._save_file_as(),
            "<Control>e": lambda *_a: self._toggle_view(),
            "<Control>t": lambda *_a: self._on_toggle_theme(None),
            "<Control>plus": lambda *_a: self._zoom_in(),
            "<Control>equal": lambda *_a: self._zoom_in(),
            "<Control>KP_Add": lambda *_a: self._zoom_in(),
            "<Control>minus": lambda *_a: self._zoom_out(),
            "<Control>KP_Subtract": lambda *_a: self._zoom_out(),
            "<Control>0": lambda *_a: self._zoom_reset(),
            "<Control>KP_0": lambda *_a: self._zoom_reset(),
            "<Control>r": lambda *_a: self._refresh_rendered_view(),
            "<Control>q": lambda *_a: self._request_quit(),
        }
        for combo, handler in shortcuts.items():
            key, mod = Gtk.accelerator_parse(combo)
            accel.connect(key, mod, 0, handler)
        self.win.add_accel_group(accel)

        # --- Drag and drop ---
        self.win.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.win.connect("drag-data-received", self._on_drag_data)
        self.win.connect("delete-event", self._on_delete_event)

        # Apply initial theme & styles
        self._apply_theme()

        self.win.show_all()

    # -- Zoom ---------------------------------------------------------------

    def _zoom_in(self):
        self._set_zoom(round(self.zoom_level + 0.1, 1))

    def _zoom_out(self):
        self._set_zoom(round(self.zoom_level - 0.1, 1))

    def _zoom_reset(self):
        self._set_zoom(1.0)

    def _set_zoom(self, level: float):
        self.zoom_level = max(0.5, min(3.0, level))
        self.webview.set_zoom_level(self.zoom_level)
        if hasattr(self, "zoom_label_btn") and self.zoom_label_btn:
            self.zoom_label_btn.set_label(f"{int(round(self.zoom_level * 100))}%")
        self._update_gtk_css()

    def _update_gtk_css(self):
        """Update GTK application styles for theme background, header elements, and editor font."""
        bg_hex = "#0d1117" if self.dark_mode else "#ffffff"
        font_size = max(8, int(round(11 * self.zoom_level)))
        css_data = f"""
        headerbar.main-headerbar {{
            min-height: 46px;
            padding-left: 8px;
            padding-right: 8px;
        }}
        headerbar.main-headerbar button {{
            border-radius: 6px;
            transition: all 120ms ease;
        }}
        headerbar.main-headerbar button.suggested-action {{
            background-image: none;
            background-color: #2563eb;
            color: #ffffff;
            font-weight: 600;
        }}
        stackswitcher.mode-switcher button {{
            border-radius: 6px;
            padding: 4px 12px;
            font-size: 0.88rem;
            font-weight: 500;
        }}
        stackswitcher.mode-switcher button:checked {{
            font-weight: 600;
        }}
        .doc-stats-label {{
            font-size: 0.78rem;
            color: alpha(currentColor, 0.75);
            background-color: alpha(currentColor, 0.08);
            border: 1px solid alpha(currentColor, 0.14);
            padding: 2px 10px;
            border-radius: 999px;
            font-weight: 500;
            margin-right: 6px;
        }}
        .zoom-controls button {{
            padding: 3px 8px;
        }}
        scrolledwindow.preview-scrolled,
        scrolledwindow.preview-scrolled viewport {{
            background-color: {bg_hex};
        }}
        textview.editor-source text {{
            font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", "Ubuntu Mono", "Source Code Pro", monospace;
            font-size: {font_size}pt;
        }}
        """
        try:
            self.css_provider.load_from_data(css_data.encode("utf-8"))
        except Exception:
            pass

    # -- Theme --------------------------------------------------------------

    @staticmethod
    def _detect_system_theme() -> bool:
        """Return True if the system GTK theme is dark."""
        settings = Gtk.Settings.get_default()
        if settings:
            theme_name = settings.get_property("gtk-theme-name") or ""
            prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")
            return prefer_dark or "dark" in theme_name.lower()
        return False

    def _get_theme_icon_name(self) -> str:
        return "display-brightness-symbolic" if self.dark_mode else "weather-clear-night-symbolic"

    def _apply_theme(self):
        """Apply the current dark_mode setting to all views."""
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", self.dark_mode)

        # WebKit background matching to eliminate white flash
        bg_rgba = (
            Gdk.RGBA(13 / 255.0, 17 / 255.0, 23 / 255.0, 1.0)
            if self.dark_mode
            else Gdk.RGBA(1.0, 1.0, 1.0, 1.0)
        )
        self.webview.set_background_color(bg_rgba)

        # GtkSourceView scheme
        sm = GtkSource.StyleSchemeManager.get_default()
        schemes = (
            ("Yaru-dark", "oblivion", "solarized-dark", "classic")
            if self.dark_mode
            else ("Yaru", "solarized-light", "classic")
        )
        for sid in schemes:
            scheme = sm.get_scheme(sid)
            if scheme:
                self.source_buffer.set_style_scheme(scheme)
                break

        self._update_gtk_css()
        self._refresh_rendered_view()

    def _on_toggle_theme(self, _btn):
        self.dark_mode = not self.dark_mode
        if hasattr(self, "theme_btn") and self.theme_btn:
            self.theme_btn.set_image(
                Gtk.Image.new_from_icon_name(self._get_theme_icon_name(), Gtk.IconSize.BUTTON)
            )
            self.theme_btn.set_tooltip_text(
                "Switch to light theme  (Ctrl+T)" if self.dark_mode else "Switch to dark theme  (Ctrl+T)"
            )
        self._apply_theme()

    # -- View toggle --------------------------------------------------------

    def _toggle_view(self):
        current = self.stack.get_visible_child_name()
        target = "source" if current == "rendered" else "rendered"
        self.stack.set_visible_child_name(target)

    def _on_stack_child_changed(self, stack, _param):
        if stack.get_visible_child_name() == "rendered":
            self._refresh_rendered_view()

    def _refresh_rendered_view(self):
        """Re-render the WebView from the current source buffer content."""
        start = self.source_buffer.get_start_iter()
        end = self.source_buffer.get_end_iter()
        text = self.source_buffer.get_text(start, end, True) or ""
        html_content = render_markdown(text, self.dark_mode)
        base_dir = os.path.dirname(self.current_file) if self.current_file else os.getcwd()
        base_uri = GLib.filename_to_uri(base_dir, None) + "/"
        self.webview.load_html(html_content, base_uri)
        self._update_stats()

    def _on_decide_policy(self, webview, decision, decision_type):
        """Handle link clicks: open external links in default desktop browser."""
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            req = action.get_request()
            uri = req.get_uri() if req else None
            if uri and (uri.startswith("http://") or uri.startswith("https://") or uri.startswith("mailto:")):
                decision.ignore()
                try:
                    Gtk.show_uri_on_window(self.win, uri, Gdk.CURRENT_TIME)
                except Exception:
                    pass
                return True
        return False

    # -- Buffer and dirty state management ----------------------------------

    def _on_buffer_changed(self, _buffer):
        if self._loading:
            return
        self._set_dirty(True)
        self._update_stats()

    def _set_dirty(self, dirty: bool):
        if self._dirty != dirty:
            self._dirty = dirty
            self._update_title()
            if hasattr(self, "save_btn") and self.save_btn:
                if self._dirty:
                    self.save_btn.get_style_context().add_class("suggested-action")
                    self.save_btn.set_tooltip_text("Save changes  (Ctrl+S) • Unsaved edits")
                else:
                    self.save_btn.get_style_context().remove_class("suggested-action")
                    self.save_btn.set_tooltip_text("Save  (Ctrl+S)")

    def _update_title(self):
        if not self.win:
            return
        if self.current_file:
            basename = os.path.basename(self.current_file)
        elif self._clipboard_mode:
            basename = "Clipboard"
        else:
            basename = "Untitled"
        prefix = "* " if self._dirty else ""
        self.win.set_title(f"{prefix}{basename} - md-viewer")
        header = self.win.get_titlebar()
        if isinstance(header, Gtk.HeaderBar):
            header.set_title(f"{prefix}{basename}")
            if self.current_file:
                subtitle = os.path.dirname(self.current_file)
            elif self._clipboard_mode:
                subtitle = "Quick Editor"
            else:
                subtitle = "Unsaved"
            header.set_subtitle(subtitle)

    def _update_stats(self):
        """Update reading stats badge in the HeaderBar."""
        if not hasattr(self, "stats_label") or not self.stats_label:
            return
        start = self.source_buffer.get_start_iter()
        end = self.source_buffer.get_end_iter()
        text = self.source_buffer.get_text(start, end, True) or ""
        words = len(re.findall(r"\b\w+\b", text))
        if words == 0:
            self.stats_label.set_text("")
            self.stats_label.set_visible(False)
            return
        reading_time = max(1, round(words / 200))
        read_text = f"{reading_time} min read" if reading_time > 1 else "1 min read"
        self.stats_label.set_text(f"{words:,} words · {read_text}")
        self.stats_label.set_visible(True)

    def _confirm_discard_changes(self) -> bool:
        """Prompt to save if there are unsaved changes. Returns True to proceed, False to abort."""
        if not self._dirty:
            return True

        target = os.path.basename(self.current_file) if self.current_file else "Untitled document"
        dialog = Gtk.MessageDialog(
            parent=self.win,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Save changes to '{target}' before proceeding?",
        )
        dialog.format_secondary_text(
            "If you proceed without saving, your changes will be discarded."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Don't Save", Gtk.ResponseType.NO)
        save_btn = dialog.add_button("Save", Gtk.ResponseType.YES)
        save_btn.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.YES)

        res = dialog.run()
        dialog.destroy()

        if res == Gtk.ResponseType.YES:
            return self._save_file()
        elif res == Gtk.ResponseType.NO:
            return True
        return False

    def _on_delete_event(self, _widget, _event) -> bool:
        """Handle window close button click."""
        if not self._confirm_discard_changes():
            return True  # Block close
        return False  # Allow close

    def _request_quit(self):
        """Handle Ctrl+Q quit shortcut."""
        if not self._confirm_discard_changes():
            return
        self.quit()

    # -- File operations: Open, Save, Save As --------------------------------

    def _save_file(self) -> bool:
        """Save buffer content to current_file. Triggers Save As if no file is set."""
        if not self.current_file:
            return self._save_file_as()

        start = self.source_buffer.get_start_iter()
        end = self.source_buffer.get_end_iter()
        text = self.source_buffer.get_text(start, end, True)
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(text)
            self._file_mtime = os.path.getmtime(self.current_file)
            self._set_dirty(False)
            self._update_title()
            self._refresh_rendered_view()
            return True
        except OSError as e:
            self._show_error(f"Failed to save file: {e}")
            return False

    def _save_file_as(self) -> bool:
        """Prompt user for a destination file and save."""
        dialog = Gtk.FileChooserDialog(
            title="Save Markdown File As",
            parent=self.win,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.set_do_overwrite_confirmation(True)
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Save", Gtk.ResponseType.OK,
        )
        md_filter = Gtk.FileFilter()
        md_filter.set_name("Markdown files (*.md)")
        md_filter.add_pattern("*.md")
        md_filter.add_pattern("*.markdown")
        dialog.add_filter(md_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        if self.current_file:
            dialog.set_current_folder(os.path.dirname(self.current_file))
            dialog.set_current_name(os.path.basename(self.current_file))
        else:
            dialog.set_current_name("untitled.md")

        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()

        if not chosen:
            return False

        if not os.path.splitext(chosen)[1]:
            chosen += ".md"

        self.current_file = chosen
        success = self._save_file()
        if success:
            self._start_file_monitor()
            self._update_title()
        return success

    def _open_file_dialog(self):
        if not self._confirm_discard_changes():
            return

        dialog = Gtk.FileChooserDialog(
            title="Open Markdown File",
            parent=self.win,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Open", Gtk.ResponseType.OK,
        )
        md_filter = Gtk.FileFilter()
        md_filter.set_name("Markdown files")
        md_filter.add_pattern("*.md")
        md_filter.add_pattern("*.markdown")
        md_filter.add_pattern("*.mdown")
        md_filter.add_pattern("*.mkd")
        md_filter.add_mime_type("text/markdown")
        md_filter.add_mime_type("text/x-markdown")
        dialog.add_filter(md_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        if self.current_file:
            dialog.set_current_folder(os.path.dirname(self.current_file))

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.current_file = dialog.get_filename()
            self._load_file()
        dialog.destroy()

    def _load_file(self):
        """Read the current file and update both views."""
        if not self.current_file or not os.path.isfile(self.current_file):
            return
        try:
            with open(self.current_file, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            self._show_error(f"Failed to read file: {e}")
            return

        self._file_mtime = os.path.getmtime(self.current_file)
        self._set_dirty(False)
        self._update_title()

        # Rendered view
        html_content = render_markdown(text, self.dark_mode)
        base_uri = GLib.filename_to_uri(os.path.dirname(self.current_file), None) + "/"
        self.webview.load_html(html_content, base_uri)

        # Source view without triggering dirty status
        self._loading = True
        try:
            self.source_buffer.begin_not_undoable_action()
            self.source_buffer.set_text(text)
            self.source_buffer.end_not_undoable_action()
        finally:
            self._loading = False

        self._update_stats()

        # Start file monitor
        self._start_file_monitor()

    def _load_clipboard_content(self, text: str):
        """Populate editor with clipboard text and switch to source view."""
        self.current_file = None
        self._set_dirty(True)

        # Rendered view
        html_content = render_markdown(text, self.dark_mode)
        base_uri = GLib.filename_to_uri(os.getcwd(), None) + "/"
        self.webview.load_html(html_content, base_uri)

        # Source view
        self._loading = True
        try:
            self.source_buffer.begin_not_undoable_action()
            self.source_buffer.set_text(text)
            self.source_buffer.end_not_undoable_action()
        finally:
            self._loading = False

        self._set_dirty(True)
        self._update_title()
        self._update_stats()

        # Start in editor mode
        self.stack.set_visible_child_name("source")

    def _show_error(self, message: str):
        dialog = Gtk.MessageDialog(
            parent=self.win,
            flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()

    # -- Drag and drop ------------------------------------------------------

    def _on_drag_data(self, _widget, _context, _x, _y, data, _info, _time):
        uris = data.get_uris()
        if uris:
            path = GLib.filename_from_uri(uris[0])[0]
            if path and os.path.isfile(path):
                if not self._confirm_discard_changes():
                    return
                self.current_file = path
                self._load_file()

    # -- File monitor -------------------------------------------------------

    def _start_file_monitor(self):
        if self._file_monitor_id:
            GLib.source_remove(self._file_monitor_id)
            self._file_monitor_id = None
        if self.current_file and os.path.isfile(self.current_file):
            try:
                self._file_mtime = os.path.getmtime(self.current_file)
            except OSError:
                return
            self._file_monitor_id = GLib.timeout_add(2000, self._check_file_changed)

    def _check_file_changed(self) -> bool:
        if not self.current_file:
            return False
        if self._dirty:
            # Don't overwrite unsaved user edits with disk changes
            return True
        try:
            mtime = os.path.getmtime(self.current_file)
            if mtime != self._file_mtime:
                self._file_mtime = mtime
                self._load_file()
        except OSError:
            pass
        return True  # keep polling


# ---------------------------------------------------------------------------
# Clipboard reading helper
# ---------------------------------------------------------------------------
def _read_system_clipboard() -> str:
    """Read text from the system clipboard, trying Wayland-native first."""
    # Wayland: wl-paste
    for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    argv = sys.argv[:]
    clipboard_mode = "--clipboard" in argv
    if clipboard_mode:
        argv.remove("--clipboard")

    app = MarkdownViewerApp()
    if clipboard_mode:
        app._clipboard_mode = True
        app._clipboard_text = _read_system_clipboard()
    app.run(argv)


if __name__ == "__main__":
    main()
