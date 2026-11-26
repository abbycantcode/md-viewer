"""Document context inspector: heuristic token counts, section breakdown, and agentic checks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from mdviewer.agentic_env import AgenticArtifact, classify_agentic_file

PROSE_CHARS_PER_TOKEN = 4.2
CODE_CHARS_PER_TOKEN = 3.4
LARGE_SECTION_TOKEN_THRESHOLD = 2000
SKILL_FILENAMES = frozenset({"SKILL.MD", "AGENTS.MD", "CLAUDE.MD", "GEMINI.MD"})

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|\Z)", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass
class SectionStats:
    """Token and size breakdown for a single document section."""

    title: str
    level: int
    line: int
    words: int
    chars: int
    est_tokens: int
    pct_of_total: float


@dataclass
class DocumentContextReport:
    """Summary of document size, heuristic tokens, sections, and agentic-doc warnings."""

    words: int
    chars: int
    lines: int
    bytes_size: int
    reading_minutes: int
    est_tokens: int
    prose_tokens: int
    code_tokens: int
    sections: list[SectionStats]
    is_skill_doc: bool
    front_matter_keys: list[str]
    warnings: list[str]
    agentic_artifact: AgenticArtifact | None = None
    broken_links: list[str] = field(default_factory=list)


def _extract_front_matter(text: str) -> tuple[dict | None, list[str], int, bool]:
    """Return (parsed_dict, keys, start_line_offset_0_based, had_front_matter)."""
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return None, [], 0, False

    raw_yaml = match.group(1)
    body_start = match.end()
    line_offset = text[:body_start].count("\n")

    if yaml is not None:
        try:
            data = yaml.safe_load(raw_yaml)
            if isinstance(data, dict):
                return data, [str(k) for k in data.keys()], line_offset, True
        except Exception:
            return None, [], line_offset, True
    return None, [], line_offset, True


def _measure_prose_and_code(lines: list[str]) -> tuple[int, int]:
    """Split lines into prose characters and fenced-code characters."""
    prose_chars = 0
    code_chars = 0
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line in lines:
        if not in_fence:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                seq = m.group(1)
                info = m.group(2)
                # Backtick info strings cannot contain backticks in CommonMark
                if not (seq[0] == "`" and "`" in info):
                    in_fence = True
                    fence_char = seq[0]
                    fence_len = len(seq)
                    code_chars += len(line)
                    continue
            prose_chars += len(line)
        else:
            code_chars += len(line)
            stripped = line.strip()
            if (
                stripped
                and len(stripped) >= fence_len
                and set(stripped) == {fence_char}
            ):
                in_fence = False
                fence_char = ""
                fence_len = 0

    return prose_chars, code_chars


def _estimate_tokens_for_lines(lines: list[str]) -> tuple[int, int, int]:
    """Return (est_tokens, prose_tokens, code_tokens) using heuristic char/token ratios."""
    prose_chars, code_chars = _measure_prose_and_code(lines)
    prose_tokens = math.floor(prose_chars / PROSE_CHARS_PER_TOKEN) if prose_chars else 0
    code_tokens = math.floor(code_chars / CODE_CHARS_PER_TOKEN) if code_chars else 0
    return prose_tokens + code_tokens, prose_tokens, code_tokens


def _split_sections(
    all_lines: list[str], body_start_idx: int
) -> list[tuple[str, int, int, list[str]]]:
    """Split body lines into (title, level, 1-based line, lines) segments."""
    segments: list[tuple[str, int, int, list[str]]] = []
    cur_title = "(Preamble)"
    cur_level = 0
    cur_line = 1
    cur_lines: list[str] = list(all_lines[:body_start_idx])

    in_fence = False
    fence_char = ""
    fence_len = 0

    for idx in range(body_start_idx, len(all_lines)):
        line = all_lines[idx]
        if not in_fence:
            fm = _FENCE_OPEN_RE.match(line)
            if fm:
                seq = fm.group(1)
                info = fm.group(2)
                if not (seq[0] == "`" and "`" in info):
                    in_fence = True
                    fence_char = seq[0]
                    fence_len = len(seq)
                    cur_lines.append(line)
                    continue

            hm = _ATX_HEADING_RE.match(line)
            if hm:
                if cur_level > 0 or any(item.strip() for item in cur_lines):
                    segments.append((cur_title, cur_level, cur_line, cur_lines))
                cur_level = len(hm.group(1))
                cur_title = (hm.group(2) or "").strip() or "(Untitled)"
                cur_line = idx + 1
                cur_lines = [line]
                continue
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

        cur_lines.append(line)

    if cur_level > 0 or any(item.strip() for item in cur_lines):
        segments.append((cur_title, cur_level, cur_line, cur_lines))

    return segments


def _find_broken_local_links(
    all_lines: list[str],
    body_start_idx: int,
    file_path: str | None,
) -> list[str]:
    """Return missing relative local file targets referenced in Markdown links."""
    if not file_path:
        return []
    doc_path = Path(file_path).expanduser()
    base_dir = doc_path.parent
    # Only check relative paths against disk when the parent directory actually exists.
    if not base_dir.is_dir():
        return []

    broken: list[str] = []
    seen: set[str] = set()
    in_fence = False
    fence_char = ""
    fence_len = 0

    for idx in range(body_start_idx, len(all_lines)):
        line = all_lines[idx]
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
            continue

        cleaned_line = _INLINE_CODE_RE.sub("", line)
        for match in _MD_LINK_RE.finditer(cleaned_line):
            raw_dest = match.group(1).strip()
            if not raw_dest:
                continue
            if raw_dest.startswith("<") and ">" in raw_dest:
                dest = raw_dest[1 : raw_dest.index(">")].strip()
            else:
                dest = raw_dest.split()[0].strip()

            if not dest or dest.startswith("#") or dest.startswith("//"):
                continue
            if _URI_SCHEME_RE.match(dest):
                continue

            path_part = dest.split("#", 1)[0].split("?", 1)[0].strip()
            if not path_part or path_part.startswith("/"):
                continue

            decoded = unquote(path_part)
            try:
                candidate = (base_dir / decoded).resolve()
                exists = candidate.exists()
            except OSError:
                exists = False

            if not exists and path_part not in seen:
                seen.add(path_part)
                broken.append(path_part)

    return broken


def analyze_document(text: str, file_path: str | None = None) -> DocumentContextReport:
    """Analyze a Markdown or agentic document and return heuristic context metrics."""
    words = len(text.split())
    chars = len(text)
    all_lines = text.splitlines(keepends=True)
    lines = len(text.splitlines())
    bytes_size = len(text.encode("utf-8"))
    reading_minutes = max(1, math.ceil(words / 200)) if words > 0 else 0

    fm_data, fm_keys, body_start_idx, had_fm = _extract_front_matter(text)
    est_tokens, prose_tokens, code_tokens = _estimate_tokens_for_lines(all_lines)

    raw_segments = _split_sections(all_lines, body_start_idx)
    sections: list[SectionStats] = []
    for title, level, line_no, seg_lines in raw_segments:
        seg_text = "".join(seg_lines)
        seg_tokens, _, _ = _estimate_tokens_for_lines(seg_lines)
        pct = round((seg_tokens / est_tokens) * 100.0, 1) if est_tokens > 0 else 0.0
        sections.append(
            SectionStats(
                title=title,
                level=level,
                line=line_no,
                words=len(seg_text.split()),
                chars=len(seg_text),
                est_tokens=seg_tokens,
                pct_of_total=pct,
            )
        )

    basename = Path(file_path).name.upper() if file_path else ""
    basename_lower = Path(file_path).name.lower() if file_path else ""
    artifact = classify_agentic_file(file_path) if file_path else None
    is_skill_doc = basename in SKILL_FILENAMES or (
        artifact is not None and artifact.kind in ("skill", "agent", "rule", "command", "prompt")
    )

    warnings: list[str] = []

    # Tailored checks by agentic file type
    if basename == "SKILL.MD":
        if not had_fm:
            warnings.append("SKILL.md is missing YAML front-matter with 'name' and 'description'.")
        elif fm_data is None:
            warnings.append("SKILL.md front-matter could not be parsed as a YAML mapping.")
        else:
            missing = [
                k for k in ("name", "description")
                if not str(fm_data.get(k, "") or "").strip()
            ]
            if missing:
                joined = ", ".join(f"'{k}'" for k in missing)
                warnings.append(f"SKILL.md front-matter is missing required {joined} metadata.")
    elif basename_lower.endswith(".mdc"):
        if not had_fm:
            warnings.append(
                "Cursor .mdc rule is missing YAML front-matter ('description' and 'globs' or 'alwaysApply')."
            )
        elif fm_data is None:
            warnings.append("Cursor .mdc rule front-matter could not be parsed as a YAML mapping.")
        else:
            if not str(fm_data.get("description", "") or "").strip():
                warnings.append("Cursor .mdc rule front-matter is missing 'description'.")
            has_globs = bool(fm_data.get("globs"))
            has_always = "alwaysApply" in fm_data or "always_apply" in fm_data
            if not has_globs and not has_always:
                warnings.append(
                    "Cursor .mdc rule front-matter should declare 'globs' or 'alwaysApply'."
                )
    elif basename_lower == "agent.md" or (
        artifact is not None and artifact.kind == "agent" and basename_lower.endswith(".md")
    ):
        if had_fm and fm_data is None:
            warnings.append("Agent definition front-matter could not be parsed as a YAML mapping.")
        has_heading = any(s.level > 0 for s in sections)
        has_meta_id = bool(
            fm_data
            and (
                str(fm_data.get("name", "") or "").strip()
                or str(fm_data.get("description", "") or "").strip()
            )
        )
        if not has_heading and not has_meta_id:
            warnings.append(
                "Agent definition lacks a heading or front-matter 'name'/'description'."
            )
    elif basename in ("AGENTS.MD", "CLAUDE.MD", "GEMINI.MD"):
        if had_fm and fm_data is None:
            warnings.append(f"{Path(file_path).name} front-matter could not be parsed as YAML.")

    # Broken local relative links check
    broken_links = _find_broken_local_links(all_lines, body_start_idx, file_path)
    for target in broken_links:
        warnings.append(f"Broken local link: '{target}' (target file not found).")

    for sec in sections:
        if sec.est_tokens > LARGE_SECTION_TOKEN_THRESHOLD:
            warnings.append(
                f"Section '{sec.title}' (line {sec.line}) is ~{sec.est_tokens} est. tokens "
                f"(> {LARGE_SECTION_TOKEN_THRESHOLD})."
            )

    return DocumentContextReport(
        words=words,
        chars=chars,
        lines=lines,
        bytes_size=bytes_size,
        reading_minutes=reading_minutes,
        est_tokens=est_tokens,
        prose_tokens=prose_tokens,
        code_tokens=code_tokens,
        sections=sections,
        is_skill_doc=is_skill_doc,
        front_matter_keys=fm_keys,
        warnings=warnings,
        agentic_artifact=artifact,
        broken_links=broken_links,
    )
