"""HTML allowlist sanitizer built on Python's stdlib ``html.parser.HTMLParser``."""

from __future__ import annotations

import html
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "div",
        "span",
        "section",
        "article",
        "details",
        "summary",
        "blockquote",
        "pre",
        "code",
        "em",
        "strong",
        "b",
        "i",
        "u",
        "s",
        "del",
        "ins",
        "mark",
        "sub",
        "sup",
        "kbd",
        "abbr",
        "cite",
        "small",
        "ul",
        "ol",
        "li",
        "dl",
        "dt",
        "dd",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "caption",
        "colgroup",
        "col",
        "a",
        "img",
        "figure",
        "figcaption",
        "input",
        "button",
    }
)

VOID_TAGS: frozenset[str] = frozenset({"br", "hr", "img", "input", "col"})

STRIP_WITH_CONTENT_TAGS: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "applet",
        "noscript",
        "template",
        "textarea",
        "select",
        "form",
        "meta",
        "base",
        "link",
        "svg",
    }
)

# Void elements inside STRIP_WITH_CONTENT_TAGS never have a closing tag in HTML.
STRIP_VOID_TAGS: frozenset[str] = frozenset({"meta", "base", "link", "embed", "frame"})

GLOBAL_ALLOWED_ATTRS: frozenset[str] = frozenset(
    {
        "id",
        "class",
        "title",
        "dir",
        "lang",
        "role",
        "data-lang",
        "data-line",
        "data-changed",
        "data-source-line",
        "data-task-index",
    }
)

TAG_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "target", "rel", "name"}),
    "img": frozenset({"src", "alt", "width", "height", "loading", "decoding"}),
    "ol": frozenset({"start", "type", "reversed"}),
    "li": frozenset({"value"}),
    "th": frozenset({"colspan", "rowspan", "scope", "align", "style"}),
    "td": frozenset({"colspan", "rowspan", "scope", "align", "style"}),
    "col": frozenset({"span", "align"}),
    "colgroup": frozenset({"span", "align"}),
    "details": frozenset({"open"}),
    "blockquote": frozenset({"cite"}),
    "del": frozenset({"cite", "datetime"}),
    "ins": frozenset({"cite", "datetime"}),
    "button": frozenset({"type", "disabled"}),
}

INPUT_CHECKBOX_ATTRS: frozenset[str] = frozenset(
    {"type", "checked", "disabled", "class", "data-task-index", "data-source-line"}
)

BOOLEAN_ATTRS: frozenset[str] = frozenset({"checked", "disabled", "open", "reversed"})

_SAFE_TEXT_ALIGN_RE = re.compile(r"^\s*text-align\s*:\s*(left|center|right)\s*;?\s*$", re.IGNORECASE)
_SAFE_ALIGN_VALS: frozenset[str] = frozenset({"left", "center", "right"})
_SAFE_RASTER_DATA_RE = re.compile(
    r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$",
    re.IGNORECASE,
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _clean_url(raw_url: str) -> str:
    return _CONTROL_CHARS_RE.sub("", raw_url).strip()


def _is_safe_href(raw_url: str) -> str | None:
    """Validate an href/cite URL, returning the cleaned URL or None if unsafe."""
    cleaned = _clean_url(raw_url)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme in ("", "http", "https", "mailto", "tel", "file"):
        return cleaned
    return None


def _classify_img_src(raw_url: str, allow_remote_images: bool) -> tuple[str, str]:
    """Classify an ``img src`` URL as ('allow' | 'block_remote' | 'drop', cleaned_url)."""
    cleaned = _clean_url(raw_url)
    if not cleaned:
        return ("drop", "")

    # Normalize backslashes outside data: URIs so browser URL normalization cannot
    # smuggle protocol-relative or remote paths (e.g. \\evil.com, /\evil.com, \foo.png).
    if not cleaned.lower().startswith("data:"):
        cleaned = cleaned.replace("\\", "/")

    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()

    # Protocol-relative //host/path behaves like remote HTTP(S).
    if scheme == "" and parsed.netloc:
        return ("allow", cleaned) if allow_remote_images else ("block_remote", cleaned)

    if scheme == "" or scheme in ("file", "blob"):
        return ("allow", cleaned)

    if scheme == "data":
        if _SAFE_RASTER_DATA_RE.match(cleaned):
            return ("allow", cleaned)
        return ("drop", "")

    if scheme in ("http", "https"):
        return ("allow", cleaned) if allow_remote_images else ("block_remote", cleaned)

    return ("drop", "")


def _is_allowed_attr(tag: str, attr_name: str) -> bool:
    if attr_name.startswith("on") or attr_name in ("srcdoc", "formaction"):
        return False
    if attr_name in GLOBAL_ALLOWED_ATTRS or attr_name.startswith("aria-"):
        return True
    allowed_for_tag = TAG_ALLOWED_ATTRS.get(tag)
    return bool(allowed_for_tag and attr_name in allowed_for_tag)


def _format_attrs(attrs: list[tuple[str, str | None]]) -> str:
    if not attrs:
        return ""
    parts: list[str] = []
    for name, value in attrs:
        if value is None or (name in BOOLEAN_ATTRS and value == ""):
            parts.append(name)
        else:
            if "&" in value or "<" in value or ">" in value or '"' in value or "'" in value:
                value = html.escape(value, quote=True)
            parts.append(f'{name}="{value}"')
    return " " + " ".join(parts)


class _SanitizingHTMLParser(HTMLParser):
    """Streaming allowlist HTML sanitizer."""

    def __init__(self, allow_remote_images: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.allow_remote_images = allow_remote_images
        self.blocked_remote_img_count = 0
        self._out: list[str] = []
        self._strip_stack: list[str] = []
        self._open_tags: list[str] = []

    def get_html(self) -> str:
        while self._open_tags:
            self._out.append(f"</{self._open_tags.pop()}>")
        return "".join(self._out)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if self._strip_stack:
            return
        if tag_l in STRIP_WITH_CONTENT_TAGS:
            return
        if tag_l not in ALLOWED_TAGS:
            return
        rendered = self._render_start_tag(tag_l, attrs)
        if rendered is not None:
            self._out.append(rendered)
            if tag_l not in VOID_TAGS:
                self._out.append(f"</{tag_l}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if self._strip_stack:
            if tag_l in STRIP_WITH_CONTENT_TAGS and tag_l not in STRIP_VOID_TAGS:
                self._strip_stack.append(tag_l)
            return

        if tag_l in STRIP_WITH_CONTENT_TAGS:
            if tag_l not in STRIP_VOID_TAGS:
                self._strip_stack.append(tag_l)
            return

        if tag_l not in ALLOWED_TAGS:
            return

        rendered = self._render_start_tag(tag_l, attrs)
        if rendered is None:
            return
        self._out.append(rendered)
        if tag_l not in VOID_TAGS:
            self._open_tags.append(tag_l)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self._strip_stack:
            if tag_l in self._strip_stack:
                while self._strip_stack:
                    popped = self._strip_stack.pop()
                    if popped == tag_l:
                        break
            return

        if tag_l not in ALLOWED_TAGS or tag_l in VOID_TAGS:
            return

        open_tags = self._open_tags
        if open_tags and open_tags[-1] == tag_l:
            open_tags.pop()
            self._out.append(f"</{tag_l}>")
        elif tag_l in open_tags:
            while open_tags:
                popped = open_tags.pop()
                self._out.append(f"</{popped}>")
                if popped == tag_l:
                    break

    def handle_data(self, data: str) -> None:
        if self._strip_stack:
            return
        if "&" in data or "<" in data or ">" in data:
            self._out.append(html.escape(data, quote=False))
        else:
            self._out.append(data)

    def handle_comment(self, data: str) -> None:
        # Strip HTML comments to prevent parser-differential or conditional comment attacks.
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def _render_start_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        if tag == "input":
            return self._render_input_tag(attrs)
        if tag == "img":
            return self._render_img_tag(attrs)
        if tag == "a":
            return self._render_a_tag(attrs)
        if not attrs:
            return f"<{tag}>"

        filtered: list[tuple[str, str | None]] = []
        seen_names: set[str] = set()
        for raw_name, raw_val in attrs:
            name = raw_name.lower()
            if name in seen_names or not _is_allowed_attr(tag, name):
                continue

            if name == "style":
                if tag not in ("th", "td") or not raw_val:
                    continue
                m = _SAFE_TEXT_ALIGN_RE.match(raw_val)
                if not m:
                    continue
                filtered.append(("style", f"text-align: {m.group(1).lower()}"))
                seen_names.add(name)
                continue

            if name == "align":
                if not raw_val or raw_val.strip().lower() not in _SAFE_ALIGN_VALS:
                    continue
                filtered.append(("align", raw_val.strip().lower()))
                seen_names.add(name)
                continue

            if name == "cite":
                if not raw_val:
                    continue
                safe_cite = _is_safe_href(raw_val)
                if safe_cite is None:
                    continue
                filtered.append(("cite", safe_cite))
                seen_names.add(name)
                continue

            if name == "type" and tag == "button":
                btn_type = (raw_val or "").strip().lower()
                if btn_type not in ("button", "reset", "submit"):
                    btn_type = "button"
                filtered.append(("type", btn_type))
                seen_names.add(name)
                continue

            seen_names.add(name)
            filtered.append((name, raw_val))

        return f"<{tag}{_format_attrs(filtered)}>"

    def _render_input_tag(self, attrs: list[tuple[str, str | None]]) -> str | None:
        attr_map: dict[str, str | None] = {}
        for raw_name, raw_val in attrs:
            name = raw_name.lower()
            if name not in attr_map:
                attr_map[name] = raw_val

        input_type = (attr_map.get("type") or "").strip().lower()
        if input_type != "checkbox":
            return None

        filtered: list[tuple[str, str | None]] = []
        for raw_name, raw_val in attrs:
            name = raw_name.lower()
            if name in INPUT_CHECKBOX_ATTRS:
                if name == "type":
                    filtered.append(("type", "checkbox"))
                elif name == "checked":
                    filtered.append(("checked", None))
                elif name == "disabled":
                    filtered.append(("disabled", None))
                else:
                    filtered.append((name, raw_val))
        return f"<input{_format_attrs(filtered)}>"

    def _render_a_tag(self, attrs: list[tuple[str, str | None]]) -> str:
        filtered: list[tuple[str, str | None]] = []
        seen_names: set[str] = set()
        for raw_name, raw_val in attrs:
            name = raw_name.lower()
            if name in seen_names or not _is_allowed_attr("a", name):
                continue
            if name == "href":
                if raw_val is None:
                    continue
                safe_href = _is_safe_href(raw_val)
                if safe_href is None:
                    continue
                filtered.append(("href", safe_href))
                seen_names.add(name)
                continue
            seen_names.add(name)
            filtered.append((name, raw_val))

        # Prevent nested <a> tags in raw HTML by keeping element clean;
        # outer <a> remains valid while inner <a> has no special nesting issues.
        return f"<a{_format_attrs(filtered)}>"

    def _render_img_tag(self, attrs: list[tuple[str, str | None]]) -> str:
        filtered: list[tuple[str, str | None]] = []
        seen_names: set[str] = set()
        class_tokens: list[str] = []
        blocked_remote_url: str | None = None

        for raw_name, raw_val in attrs:
            name = raw_name.lower()
            if name in seen_names or not _is_allowed_attr("img", name):
                continue
            if name == "class":
                seen_names.add("class")
                if raw_val:
                    class_tokens.extend(tok for tok in raw_val.split() if tok)
                continue
            if name == "src":
                seen_names.add("src")
                if raw_val is None:
                    continue
                action, cleaned = _classify_img_src(raw_val, self.allow_remote_images)
                if action == "allow":
                    filtered.append(("src", cleaned))
                elif action == "block_remote":
                    blocked_remote_url = cleaned
                    self.blocked_remote_img_count += 1
                continue
            seen_names.add(name)
            filtered.append((name, raw_val))

        if blocked_remote_url is not None:
            filtered.append(("data-blocked-src", blocked_remote_url))
            if "blocked-remote-img" not in class_tokens:
                class_tokens.append("blocked-remote-img")

        if class_tokens:
            filtered.append(("class", " ".join(class_tokens)))

        return f"<img{_format_attrs(filtered)}>"


def sanitize_html(raw_html: str, allow_remote_images: bool = False) -> tuple[str, int]:
    """Sanitize raw HTML using an allowlist parser.

    Returns ``(sanitized_html, blocked_remote_img_count)``.
    """
    if not raw_html:
        return "", 0
    parser = _SanitizingHTMLParser(allow_remote_images=allow_remote_images)
    parser.feed(raw_html)
    parser.close()
    return parser.get_html(), parser.blocked_remote_img_count
