"""Hardened Markdown and technical-file rendering engine for Markveil."""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import secrets
import tomllib
import xml.etree.ElementTree as etree

import markdown
from markdown.extensions import Extension, toc
from markdown.inlinepatterns import InlineProcessor, SimpleTagInlineProcessor
from markdown.treeprocessors import Treeprocessor
from markdown.util import AtomicString
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
import yaml

from mdviewer.sanitizer import sanitize_html

try:
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib
except Exception:
    GLib = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Theme and client JS imports (with minimal built-in fallbacks)
# ---------------------------------------------------------------------------
_DEFAULT_FALLBACK_CSS = """\
:root {
    --bg-color: #ffffff;
    --text-color: #0f172a;
    --muted-color: #64748b;
    --border-color: #e2e8f0;
    --link-color: #2563eb;
    --inline-code-bg: #f1f5f9;
    --pre-bg: #0f172a;
    --pre-color: #f8fafc;
}
body.dark {
    --bg-color: #0d1117;
    --text-color: #e6edf3;
    --muted-color: #8b949e;
    --border-color: #30363d;
    --link-color: #58a6ff;
    --inline-code-bg: #161b22;
    --pre-bg: #161b22;
    --pre-color: #e6edf3;
}
body {
    background: var(--bg-color);
    color: var(--text-color);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.65;
    margin: 0;
    padding: 2rem;
}
.markdown-container { max-width: 860px; margin: 0 auto; }
a { color: var(--link-color); }
code { background: var(--inline-code-bg); padding: 0.15em 0.35em; border-radius: 4px; }
pre code { background: transparent; padding: 0; }
.task-list-item { list-style: none; margin-left: -1.4em; }
.task-checkbox { margin-right: 0.5em; }
.blocked-remote-img {
    display: inline-block;
    border: 1px dashed var(--border-color);
    padding: 0.25rem 0.5rem;
    color: var(--muted-color);
}
[data-changed="true"] {
    border-left: 3px solid #22c55e;
    padding-left: 0.65rem;
}
.file-status-badge {
    display: inline-block;
    padding: 0.25rem 0.65rem;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 1rem;
}
.status-valid { background: rgba(34, 197, 94, 0.14); color: #16a34a; }
.status-invalid { background: rgba(239, 68, 68, 0.14); color: #dc2626; }
.diff-line { font-family: monospace; white-space: pre-wrap; padding: 0.05rem 0.5rem; }
.diff-add { background: rgba(34, 197, 94, 0.14); }
.diff-del { background: rgba(239, 68, 68, 0.14); }
.diff-hunk-header { color: var(--muted-color); font-family: monospace; font-weight: 600; }
"""

_DEFAULT_FALLBACK_JS = """\
(function () {
    function init() {
        if (typeof renderMathInElement === "function") {
            document.querySelectorAll(".katex-display-math, .katex-inline-math").forEach(function (el) {
                if (typeof katex !== "undefined") {
                    var expr = el.getAttribute("data-math") || "";
                    try {
                        katex.render(expr, el, {
                            displayMode: el.classList.contains("katex-display-math"),
                            throwOnError: false
                        });
                    } catch (e) {}
                }
            });
        }
        if (typeof mermaid !== "undefined") {
            try {
                mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
                document.querySelectorAll(".mermaid:not(.rendered)").forEach(function (el, idx) {
                    var src = el.getAttribute("data-source") || el.textContent.trim();
                    mermaid.render("mermaid-chart-" + idx, src).then(function (res) {
                        el.innerHTML = res.svg;
                        el.classList.add("rendered");
                    }).catch(function () {});
                });
            } catch (e) {}
        }
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
"""

try:
    from mdviewer.themes import (
        get_bg_hex as _theme_get_bg_hex,
        get_document_css as _theme_get_document_css,
        get_pygments_style as _theme_get_pygments_style,
        is_dark_theme as _theme_is_dark_theme,
        resolve_theme_id as _theme_resolve_theme_id,
    )
except ImportError:
    _theme_get_bg_hex = None
    _theme_get_document_css = None
    _theme_get_pygments_style = None
    _theme_is_dark_theme = None
    _theme_resolve_theme_id = None

try:
    from mdviewer.client_js import get_client_js as _client_get_js
except ImportError:
    _client_get_js = None


def _resolve_theme_and_dark(theme: str, dark: bool | None) -> tuple[str, bool]:
    system_dark = bool(dark) if dark is not None else False
    if _theme_resolve_theme_id is not None:
        try:
            resolved_theme = str(_theme_resolve_theme_id(theme, system_dark=system_dark))
        except TypeError:
            resolved_theme = str(_theme_resolve_theme_id(theme, system_dark))
        except Exception:
            resolved_theme = "obsidian" if system_dark else "paper"
    else:
        if theme.lower() == "auto":
            resolved_theme = "obsidian" if system_dark else "paper"
        else:
            resolved_theme = theme

    if dark is not None:
        return resolved_theme, dark
    if _theme_is_dark_theme is not None:
        try:
            return resolved_theme, bool(_theme_is_dark_theme(resolved_theme))
        except Exception:
            pass
    return resolved_theme, resolved_theme.lower() in ("obsidian", "nordic", "dark")


def _get_pygments_style(resolved_theme: str, dark: bool) -> str:
    if _theme_get_pygments_style is not None:
        try:
            return str(_theme_get_pygments_style(resolved_theme))
        except TypeError:
            return str(_theme_get_pygments_style(resolved_theme, dark))
        except Exception:
            pass
    return "github-dark" if dark else "friendly"


def _get_bg_hex(resolved_theme: str, dark: bool) -> str:
    if _theme_get_bg_hex is not None:
        try:
            return str(_theme_get_bg_hex(resolved_theme))
        except TypeError:
            return str(_theme_get_bg_hex(resolved_theme, dark))
        except Exception:
            pass
    return "#0d1117" if dark else "#ffffff"


def _get_document_css(resolved_theme: str, dark: bool) -> str:
    if _theme_get_document_css is not None:
        try:
            return str(_theme_get_document_css(resolved_theme))
        except TypeError:
            return str(_theme_get_document_css(resolved_theme, dark))
        except Exception:
            pass
    return _DEFAULT_FALLBACK_CSS


def _get_client_js(
    resolved_theme: str,
    dark: bool,
    *,
    vim_enabled: bool = True,
    initial_scroll_ratio: float = 0.0,
    initial_section: str | None = None,
    follow_changed: bool = False,
) -> str:
    if _client_get_js is not None:
        try:
            return str(
                _client_get_js(
                    vim_enabled=vim_enabled,
                    initial_scroll_ratio=initial_scroll_ratio,
                    initial_section=initial_section,
                    follow_changed=follow_changed,
                    theme_id=resolved_theme,
                )
            )
        except TypeError:
            try:
                return str(_client_get_js(dark=dark))
            except TypeError:
                return str(_client_get_js())
        except Exception:
            pass
    return _DEFAULT_FALLBACK_JS


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class HeadingItem:
    level: int
    text: str
    slug: str
    line: int


@dataclass(slots=True)
class RenderResult:
    html: str
    headings: list[HeadingItem]
    front_matter: dict | None
    blocked_remote_images: int
    nonce: str
    file_kind: str


# ---------------------------------------------------------------------------
# Vendor asset discovery
# ---------------------------------------------------------------------------
def _find_vendor_dir() -> Path:
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir.parent / "assets" / "vendor",
        pkg_dir / "assets" / "vendor",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


ASSETS_DIR = _find_vendor_dir()
KATEX_CSS_PATH = ASSETS_DIR / "katex" / "katex.min.css"
KATEX_JS_PATH = ASSETS_DIR / "katex" / "katex.min.js"
KATEX_AUTO_PATH = ASSETS_DIR / "katex" / "contrib" / "auto-render.min.js"
MERMAID_JS_PATH = ASSETS_DIR / "mermaid" / "mermaid.min.js"


def _path_to_uri(path: Path) -> str:
    resolved = path.resolve()
    if GLib is not None:
        try:
            return GLib.filename_to_uri(str(resolved), None)
        except Exception:
            pass
    return resolved.as_uri()


# ---------------------------------------------------------------------------
# Pygments CustomHtmlFormatter
# ---------------------------------------------------------------------------
class CustomHtmlFormatter(HtmlFormatter):
    """Custom Pygments HTML formatter that safely escapes language tags on code containers."""

    def __init__(self, lang_str: str = "", **options):
        super().__init__(**options)
        self.raw_lang = lang_str.removeprefix("language-") if lang_str else ""
        self.lang_str = lang_str

    def _wrap_div(self, inner):
        cls = html.escape((self.cssclass + " " + self.lang_str).strip(), quote=True)
        data_attr = (
            f' data-lang="{html.escape(self.raw_lang, quote=True)}"' if self.raw_lang else ""
        )
        yield 0, f'<div class="{cls}"{data_attr}>'
        yield from inner
        yield 0, "</div>\n"


# ---------------------------------------------------------------------------
# Front-matter & GitHub Alerts
# ---------------------------------------------------------------------------
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|$)", re.DOTALL)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_front_matter_with_offset(text: str) -> tuple[dict | None, str, int]:
    """Extract YAML front-matter, returning ``(meta, body, body_line_offset)``."""
    normalized = _normalize_newlines(text)
    match = _FRONT_MATTER_RE.match(normalized)
    if not match:
        return None, normalized, 0

    raw_yaml = match.group(1)
    body = normalized[match.end() :]
    line_offset = normalized[: match.end()].count("\n")

    try:
        data = yaml.safe_load(raw_yaml)
        if isinstance(data, dict):
            return data, body, line_offset
    except Exception:
        # Fallback for simple unquoted key: value lines when YAML has minor quirks
        meta: dict[str, str] = {}
        for line in raw_yaml.splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, v = line.split(":", 1)
                if k.strip():
                    meta[k.strip()] = v.strip()
        if meta:
            return meta, body, line_offset

    return None, normalized, 0


def parse_front_matter(text: str) -> tuple[dict | None, str]:
    """Extract and parse YAML front-matter from document head if present."""
    meta, body, _ = parse_front_matter_with_offset(text)
    return meta, body


def render_front_matter_html(meta: dict | None) -> str:
    """Format parsed front-matter metadata into a collapsible escaped card."""
    if not meta:
        return ""

    title = meta.get("title")
    tags = meta.get("tags") or meta.get("categories") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.strip("[]").split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = [tags]

    rows: list[str] = []
    for k, v in meta.items():
        if k in ("title", "tags", "categories"):
            continue
        if isinstance(v, list):
            val_str = ", ".join(html.escape(str(item), quote=True) for item in v)
        else:
            val_str = html.escape(str(v), quote=True)
        k_str = html.escape(str(k), quote=True)
        rows.append(f"<tr><th>{k_str}</th><td>{val_str}</td></tr>")

    tag_pills = "".join(
        f'<span class="front-matter-tag">{html.escape(str(t), quote=True)}</span>'
        for t in tags
    )
    tag_html = f'<div class="front-matter-tags">{tag_pills}</div>' if tag_pills else ""
    title_html = (
        f'<span class="front-matter-doc-title">{html.escape(str(title), quote=True)}</span>'
        if title is not None
        else ""
    )
    table_html = (
        f'<table class="front-matter-table"><tbody>{"".join(rows)}</tbody></table>'
        if rows
        else ""
    )

    return (
        '<details class="front-matter-card">\n'
        '  <summary class="front-matter-summary">\n'
        '    <span class="front-matter-badge">\n'
        '      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">\n'
        '        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>\n'
        "      </svg>\n"
        "      Metadata\n"
        "    </span>\n"
        f"    {title_html}\n"
        "  </summary>\n"
        '  <div class="front-matter-content">\n'
        f"    {tag_html}\n"
        f"    {table_html}\n"
        "  </div>\n"
        "</details>\n"
    )


_ALERT_RE = re.compile(
    r"^(> ?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*\n(?:> ?.*(?:\n|$))+)",
    re.MULTILINE | re.IGNORECASE,
)


def transform_github_alerts(text: str) -> str:
    """Transform GitHub-style blockquote alerts (``> [!NOTE]``) into admonition blocks."""

    def _repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        alert_type = match.group(2).lower()
        lines = raw.split("\n")
        content_lines: list[str] = []
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

    return _ALERT_RE.sub(_repl, text)


# ---------------------------------------------------------------------------
# Custom Python-Markdown Extensions (Strikethrough, Task Lists, Bare URLs)
# ---------------------------------------------------------------------------
_TASK_LINE_RE = re.compile(
    r"^(\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+)\[([ xX])\]((?:\s+.*)?)$"
)
_TASK_CONTENT_PREFIX_RE = re.compile(r"^\[([ xX])\](?:\s+(.*))?$", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"^([ ]{0,3})(`{3,}|~{3,})([^\n]*)$")


def _is_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    stripped = line.rstrip("\r\n")
    m = re.match(rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$", stripped)
    return m is not None


def _is_fence_open(line: str) -> tuple[str, int, str] | None:
    stripped = line.rstrip("\r\n")
    m = _FENCE_OPEN_RE.match(stripped)
    if not m:
        return None
    fence = m.group(2)
    info = m.group(3).strip()
    # CommonMark: backtick info strings cannot contain backticks.
    if fence[0] == "`" and "`" in info:
        return None
    return (fence[0], len(fence), info)


def _scan_task_source_lines(body: str, line_offset: int) -> list[int]:
    """Return exact 1-based original source line numbers for GFM task list items."""
    task_lines: list[int] = []
    fence_state: tuple[str, int] | None = None

    for idx, line in enumerate(body.splitlines(), start=1):
        if fence_state is not None:
            if _is_fence_close(line, fence_state[0], fence_state[1]):
                fence_state = None
            continue

        opened = _is_fence_open(line)
        if opened is not None:
            fence_state = (opened[0], opened[1])
            continue

        if _TASK_LINE_RE.match(line):
            task_lines.append(line_offset + idx)

    return task_lines


def toggle_task_checkbox_in_text(
    text: str,
    task_index: int,
    line_hint: int | None,
    checked: bool,
) -> str:
    """Toggle a GFM task checkbox in Markdown source text, returning updated text."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    new_mark = "x" if checked else " "

    def _toggle_line(raw_line: str) -> str | None:
        line_ending = ""
        core = raw_line
        if core.endswith("\r\n"):
            line_ending = "\r\n"
            core = core[:-2]
        elif core.endswith("\n") or core.endswith("\r"):
            line_ending = core[-1]
            core = core[:-1]

        m = _TASK_LINE_RE.match(core)
        if not m:
            return None
        return f"{m.group(1)}[{new_mark}]{m.group(3)}{line_ending}"

    # Determine front-matter and fenced code line ranges to avoid mutating code examples.
    _, body, line_offset = parse_front_matter_with_offset(text)
    fenced_lines: set[int] = set()
    fence_state: tuple[str, int] | None = None
    for idx, line in enumerate(body.splitlines(), start=1):
        orig_line = line_offset + idx
        if fence_state is not None:
            fenced_lines.add(orig_line)
            if _is_fence_close(line, fence_state[0], fence_state[1]):
                fence_state = None
            continue
        opened = _is_fence_open(line)
        if opened is not None:
            fenced_lines.add(orig_line)
            fence_state = (opened[0], opened[1])

    if line_hint is not None and 1 <= line_hint <= len(lines):
        if line_hint > line_offset and line_hint not in fenced_lines:
            updated = _toggle_line(lines[line_hint - 1])
            if updated is not None:
                lines[line_hint - 1] = updated
                return "".join(lines)

    # Fallback: locate by 0-based task_index outside front-matter & code fences.
    if task_index < 0:
        return text

    seen = 0
    for idx in range(line_offset, len(lines)):
        orig_line = idx + 1
        if orig_line in fenced_lines:
            continue
        updated = _toggle_line(lines[idx])
        if updated is not None:
            if seen == task_index:
                lines[idx] = updated
                return "".join(lines)
            seen += 1

    return text


class _TaskListTreeprocessor(Treeprocessor):
    """Convert ``- [ ]`` / ``- [x]`` list items into interactive task-list checkboxes."""

    def __init__(self, md: markdown.Markdown, source_lines: list[int]) -> None:
        super().__init__(md)
        self.source_lines = source_lines

    def run(self, root: etree.Element) -> etree.Element | None:
        task_index = 0
        for li in root.iter("li"):
            target_el = self._find_checkbox_holder(li)
            if target_el is None or not target_el.text:
                continue

            m = _TASK_CONTENT_PREFIX_RE.match(target_el.text)
            if not m:
                continue

            is_checked = m.group(1).lower() == "x"
            remainder = m.group(2) or ""
            had_children = len(target_el) > 0

            existing_li_class = li.get("class", "").strip()
            li_classes = existing_li_class.split() if existing_li_class else []
            if "task-list-item" not in li_classes:
                li_classes.append("task-list-item")
            li.set("class", " ".join(li_classes))

            attrs: dict[str, str] = {
                "type": "checkbox",
                "class": "task-checkbox",
                "data-task-index": str(task_index),
            }
            if task_index < len(self.source_lines):
                attrs["data-source-line"] = str(self.source_lines[task_index])
            if is_checked:
                attrs["checked"] = "checked"

            checkbox = etree.Element("input", attrs)
            if remainder:
                checkbox.tail = " " + remainder
            elif had_children:
                checkbox.tail = " "
            else:
                checkbox.tail = ""
            target_el.text = ""
            target_el.insert(0, checkbox)
            task_index += 1
        return None

    @staticmethod
    def _find_checkbox_holder(li: etree.Element) -> etree.Element | None:
        if li.text and _TASK_CONTENT_PREFIX_RE.match(li.text.lstrip("\n")):
            if li.text.startswith("\n"):
                li.text = li.text.lstrip("\n")
            return li
        if len(li) > 0 and li[0].tag == "p" and li[0].text:
            if _TASK_CONTENT_PREFIX_RE.match(li[0].text):
                return li[0]
        return None


class TaskListExtension(Extension):
    """Python-Markdown extension for GFM task lists with 1-based source line mapping."""

    def __init__(self, source_lines: list[int] | None = None, **kwargs) -> None:
        self.source_lines = source_lines or []
        super().__init__(**kwargs)

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        md.treeprocessors.register(
            _TaskListTreeprocessor(md, self.source_lines),
            "gfm_task_list",
            15,
        )


class StrikethroughExtension(Extension):
    """Python-Markdown extension for ``~~strikethrough~~``."""

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        md.inlinePatterns.register(
            SimpleTagInlineProcessor(r"(~{2})(?!~)(.+?)(?<!~)\1", "del"),
            "strikethrough",
            65,
        )


class _BareUrlInlineProcessor(InlineProcessor):
    """Turn bare ``http://`` / ``https://`` URLs into ``<a>`` links outside code/links."""

    def handleMatch(self, m: re.Match[str], data: str):
        url = m.group(1)
        trailing = ""
        while url and url[-1] in ".,;:!?":
            trailing = url[-1] + trailing
            url = url[:-1]
        while url.endswith(")") and url.count(")") > url.count("("):
            trailing = ")" + trailing
            url = url[:-1]
        while url and url[-1] in "]}'\"":
            trailing = url[-1] + trailing
            url = url[:-1]

        if not url or url in ("http://", "https://"):
            return None, None, None

        el = etree.Element("a")
        el.set("href", url)
        el.text = AtomicString(url)
        end = m.end(1) - len(trailing)
        return el, m.start(1), end


class _UnwrapNestedLinksTreeprocessor(Treeprocessor):
    """Prevent nested ``<a>`` elements when a bare URL appears inside link label text."""

    def run(self, root: etree.Element) -> etree.Element | None:
        self._walk(root, inside_anchor=False)
        return None

    def _walk(self, parent: etree.Element, inside_anchor: bool) -> None:
        idx = 0
        while idx < len(parent):
            child = parent[idx]
            is_anchor = child.tag == "a"
            if inside_anchor and is_anchor:
                # Flatten inner <a> into parent's text/tail flow.
                inner_text = "".join(child.itertext())
                tail = child.tail or ""
                combined = inner_text + tail
                if idx == 0:
                    parent.text = (parent.text or "") + combined
                else:
                    prev = parent[idx - 1]
                    prev.tail = (prev.tail or "") + combined
                parent.remove(child)
                continue
            self._walk(child, inside_anchor or is_anchor)
            idx += 1


class BareUrlExtension(Extension):
    """Python-Markdown extension for bare ``http(s)://`` autolinks."""

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        md.inlinePatterns.register(
            _BareUrlInlineProcessor(r"(?<![A-Za-z0-9_/@])(https?://[^\s<>\"'`]+)", md),
            "bare_url",
            75,
        )
        md.treeprocessors.register(
            _UnwrapNestedLinksTreeprocessor(md),
            "unwrap_nested_links",
            19,
        )


# ---------------------------------------------------------------------------
# Code-first preprocessing (fences -> inline code -> math)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _PreprocessContext:
    text: str
    placeholders: dict[str, str]
    block_line_ranges: dict[str, tuple[int, int]]
    token_prefix: str


def _make_mermaid_container(code: str, changed: bool = False) -> str:
    escaped = html.escape(code.strip(), quote=True)
    changed_attr = ' data-changed="true"' if changed else ""
    return (
        f'<div class="mermaid-container"{changed_attr}>\n'
        '  <div class="mermaid-header">\n'
        '    <span class="mermaid-badge">\n'
        '      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">\n'
        '        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>\n'
        '        <polyline points="2 17 12 22 22 17"></polyline>\n'
        '        <polyline points="2 12 12 17 22 12"></polyline>\n'
        "      </svg>\n"
        "      Diagram\n"
        "    </span>\n"
        '    <span class="mermaid-type">Mermaid</span>\n'
        "  </div>\n"
        '  <div class="mermaid-viewport">\n'
        f'    <div class="mermaid" data-source="{escaped}">{escaped}</div>\n'
        "  </div>\n"
        "</div>"
    )


def _make_math_block_container(code: str, changed: bool = False) -> str:
    escaped = html.escape(code.strip(), quote=True)
    changed_attr = ' data-changed="true"' if changed else ""
    return (
        f'<div class="katex-block"{changed_attr}>\n'
        f'  <div class="katex-display-math" data-math="{escaped}">$${escaped}$$</div>\n'
        "</div>"
    )


def _make_math_inline_container(code: str) -> str:
    escaped = html.escape(code.strip(), quote=True)
    return f'<span class="katex-inline-math" data-math="{escaped}">${escaped}$</span>'


def _preprocess_code_first(
    body: str,
    line_offset: int = 0,
    changed_lines: set[int] | None = None,
) -> _PreprocessContext:
    """Protect 3+ backtick/tilde fences first, then inline code, then math."""
    token_prefix = f"XMDPX{secrets.token_hex(4).upper()}"
    placeholders: dict[str, str] = {}
    protected_code_blocks: dict[str, str] = {}
    block_line_ranges: dict[str, tuple[int, int]] = {}
    counter = 0

    def next_token(kind: str) -> str:
        nonlocal counter
        counter += 1
        return f"{token_prefix}{kind}{counter}X"

    def is_changed(start_line: int, end_line: int) -> bool:
        if not changed_lines:
            return False
        return any(ln in changed_lines for ln in range(start_line, end_line + 1))

    # 1. Line-based fence scanner: protects 3+ backtick/tilde fences (incl. 4-backtick wrappers).
    lines = body.splitlines(keepends=True)
    out_parts: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        opened = _is_fence_open(lines[i])
        if opened is None:
            out_parts.append(lines[i])
            i += 1
            continue

        fence_char, fence_len, info = opened
        start_idx = i
        i += 1
        inner_lines: list[str] = []
        while i < n:
            if _is_fence_close(lines[i], fence_char, fence_len):
                i += 1
                break
            inner_lines.append(lines[i])
            i += 1
        end_idx = i - 1

        start_line = line_offset + start_idx + 1
        end_line = line_offset + end_idx + 1
        lang = info.split()[0].lower() if info else ""
        inner_text = "".join(inner_lines)
        raw_fence = "".join(lines[start_idx : end_idx + 1])

        if lang == "mermaid":
            tok = next_token("MERMAID")
            placeholders[tok] = _make_mermaid_container(
                inner_text, changed=is_changed(start_line, end_line)
            )
            block_line_ranges[tok] = (start_line, end_line)
            out_parts.append(f"\n\n{tok}\n\n")
        elif lang in ("math", "katex", "latex"):
            tok = next_token("MATHBLOCK")
            placeholders[tok] = _make_math_block_container(
                inner_text, changed=is_changed(start_line, end_line)
            )
            block_line_ranges[tok] = (start_line, end_line)
            out_parts.append(f"\n\n{tok}\n\n")
        else:
            tok = next_token("CODEBLOCK")
            protected_code_blocks[tok] = raw_fence
            block_line_ranges[tok] = (start_line, end_line)
            out_parts.append(tok)

    text = "".join(out_parts)

    # 2. Transform GitHub alerts while fenced code blocks are protected.
    text = transform_github_alerts(text)

    # 3. Protect inline code spans `...` before scanning for $...$ / \(...\) / $$...$$.
    protected_inline: dict[str, str] = {}

    def protect_inline(m: re.Match[str]) -> str:
        tok = next_token("INLINE")
        protected_inline[tok] = m.group(0)
        return tok

    text = re.sub(r"(?<!\\)(`+)(.+?)(?<!`)\1(?!`)", protect_inline, text)

    # 4. Extract display math blocks: $$ ... $$ and \[ ... \]
    def repl_display_math(m: re.Match[str]) -> str:
        tok = next_token("MATHBLOCK")
        placeholders[tok] = _make_math_block_container(m.group(1))
        return f"\n\n{tok}\n\n"

    text = re.sub(r"(?<!\\)\$\$\n?([\s\S]*?)\n?(?<!\\)\$\$", repl_display_math, text)
    text = re.sub(r"(?<!\\)\\\[\n?([\s\S]*?)\n?(?<!\\)\\\]", repl_display_math, text)

    # 5. Extract inline math: $...$ and \(...\)
    def repl_inline_math(m: re.Match[str]) -> str:
        tok = next_token("MATHINLINE")
        placeholders[tok] = _make_math_inline_container(m.group(1))
        return tok

    text = re.sub(r"(?<!\\)\$(?!\s)([^\$\n]+?)(?<!\s)(?<!\\)\$(?!\d)", repl_inline_math, text)
    text = re.sub(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", repl_inline_math, text)

    # 6. Restore protected inline code and fenced code blocks for Markdown parsing.
    for tok, original in protected_inline.items():
        text = text.replace(tok, original)
    for tok, original in protected_code_blocks.items():
        text = text.replace(tok, original)

    return _PreprocessContext(
        text=text,
        placeholders=placeholders,
        block_line_ranges=block_line_ranges,
        token_prefix=token_prefix,
    )


def preprocess_markdown(text: str) -> tuple[str, dict[str, str]]:
    """Backward-compatible wrapper returning preprocessed text and placeholder map."""
    ctx = _preprocess_code_first(text, line_offset=0, changed_lines=None)
    return ctx.text, ctx.placeholders


# ---------------------------------------------------------------------------
# Heading Extraction (synced with markdown.extensions.toc slugify)
# ---------------------------------------------------------------------------
_ATX_HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+(.*))?$")
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_TAG_RE = re.compile(r"<[^>]+>")


def _strip_heading_markdown(raw: str) -> str:
    text = re.sub(r"[ \t]+#+\s*$", "", raw).strip()
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _INLINE_TAG_RE.sub("", text)
    text = text.replace("`", "").replace("~~", "")
    text = re.sub(r"(\*\*|__|\*|_)", "", text)
    return text.strip()


def extract_headings(text: str) -> list[HeadingItem]:
    """Extract headings with 1-based source line numbers and ``toc``-matching slugs."""
    _, body, line_offset = parse_front_matter_with_offset(text)
    headings: list[HeadingItem] = []
    seen_slugs: set[str] = set()
    fence_state: tuple[str, int] | None = None

    for idx, line in enumerate(body.splitlines(), start=1):
        if fence_state is not None:
            if _is_fence_close(line, fence_state[0], fence_state[1]):
                fence_state = None
            continue

        opened = _is_fence_open(line)
        if opened is not None:
            fence_state = (opened[0], opened[1])
            continue

        m = _ATX_HEADING_RE.match(line)
        if not m:
            continue

        level = len(m.group(1))
        raw_title = (m.group(2) or "").strip()
        if not raw_title or set(raw_title) == {"#"}:
            continue

        plain_title = _strip_heading_markdown(raw_title)
        base_slug = toc.slugify(plain_title, "-")
        unique_slug = toc.unique(base_slug, seen_slugs)
        seen_slugs.add(unique_slug)
        headings.append(
            HeadingItem(
                level=level,
                text=plain_title,
                slug=unique_slug,
                line=line_offset + idx,
            )
        )

    return headings


# ---------------------------------------------------------------------------
# Watch Mode change markers
# ---------------------------------------------------------------------------
def _mark_changed_elements(
    html_body: str,
    headings: list[HeadingItem],
    changed_lines: set[int] | None,
    body_text: str = "",
    line_offset: int = 0,
    already_covered_lines: set[int] | None = None,
) -> str:
    if not changed_lines:
        return html_body

    matched_lines: set[int] = set(already_covered_lines or ())

    # 1. Mark headings whose 1-based source line is in changed_lines.
    changed_slugs: set[str] = set()
    for h in headings:
        if h.line in changed_lines:
            changed_slugs.add(h.slug)
            matched_lines.add(h.line)

    for slug in changed_slugs:
        escaped_slug = re.escape(html.escape(slug, quote=True))
        html_body = re.sub(
            rf'(<h[1-6]\b[^>]*\bid="{escaped_slug}"[^>]*)(>)',
            r'\1 data-changed="true"\2',
            html_body,
            count=1,
        )

    # 2. Mark task-list <li> items whose <input data-source-line="L"> matches changed_lines.
    def _mark_task_li(m: re.Match[str]) -> str:
        li_open, inner = m.group(1), m.group(2)
        if 'data-changed="true"' in li_open:
            return m.group(0)
        line_match = re.search(r'data-source-line="(\d+)"', inner)
        if line_match:
            line_num = int(line_match.group(1))
            if line_num in changed_lines:
                matched_lines.add(line_num)
                return li_open[:-1] + ' data-changed="true">' + inner
        return m.group(0)

    html_body = re.sub(
        r'(<li\b[^>]*\bclass="[^"]*\btask-list-item\b[^"]*"[^>]*>)([\s\S]*?</li>)',
        _mark_task_li,
        html_body,
    )

    # 3. Mark matching paragraph blocks for remaining changed lines.
    remaining_lines = sorted(ln for ln in changed_lines if ln not in matched_lines)
    if body_text and remaining_lines:
        body_lines = body_text.splitlines()
        snippets: list[str] = []
        for ln in remaining_lines:
            rel_idx = ln - line_offset - 1
            if 0 <= rel_idx < len(body_lines):
                snippet = _strip_heading_markdown(body_lines[rel_idx]).strip()
                if len(snippet) >= 3:
                    snippets.append(html.escape(snippet, quote=False))

        if snippets:
            def _mark_para(m: re.Match[str]) -> str:
                tag_open, content, tag_close = m.group(1), m.group(2), m.group(3)
                if 'data-changed="true"' in tag_open:
                    return m.group(0)
                plain = _INLINE_TAG_RE.sub("", content)
                if any(snip in plain for snip in snippets):
                    return tag_open[:-1] + ' data-changed="true">' + content + tag_close
                return m.group(0)

            html_body = re.sub(
                r"(<p\b[^>]*>)([\s\S]*?)(</p>)",
                _mark_para,
                html_body,
            )

    return html_body


# ---------------------------------------------------------------------------
# Technical File Renderers
# ---------------------------------------------------------------------------
_EXTENSION_KIND_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".mkd": "markdown",
    ".mdx": "markdown",
    ".json": "json",
    ".jsonc": "jsonc",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".diff": "diff",
    ".patch": "diff",
    ".mmd": "mermaid",
    ".mermaid": "mermaid",
    ".txt": "text",
}


def detect_file_kind(file_path: str | None) -> str:
    """Detect rendering file kind from a file path extension."""
    if not file_path:
        return "markdown"
    suffix = Path(file_path).suffix.lower()
    if not suffix:
        return "markdown"
    return _EXTENSION_KIND_MAP.get(suffix, "text")


def _strip_jsonc_comments_and_trailing_commas(text: str) -> str:
    """Strip ``//`` and ``/* */`` comments (and trailing commas) outside JSON string literals."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False

    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
                continue

        out.append(ch)
        i += 1

    # Remove trailing commas before } or ] outside strings.
    cleaned = "".join(out)
    final: list[str] = []
    i = 0
    n = len(cleaned)
    in_string = False
    while i < n:
        ch = cleaned[i]
        if in_string:
            final.append(ch)
            if ch == "\\" and i + 1 < n:
                final.append(cleaned[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            final.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and cleaned[j] in " \t\r\n":
                j += 1
            if j < n and cleaned[j] in ("}", "]"):
                i += 1
                continue
        final.append(ch)
        i += 1
    return "".join(final)


def _render_json_tree_html(value: object, key: str | None = None, depth: int = 0) -> str:
    label_html = (
        f'<span class="json-key">{html.escape(key)}</span>: ' if key is not None else ""
    )
    if isinstance(value, dict):
        open_attr = " open" if depth < 2 else ""
        count = len(value)
        children = "".join(_render_json_tree_html(v, str(k), depth + 1) for k, v in value.items())
        return (
            f'<details class="json-node"{open_attr}>'
            f"<summary>{label_html}<span class=\"json-meta\">Object ({count})</span></summary>"
            f'<div class="json-children">{children}</div>'
            "</details>"
        )
    if isinstance(value, list):
        open_attr = " open" if depth < 2 else ""
        count = len(value)
        children = "".join(
            _render_json_tree_html(item, f"[{idx}]", depth + 1) for idx, item in enumerate(value)
        )
        return (
            f'<details class="json-node"{open_attr}>'
            f"<summary>{label_html}<span class=\"json-meta\">Array ({count})</span></summary>"
            f'<div class="json-children">{children}</div>'
            "</details>"
        )
    if value is None:
        val_html = '<span class="json-null">null</span>'
    elif isinstance(value, bool):
        val_html = f'<span class="json-bool">{str(value).lower()}</span>'
    elif isinstance(value, (int, float)):
        val_html = f'<span class="json-num">{html.escape(str(value))}</span>'
    else:
        val_html = f'<span class="json-str">"{html.escape(str(value))}"</span>'
    return f'<div class="json-leaf">{label_html}{val_html}</div>'


def _highlight_code(text: str, lexer_name: str, pygments_style: str) -> str:
    try:
        lexer = get_lexer_by_name(lexer_name)
    except Exception:
        lexer = get_lexer_by_name("text")
    formatter = CustomHtmlFormatter(
        lang_str=f"language-{lexer_name}",
        cssclass="highlight",
        style=pygments_style,
    )
    return pygments_highlight(text, lexer, formatter)


def _render_json_document(text: str, kind: str, pygments_style: str) -> str:
    label = "JSONC" if kind == "jsonc" else "JSON"
    payload = _strip_jsonc_comments_and_trailing_commas(text) if kind == "jsonc" else text
    tree_html = ""
    try:
        parsed = json.loads(payload)
        badge = f'<div class="file-status-badge validation-badge status-valid valid">Valid {label}</div>'
        tree_html = (
            '<details class="structured-tree json-tree" open>'
            "<summary>Structured Tree</summary>"
            f'<div class="json-tree-root">{_render_json_tree_html(parsed)}</div>'
            "</details>"
        )
    except json.JSONDecodeError as exc:
        err_msg = html.escape(f"{exc.msg} (line {exc.lineno}, col {exc.colno})")
        badge = (
            f'<div class="file-status-badge validation-badge status-invalid invalid">'
            f"Invalid {label}: {err_msg}</div>"
        )

    code_html = _highlight_code(text, "json", pygments_style)
    return f"{badge}\n{tree_html}\n{code_html}"


def _render_yaml_document(text: str, pygments_style: str) -> str:
    try:
        docs = list(yaml.safe_load_all(text))
        badge = (
            '<div class="file-status-badge validation-badge status-valid valid">'
            f"Valid YAML ({len(docs)} doc)</div>"
        )
    except yaml.YAMLError as exc:
        err_msg = html.escape(str(exc))
        badge = (
            '<div class="file-status-badge validation-badge status-invalid invalid">'
            f"Invalid YAML: {err_msg}</div>"
        )
    code_html = _highlight_code(text, "yaml", pygments_style)
    return f"{badge}\n{code_html}"


def _render_toml_document(text: str, pygments_style: str) -> str:
    try:
        tomllib.loads(text)
        badge = '<div class="file-status-badge validation-badge status-valid valid">Valid TOML</div>'
    except tomllib.TOMLDecodeError as exc:
        err_msg = html.escape(str(exc))
        badge = (
            '<div class="file-status-badge validation-badge status-invalid invalid">'
            f"Invalid TOML: {err_msg}</div>"
        )
    code_html = _highlight_code(text, "toml", pygments_style)
    return f"{badge}\n{code_html}"


def _render_diff_document(text: str) -> str:
    additions = 0
    deletions = 0
    line_divs: list[str] = []

    for line in _normalize_newlines(text).splitlines():
        escaped = html.escape(line)
        if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            line_divs.append(f'<div class="diff-line diff-file-header">{escaped}</div>')
        elif line.startswith("@@"):
            line_divs.append(f'<div class="diff-line diff-hunk-header">{escaped}</div>')
        elif line.startswith("+"):
            additions += 1
            line_divs.append(f'<div class="diff-line diff-add">{escaped}</div>')
        elif line.startswith("-"):
            deletions += 1
            line_divs.append(f'<div class="diff-line diff-del">{escaped}</div>')
        else:
            line_divs.append(f'<div class="diff-line diff-ctx">{escaped}</div>')

    stats = (
        '<div class="diff-stats">'
        f'<span class="diff-stat-add">+{additions}</span> '
        f'<span class="diff-stat-del">-{deletions}</span>'
        "</div>"
    )
    return f'<div class="diff-view">{stats}\n' + "\n".join(line_divs) + "\n</div>"


def _render_text_document(text: str, changed_lines: set[int] | None) -> str:
    if not changed_lines:
        return f'<pre class="plain-text-view">{html.escape(text)}</pre>'
    parts: list[str] = ['<div class="plain-text-view">']
    for idx, line in enumerate(_normalize_newlines(text).splitlines(), start=1):
        changed_attr = ' data-changed="true"' if idx in changed_lines else ""
        parts.append(f'<div class="plain-text-line"{changed_attr}>{html.escape(line) or " "}</div>')
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public Rendering Entrypoints
# ---------------------------------------------------------------------------
def _unwrap_block_placeholders(html_body: str, token_prefix: str) -> str:
    pattern = re.compile(
        rf"<p>\s*({re.escape(token_prefix)}(?:MERMAID|MATHBLOCK)\d+X)\s*</p>"
    )
    return pattern.sub(r"\1", html_body)


def _wrap_tables(html_body: str) -> str:
    return re.sub(
        r"(<table>[\s\S]*?</table>)",
        r'<div class="table-wrapper">\1</div>',
        html_body,
    )


def _build_csp(nonce: str, allow_remote_images: bool) -> str:
    img_src = "* file: data: blob:" if allow_remote_images else "'self' file: data: blob:"
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' file:; "
        "font-src 'self' file: data:; "
        f"img-src {img_src}; "
        "connect-src 'none'; "
        "media-src 'none'; "
        "object-src 'none'; "
        "frame-src 'none';"
    )


def _build_vendor_asset_tags(nonce: str) -> str:
    tags: list[str] = []
    if KATEX_CSS_PATH.is_file():
        tags.append(f'<link rel="stylesheet" href="{html.escape(_path_to_uri(KATEX_CSS_PATH), quote=True)}">')
    for js_path in (KATEX_JS_PATH, KATEX_AUTO_PATH, MERMAID_JS_PATH):
        if js_path.is_file():
            uri = html.escape(_path_to_uri(js_path), quote=True)
            tags.append(f'<script nonce="{nonce}" src="{uri}"></script>')
    return "\n".join(tags)


def render_document(
    text: str,
    file_path: str | None = None,
    *,
    file_kind: str | None = None,
    theme: str = "auto",
    dark: bool | None = None,
    allow_remote_images: bool = False,
    hard_breaks: bool = False,
    custom_css: str = "",
    changed_lines: set[int] | None = None,
    body_html_override: str | None = None,
    vim_enabled: bool = True,
    initial_scroll_ratio: float = 0.0,
    initial_section: str | None = None,
    follow_changed: bool = False,
) -> RenderResult:
    """Render Markdown or technical file content into a CSP-hardened HTML5 document."""
    resolved_theme, resolved_dark = _resolve_theme_and_dark(theme, dark)
    pygments_style = _get_pygments_style(resolved_theme, resolved_dark)
    bg_hex = _get_bg_hex(resolved_theme, resolved_dark)
    doc_css = _get_document_css(resolved_theme, resolved_dark)
    client_js = _get_client_js(
        resolved_theme,
        resolved_dark,
        vim_enabled=vim_enabled,
        initial_scroll_ratio=initial_scroll_ratio,
        initial_section=initial_section,
        follow_changed=follow_changed,
    )
    pygments_css = HtmlFormatter(style=pygments_style).get_style_defs(".highlight")

    kind = file_kind or detect_file_kind(file_path)
    nonce = secrets.token_urlsafe(16)
    headings: list[HeadingItem] = []
    front_matter: dict | None = None
    blocked_remote_images = 0

    if body_html_override is not None:
        sanitized_body, blocked_remote_images = sanitize_html(
            body_html_override,
            allow_remote_images=allow_remote_images,
        )
        body_markup = sanitized_body
    elif kind == "markdown":
        meta, body, line_offset = parse_front_matter_with_offset(text)
        front_matter = meta
        headings = extract_headings(text)
        task_source_lines = _scan_task_source_lines(body, line_offset)
        ctx = _preprocess_code_first(body, line_offset=line_offset, changed_lines=changed_lines)

        extensions: list[str | Extension] = [
            "markdown.extensions.fenced_code",
            "markdown.extensions.tables",
            "markdown.extensions.toc",
            "markdown.extensions.sane_lists",
            "markdown.extensions.codehilite",
            "markdown.extensions.admonition",
            "markdown.extensions.def_list",
            "markdown.extensions.footnotes",
            StrikethroughExtension(),
            TaskListExtension(source_lines=task_source_lines),
            BareUrlExtension(),
        ]
        if hard_breaks:
            extensions.append("markdown.extensions.nl2br")

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

        raw_md_html = markdown.markdown(
            ctx.text,
            extensions=extensions,
            extension_configs=extension_configs,
        )
        raw_md_html = _unwrap_block_placeholders(raw_md_html, ctx.token_prefix)

        # Sanitize Markdown HTML BEFORE restoring trusted escaped Mermaid/KaTeX/front-matter.
        sanitized_html, blocked_remote_images = sanitize_html(
            raw_md_html,
            allow_remote_images=allow_remote_images,
        )
        sanitized_html = _wrap_tables(sanitized_html)

        for tok, markup in ctx.placeholders.items():
            sanitized_html = sanitized_html.replace(tok, markup)

        covered_lines: set[int] = set()
        for tok, (start_ln, end_ln) in ctx.block_line_ranges.items():
            if tok in ctx.placeholders:
                covered_lines.update(range(start_ln, end_ln + 1))

        sanitized_html = _mark_changed_elements(
            sanitized_html,
            headings=headings,
            changed_lines=changed_lines,
            body_text=body,
            line_offset=line_offset,
            already_covered_lines=covered_lines,
        )

        fm_html = render_front_matter_html(front_matter)
        if fm_html and changed_lines and line_offset > 0:
            if any(1 <= ln <= line_offset for ln in changed_lines):
                fm_html = fm_html.replace(
                    '<details class="front-matter-card"',
                    '<details class="front-matter-card" data-changed="true"',
                    1,
                )

        body_markup = f"{fm_html}{sanitized_html}"
    elif kind in ("json", "jsonc"):
        body_markup = _render_json_document(text, kind, pygments_style)
    elif kind == "yaml":
        body_markup = _render_yaml_document(text, pygments_style)
    elif kind == "toml":
        body_markup = _render_toml_document(text, pygments_style)
    elif kind == "diff":
        body_markup = _render_diff_document(text)
    elif kind == "mermaid":
        changed = bool(changed_lines)
        body_markup = _make_mermaid_container(text, changed=changed)
    else:
        body_markup = _render_text_document(text, changed_lines)

    safe_custom_css = re.sub(r"</style", r"<\/style", custom_css, flags=re.IGNORECASE)
    safe_client_js = re.sub(r"</script", r"<\/script", client_js, flags=re.IGNORECASE)

    csp = _build_csp(nonce, allow_remote_images=allow_remote_images)
    assets_html = _build_vendor_asset_tags(nonce)
    theme_class = "dark" if resolved_dark else ""
    scheme = "dark" if resolved_dark else "light"
    safe_theme_attr = html.escape(resolved_theme, quote=True)

    full_html = (
        "<!DOCTYPE html>\n"
        f'<html data-theme="{safe_theme_attr}" style="background-color: {bg_hex}; color-scheme: {scheme};">'
        "<head>"
        '<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"{assets_html}\n"
        f"<style>\n{doc_css}\n{pygments_css}\n{safe_custom_css}\n</style>\n"
        "</head>"
        f'<body class="{theme_class}">\n'
        '<div class="markdown-container">\n'
        f"{body_markup}\n"
        "</div>\n"
        f'<script nonce="{nonce}">\n{safe_client_js}\n</script>\n'
        "</body></html>"
    )

    return RenderResult(
        html=full_html,
        headings=headings,
        front_matter=front_matter,
        blocked_remote_images=blocked_remote_images,
        nonce=nonce,
        file_kind=kind,
    )


def render_markdown(text: str, dark: bool = False, **kwargs) -> str:
    """Compatibility wrapper returning rendered HTML string."""
    return render_document(text, dark=dark, **kwargs).html
