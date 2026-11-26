"""Diff engine: line change tracking, git HEAD diffing, and semantic HTML rendering."""

from __future__ import annotations

import difflib
import html
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_INLINE_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+")


@dataclass
class DiffReport:
    """Result of comparing two text revisions or files."""

    old_label: str
    new_label: str
    additions: int
    deletions: int
    hunks_count: int
    html: str
    error: str | None = None


def compute_changed_lines(old_text: str, new_text: str) -> set[int]:
    """Return 1-based line numbers in new_text that were inserted or replaced."""
    if old_text == new_text:
        return set()
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changed: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def _index_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Return sorted list of (1-based line, heading_text) outside fenced code blocks."""
    headings: list[tuple[int, str]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for idx, line in enumerate(lines, start=1):
        if not in_fence:
            fm = _FENCE_OPEN_RE.match(line)
            if fm:
                seq = fm.group(1)
                info = fm.group(2)
                if not (seq[0] == "`" and "`" in info):
                    in_fence = True
                    fence_char = seq[0]
                    fence_len = len(seq)
                    continue
            hm = _ATX_HEADING_RE.match(line)
            if hm:
                headings.append((idx, f"{hm.group(1)} {hm.group(2).strip()}"))
        else:
            stripped = line.strip()
            if (
                stripped
                and len(stripped) >= fence_len
                and set(stripped) == {fence_char}
            ):
                in_fence = False
                fence_char = ""
                fence_len = 0
    return headings


def _nearest_heading(headings: list[tuple[int, str]], line_no_1based: int) -> str | None:
    """Find the nearest Markdown heading at or before line_no_1based."""
    found: str | None = None
    for h_line, h_text in headings:
        if h_line <= line_no_1based:
            found = h_text
        else:
            break
    return found


def _render_inline_pair(old_line: str, new_line: str) -> tuple[str, str]:
    """Compute HTML with inline <del class='diff-word'> / <ins class='diff-word'> spans."""
    if len(old_line) > 1000 or len(new_line) > 1000:
        return html.escape(old_line), html.escape(new_line)

    old_tokens = _INLINE_TOKEN_RE.findall(old_line)
    new_tokens = _INLINE_TOKEN_RE.findall(new_line)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)

    old_out: list[str] = []
    new_out: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_seg = html.escape("".join(old_tokens[i1:i2]))
        new_seg = html.escape("".join(new_tokens[j1:j2]))
        if tag == "equal":
            old_out.append(old_seg)
            new_out.append(new_seg)
        elif tag == "delete":
            old_out.append(f'<del class="diff-word">{old_seg}</del>')
        elif tag == "insert":
            new_out.append(f'<ins class="diff-word">{new_seg}</ins>')
        elif tag == "replace":
            if old_seg:
                old_out.append(f'<del class="diff-word">{old_seg}</del>')
            if new_seg:
                new_out.append(f'<ins class="diff-word">{new_seg}</ins>')
    return "".join(old_out), "".join(new_out)


def _format_hunk_header(
    group: list[tuple[str, int, int, int, int]],
    new_headings: list[tuple[int, str]],
    old_headings: list[tuple[int, str]],
) -> str:
    i_start = group[0][1] + 1
    i_len = group[-1][2] - group[0][1]
    j_start = group[0][3] + 1
    j_len = group[-1][4] - group[0][3]

    heading = _nearest_heading(new_headings, j_start) or _nearest_heading(
        old_headings, i_start
    )
    ctx_suffix = f" &mdash; {html.escape(heading)}" if heading else ""
    return f"@@ -{i_start},{i_len} +{j_start},{j_len} @@{ctx_suffix}"


def render_diff_html(
    old_text: str,
    new_text: str,
    old_label: str = "Before",
    new_label: str = "After",
    mode: str = "unified",
    context_lines: int = 3,
) -> tuple[str, int, int, int]:
    """Render escaped semantic HTML diff and return (html, additions, deletions, hunks_count)."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    groups = list(matcher.get_grouped_opcodes(n=context_lines))

    additions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            additions += j2 - j1
        if tag in ("delete", "replace"):
            deletions += i2 - i1

    hunks_count = len(groups)
    old_headings = _index_headings(old_lines)
    new_headings = _index_headings(new_lines)

    header_html = (
        '<div class="diff-header">'
        f'<span class="diff-labels">{html.escape(old_label)} &rarr; {html.escape(new_label)}</span>'
        f'<span class="diff-stats"><span class="diff-stat-add">+{additions}</span>'
        f' / <span class="diff-stat-del">-{deletions}</span></span>'
        "</div>"
    )

    if not groups:
        body = (
            '<div class="diff-container">'
            f"{header_html}"
            '<p class="diff-empty">No changes between revisions.</p>'
            "</div>"
        )
        return body, 0, 0, 0

    is_split = mode == "split"
    table_cls = "diff-table diff-split" if is_split else "diff-table"
    colspan = 4
    rows: list[str] = []

    for group in groups:
        hunk_title = _format_hunk_header(group, new_headings, old_headings)
        rows.append(
            f'<tr class="diff-hunk-heading"><td colspan="{colspan}">{hunk_title}</td></tr>'
        )
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for off in range(i2 - i1):
                    old_no = i1 + off + 1
                    new_no = j1 + off + 1
                    esc = html.escape(old_lines[i1 + off])
                    if is_split:
                        rows.append(
                            '<tr class="diff-line-ctx">'
                            f'<td class="diff-ln">{old_no}</td><td class="diff-code">{esc}</td>'
                            f'<td class="diff-ln">{new_no}</td><td class="diff-code">{esc}</td>'
                            "</tr>"
                        )
                    else:
                        rows.append(
                            '<tr class="diff-line-ctx">'
                            f'<td class="diff-ln">{old_no}</td><td class="diff-ln">{new_no}</td>'
                            f'<td class="diff-sign"> </td><td class="diff-code">{esc}</td>'
                            "</tr>"
                        )
            elif tag == "delete":
                for idx in range(i1, i2):
                    esc = html.escape(old_lines[idx])
                    if is_split:
                        rows.append(
                            '<tr class="diff-line-del">'
                            f'<td class="diff-ln">{idx + 1}</td><td class="diff-code">{esc}</td>'
                            '<td class="diff-ln"></td><td class="diff-code"></td>'
                            "</tr>"
                        )
                    else:
                        rows.append(
                            '<tr class="diff-line-del">'
                            f'<td class="diff-ln">{idx + 1}</td><td class="diff-ln"></td>'
                            f'<td class="diff-sign">-</td><td class="diff-code">{esc}</td>'
                            "</tr>"
                        )
            elif tag == "insert":
                for idx in range(j1, j2):
                    esc = html.escape(new_lines[idx])
                    if is_split:
                        rows.append(
                            '<tr class="diff-line-add">'
                            '<td class="diff-ln"></td><td class="diff-code"></td>'
                            f'<td class="diff-ln">{idx + 1}</td><td class="diff-code">{esc}</td>'
                            "</tr>"
                        )
                    else:
                        rows.append(
                            '<tr class="diff-line-add">'
                            f'<td class="diff-ln"></td><td class="diff-ln">{idx + 1}</td>'
                            f'<td class="diff-sign">+</td><td class="diff-code">{esc}</td>'
                            "</tr>"
                        )
            elif tag == "replace":
                old_slice = old_lines[i1:i2]
                new_slice = new_lines[j1:j2]
                paired = min(len(old_slice), len(new_slice))

                inline_old: list[str] = []
                inline_new: list[str] = []
                for k in range(paired):
                    o_html, n_html = _render_inline_pair(old_slice[k], new_slice[k])
                    inline_old.append(o_html)
                    inline_new.append(n_html)
                for k in range(paired, len(old_slice)):
                    inline_old.append(html.escape(old_slice[k]))
                for k in range(paired, len(new_slice)):
                    inline_new.append(html.escape(new_slice[k]))

                if is_split:
                    total = max(len(inline_old), len(inline_new))
                    for k in range(total):
                        has_old = k < len(inline_old)
                        has_new = k < len(inline_new)
                        o_ln = str(i1 + k + 1) if has_old else ""
                        o_code = inline_old[k] if has_old else ""
                        n_ln = str(j1 + k + 1) if has_new else ""
                        n_code = inline_new[k] if has_new else ""
                        cls = "diff-line-del" if has_old and not has_new else (
                            "diff-line-add" if has_new and not has_old else "diff-line-del diff-line-add"
                        )
                        rows.append(
                            f'<tr class="{cls}">'
                            f'<td class="diff-ln">{o_ln}</td><td class="diff-code">{o_code}</td>'
                            f'<td class="diff-ln">{n_ln}</td><td class="diff-code">{n_code}</td>'
                            "</tr>"
                        )
                else:
                    for k, o_html in enumerate(inline_old):
                        rows.append(
                            '<tr class="diff-line-del">'
                            f'<td class="diff-ln">{i1 + k + 1}</td><td class="diff-ln"></td>'
                            f'<td class="diff-sign">-</td><td class="diff-code">{o_html}</td>'
                            "</tr>"
                        )
                    for k, n_html in enumerate(inline_new):
                        rows.append(
                            '<tr class="diff-line-add">'
                            f'<td class="diff-ln"></td><td class="diff-ln">{j1 + k + 1}</td>'
                            f'<td class="diff-sign">+</td><td class="diff-code">{n_html}</td>'
                            "</tr>"
                        )

    full_html = (
        '<div class="diff-container">'
        f"{header_html}"
        f'<table class="{table_cls}"><tbody>{"".join(rows)}</tbody></table>'
        "</div>"
    )
    return full_html, additions, deletions, hunks_count


def diff_texts(
    old_text: str,
    new_text: str,
    old_label: str = "Before",
    new_label: str = "After",
    mode: str = "unified",
) -> DiffReport:
    """Compare two strings and produce a DiffReport with rendered HTML."""
    norm_mode = mode if mode in ("unified", "split") else "unified"
    diff_html, adds, dels, hunks = render_diff_html(
        old_text, new_text, old_label=old_label, new_label=new_label, mode=norm_mode
    )
    return DiffReport(
        old_label=old_label,
        new_label=new_label,
        additions=adds,
        deletions=dels,
        hunks_count=hunks,
        html=diff_html,
        error=None,
    )


def diff_files(path_a: str, path_b: str, mode: str = "unified") -> DiffReport:
    """Read two files and compare them, returning a non-crashing DiffReport on error."""
    try:
        text_a = Path(path_a).read_text(encoding="utf-8", errors="replace")
        text_b = Path(path_b).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return DiffReport(
            old_label=path_a,
            new_label=path_b,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"Failed to read file for diff: {exc}",
        )
    return diff_texts(
        text_a,
        text_b,
        old_label=Path(path_a).name,
        new_label=Path(path_b).name,
        mode=mode,
    )


def diff_git_head(
    file_path: str, revision: str = "HEAD", mode: str = "unified"
) -> DiffReport:
    """Compare a working-tree file against a git revision without crashing on errors."""
    if not revision or revision.startswith("-"):
        return DiffReport(
            old_label=revision or "HEAD",
            new_label=file_path,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"Invalid git revision: {revision!r}",
        )

    target = Path(file_path).resolve()
    if not target.is_file():
        return DiffReport(
            old_label=f"{revision}:{file_path}",
            new_label=file_path,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"File not found: {file_path}",
        )

    try:
        top_proc = subprocess.run(
            ["git", "-C", str(target.parent), "rev-parse", "--show-toplevel"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return DiffReport(
            old_label=f"{revision}:{target.name}",
            new_label=target.name,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"Git command failed: {exc}",
        )

    if top_proc.returncode != 0:
        err = top_proc.stderr.strip() or "Not inside a git repository."
        return DiffReport(
            old_label=f"{revision}:{target.name}",
            new_label=target.name,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=err,
        )

    repo_root = str(Path(top_proc.stdout.strip()).resolve())
    relpath = Path(os.path.relpath(target, repo_root)).as_posix()

    try:
        ls_proc = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--error-unmatch", "--", relpath],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ls_proc.returncode != 0:
            return DiffReport(
                old_label=f"{revision}:{relpath}",
                new_label=relpath,
                additions=0,
                deletions=0,
                hunks_count=0,
                html="",
                error=f"File is untracked in git: {relpath}",
            )

        show_proc = subprocess.run(
            ["git", "-C", repo_root, "show", f"{revision}:{relpath}"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return DiffReport(
            old_label=f"{revision}:{relpath}",
            new_label=relpath,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"Git command failed: {exc}",
        )

    if show_proc.returncode != 0:
        err = show_proc.stderr.strip() or f"Revision {revision}:{relpath} not found."
        return DiffReport(
            old_label=f"{revision}:{relpath}",
            new_label=relpath,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=err,
        )

    try:
        new_text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return DiffReport(
            old_label=f"{revision}:{relpath}",
            new_label=relpath,
            additions=0,
            deletions=0,
            hunks_count=0,
            html="",
            error=f"Failed to read working file: {exc}",
        )

    return diff_texts(
        show_proc.stdout,
        new_text,
        old_label=f"{relpath} ({revision})",
        new_label=f"{relpath} (Working Tree)",
        mode=mode,
    )
