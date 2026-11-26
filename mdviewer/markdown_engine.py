"""Hardened Markdown and technical-file rendering engine for Markveil."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
import json
from pathlib import Path
import re
import secrets
import threading
import tomllib
from urllib.parse import quote, urlparse
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


@lru_cache(maxsize=16)
def _get_document_css(resolved_theme: str, dark: bool) -> str:
    if _theme_get_document_css is not None:
        try:
            return str(_theme_get_document_css(resolved_theme))
        except TypeError:
            return str(_theme_get_document_css(resolved_theme, dark))
        except Exception:
            pass
    return _DEFAULT_FALLBACK_CSS


@lru_cache(maxsize=16)
def _get_pygments_css(pygments_style: str) -> str:
    return HtmlFormatter(style=pygments_style).get_style_defs(".highlight")


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


@lru_cache(maxsize=16)
def _path_to_uri(path: Path) -> str:
    resolved = path.resolve()
    if GLib is not None:
        try:
            return GLib.filename_to_uri(str(resolved), None)
        except Exception:
            pass
    return resolved.as_uri()


# ---------------------------------------------------------------------------
# Pygments CustomHtmlFormatter & Line-Anchored Source Formatter
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


class _SourceCodeHtmlFormatter(CustomHtmlFormatter):
    """Pygments HTML formatter emitting ``id="L<n>" data-line="<n>"`` line anchors."""

    def __init__(
        self,
        lang_str: str = "",
        changed_lines: set[int] | None = None,
        **options,
    ):
        super().__init__(lang_str=lang_str, **options)
        self._changed_lines: set[int] = changed_lines or set()

    def _wrap_div(self, inner):
        cls = html.escape(
            (self.cssclass + " mdv-source-view " + self.lang_str).strip(),
            quote=True,
        )
        data_attr = (
            f' data-lang="{html.escape(self.raw_lang, quote=True)}"' if self.raw_lang else ""
        )
        yield 0, f'<div class="{cls}"{data_attr}>'
        yield from inner
        yield 0, "</div>\n"

    def _wrap_line_anchors(self, source):
        line_no = 0
        changed = self._changed_lines
        for t, line in source:
            if t == 1:
                line_no += 1
                changed_attr = ' data-changed="true"' if line_no in changed else ""
                body = line.rstrip("\r\n")
                yield 1, (
                    f'<span id="L{line_no}" data-line="{line_no}" '
                    f'class="mdv-code-line"{changed_attr}>{body}</span>'
                )
            else:
                yield t, line

    def wrap(self, source):
        return self._wrap_pre(self._wrap_line_anchors(source))


@lru_cache(maxsize=64)
def _get_cached_lexer(lang_name: str):
    try:
        return get_lexer_by_name(lang_name)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _get_cached_code_formatter(lang_str: str, pygments_style: str) -> CustomHtmlFormatter:
    return CustomHtmlFormatter(
        lang_str=lang_str,
        cssclass="highlight",
        style=pygments_style,
    )


@lru_cache(maxsize=256)
def _highlight_fenced_code_cached(code: str, lang: str, pygments_style: str) -> str | None:
    lexer = _get_cached_lexer(lang)
    if lexer is None:
        return None
    formatter = _get_cached_code_formatter(f"language-{lang}", pygments_style)
    return pygments_highlight(code, lexer, formatter)


def _make_code_block_container(
    code: str,
    lang: str,
    pygments_style: str,
    changed: bool = False,
) -> str:
    """Highlight a fenced code block with cached Pygments lexer/formatter (no lang guessing)."""
    if lang:
        if len(code) <= 8192:
            highlighted = _highlight_fenced_code_cached(code, lang, pygments_style)
        else:
            lexer = _get_cached_lexer(lang)
            highlighted = (
                pygments_highlight(
                    code, lexer, _get_cached_code_formatter(f"language-{lang}", pygments_style)
                )
                if lexer is not None
                else None
            )
        if highlighted is not None:
            if changed:
                return highlighted.replace("<div ", '<div data-changed="true" ', 1)
            return highlighted

    lang_cls = f" language-{html.escape(lang, quote=True)}" if lang else ""
    lang_attr = f' data-lang="{html.escape(lang, quote=True)}"' if lang else ""
    changed_attr = ' data-changed="true"' if changed else ""
    escaped_code = html.escape(code, quote=False)
    return (
        f'<div class="highlight{lang_cls}"{lang_attr}{changed_attr}>'
        f"<pre><span></span><code>{escaped_code}</code></pre></div>\n"
    )


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
    stripped = line.rstrip(" \t\r\n")
    if not stripped:
        return False
    lead = len(stripped) - len(stripped.lstrip(" "))
    if lead > 3:
        return False
    core = stripped[lead:]
    return len(core) >= fence_len and core == fence_char * len(core)


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
        self._processor: _TaskListTreeprocessor | None = None
        super().__init__(**kwargs)

    def set_source_lines(self, source_lines: list[int]) -> None:
        self.source_lines = source_lines
        if self._processor is not None:
            self._processor.source_lines = source_lines

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        self._processor = _TaskListTreeprocessor(md, self.source_lines)
        md.treeprocessors.register(
            self._processor,
            "gfm_task_list",
            15,
        )


def _unique_slug_fast(base_slug: str, seen: set[str], counters: dict[str, int]) -> str:
    """O(1)-amortized drop-in replacement for ``markdown.extensions.toc.unique``."""
    if base_slug and base_slug not in seen:
        seen.add(base_slug)
        return base_slug

    m = toc.IDCOUNT_RE.match(base_slug)
    if m:
        stem = m.group(1)
        idx = max(int(m.group(2)) + 1, counters.get(base_slug, 1))
        counter_key = base_slug
    else:
        stem = base_slug
        idx = counters.get(base_slug, 1)
        counter_key = base_slug

    while True:
        candidate = f"{stem}_{idx}"
        if candidate not in seen:
            seen.add(candidate)
            counters[counter_key] = idx + 1
            return candidate
        idx += 1


class _FastTocTreeprocessor(toc.TocTreeprocessor):
    """TOC treeprocessor replacing O(H^2) ``toc.unique`` probing with O(1) counters."""

    def run(self, doc: etree.Element) -> None:
        if not hasattr(toc, "render_inner_html") or not hasattr(toc, "remove_fnrefs"):
            super().run(doc)
            return

        used_ids: set[str] = set()
        has_marker = False
        marker = self.marker
        for el in doc.iter():
            el_id = el.attrib.get("id")
            if el_id is not None:
                used_ids.add(el_id)
            if marker and not has_marker and el.text and marker in el.text:
                has_marker = True

        slug_counters: dict[str, int] = {}

        # Fast path when [TOC] marker is absent and permalinks/anchors are disabled:
        # assign exact toc-matching IDs without deep-copying or building unused TOC HTML.
        if not has_marker and not self.use_anchors and self.use_permalinks in (False, None):
            header_rgx = self.header_rgx
            slugify = self.slugify
            sep = self.sep
            for el in doc.iter():
                tag = el.tag
                if isinstance(tag, str) and len(tag) == 2 and tag[0] == "h" and header_rgx.match(tag):
                    self.set_level(el)
                    if "id" not in el.attrib:
                        # Exclude footnote <sup> refs if any exist inside the heading.
                        if any(child.tag == "sup" for child in el.iter()):
                            innerhtml = toc.render_inner_html(toc.remove_fnrefs(el), self.md)
                            plain_name = html.unescape(toc.strip_tags(innerhtml))
                        else:
                            plain_name = "".join(el.itertext())
                        base = slugify(plain_name, sep)
                        el.attrib["id"] = _unique_slug_fast(base, used_ids, slug_counters)
                    if "data-toc-label" in el.attrib:
                        del el.attrib["data-toc-label"]
            self.md.toc_tokens = []
            self.md.toc = ""
            return

        toc_tokens: list[dict] = []
        for el in doc.iter():
            if isinstance(el.tag, str) and self.header_rgx.match(el.tag):
                self.set_level(el)
                innerhtml = toc.render_inner_html(toc.remove_fnrefs(el), self.md)
                name = toc.strip_tags(innerhtml)

                if "id" not in el.attrib:
                    base = self.slugify(html.unescape(name), self.sep)
                    el.attrib["id"] = _unique_slug_fast(base, used_ids, slug_counters)

                data_toc_label = ""
                if "data-toc-label" in el.attrib:
                    data_toc_label = toc.run_postprocessors(
                        toc.unescape(el.attrib["data-toc-label"]), self.md
                    )
                    name = toc.escape_cdata(toc.strip_tags(data_toc_label))
                    del el.attrib["data-toc-label"]

                level = int(el.tag[-1])
                if self.toc_top <= level <= self.toc_bottom:
                    toc_tokens.append(
                        {
                            "level": level,
                            "id": toc.unescape(el.attrib["id"]),
                            "name": name,
                            "html": innerhtml,
                            "data-toc-label": data_toc_label,
                        }
                    )

                if self.use_anchors:
                    self.add_anchor(el, el.attrib["id"])
                if self.use_permalinks not in [False, None]:
                    self.add_permalink(el, el.attrib["id"])

        toc_tokens = toc.nest_toc_tokens(toc_tokens)
        div = self.build_toc_div(toc_tokens)
        if self.marker:
            self.replace_marker(doc, div)

        rendered_toc = self.md.serializer(div)
        for pp in self.md.postprocessors:
            rendered_toc = pp.run(rendered_toc)
        self.md.toc_tokens = toc_tokens
        self.md.toc = rendered_toc


class _FastTocExtension(toc.TocExtension):
    """Drop-in TocExtension using ``_FastTocTreeprocessor``."""

    TreeProcessorClass = _FastTocTreeprocessor


class StrikethroughExtension(Extension):
    """Python-Markdown extension for ``~~strikethrough~~``."""

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        md.inlinePatterns.register(
            SimpleTagInlineProcessor(r"(~{2})(?!~)(.+?)(?<!~)\1", "del"),
            "strikethrough",
            65,
        )


_BARE_URL_PREV_DISALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_/@"
)


class _BareUrlInlineProcessor(InlineProcessor):
    """Turn bare ``http://`` / ``https://`` URLs into ``<a>`` links outside code/links."""

    def handleMatch(self, m: re.Match[str], data: str):
        start = m.start(1)
        if start > 0 and data[start - 1] in _BARE_URL_PREV_DISALLOWED:
            return None, None, None
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
            _BareUrlInlineProcessor(r"(https?://[^\s<>\"'`]+)", md),
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


_INLINE_CODE_RE = re.compile(r"(?<!\\)(`+)(.+?)(?<!`)\1(?!`)")
_DISPLAY_MATH_DOLLAR_RE = re.compile(r"(?<!\\)\$\$\n?([\s\S]*?)\n?(?<!\\)\$\$")
_DISPLAY_MATH_BRACKET_RE = re.compile(r"(?<!\\)\\\[\n?([\s\S]*?)\n?(?<!\\)\\\]")
_INLINE_MATH_DOLLAR_RE = re.compile(r"(?<!\\)\$(?!\s)([^\$\n]+?)(?<!\s)(?<!\\)\$(?!\d)")
_INLINE_MATH_PAREN_RE = re.compile(r"(?<!\\)\\\((.+?)(?<!\\)\\\)")


def _preprocess_code_first(
    body: str,
    line_offset: int = 0,
    changed_lines: set[int] | None = None,
    pygments_style: str | None = None,
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
        elif pygments_style is not None:
            tok = next_token("CODEBLOCK")
            placeholders[tok] = _make_code_block_container(
                inner_text,
                lang,
                pygments_style,
                changed=is_changed(start_line, end_line),
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

    text = _INLINE_CODE_RE.sub(protect_inline, text)

    # 4. Extract display math blocks: $$ ... $$ and \[ ... \]
    def repl_display_math(m: re.Match[str]) -> str:
        tok = next_token("MATHBLOCK")
        placeholders[tok] = _make_math_block_container(m.group(1))
        return f"\n\n{tok}\n\n"

    if "$$" in text:
        text = _DISPLAY_MATH_DOLLAR_RE.sub(repl_display_math, text)
    if "\\[" in text:
        text = _DISPLAY_MATH_BRACKET_RE.sub(repl_display_math, text)

    # 5. Extract inline math: $...$ and \(...\)
    def repl_inline_math(m: re.Match[str]) -> str:
        tok = next_token("MATHINLINE")
        placeholders[tok] = _make_math_inline_container(m.group(1))
        return tok

    if "$" in text:
        text = _INLINE_MATH_DOLLAR_RE.sub(repl_inline_math, text)
    if "\\(" in text:
        text = _INLINE_MATH_PAREN_RE.sub(repl_inline_math, text)

    # 6. Restore protected inline code and fenced code blocks in single O(N) passes.
    if protected_inline:
        inline_tok_re = re.compile(rf"{re.escape(token_prefix)}INLINE\d+X")
        text = inline_tok_re.sub(lambda m: protected_inline.get(m.group(0), m.group(0)), text)
    if protected_code_blocks:
        code_tok_re = re.compile(rf"{re.escape(token_prefix)}CODEBLOCK\d+X")
        text = code_tok_re.sub(
            lambda m: protected_code_blocks.get(m.group(0), m.group(0)), text
        )

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
_TRAILING_HASH_RE = re.compile(r"[ \t]+#+\s*$")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)")
_HEADING_ID_RE = re.compile(r'(<h[1-6]\b[^>]*\bid="([^"]+)"[^>]*)(>)')
_TASK_LI_RE = re.compile(r'(<li\b[^>]*\bclass="[^"]*\btask-list-item\b[^"]*"[^>]*>)([\s\S]*?</li>)')
_DATA_SOURCE_LINE_RE = re.compile(r'data-source-line="(\d+)"')
_PARA_RE = re.compile(r"(<p\b[^>]*>)([\s\S]*?)(</p>)")


def _strip_heading_markdown(raw: str) -> str:
    text = _TRAILING_HASH_RE.sub("", raw).strip()
    if "[" in text:
        text = _MD_LINK_RE.sub(r"\1", text)
    if "<" in text:
        text = _INLINE_TAG_RE.sub("", text)
    if "`" in text or "~~" in text:
        text = text.replace("`", "").replace("~~", "")
    if "*" in text or "_" in text:
        text = _EMPHASIS_RE.sub("", text)
    return text.strip()


def _scan_body_metadata(body: str, line_offset: int) -> tuple[list[HeadingItem], list[int]]:
    """Single-pass scan extracting headings and 1-based task checkbox lines outside fences."""
    headings: list[HeadingItem] = []
    task_lines: list[int] = []
    seen_slugs: set[str] = set()
    slug_counters: dict[str, int] = {}
    fence_state: tuple[str, int] | None = None

    for idx, line in enumerate(body.splitlines(), start=1):
        if fence_state is not None:
            if _is_fence_close(line, fence_state[0], fence_state[1]):
                fence_state = None
            continue

        if "`" in line or "~" in line:
            opened = _is_fence_open(line)
            if opened is not None:
                fence_state = (opened[0], opened[1])
                continue

        if "#" in line:
            m = _ATX_HEADING_RE.match(line)
            if m:
                level = len(m.group(1))
                raw_title = (m.group(2) or "").strip()
                if raw_title and set(raw_title) != {"#"}:
                    plain_title = _strip_heading_markdown(raw_title)
                    base_slug = toc.slugify(plain_title, "-")
                    unique_slug = _unique_slug_fast(base_slug, seen_slugs, slug_counters)
                    headings.append(
                        HeadingItem(
                            level=level,
                            text=plain_title,
                            slug=unique_slug,
                            line=line_offset + idx,
                        )
                    )
                continue

        if "[" in line and _TASK_LINE_RE.match(line):
            task_lines.append(line_offset + idx)

    return headings, task_lines


def extract_headings(text: str) -> list[HeadingItem]:
    """Extract headings with 1-based source line numbers and ``toc``-matching slugs."""
    _, body, line_offset = parse_front_matter_with_offset(text)
    headings, _ = _scan_body_metadata(body, line_offset)
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

    # 1. Mark headings whose 1-based source line is in changed_lines in one pass.
    changed_slugs_escaped: set[str] = set()
    for h in headings:
        if h.line in changed_lines:
            changed_slugs_escaped.add(html.escape(h.slug, quote=True))
            matched_lines.add(h.line)

    if changed_slugs_escaped:
        def _mark_heading(m: re.Match[str]) -> str:
            tag_prefix, attr_id, tag_end = m.group(1), m.group(2), m.group(3)
            if attr_id in changed_slugs_escaped and 'data-changed="true"' not in tag_prefix:
                return f'{tag_prefix} data-changed="true"{tag_end}'
            return m.group(0)

        html_body = _HEADING_ID_RE.sub(_mark_heading, html_body)

    # 2. Mark task-list <li> items whose <input data-source-line="L"> matches changed_lines.
    if "task-list-item" in html_body:
        def _mark_task_li(m: re.Match[str]) -> str:
            li_open, inner = m.group(1), m.group(2)
            if 'data-changed="true"' in li_open:
                return m.group(0)
            line_match = _DATA_SOURCE_LINE_RE.search(inner)
            if line_match:
                line_num = int(line_match.group(1))
                if line_num in changed_lines:
                    matched_lines.add(line_num)
                    return li_open[:-1] + ' data-changed="true">' + inner
            return m.group(0)

        html_body = _TASK_LI_RE.sub(_mark_task_li, html_body)

    # 3. Mark matching paragraph blocks for remaining changed lines using single compiled matcher.
    remaining_lines = sorted(ln for ln in changed_lines if ln not in matched_lines)
    if body_text and remaining_lines:
        body_lines = body_text.splitlines()
        seen_snips: set[str] = set()
        snippets: list[str] = []
        for ln in remaining_lines:
            rel_idx = ln - line_offset - 1
            if 0 <= rel_idx < len(body_lines):
                snippet = _strip_heading_markdown(body_lines[rel_idx]).strip()
                if len(snippet) >= 3:
                    escaped_snip = html.escape(snippet, quote=False)
                    if escaped_snip not in seen_snips:
                        seen_snips.add(escaped_snip)
                        snippets.append(escaped_snip)

        if snippets:
            # Cap single alternation regex branches to keep compilation fast on giant diffs.
            snippet_re = re.compile("|".join(re.escape(s) for s in snippets[:256]))
            overflow_snips = snippets[256:]

            def _mark_para(m: re.Match[str]) -> str:
                tag_open, content, tag_close = m.group(1), m.group(2), m.group(3)
                if 'data-changed="true"' in tag_open:
                    return m.group(0)
                plain = _INLINE_TAG_RE.sub("", content) if "<" in content else content
                if (
                    plain in seen_snips
                    or snippet_re.search(plain) is not None
                    or (overflow_snips and any(s in plain for s in overflow_snips))
                ):
                    return tag_open[:-1] + ' data-changed="true">' + content + tag_close
                return m.group(0)

            html_body = _PARA_RE.sub(_mark_para, html_body)

    return html_body


# ---------------------------------------------------------------------------
# Technical, Agentic & Source File Renderers
# ---------------------------------------------------------------------------
_EXTENSION_KIND_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".mkd": "markdown",
    ".mdx": "markdown",
    ".mdc": "markdown",
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
    ".log": "text",
    ".csv": "text",
    ".tsv": "text",
}

_SOURCE_LEXER_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".sql": "sql",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".lua": "lua",
    ".php": "php",
    ".pl": "perl",
    ".r": "r",
    ".scala": "scala",
    ".zig": "zig",
    ".nim": "nim",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".vim": "vim",
    ".nix": "nix",
    ".tf": "terraform",
    ".hcl": "terraform",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".vue": "html",
    ".svelte": "html",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".properties": "properties",
    ".rules": "python",
    ".star": "python",
    ".bzl": "python",
    ".cmake": "cmake",
    ".mk": "makefile",
    ".gradle": "groovy",
    ".dockerfile": "docker",
    ".desktop": "ini",
}

_SOURCE_LEXER_BY_NAME: dict[str, str] = {
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "dockerfile": "docker",
    "containerfile": "docker",
    "justfile": "makefile",
    "vagrantfile": "ruby",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "brewfile": "ruby",
    "cmakelists.txt": "cmake",
    "meson.build": "python",
    "build": "python",
    "workspace": "python",
    ".bashrc": "bash",
    ".zshrc": "bash",
    ".profile": "bash",
    ".gitignore": "text",
    ".dockerignore": "text",
    ".editorconfig": "ini",
}

_MARKDOWN_EXACT_NAMES: frozenset[str] = frozenset(
    {
        ".cursorrules",
        ".clauderules",
        ".windsurfrules",
    }
)

_TEXT_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "license",
        "copying",
        "authors",
        "notice",
        "procfile",
    }
)

_SUPPORTED_LOCAL_EXTENSIONS: frozenset[str] = frozenset(
    set(_EXTENSION_KIND_MAP) | set(_SOURCE_LEXER_BY_EXT)
)
_SUPPORTED_EXACT_FILENAMES: frozenset[str] = frozenset(
    set(_SOURCE_LEXER_BY_NAME)
    | _MARKDOWN_EXACT_NAMES
    | _TEXT_EXACT_NAMES
    | {"readme", "changelog", "todo"}
)


def is_supported_local_file(path: str | Path) -> bool:
    """Return True if ``path`` is a Markdown, technical, agentic, or source file Markveil renders."""
    if not path:
        return False
    p = Path(path)
    name = p.name.lower()
    if not name:
        return False
    if name in _SUPPORTED_EXACT_FILENAMES:
        return True
    if name.startswith(("dockerfile.", "makefile.", "license.")):
        return True
    suffix = p.suffix.lower()
    return bool(suffix and suffix in _SUPPORTED_LOCAL_EXTENSIONS)


def _resolve_source_lexer(file_path: str | None) -> str:
    if not file_path:
        return "text"
    p = Path(file_path)
    name = p.name.lower()
    if name in _SOURCE_LEXER_BY_NAME:
        return _SOURCE_LEXER_BY_NAME[name]
    if name.startswith("dockerfile."):
        return "docker"
    if name.startswith("makefile."):
        return "makefile"
    return _SOURCE_LEXER_BY_EXT.get(p.suffix.lower(), "text")


def detect_file_kind(file_path: str | None) -> str:
    """Detect rendering file kind from a file path extension or well-known filename."""
    if not file_path:
        return "markdown"
    p = Path(file_path)
    name = p.name.lower()
    if name in _MARKDOWN_EXACT_NAMES:
        return "markdown"
    if name in _SOURCE_LEXER_BY_NAME or name.startswith(("dockerfile.", "makefile.")):
        return "code"
    if name in _TEXT_EXACT_NAMES or name.startswith("license."):
        return "text"
    suffix = p.suffix.lower()
    if not suffix:
        return "markdown"
    if suffix in _EXTENSION_KIND_MAP:
        return _EXTENSION_KIND_MAP[suffix]
    if suffix in _SOURCE_LEXER_BY_EXT:
        return "code"
    return "text"


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


_JSON_TREE_MAX_DEPTH = 20
_JSON_TREE_MAX_NODES = 2000


def _render_json_tree_html(
    value: object,
    key: str | None = None,
    depth: int = 0,
    *,
    max_depth: int = _JSON_TREE_MAX_DEPTH,
    max_nodes: int = _JSON_TREE_MAX_NODES,
    _state: list[int] | None = None,
) -> str:
    if _state is None:
        _state = [0]
    _state[0] += 1

    label_html = (
        f'<span class="json-key">{html.escape(key)}</span>: ' if key is not None else ""
    )
    if isinstance(value, dict):
        count = len(value)
        if depth >= max_depth:
            return (
                f'<div class="json-leaf">{label_html}'
                f'<span class="json-meta">Object ({count}) — max depth reached</span></div>'
            )
        open_attr = " open" if depth < 2 else ""
        child_parts: list[str] = []
        rendered = 0
        for k, v in value.items():
            if _state[0] >= max_nodes:
                remaining = count - rendered
                child_parts.append(
                    f'<div class="json-leaf"><span class="json-meta">'
                    f"… {remaining} more items</span></div>"
                )
                break
            child_parts.append(
                _render_json_tree_html(
                    v,
                    str(k),
                    depth + 1,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    _state=_state,
                )
            )
            rendered += 1
        return (
            f'<details class="json-node"{open_attr}>'
            f'<summary>{label_html}<span class="json-meta">Object ({count})</span></summary>'
            f'<div class="json-children">{"".join(child_parts)}</div>'
            "</details>"
        )
    if isinstance(value, list):
        count = len(value)
        if depth >= max_depth:
            return (
                f'<div class="json-leaf">{label_html}'
                f'<span class="json-meta">Array ({count}) — max depth reached</span></div>'
            )
        open_attr = " open" if depth < 2 else ""
        child_parts = []
        rendered = 0
        for idx, item in enumerate(value):
            if _state[0] >= max_nodes:
                remaining = count - rendered
                child_parts.append(
                    f'<div class="json-leaf"><span class="json-meta">'
                    f"… {remaining} more items</span></div>"
                )
                break
            child_parts.append(
                _render_json_tree_html(
                    item,
                    f"[{idx}]",
                    depth + 1,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    _state=_state,
                )
            )
            rendered += 1
        return (
            f'<details class="json-node"{open_attr}>'
            f'<summary>{label_html}<span class="json-meta">Array ({count})</span></summary>'
            f'<div class="json-children">{"".join(child_parts)}</div>'
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


def _highlight_code(
    text: str,
    lexer_name: str,
    pygments_style: str,
    *,
    with_line_anchors: bool = True,
    changed_lines: set[int] | None = None,
) -> str:
    try:
        lexer = get_lexer_by_name(lexer_name)
    except Exception:
        lexer = get_lexer_by_name("text")
    if with_line_anchors:
        formatter: HtmlFormatter = _SourceCodeHtmlFormatter(
            lang_str=f"language-{lexer_name}",
            changed_lines=changed_lines,
            cssclass="highlight",
            style=pygments_style,
        )
    else:
        formatter = CustomHtmlFormatter(
            lang_str=f"language-{lexer_name}",
            cssclass="highlight",
            style=pygments_style,
        )
    return pygments_highlight(text, lexer, formatter)


def _render_code_document(
    text: str,
    file_path: str | None,
    pygments_style: str,
    changed_lines: set[int] | None = None,
) -> str:
    lexer_name = _resolve_source_lexer(file_path)
    return _highlight_code(
        text,
        lexer_name,
        pygments_style,
        with_line_anchors=True,
        changed_lines=changed_lines,
    )


def _render_json_document(
    text: str,
    kind: str,
    pygments_style: str,
    changed_lines: set[int] | None = None,
) -> str:
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

    code_html = _highlight_code(
        text, "json", pygments_style, with_line_anchors=True, changed_lines=changed_lines
    )
    return f"{badge}\n{tree_html}\n{code_html}"


def _render_yaml_document(
    text: str,
    pygments_style: str,
    changed_lines: set[int] | None = None,
) -> str:
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
    code_html = _highlight_code(
        text, "yaml", pygments_style, with_line_anchors=True, changed_lines=changed_lines
    )
    return f"{badge}\n{code_html}"


def _render_toml_document(
    text: str,
    pygments_style: str,
    changed_lines: set[int] | None = None,
) -> str:
    try:
        tomllib.loads(text)
        badge = '<div class="file-status-badge validation-badge status-valid valid">Valid TOML</div>'
    except tomllib.TOMLDecodeError as exc:
        err_msg = html.escape(str(exc))
        badge = (
            '<div class="file-status-badge validation-badge status-invalid invalid">'
            f"Invalid TOML: {err_msg}</div>"
        )
    code_html = _highlight_code(
        text, "toml", pygments_style, with_line_anchors=True, changed_lines=changed_lines
    )
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
    changed = changed_lines or set()
    lines = _normalize_newlines(text).splitlines()
    parts: list[str] = ['<div class="plain-text-view">']
    for idx, line in enumerate(lines, start=1):
        changed_attr = ' data-changed="true"' if idx in changed else ""
        parts.append(
            f'<div id="L{idx}" data-line="{idx}" class="plain-text-line mdv-code-line"{changed_attr}>'
            f'{html.escape(line) or " "}</div>'
        )
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Agentic Artifact Classification Strip
# ---------------------------------------------------------------------------
_ENV_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
    "agents": "Agents",
    "cursor": "Cursor",
    "opencode": "OpenCode",
    "grok": "Grok",
    "project": "Project",
}

_KIND_DISPLAY_NAMES: dict[str, str] = {
    "skill": "Skill",
    "agent": "Agent",
    "rule": "Rule",
    "command": "Command",
    "reference": "Reference",
    "prompt": "Prompt",
    "memory": "Memory",
    "config": "Config",
}


def _safe_sibling_href(raw_path: str) -> str | None:
    """Convert a local sibling path or file URI into a safe href compatible with Markveil."""
    cleaned = raw_path.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        return cleaned
    if scheme != "":
        # Reject javascript:, data:, vbscript:, http:, etc. in local sibling links.
        return None
    if cleaned.startswith("//") or cleaned.startswith("\\\\"):
        return None
    if cleaned.startswith("/"):
        return f"file://{quote(cleaned, safe='/')}"
    return quote(cleaned.replace("\\", "/"), safe="/._-~#")


def _render_agentic_strip_html(agentic_meta: dict | None) -> str:
    """Render a palette-faithful, HTML-escaped Agentic Classification Strip."""
    if not agentic_meta or not isinstance(agentic_meta, dict):
        return ""

    pills: list[str] = []
    env_raw = str(agentic_meta.get("env_source") or "").strip()
    if env_raw:
        env_label = _ENV_DISPLAY_NAMES.get(env_raw.lower(), env_raw.title())
        pills.append(
            f'<span class="mdv-agentic-pill mdv-agentic-pill-env">'
            f"{html.escape(env_label, quote=True)}</span>"
        )

    kind_raw = str(agentic_meta.get("kind") or "").strip()
    if kind_raw:
        kind_label = _KIND_DISPLAY_NAMES.get(kind_raw.lower(), kind_raw.title())
        pills.append(
            f'<span class="mdv-agentic-pill mdv-agentic-pill-kind">'
            f"{html.escape(kind_label, quote=True)}</span>"
        )

    scope_raw = str(agentic_meta.get("scope") or "").strip()
    if scope_raw:
        scope_label = scope_raw.title()
        pills.append(
            f'<span class="mdv-agentic-pill mdv-agentic-pill-scope">'
            f"{html.escape(scope_label, quote=True)}</span>"
        )

    if agentic_meta.get("always_apply"):
        pills.append('<span class="mdv-agentic-pill mdv-agentic-pill-flag">Always Apply</span>')

    stats: list[str] = []
    rel_path = str(agentic_meta.get("rel_path") or "").strip()
    if rel_path:
        stats.append(f"<span>{html.escape(rel_path, quote=True)}</span>")

    tok_est = agentic_meta.get("token_estimate")
    if isinstance(tok_est, int) and not isinstance(tok_est, bool) and tok_est > 0:
        stats.append(f"<span>~{tok_est:,} tok</span>")

    name = str(agentic_meta.get("name") or "").strip()
    desc = str(agentic_meta.get("description") or "").strip()

    triggers_raw = agentic_meta.get("triggers") or ()
    if isinstance(triggers_raw, str):
        triggers = [triggers_raw.strip()] if triggers_raw.strip() else []
    else:
        triggers = [str(t).strip() for t in triggers_raw if str(t).strip()]

    globs_raw = agentic_meta.get("globs") or ()
    if isinstance(globs_raw, str):
        globs = [globs_raw.strip()] if globs_raw.strip() else []
    else:
        globs = [str(g).strip() for g in globs_raw if str(g).strip()]

    links_raw = agentic_meta.get("sibling_links") or ()
    link_tags: list[str] = []
    for item in links_raw:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            label, target_path = str(item[0]).strip(), str(item[1]).strip()
        elif isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            target_path = str(item.get("path") or "").strip()
        else:
            continue
        if not label or not target_path:
            continue
        href = _safe_sibling_href(target_path)
        if not href:
            continue
        link_tags.append(
            f'<a class="mdv-agentic-link" href="{html.escape(href, quote=True)}">'
            f"{html.escape(label, quote=True)}</a>"
        )

    if not (pills or stats or name or desc or triggers or globs or link_tags):
        return ""

    parts: list[str] = [
        '<section class="mdv-agentic-strip" aria-label="Agentic artifact classification">'
    ]
    if pills or stats:
        parts.append('<div class="mdv-agentic-header">')
        parts.append(f'<div class="mdv-agentic-pills">{"".join(pills)}</div>')
        if stats:
            parts.append(f'<div class="mdv-agentic-stats">{"".join(stats)}</div>')
        parts.append("</div>")

    if name or desc or triggers or globs:
        parts.append('<div class="mdv-agentic-meta">')
        if name or desc:
            name_html = (
                f'<span class="mdv-agentic-name">{html.escape(name, quote=True)}</span>'
                if name
                else ""
            )
            desc_html = (
                f'<span class="mdv-agentic-desc">{html.escape(desc, quote=True)}</span>'
                if desc
                else ""
            )
            parts.append(f"<div>{name_html}{desc_html}</div>")
        if triggers:
            chips = "".join(
                f'<span class="mdv-agentic-tag">{html.escape(t, quote=True)}</span>'
                for t in triggers[:12]
            )
            parts.append(
                '<div class="mdv-agentic-tags">'
                '<span class="mdv-agentic-tag-label">Triggers:</span>'
                f"{chips}</div>"
            )
        if globs:
            chips = "".join(
                f'<span class="mdv-agentic-tag">{html.escape(g, quote=True)}</span>'
                for g in globs[:12]
            )
            parts.append(
                '<div class="mdv-agentic-tags">'
                '<span class="mdv-agentic-tag-label">Globs:</span>'
                f"{chips}</div>"
            )
        parts.append("</div>")

    if link_tags:
        parts.append(
            '<div class="mdv-agentic-links">'
            '<span class="mdv-agentic-links-label">Related:</span>'
            f'{"".join(link_tags[:16])}</div>'
        )

    parts.append("</section>")
    raw_strip = "".join(parts)
    # Run through sanitizer to guarantee allowlist compliance by construction.
    sanitized_strip, _ = sanitize_html(raw_strip, allow_remote_images=False)
    return sanitized_strip + "\n"


# ---------------------------------------------------------------------------
# Public Rendering Entrypoints & Cached Markdown Converter
# ---------------------------------------------------------------------------
_TABLE_WRAP_RE = re.compile(r"(<table>[\s\S]*?</table>)")
_CLOSING_STYLE_RE = re.compile(r"</style", re.IGNORECASE)
_CLOSING_SCRIPT_RE = re.compile(r"</script", re.IGNORECASE)
_MD_THREAD_LOCAL = threading.local()


def _get_markdown_converter(
    pygments_style: str,
    hard_breaks: bool,
) -> tuple[markdown.Markdown, TaskListExtension]:
    cache: dict[tuple[str, bool], tuple[markdown.Markdown, TaskListExtension]] | None = getattr(
        _MD_THREAD_LOCAL, "converters", None
    )
    if cache is None:
        cache = {}
        _MD_THREAD_LOCAL.converters = cache

    key = (pygments_style, hard_breaks)
    cached = cache.get(key)
    if cached is not None:
        return cached

    task_ext = TaskListExtension()
    extensions: list[str | Extension] = [
        "markdown.extensions.fenced_code",
        "markdown.extensions.tables",
        _FastTocExtension(permalink=False),
        "markdown.extensions.sane_lists",
        "markdown.extensions.codehilite",
        "markdown.extensions.admonition",
        "markdown.extensions.def_list",
        "markdown.extensions.footnotes",
        StrikethroughExtension(),
        task_ext,
        BareUrlExtension(),
    ]
    if hard_breaks:
        extensions.append("markdown.extensions.nl2br")

    extension_configs = {
        "markdown.extensions.codehilite": {
            "css_class": "highlight",
            "guess_lang": False,
            "pygments_style": pygments_style,
            "pygments_formatter": CustomHtmlFormatter,
        },
    }
    md = markdown.Markdown(
        extensions=extensions,
        extension_configs=extension_configs,
    )
    cached = (md, task_ext)
    cache[key] = cached
    return cached


def _unwrap_block_placeholders(html_body: str, token_prefix: str) -> str:
    pattern = re.compile(
        rf"<p>\s*({re.escape(token_prefix)}(?:MERMAID|MATHBLOCK|CODEBLOCK)\d+X)\s*</p>"
    )
    return pattern.sub(r"\1", html_body)


def _wrap_tables(html_body: str) -> str:
    if "<table" not in html_body:
        return html_body
    return _TABLE_WRAP_RE.sub(r'<div class="table-wrapper">\1</div>', html_body)


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
        tags.append(
            f'<link rel="stylesheet" href="{html.escape(_path_to_uri(KATEX_CSS_PATH), quote=True)}">'
        )
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
    agentic_meta: dict | None = None,
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
    pygments_css = _get_pygments_css(pygments_style)

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
        headings, task_source_lines = _scan_body_metadata(body, line_offset)
        ctx = _preprocess_code_first(
            body,
            line_offset=line_offset,
            changed_lines=changed_lines,
            pygments_style=pygments_style,
        )

        md, task_ext = _get_markdown_converter(pygments_style, hard_breaks)
        task_ext.set_source_lines(task_source_lines)
        try:
            md.reset()
            raw_md_html = md.convert(ctx.text)
        finally:
            task_ext.set_source_lines([])

        if ctx.placeholders:
            raw_md_html = _unwrap_block_placeholders(raw_md_html, ctx.token_prefix)

        # Sanitize Markdown HTML BEFORE restoring trusted escaped Mermaid/KaTeX/Code/front-matter.
        sanitized_html, blocked_remote_images = sanitize_html(
            raw_md_html,
            allow_remote_images=allow_remote_images,
        )
        sanitized_html = _wrap_tables(sanitized_html)

        if ctx.placeholders:
            ph_re = re.compile(
                rf"{re.escape(ctx.token_prefix)}(?:MERMAID|MATHBLOCK|MATHINLINE|CODEBLOCK)\d+X"
            )
            sanitized_html = ph_re.sub(
                lambda m: ctx.placeholders.get(m.group(0), m.group(0)),
                sanitized_html,
            )

        covered_lines: set[int] = set()
        if changed_lines:
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
        body_markup = _render_json_document(text, kind, pygments_style, changed_lines=changed_lines)
    elif kind == "yaml":
        body_markup = _render_yaml_document(text, pygments_style, changed_lines=changed_lines)
    elif kind == "toml":
        body_markup = _render_toml_document(text, pygments_style, changed_lines=changed_lines)
    elif kind == "diff":
        body_markup = _render_diff_document(text)
    elif kind == "mermaid":
        changed = bool(changed_lines)
        body_markup = _make_mermaid_container(text, changed=changed)
    elif kind == "code":
        body_markup = _render_code_document(
            text, file_path, pygments_style, changed_lines=changed_lines
        )
    else:
        body_markup = _render_text_document(text, changed_lines)

    if agentic_meta and body_html_override is None:
        strip_html = _render_agentic_strip_html(agentic_meta)
        if strip_html:
            body_markup = f"{strip_html}{body_markup}"

    safe_custom_css = (
        _CLOSING_STYLE_RE.sub(r"<\/style", custom_css) if custom_css else ""
    )
    safe_client_js = _CLOSING_SCRIPT_RE.sub(r"<\/script", client_js)

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
