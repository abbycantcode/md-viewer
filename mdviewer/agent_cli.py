"""Non-blocking external CLI agent integration with desktop-safe PATH discovery."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAX_CONTEXT_CHARS = 32000

PROMPT_PRESETS: dict[str, tuple[str, str]] = {
    "summarize": (
        "Summarize",
        "Summarize the key points, decisions, and action items in this document concisely.",
    ),
    "gaps": (
        "Find Gaps",
        "Review this document for missing details, ambiguities, edge cases, or unstated assumptions.",
    ),
    "architecture": (
        "Check Architecture",
        "Evaluate the technical architecture, boundaries, failure modes, and tradeoffs described here.",
    ),
    "tighten": (
        "Tighten Prose",
        "Suggest concrete ways to tighten and clarify this document without losing technical precision.",
    ),
}

_KNOWN_BACKENDS: tuple[tuple[str, str, str], ...] = (
    ("claude", "Claude Code", "claude"),
    ("codex", "Codex CLI", "codex"),
    ("agy", "Antigravity CLI", "agy"),
    ("cursor-agent", "Cursor Agent", "cursor-agent"),
    ("opencode", "OpenCode", "opencode"),
    ("kimi", "Kimi Code", "kimi"),
    ("gemini", "Gemini CLI", "gemini"),
    ("cline", "Cline CLI", "cline"),
    ("devin", "Devin CLI", "devin"),
)

SUPPORTED_AGENT_IDS: tuple[str, ...] = tuple(item[0] for item in _KNOWN_BACKENDS)
SUPPORTED_AGENT_LABELS: dict[str, str] = {item[0]: item[1] for item in _KNOWN_BACKENDS}
_BACKEND_BINARIES: dict[str, str] = {item[0]: item[2] for item in _KNOWN_BACKENDS}

# Electron / GUI wrappers that must never be mistaken for headless agent CLIs.
_REJECTED_EXECUTABLES: dict[str, frozenset[str]] = {
    "cursor-agent": frozenset({"cursor"}),
    "devin": frozenset({"devin-desktop"}),
}


@dataclass(frozen=True)
class AgentBackend:
    """Detected CLI agent backend available on the augmented PATH."""

    id: str
    name: str
    executable: str


def _semver_key(version_name: str) -> tuple[int, ...]:
    """Parse a version directory name (e.g. 'v24.22.1') into a sortable numeric tuple."""
    cleaned = version_name.lstrip("vV")
    parts: list[int] = []
    for token in re.split(r"[.\-+]", cleaned):
        if token.isdigit():
            parts.append(int(token))
        else:
            match = re.match(r"^(\d+)", token)
            if match:
                parts.append(int(match.group(1)))
            break
    return tuple(parts) if parts else (0,)


def _sorted_versioned_bin_dirs(base_dir: Path, suffix: tuple[str, ...]) -> list[str]:
    """Return existing versioned bin directories sorted descending by semver."""
    if not base_dir.is_dir():
        return []
    candidates: list[tuple[tuple[int, ...], str, str]] = []
    try:
        with os.scandir(base_dir) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=True):
                    continue
                bin_dir = Path(entry.path).joinpath(*suffix)
                if bin_dir.is_dir():
                    candidates.append((_semver_key(entry.name), entry.name, str(bin_dir)))
    except OSError:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in candidates]


def get_augmented_path(base_path: str | None = None) -> str:
    """Build a deduplicated PATH combining inherited PATH with common user CLI dirs."""
    inherited = os.environ.get("PATH", "") if base_path is None else base_path
    home = Path.home()

    extra_dirs: list[str] = [
        str(home / ".local" / "bin"),
        *_sorted_versioned_bin_dirs(home / ".nvm" / "versions" / "node", ("bin",)),
        *_sorted_versioned_bin_dirs(
            home / ".fnm" / "node-versions", ("installation", "bin")
        ),
        str(home / ".volta" / "bin"),
        str(home / ".asdf" / "shims"),
        str(home / ".mise" / "shims"),
        str(home / ".opencode" / "bin"),
        str(home / ".kimi-code" / "bin"),
        str(home / ".gemini" / "antigravity" / "bin"),
        str(home / ".cargo" / "bin"),
        str(home / ".bun" / "bin"),
        str(home / ".npm-global" / "bin"),
        str(home / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/snap/bin",
    ]

    result: list[str] = []
    seen: set[str] = set()

    for segment in inherited.split(os.pathsep):
        cleaned = segment.strip()
        if not cleaned:
            continue
        norm = os.path.normpath(cleaned)
        if norm not in seen:
            seen.add(norm)
            result.append(cleaned)

    for directory in extra_dirs:
        norm = os.path.normpath(directory)
        if norm not in seen:
            seen.add(norm)
            result.append(directory)

    return os.pathsep.join(result)


def _is_rejected_executable(backend_id: str, resolved: str) -> bool:
    rejected = _REJECTED_EXECUTABLES.get(backend_id)
    if not rejected:
        return False
    basename = Path(resolved).name.lower()
    if basename in rejected:
        return True
    try:
        real_basename = Path(resolved).resolve().name.lower()
        if real_basename in rejected:
            return True
    except OSError:
        pass
    return False


def _which_on_path(binary: str, search_path: str) -> str | None:
    """Resolve binary on search_path, staying compatible with 1-arg test mocks."""
    try:
        return shutil.which(binary, path=search_path)
    except TypeError:
        return shutil.which(binary)


def detect_available_agents(base_path: str | None = None) -> list[AgentBackend]:
    """Probe augmented PATH for supported local agent CLIs."""
    search_path = get_augmented_path(base_path)
    available: list[AgentBackend] = []
    for backend_id, name, binary in _KNOWN_BACKENDS:
        resolved = _which_on_path(binary, search_path)
        if resolved and not _is_rejected_executable(backend_id, resolved):
            available.append(AgentBackend(id=backend_id, name=name, executable=resolved))
    return available


# Alias kept for cross-module contract clarity.
detect_installed_agents = detect_available_agents


def resolve_agent_backend(
    backend_id: str,
    base_path: str | None = None,
) -> AgentBackend | None:
    """Resolve a single supported agent backend by ID on the augmented PATH."""
    for bid, name, binary in _KNOWN_BACKENDS:
        if bid == backend_id:
            search_path = get_augmented_path(base_path)
            resolved = _which_on_path(binary, search_path)
            if resolved and not _is_rejected_executable(bid, resolved):
                return AgentBackend(id=bid, name=name, executable=resolved)
            return None
    return None


def build_agent_env(
    executable: str | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct subprocess env with executable's parent dir prepended to augmented PATH."""
    env = dict(os.environ if base_env is None else base_env)
    augmented = get_augmented_path(env.get("PATH", ""))

    segments: list[str] = []
    seen: set[str] = set()

    if executable:
        exe_path = Path(executable)
        if exe_path.is_absolute() or os.sep in executable:
            parent = str(exe_path.parent)
            if parent:
                norm_parent = os.path.normpath(parent)
                seen.add(norm_parent)
                segments.append(parent)

    for seg in augmented.split(os.pathsep):
        cleaned = seg.strip()
        if not cleaned:
            continue
        norm = os.path.normpath(cleaned)
        if norm not in seen:
            seen.add(norm)
            segments.append(cleaned)

    env["PATH"] = os.pathsep.join(segments)
    return env


def build_command(
    backend_id: str,
    prompt: str,
    executable: str | None = None,
) -> list[str]:
    """Build the non-interactive subprocess argument list for a backend."""
    exe = executable or _BACKEND_BINARIES.get(backend_id)
    if backend_id == "claude":
        return [exe or "claude", "-p", prompt, "--output-format", "text"]
    if backend_id == "codex":
        return [exe or "codex", "exec", prompt]
    if backend_id == "agy":
        return [exe or "agy", "-p", prompt, "--output-format", "text"]
    if backend_id == "cursor-agent":
        return [exe or "cursor-agent", "-p", prompt, "--output-format", "text"]
    if backend_id == "opencode":
        return [exe or "opencode", "run", prompt]
    if backend_id == "kimi":
        return [exe or "kimi", "-p", prompt, "--output-format", "text"]
    if backend_id == "gemini":
        return [exe or "gemini", "-p", prompt]
    if backend_id == "cline":
        return [exe or "cline", "--plan", prompt]
    if backend_id == "devin":
        return [exe or "devin", "-p", prompt]
    raise ValueError(f"Unsupported agent backend: {backend_id!r}")


def build_agent_prompt(
    document_text: str,
    file_path: str | None,
    question: str,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> str:
    """Assemble a bounded document context + user question prompt."""
    label = Path(file_path).name if file_path else "Untitled Document"
    text = document_text or ""
    if len(text) > max_chars:
        text = (
            text[:max_chars]
            + f"\n\n[... document truncated at {max_chars} of {len(document_text)} chars ...]"
        )

    clean_question = (question or "").strip() or PROMPT_PRESETS["summarize"][1]
    return (
        f"You are reviewing the Markdown document `{label}`.\n\n"
        "Document content:\n"
        "<<<<DOCUMENT>>>>\n"
        f"{text}\n"
        "<<<<END_DOCUMENT>>>>\n\n"
        f"Request: {clean_question}\n"
    )


class AgentTaskHandle:
    """Handle for cancelling or awaiting a background CLI agent invocation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _set_process(self, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = proc
            if self._cancelled.is_set():
                self._terminate_locked()

    def _terminate_locked(self) -> None:
        proc = self._process
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
        except OSError:
            pass

    def cancel(self) -> None:
        """Request cancellation and terminate the running subprocess if active."""
        self._cancelled.set()
        with self._lock:
            self._terminate_locked()

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the background thread to finish; return True if finished."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()


def _invoke_callback(
    dispatch: Callable[[Callable[[], None]], None] | None,
    fn: Callable[[str], None],
    arg: str,
) -> None:
    if dispatch is not None:
        dispatch(lambda: fn(arg))
    else:
        fn(arg)


def run_agent_async(
    backend_id: str,
    document_text: str,
    file_path: str | None,
    question: str,
    on_done: Callable[[str], None],
    on_error: Callable[[str], None],
    timeout_sec: int = 90,
    dispatch: Callable[[Callable[[], None]], None] | None = None,
) -> AgentTaskHandle:
    """Run an external CLI agent asynchronously in a daemon thread with cancellation support."""
    handle = AgentTaskHandle()
    prompt = build_agent_prompt(document_text, file_path, question)

    try:
        cmd = build_command(backend_id, prompt)
    except ValueError as exc:
        _invoke_callback(dispatch, on_error, str(exc))
        return handle

    backend = resolve_agent_backend(backend_id)
    default_bin = _BACKEND_BINARIES.get(backend_id)
    if backend is not None and cmd and default_bin and cmd[0] == default_bin:
        cmd = [backend.executable, *cmd[1:]]

    proc_env = build_agent_env(cmd[0] if cmd else None)

    def _worker() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                env=proc_env,
            )
        except FileNotFoundError:
            if not handle.cancelled:
                _invoke_callback(
                    dispatch, on_error, f"Agent CLI executable not found for {backend_id!r}."
                )
            return
        except OSError as exc:
            if not handle.cancelled:
                _invoke_callback(dispatch, on_error, f"Failed to start agent CLI: {exc}")
            return

        handle._set_process(proc)
        if handle.cancelled:
            return

        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            handle.cancel()
            _invoke_callback(
                dispatch,
                on_error,
                f"Agent CLI timed out after {timeout_sec}s.",
            )
            return
        except OSError as exc:
            if not handle.cancelled:
                _invoke_callback(dispatch, on_error, f"Agent CLI I/O error: {exc}")
            return

        if handle.cancelled:
            return

        if proc.returncode != 0:
            err_msg = (stderr or "").strip() or f"Agent CLI exited with status {proc.returncode}."
            _invoke_callback(dispatch, on_error, err_msg)
            return

        _invoke_callback(dispatch, on_done, (stdout or "").strip())

    thread = threading.Thread(
        target=_worker,
        name=f"mdv-agent-{backend_id}",
        daemon=True,
    )
    handle._thread = thread
    thread.start()
    return handle
