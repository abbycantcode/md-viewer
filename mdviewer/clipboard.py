"""Smart clipboard reading/writing and pure-Python HTML-to-Markdown conversion."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class ClipboardPayload:
    """Clipboard contents along with whether HTML was converted to Markdown."""

    text: str
    was_html: bool = False
    raw_html: str = ""


class _HtmlToMarkdownParser(HTMLParser):
    """Streaming HTMLParser converting rich HTML fragments into clean Markdown."""

    _SKIP_TAGS = frozenset({"script", "style", "head", "meta", "title", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0
        self._in_pre = False
        self._pre_lang = ""
        self._pre_chunks: list[str] = []
        self._inline_code_depth = 0
        self._inline_code_chunks: list[str] = []
        self._link_stack: list[tuple[str, list[str]]] = []
        self._list_stack: list[tuple[str, int]] = []  # ("ul" | "ol", counter)
        self._blockquote_depth = 0
        self._in_table = False
        self._table_rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._heading_level = 0

    def _emit(self, text: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(text)
        elif self._link_stack:
            self._link_stack[-1][1].append(text)
        else:
            self.out.append(text)

    def _ensure_blank_line(self) -> None:
        if self._current_cell is not None or self._link_stack:
            return
        joined = "".join(self.out)
        if not joined:
            return
        if joined.endswith("\n\n"):
            return
        if joined.endswith("\n"):
            self.out.append("\n")
        else:
            self.out.append("\n\n")

    def _ensure_newline(self) -> None:
        if self._current_cell is not None or self._link_stack:
            return
        joined = "".join(self.out)
        if joined and not joined.endswith("\n"):
            self.out.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._ensure_blank_line()
            self._heading_level = int(tag[1])
            self._emit("#" * self._heading_level + " ")
        elif tag == "p":
            if self._list_stack:
                pass
            else:
                self._ensure_blank_line()
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._ensure_blank_line()
            self._emit("---\n\n")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("del", "s"):
            self._emit("~~")
        elif tag == "pre":
            self._ensure_blank_line()
            self._in_pre = True
            self._pre_lang = ""
            cls = attr_map.get("class", "")
            m = re.search(r"language-([A-Za-z0-9_+-]+)", cls)
            if m:
                self._pre_lang = m.group(1)
            self._pre_chunks = []
        elif tag == "code":
            if self._in_pre:
                cls = attr_map.get("class", "")
                if not self._pre_lang:
                    m = re.search(r"language-([A-Za-z0-9_+-]+)", cls)
                    if m:
                        self._pre_lang = m.group(1)
            else:
                self._inline_code_depth += 1
                if self._inline_code_depth == 1:
                    self._inline_code_chunks = []
        elif tag == "a":
            href = attr_map.get("href", "").strip()
            self._link_stack.append((href, []))
        elif tag == "ul":
            if not self._list_stack:
                self._ensure_blank_line()
            else:
                self._ensure_newline()
            self._list_stack.append(("ul", 0))
        elif tag == "ol":
            if not self._list_stack:
                self._ensure_blank_line()
            else:
                self._ensure_newline()
            self._list_stack.append(("ol", 0))
        elif tag == "li":
            self._ensure_newline()
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack:
                kind, count = self._list_stack[-1]
                count += 1
                self._list_stack[-1] = (kind, count)
                marker = f"{count}. " if kind == "ol" else "- "
            else:
                marker = "- "
            self._emit(f"{indent}{marker}")
        elif tag == "blockquote":
            self._ensure_blank_line()
            self._blockquote_depth += 1
            self._emit("> " * self._blockquote_depth)
        elif tag == "table":
            self._ensure_blank_line()
            self._in_table = True
            self._table_rows = []
        elif tag == "tr" and self._in_table:
            self._current_row = []
        elif tag in ("th", "td") and self._in_table and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_level = 0
            self._ensure_blank_line()
        elif tag == "p":
            if self._list_stack:
                self._ensure_newline()
            else:
                self._ensure_blank_line()
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag in ("del", "s"):
            self._emit("~~")
        elif tag == "code" and not self._in_pre:
            if self._inline_code_depth > 0:
                self._inline_code_depth -= 1
                if self._inline_code_depth == 0:
                    code_text = "".join(self._inline_code_chunks).strip("\n")
                    fence = "``" if "`" in code_text else "`"
                    if fence == "``" and (code_text.startswith("`") or code_text.endswith("`")):
                        self._emit(f"{fence} {code_text} {fence}")
                    else:
                        self._emit(f"{fence}{code_text}{fence}")
                    self._inline_code_chunks = []
        elif tag == "pre":
            if self._in_pre:
                raw_code = "".join(self._pre_chunks).strip("\n")
                fence = "````" if "```" in raw_code else "```"
                lang = self._pre_lang
                self._in_pre = False
                self._pre_lang = ""
                self._pre_chunks = []
                self._emit(f"{fence}{lang}\n{raw_code}\n{fence}\n\n")
        elif tag == "a":
            if self._link_stack:
                href, label_parts = self._link_stack.pop()
                label = "".join(label_parts).strip() or href
                if href:
                    self._emit(f"[{label}]({href})")
                else:
                    self._emit(label)
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if not self._list_stack:
                self._ensure_blank_line()
        elif tag == "li":
            self._ensure_newline()
        elif tag == "blockquote":
            if self._blockquote_depth > 0:
                self._blockquote_depth -= 1
            self._ensure_blank_line()
        elif tag in ("th", "td") and self._in_table and self._current_row is not None:
            cell = " ".join("".join(self._current_cell or []).split())
            cell = cell.replace("|", "\\|")
            self._current_row.append(cell)
            self._current_cell = None
        elif tag == "tr" and self._in_table and self._current_row is not None:
            if self._current_row:
                self._table_rows.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._in_table:
            self._in_table = False
            if self._table_rows:
                col_count = max(len(r) for r in self._table_rows)
                norm_rows = [r + [""] * (col_count - len(r)) for r in self._table_rows]
                lines = ["| " + " | ".join(norm_rows[0]) + " |"]
                lines.append("| " + " | ".join(["---"] * col_count) + " |")
                for row in norm_rows[1:]:
                    lines.append("| " + " | ".join(row) + " |")
                self._emit("\n".join(lines) + "\n\n")
            self._table_rows = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_pre:
            self._pre_chunks.append(data)
            return
        if self._inline_code_depth > 0:
            self._inline_code_chunks.append(data)
            return

        # Collapse source HTML indentation/newlines into single spaces outside <pre>
        normalized = re.sub(r"[ \t\r\n]+", " ", data)
        if not normalized:
            return
        if self._blockquote_depth > 0 and normalized == " ":
            return
        # Avoid leading space right after block start/newline/list marker
        if not self._current_cell and not self._link_stack:
            joined = "".join(self.out)
            if (
                not joined
                or joined.endswith("\n")
                or joined.endswith("# ")
                or joined.endswith("- ")
                or joined.endswith("> ")
                or re.search(r"\d+\. $", joined)
            ) and normalized == " ":
                return
        self._emit(normalized)


def html_to_markdown(raw_html: str) -> str:
    """Convert an HTML fragment or document to clean Markdown using stdlib html.parser."""
    if not raw_html or not raw_html.strip():
        return ""
    parser = _HtmlToMarkdownParser()
    parser.feed(raw_html)
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_clipboard_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace").replace("\x00", "")
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def _get_gtk_clipboard():
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        ok, _ = Gtk.init_check([])
        if not ok:
            return None, None, None
        display = Gdk.Display.get_default()
        if display is None:
            return None, None, None
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        return Gtk, Gdk, cb
    except Exception:
        return None, None, None


def _run_cli_paste(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return _decode_clipboard_bytes(proc.stdout)


def read_clipboard_smart(prefer_html_convert: bool = True) -> ClipboardPayload:
    """Read clipboard contents, optionally converting HTML clipboard payloads to Markdown."""
    _gtk, gdk, cb = _get_gtk_clipboard()
    if cb is not None and gdk is not None:
        if prefer_html_convert:
            try:
                html_atom = gdk.Atom.intern("text/html", False)
                sel = cb.wait_for_contents(html_atom)
                if sel is not None:
                    raw_html = _decode_clipboard_bytes(sel.get_data())
                    if raw_html.strip():
                        converted = html_to_markdown(raw_html)
                        if converted:
                            return ClipboardPayload(
                                text=converted, was_html=True, raw_html=raw_html
                            )
            except Exception:
                pass
        try:
            text = cb.wait_for_text()
            if text:
                return ClipboardPayload(text=text, was_html=False, raw_html="")
        except Exception:
            pass

    if prefer_html_convert:
        for cmd in (
            ["wl-paste", "--type", "text/html", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-t", "text/html", "-o"],
        ):
            raw_html = _run_cli_paste(cmd)
            if raw_html.strip():
                converted = html_to_markdown(raw_html)
                if converted:
                    return ClipboardPayload(
                        text=converted, was_html=True, raw_html=raw_html
                    )

    for cmd in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        text = _run_cli_paste(cmd)
        if text:
            return ClipboardPayload(text=text, was_html=False, raw_html="")

    return ClipboardPayload(text="", was_html=False, raw_html="")


def write_clipboard_text(text: str) -> bool:
    """Write plain text to the system clipboard via GTK or CLI fallback."""
    _gtk, _gdk, cb = _get_gtk_clipboard()
    wrote_gtk = False
    if cb is not None:
        try:
            cb.set_text(text, -1)
            cb.store()
            wrote_gtk = True
        except Exception:
            wrote_gtk = False

    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                input=text,
                text=True,
                shell=False,
                capture_output=True,
                timeout=3,
            )
            if proc.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    return wrote_gtk
