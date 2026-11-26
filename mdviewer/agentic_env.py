"""Offline-first discovery and classification of Global & Project agentic environments."""

from __future__ import annotations

import fnmatch
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

MAX_SCAN_DEPTH = 4
HEAD_READ_BYTES = 2048
MAX_SIBLING_LINKS = 12
CACHE_TTL_SECONDS = 30.0

DENIED_DIRS: frozenset[str] = frozenset(
    {
        "sessions",
        "archived_sessions",
        "session-env",
        "brain",
        "conversations",
        "projects",
        "chats",
        "history",
        "file-history",
        "shell-snapshots",
        "paste-cache",
        "telemetry",
        "backups",
        "downloads",
        ".trash",
        "cache",
        "logs",
        "log",
        "debug",
        "node_modules",
        ".git",
        ".venv",
        "__pycache__",
        "worktrees",
        "tmp",
        ".ruff_cache",
        "extensions",
        "ai-tracking",
        "marketplace-cache",
    }
)

SENSITIVE_FILE_PATTERNS: tuple[str, ...] = (
    "*credentials*",
    "*auth*",
    "*secret*",
    "*token*",
    "*accounts*",
    "*.env",
    ".env",
    ".env.*",
    "*.sqlite",
    "*.sqlite*",
    "*.db",
    "*.jsonl",
    "*.key",
    "*.pem",
)

_SENSITIVE_FILENAME_RE = re.compile(
    "|".join(fnmatch.translate(pat) for pat in SENSITIVE_FILE_PATTERNS),
    re.IGNORECASE,
)

KNOWN_CONFIG_FILES: frozenset[str] = frozenset(
    {
        "config.toml",
        "opencode.json",
        "settings.json",
        "cli-config.json",
        "skills-registry.yaml",
    }
)

_TEXT_ARTIFACT_EXTS: frozenset[str] = frozenset(
    {".md", ".markdown", ".mdc", ".rules", ".txt"}
)
_AGENT_DIR_EXTS: frozenset[str] = frozenset(
    {".md", ".markdown", ".mdc", ".rules", ".toml", ".yaml", ".yml", ".txt"}
)

_PROJECT_ROOT_MARKERS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".claude",
    ".codex",
    ".agents",
    ".gemini",
    ".cursor",
    ".opencode",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
)

_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FRONTMATTER_CLOSE_RE = re.compile(r"\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)")

_CATALOG_CACHE: dict[tuple[str | None, bool], tuple[float, AgenticCatalog]] = {}
_HEAD_META_CACHE: dict[tuple[int, int, int], tuple[str, str, tuple[str, ...], tuple[str, ...], bool]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class AgenticArtifact:
    """Metadata for a single discovered agentic skill, agent, rule, or config artifact."""

    path: str
    rel_path: str
    env_source: str  # claude|codex|gemini|agents|cursor|opencode|grok|project
    scope: str  # global|project
    kind: str  # skill|agent|rule|command|reference|prompt|memory|config
    name: str
    description: str
    triggers: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    always_apply: bool = False
    size_bytes: int = 0
    mtime: float = 0.0
    sibling_links: tuple[tuple[str, str], ...] = ()

    def to_banner_dict(self, token_estimate: int | None = None) -> dict[str, Any]:
        """Serialize metadata for Markveil's editorial Agentic Classification Strip."""
        est = (
            token_estimate
            if token_estimate is not None
            else (max(1, round(self.size_bytes / 4.2)) if self.size_bytes > 0 else 0)
        )
        return {
            "path": self.path,
            "rel_path": self.rel_path,
            "env_source": self.env_source,
            "scope": self.scope,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "globs": list(self.globs),
            "always_apply": self.always_apply,
            "sibling_links": list(self.sibling_links),
            "token_estimate": est,
        }


@dataclass
class AgenticCatalog:
    """Collection of discovered global and project-local agentic artifacts."""

    artifacts: tuple[AgenticArtifact, ...]
    project_root: str | None
    scan_ms: float

    def filter(
        self,
        scope: str = "all",
        env_source: str = "all",
        kind: str = "all",
        query: str = "",
    ) -> list[AgenticArtifact]:
        """Filter artifacts by scope, environment, kind, and free-text query."""
        scope_f = (scope or "all").strip().lower()
        env_f = (env_source or "all").strip().lower()
        kind_f = (kind or "all").strip().lower()
        q = (query or "").strip().lower()

        results: list[AgenticArtifact] = []
        for art in self.artifacts:
            if scope_f and scope_f != "all" and art.scope != scope_f:
                continue
            if env_f and env_f != "all" and art.env_source != env_f:
                continue
            if kind_f and kind_f != "all" and art.kind != kind_f:
                continue
            if q:
                haystack = " ".join(
                    (
                        art.name,
                        art.description,
                        art.rel_path,
                        art.env_source,
                        art.kind,
                        " ".join(art.triggers),
                        " ".join(art.globs),
                    )
                ).lower()
                if q not in haystack:
                    continue
            results.append(art)
        return results

    def counts_by_env(self) -> dict[str, int]:
        """Return artifact counts grouped by env_source."""
        counts: dict[str, int] = {}
        for art in self.artifacts:
            counts[art.env_source] = counts.get(art.env_source, 0) + 1
        return counts

    def counts_by_kind(self) -> dict[str, int]:
        """Return artifact counts grouped by kind."""
        counts: dict[str, int] = {}
        for art in self.artifacts:
            counts[art.kind] = counts.get(art.kind, 0) + 1
        return counts


def clear_catalog_cache() -> None:
    """Clear the in-memory agentic catalog cache."""
    with _CACHE_LOCK:
        _CATALOG_CACHE.clear()
        _HEAD_META_CACHE.clear()


def is_sensitive_filename(filename: str) -> bool:
    """Return True if a filename matches the strict secret/session denylist."""
    return bool(_SENSITIVE_FILENAME_RE.match(filename))


def is_denied_path(path: Path, relative_to: Path | None = None) -> bool:
    """Return True if filename is sensitive or any scoped directory component is denied."""
    if is_sensitive_filename(path.name):
        return True
    check_path = path
    if relative_to is not None:
        try:
            check_path = path.relative_to(relative_to)
        except ValueError:
            check_path = path
    parts = check_path.parts
    if not parts:
        return False
    for part in parts[:-1]:
        if part.lower() in DENIED_DIRS:
            return True
    return parts[-1].lower() in DENIED_DIRS


def find_project_root(path: str | Path | None = None) -> Path | None:
    """Locate the enclosing project/repository root without climbing into $HOME."""
    try:
        start = Path.cwd() if path is None else Path(path).expanduser()
        if not start.is_absolute():
            start = (Path.cwd() / start).resolve()
        else:
            start = Path(os.path.abspath(str(start)))
    except OSError:
        return None

    cur = start.parent if start.is_file() or (not start.exists() and start.suffix) else start
    home = Path(os.path.abspath(str(Path.home())))

    fallback: Path | None = None
    while True:
        if cur == home or cur == cur.parent:
            break
        if (cur / ".git").exists():
            return cur
        if fallback is None:
            for marker in _PROJECT_ROOT_MARKERS:
                if (cur / marker).exists():
                    fallback = cur
                    break
        cur = cur.parent

    return fallback


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
        return tuple(items)
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is not None:
                s = str(item).strip()
                if s:
                    out.append(s)
        return tuple(out)
    s = str(value).strip()
    return (s,) if s else ()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return False


def _strip_yaml_quotes(value: str) -> str:
    val = value.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    return val


def _parse_frontmatter_fast(raw_yaml: str) -> dict[str, Any] | None:
    """Fast stdlib parser for common flat YAML frontmatter; returns None to trigger PyYAML."""
    result: dict[str, Any] = {}
    lines = raw_yaml.splitlines()
    idx = 0
    n = len(lines)

    while idx < n:
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        if line[0] in (" ", "\t") or ":" not in line:
            return None

        key_raw, _, val_raw = line.partition(":")
        key = key_raw.strip()
        if not key:
            return None
        val = val_raw.strip()

        if val in ("|", ">", "|-", ">-", "|+", ">+"):
            block_lines: list[str] = []
            idx += 1
            while idx < n and (lines[idx].startswith((" ", "\t")) or not lines[idx].strip()):
                block_lines.append(lines[idx].strip())
                idx += 1
            joiner = " " if val.startswith(">") else "\n"
            result[key] = joiner.join(part for part in block_lines if part).strip()
            continue

        if not val:
            items: list[str] = []
            idx += 1
            while idx < n:
                sub = lines[idx]
                sub_strip = sub.strip()
                if not sub_strip or sub_strip.startswith("#"):
                    idx += 1
                    continue
                if sub.startswith((" ", "\t")) and sub_strip.startswith("- "):
                    items.append(_strip_yaml_quotes(sub_strip[2:]))
                    idx += 1
                elif sub.startswith((" ", "\t")):
                    # Nested mapping -> let PyYAML handle it cleanly.
                    return None
                else:
                    break
            result[key] = items
            continue

        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                result[key] = []
            else:
                result[key] = [_strip_yaml_quotes(part) for part in inner.split(",") if part.strip()]
            idx += 1
            continue

        low = val.lower()
        if low == "true":
            result[key] = True
        elif low == "false":
            result[key] = False
        else:
            result[key] = _strip_yaml_quotes(val)
        idx += 1

    return result


def _parse_head_metadata(
    file_path: Path | str,
    st: os.stat_result | None = None,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], bool]:
    """Read at most HEAD_READ_BYTES and extract (name, description, triggers, globs, always_apply)."""
    cache_key: tuple[int, int, int] | None = None
    if st is not None and st.st_ino:
        cache_key = (st.st_dev, st.st_ino, st.st_mtime_ns)
        cached = _HEAD_META_CACHE.get(cache_key)
        if cached is not None:
            return cached

    try:
        with open(file_path, "rb") as fh:
            raw = fh.read(HEAD_READ_BYTES)
    except OSError:
        return "", "", (), (), False

    if b"\x00" in raw:
        return "", "", (), (), False

    text = raw.decode("utf-8", errors="replace")
    fm_data: dict[str, Any] | None = None
    body_text = text

    if text.startswith("---\n") or text.startswith("---\r\n"):
        nl_idx = text.find("\n")
        close_match = _FRONTMATTER_CLOSE_RE.search(text, nl_idx)
        if close_match:
            raw_yaml = text[nl_idx + 1 : close_match.start()]
            body_text = text[close_match.end() :]
            fm_data = _parse_frontmatter_fast(raw_yaml)
            if fm_data is None and yaml is not None:
                try:
                    parsed = yaml.safe_load(raw_yaml)
                    if isinstance(parsed, dict):
                        fm_data = parsed
                except Exception:
                    fm_data = None

    name = ""
    description = ""
    triggers: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    always_apply = False

    if fm_data:
        raw_name = fm_data.get("name") or fm_data.get("title")
        if isinstance(raw_name, str):
            name = raw_name.strip()
        raw_desc = fm_data.get("description") or fm_data.get("summary")
        if isinstance(raw_desc, str):
            description = " ".join(raw_desc.split())[:240]
        triggers = _coerce_str_tuple(fm_data.get("triggers") or fm_data.get("trigger"))
        globs = _coerce_str_tuple(fm_data.get("globs") or fm_data.get("paths"))
        always_apply = _coerce_bool(
            fm_data.get("alwaysApply")
            if "alwaysApply" in fm_data
            else fm_data.get("always_apply")
        )

    if not description:
        for line in body_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            hm = _HEADING_RE.match(stripped)
            if hm:
                description = hm.group(1).strip()[:160]
                break
            if not stripped.startswith(("```", "~~~", "<!--")):
                description = stripped[:160]
                break

    result = (name, description, triggers, globs, always_apply)
    if cache_key is not None and len(_HEAD_META_CACHE) < 8192:
        _HEAD_META_CACHE[cache_key] = result
    return result


def _collect_sibling_links(file_path: Path) -> tuple[tuple[str, str], ...]:
    """List readable sibling references/ and scripts/ entries for SKILL.md / agent.md."""
    parent = file_path.parent
    links: list[tuple[str, str]] = []
    for subdir_name in ("references", "scripts"):
        sub = parent / subdir_name
        if not sub.is_dir():
            continue
        try:
            with os.scandir(sub) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.name.lower() in DENIED_DIRS or is_sensitive_filename(entry.name):
                continue
            try:
                if not entry.is_file(follow_symlinks=True):
                    continue
            except OSError:
                continue
            links.append((f"{subdir_name}/{entry.name}", entry.path))
            if len(links) >= MAX_SIBLING_LINKS:
                return tuple(links)
    return tuple(links)


def _infer_kind(filename: str, rel_parts: tuple[str, ...]) -> str | None:
    """Deterministically infer artifact kind from filename and relative directory segments."""
    name_upper = filename.upper()
    name_lower = filename.lower()
    _, ext = os.path.splitext(name_lower)

    if name_upper == "SKILL.MD":
        return "skill"
    if name_upper in ("AGENTS.MD", "CLAUDE.MD", "GEMINI.MD") or name_lower == ".cursorrules":
        return "rule"
    if name_upper == "MEMORY.MD":
        return "memory"
    if name_lower == "agent.md":
        return "agent"
    if name_lower in KNOWN_CONFIG_FILES:
        return "config"

    # Walk parent directory segments from innermost to outermost.
    for seg in reversed(rel_parts[:-1]):
        seg_l = seg.lower()
        if seg_l == "references":
            return "reference"
        if seg_l == "commands":
            return "command"
        if seg_l == "prompts":
            return "prompt"
        if seg_l == "memory":
            return "memory"
        if seg_l == "rules":
            return "rule"
        if seg_l == "agents":
            return "agent"
        if seg_l in ("skills", "skills-cursor"):
            return "skill"
        if seg_l == "docs":
            return "reference"

    if ext in (".mdc", ".rules"):
        return "rule"
    return None


def _default_artifact_name(file_path: Path, kind: str) -> str:
    fname = file_path.name
    if fname.upper() in ("SKILL.MD", "AGENT.MD") and file_path.parent.name:
        return file_path.parent.name
    if fname.upper() in ("AGENTS.MD", "CLAUDE.MD", "GEMINI.MD", "MEMORY.MD") or fname.lower() == ".cursorrules":
        return fname
    if kind == "config":
        return fname
    return file_path.stem or fname


def _build_artifact(
    file_path: Path,
    rel_path: str,
    env_source: str,
    scope: str,
    kind: str,
    st: os.stat_result | None = None,
) -> AgenticArtifact | None:
    if st is None:
        try:
            st = file_path.stat()
        except OSError:
            return None

    # Never read bodies of config files (extra secret-safety guarantee).
    if kind == "config":
        name = _default_artifact_name(file_path, kind)
        return AgenticArtifact(
            path=str(file_path),
            rel_path=rel_path,
            env_source=env_source,
            scope=scope,
            kind=kind,
            name=name,
            description=f"{env_source} configuration ({file_path.name})",
            triggers=(),
            globs=(),
            always_apply=False,
            size_bytes=st.st_size,
            mtime=st.st_mtime,
            sibling_links=(),
        )

    fm_name, description, triggers, globs, always_apply = _parse_head_metadata(file_path, st=st)
    name = fm_name or _default_artifact_name(file_path, kind)

    sibling_links: tuple[tuple[str, str], ...] = ()
    if file_path.name.upper() in ("SKILL.MD", "AGENT.MD"):
        sibling_links = _collect_sibling_links(file_path)

    return AgenticArtifact(
        path=str(file_path),
        rel_path=rel_path,
        env_source=env_source,
        scope=scope,
        kind=kind,
        name=name,
        description=description,
        triggers=triggers,
        globs=globs,
        always_apply=always_apply,
        size_bytes=st.st_size,
        mtime=st.st_mtime,
        sibling_links=sibling_links,
    )


def _global_root_specs(home: Path) -> list[tuple[Path, str, tuple[str, ...], tuple[str, ...]]]:
    """Return (root_dir, env_source, direct_files, allowlisted_subdirs) for global scanning."""
    return [
        (
            home / ".claude",
            "claude",
            ("CLAUDE.md", "settings.json"),
            ("skills", "commands", "agents", "rules", "prompts", "memory", "references"),
        ),
        (
            home / ".codex",
            "codex",
            ("AGENTS.md", "config.toml"),
            ("skills", "agents", "rules", "commands", "prompts", "memory", "references"),
        ),
        (
            home / ".agents",
            "agents",
            ("AGENTS.md", "skills-registry.yaml"),
            ("skills", "agents", "rules", "docs", "references", "prompts"),
        ),
        (
            home / ".gemini",
            "gemini",
            ("GEMINI.md", "settings.json"),
            (
                "config/skills",
                "config/agents",
                "config/rules",
                "config/commands",
                "config/prompts",
                "antigravity/builtin/skills",
                "skills",
                "agents",
                "rules",
                "commands",
            ),
        ),
        (
            home / ".cursor",
            "cursor",
            ("cli-config.json", ".cursorrules"),
            ("agents", "skills-cursor", "skills", "rules", "commands", "prompts"),
        ),
        (
            home / ".config" / "opencode",
            "opencode",
            ("AGENTS.md", "opencode.json"),
            (
                "skills",
                "agents",
                "commands",
                "memory",
                "rules",
                "prompts",
                ".opencode/agents",
                ".opencode/commands",
                ".opencode/memory",
                ".opencode/skills",
                ".opencode/rules",
            ),
        ),
        (
            home / ".grok",
            "grok",
            ("config.toml", "AGENTS.md"),
            ("skills", "docs", "agents", "rules", "prompts"),
        ),
    ]


def _standalone_global_files(home: Path) -> list[tuple[Path, str, str]]:
    """Return (file_path, env_source, rel_path) for standalone global instruction files."""
    return [
        (home / ".config" / "CLAUDE.md", "claude", "~/.config/CLAUDE.md"),
        (home / ".config" / "GEMINI.md", "gemini", "~/.config/GEMINI.md"),
        (home / ".antigravity" / "GEMINI.md", "gemini", "~/.antigravity/GEMINI.md"),
    ]


def _project_root_specs(root: Path) -> list[tuple[Path, str, tuple[str, ...], tuple[str, ...]]]:
    """Return (dir_path, env_source, direct_files, allowlisted_subdirs) for project scanning."""
    return [
        (
            root / ".claude",
            "claude",
            ("CLAUDE.md", "settings.json"),
            ("skills", "agents", "commands", "rules", "prompts", "memory", "references"),
        ),
        (
            root / ".codex",
            "codex",
            ("AGENTS.md", "config.toml"),
            ("skills", "agents", "rules", "commands", "prompts", "memory", "references"),
        ),
        (
            root / ".agents",
            "agents",
            ("AGENTS.md", "skills-registry.yaml"),
            ("skills", "agents", "rules", "references", "docs"),
        ),
        (
            root / ".gemini",
            "gemini",
            ("GEMINI.md", "settings.json"),
            ("skills", "agents", "rules", "commands", "prompts"),
        ),
        (
            root / ".cursor",
            "cursor",
            (".cursorrules", "cli-config.json"),
            ("rules", "agents", "skills", "commands", "prompts"),
        ),
        (
            root / ".opencode",
            "opencode",
            ("AGENTS.md", "opencode.json"),
            ("skills", "agents", "commands", "memory", "rules", "prompts"),
        ),
        (
            root,
            "project",
            (),
            ("skills", "agents", "rules", "references", "prompts"),
        ),
    ]


def _project_direct_files(root: Path) -> list[tuple[Path, str, str]]:
    """Return (file_path, env_source, kind) for root-level project agentic files."""
    return [
        (root / "AGENTS.md", "agents", "rule"),
        (root / "CLAUDE.md", "claude", "rule"),
        (root / "GEMINI.md", "gemini", "rule"),
        (root / ".cursorrules", "cursor", "rule"),
        (root / "MEMORY.md", "project", "memory"),
    ]


def _is_scannable_file(filename: str, inside_agent_dir: bool) -> bool:
    if _SENSITIVE_FILENAME_RE.match(filename):
        return False
    low = filename.lower()
    if low in KNOWN_CONFIG_FILES or low == ".cursorrules":
        return True
    _, ext = os.path.splitext(low)
    if inside_agent_dir:
        return ext in _AGENT_DIR_EXTS
    return ext in _TEXT_ARTIFACT_EXTS


def _scan_dir_bounded(
    base_dir: Path,
    rel_prefix: str,
    env_source: str,
    scope: str,
    artifacts: list[AgenticArtifact],
    seen_paths: set[str],
    max_depth: int = MAX_SCAN_DEPTH,
) -> None:
    """Iterative bounded-depth scanner using os.scandir with strict denylists."""
    if not base_dir.is_dir():
        return

    visited_real_dirs: set[str] = set()
    stack: list[tuple[str, tuple[str, ...], int]] = [(str(base_dir), tuple(rel_prefix.split("/")), 0)]

    while stack:
        cur_dir, rel_parts, depth = stack.pop()
        try:
            real_dir = os.path.realpath(cur_dir)
        except OSError:
            continue
        if real_dir in visited_real_dirs:
            continue
        visited_real_dirs.add(real_dir)

        try:
            with os.scandir(cur_dir) as it:
                entries = list(it)
        except OSError:
            continue

        in_agent_dir = any(p.lower() == "agents" for p in rel_parts)

        for entry in entries:
            name = entry.name
            low = name.lower()
            if low in DENIED_DIRS:
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=True)
            except OSError:
                continue

            if is_dir:
                if depth + 1 < max_depth and not (name.startswith(".") and low != ".opencode"):
                    stack.append((entry.path, (*rel_parts, name), depth + 1))
                continue

            if not _is_scannable_file(name, in_agent_dir):
                continue

            abs_path = os.path.abspath(entry.path)
            if abs_path in seen_paths:
                continue

            file_rel_parts = (*rel_parts, name)
            kind = _infer_kind(name, file_rel_parts)
            if kind is None:
                continue

            try:
                st = entry.stat(follow_symlinks=True)
            except OSError:
                continue

            rel_display = "/".join(file_rel_parts)
            art = _build_artifact(
                Path(abs_path),
                rel_path=rel_display,
                env_source=env_source,
                scope=scope,
                kind=kind,
                st=st,
            )
            if art is not None:
                seen_paths.add(abs_path)
                artifacts.append(art)


def _format_global_rel(path: Path, home: Path) -> str:
    try:
        rel = path.relative_to(home)
        return f"~/{rel.as_posix()}"
    except ValueError:
        return str(path)


def discover_agentic_catalog(
    project_root: str | Path | None = None,
    *,
    include_global: bool = True,
    force_refresh: bool = False,
) -> AgenticCatalog:
    """Scan allowlisted global and project agentic directories safely and quickly."""
    resolved_project: Path | None = None
    if project_root is not None:
        candidate = Path(project_root).expanduser()
        if candidate.is_file():
            candidate = candidate.parent
        if candidate.is_dir():
            resolved_project = Path(os.path.abspath(str(candidate)))
    else:
        resolved_project = find_project_root()

    cache_key = (str(resolved_project) if resolved_project else None, bool(include_global))
    if not force_refresh:
        with _CACHE_LOCK:
            cached = _CATALOG_CACHE.get(cache_key)
            if cached is not None and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
                return cached[1]

    t0 = time.perf_counter()
    artifacts: list[AgenticArtifact] = []
    seen_paths: set[str] = set()

    # 1. Project-local allowlisted roots
    if resolved_project is not None:
        for file_path, env_source, kind in _project_direct_files(resolved_project):
            if not file_path.is_file() or is_sensitive_filename(file_path.name):
                continue
            abs_p = os.path.abspath(str(file_path))
            if abs_p in seen_paths:
                continue
            art = _build_artifact(
                Path(abs_p),
                rel_path=file_path.name,
                env_source=env_source,
                scope="project",
                kind=kind,
            )
            if art is not None:
                seen_paths.add(abs_p)
                artifacts.append(art)

        for root_dir, env_source, direct_files, subdirs in _project_root_specs(resolved_project):
            if not root_dir.is_dir():
                continue
            for fname in direct_files:
                fpath = root_dir / fname
                if not fpath.is_file() or is_sensitive_filename(fname):
                    continue
                abs_p = os.path.abspath(str(fpath))
                if abs_p in seen_paths:
                    continue
                try:
                    rel_display = fpath.relative_to(resolved_project).as_posix()
                except ValueError:
                    rel_display = fname
                kind = _infer_kind(fname, tuple(rel_display.split("/")))
                if kind is None:
                    continue
                art = _build_artifact(
                    Path(abs_p),
                    rel_path=rel_display,
                    env_source=env_source,
                    scope="project",
                    kind=kind,
                )
                if art is not None:
                    seen_paths.add(abs_p)
                    artifacts.append(art)

            for sub in subdirs:
                sub_dir = root_dir / sub
                if not sub_dir.is_dir():
                    continue
                try:
                    rel_prefix = sub_dir.relative_to(resolved_project).as_posix()
                except ValueError:
                    rel_prefix = sub
                _scan_dir_bounded(
                    sub_dir,
                    rel_prefix=rel_prefix,
                    env_source=env_source,
                    scope="project",
                    artifacts=artifacts,
                    seen_paths=seen_paths,
                    max_depth=MAX_SCAN_DEPTH,
                )

    # 2. Global allowlisted roots
    if include_global:
        home = Path(os.path.abspath(str(Path.home())))

        for fpath, env_source, rel_display in _standalone_global_files(home):
            if not fpath.is_file() or is_sensitive_filename(fpath.name):
                continue
            abs_p = os.path.abspath(str(fpath))
            if abs_p in seen_paths:
                continue
            art = _build_artifact(
                Path(abs_p),
                rel_path=rel_display,
                env_source=env_source,
                scope="global",
                kind="rule",
            )
            if art is not None:
                seen_paths.add(abs_p)
                artifacts.append(art)

        for root_dir, env_source, direct_files, subdirs in _global_root_specs(home):
            if not root_dir.is_dir():
                continue
            for fname in direct_files:
                fpath = root_dir / fname
                if not fpath.is_file() or is_sensitive_filename(fname):
                    continue
                abs_p = os.path.abspath(str(fpath))
                if abs_p in seen_paths:
                    continue
                rel_display = _format_global_rel(fpath, home)
                kind = _infer_kind(fname, tuple(rel_display.split("/")))
                if kind is None:
                    continue
                art = _build_artifact(
                    Path(abs_p),
                    rel_path=rel_display,
                    env_source=env_source,
                    scope="global",
                    kind=kind,
                )
                if art is not None:
                    seen_paths.add(abs_p)
                    artifacts.append(art)

            for sub in subdirs:
                sub_dir = root_dir / sub
                if not sub_dir.is_dir():
                    continue
                rel_prefix = _format_global_rel(sub_dir, home)
                _scan_dir_bounded(
                    sub_dir,
                    rel_prefix=rel_prefix,
                    env_source=env_source,
                    scope="global",
                    artifacts=artifacts,
                    seen_paths=seen_paths,
                    max_depth=MAX_SCAN_DEPTH,
                )

    # Sort deterministically: project first, then by env_source, kind, name
    scope_rank = {"project": 0, "global": 1}
    artifacts.sort(
        key=lambda a: (scope_rank.get(a.scope, 2), a.env_source, a.kind, a.name.lower(), a.rel_path)
    )

    scan_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    catalog = AgenticCatalog(
        artifacts=tuple(artifacts),
        project_root=str(resolved_project) if resolved_project else None,
        scan_ms=scan_ms,
    )
    with _CACHE_LOCK:
        _CATALOG_CACHE[cache_key] = (time.monotonic(), catalog)
    return catalog


def discover_agentic_catalog_async(
    callback: Callable[[AgenticCatalog], None],
    project_root: str | Path | None = None,
    *,
    include_global: bool = True,
    force_refresh: bool = False,
) -> threading.Thread:
    """Run discover_agentic_catalog on a daemon thread and deliver result to callback."""

    def _worker() -> None:
        catalog = discover_agentic_catalog(
            project_root=project_root,
            include_global=include_global,
            force_refresh=force_refresh,
        )
        callback(catalog)

    thread = threading.Thread(
        target=_worker,
        name="mdv-agentic-scan",
        daemon=True,
    )
    thread.start()
    return thread


def classify_agentic_file(
    path: str | Path | None,
    project_root: str | Path | None = None,
) -> AgenticArtifact | None:
    """Classify a single file path as an AgenticArtifact, or return None if non-agentic/denied."""
    if not path:
        return None
    try:
        file_path = Path(os.path.abspath(str(Path(path).expanduser())))
    except OSError:
        return None

    if is_sensitive_filename(file_path.name) or file_path.name.lower() in DENIED_DIRS:
        return None

    home = Path(os.path.abspath(str(Path.home())))

    # Resolve enclosing project root (if any) so git worktrees nested under e.g.
    # ~/.gemini/antigravity/worktrees/... are still recognized as project files.
    resolved_project: Path | None = None
    if project_root is not None:
        resolved_project = Path(os.path.abspath(str(Path(project_root).expanduser())))
    else:
        resolved_project = find_project_root(file_path)

    # Check global standalone files first
    for gpath, env_source, rel_display in _standalone_global_files(home):
        if os.path.abspath(str(gpath)) == str(file_path):
            return _build_artifact(
                file_path,
                rel_path=rel_display,
                env_source=env_source,
                scope="global",
                kind="rule",
            )

    # Check global roots
    matched_global_root: Path | None = None
    for root_dir, env_source, _direct_files, _subdirs in _global_root_specs(home):
        root_abs = Path(os.path.abspath(str(root_dir)))
        try:
            rel_under_root = file_path.relative_to(root_abs)
        except ValueError:
            continue
        matched_global_root = root_abs
        if any(part.lower() in DENIED_DIRS for part in rel_under_root.parts[:-1]):
            # Only fall through to project classification if a distinct project root
            # exists strictly inside this global root (e.g. a git worktree).
            if resolved_project is not None:
                try:
                    resolved_project.relative_to(root_abs)
                    if resolved_project != root_abs:
                        break
                except ValueError:
                    pass
            return None
        kind = _infer_kind(file_path.name, rel_under_root.parts)
        if kind is None:
            return None
        return _build_artifact(
            file_path,
            rel_path=_format_global_rel(file_path, home),
            env_source=env_source,
            scope="global",
            kind=kind,
        )

    # If inside a global root but not a deeper project root, do not misclassify as project
    if matched_global_root is not None and resolved_project is None:
        return None

    # Check project-local classification
    rel_parts: tuple[str, ...]
    if resolved_project is not None:
        try:
            rel = file_path.relative_to(resolved_project)
            if is_denied_path(file_path, relative_to=resolved_project):
                return None
            rel_parts = rel.parts
            rel_display = rel.as_posix()
        except ValueError:
            rel_parts = file_path.parts[-3:]
            rel_display = file_path.name
    else:
        # Without a known project root, check immediate parent dirs (not system /tmp)
        tail = file_path.parts[-3:]
        if any(p.lower() in DENIED_DIRS for p in tail[:-1]):
            return None
        rel_parts = tail
        rel_display = file_path.name

    kind = _infer_kind(file_path.name, rel_parts)
    if kind is None:
        return None

    # Determine env_source for project file
    parts_lower = [p.lower() for p in rel_parts[:-1]]
    fname_upper = file_path.name.upper()
    fname_lower = file_path.name.lower()

    if ".claude" in parts_lower or fname_upper == "CLAUDE.MD":
        env_source = "claude"
    elif ".codex" in parts_lower:
        env_source = "codex"
    elif ".gemini" in parts_lower or fname_upper == "GEMINI.MD":
        env_source = "gemini"
    elif ".agents" in parts_lower or fname_upper == "AGENTS.MD":
        env_source = "agents"
    elif ".cursor" in parts_lower or fname_lower == ".cursorrules" or fname_lower.endswith(".mdc"):
        env_source = "cursor"
    elif ".opencode" in parts_lower or fname_lower == "opencode.json":
        env_source = "opencode"
    else:
        env_source = "project"

    # For non-existent synthetic paths (e.g. unit tests passing file_path="/repo/SKILL.md")
    if not file_path.is_file():
        return AgenticArtifact(
            path=str(file_path),
            rel_path=rel_display,
            env_source=env_source,
            scope="project",
            kind=kind,
            name=_default_artifact_name(file_path, kind),
            description="",
            triggers=(),
            globs=(),
            always_apply=False,
            size_bytes=0,
            mtime=0.0,
            sibling_links=(),
        )

    return _build_artifact(
        file_path,
        rel_path=rel_display,
        env_source=env_source,
        scope="project",
        kind=kind,
    )
