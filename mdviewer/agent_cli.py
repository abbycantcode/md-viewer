"""Non-blocking external CLI agent integration (claude, codex, agy)."""

from __future__ import annotations

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
)


@dataclass(frozen=True)
class AgentBackend:
    """Detected CLI agent backend available on PATH."""

    id: str
    name: str
    executable: str


def detect_available_agents() -> list[AgentBackend]:
    """Probe PATH via shutil.which for supported agent CLIs."""
    available: list[AgentBackend] = []
    for backend_id, name, binary in _KNOWN_BACKENDS:
        resolved = shutil.which(binary)
        if resolved:
            available.append(AgentBackend(id=backend_id, name=name, executable=resolved))
    return available


def build_command(backend_id: str, prompt: str) -> list[str]:
    """Build the non-interactive subprocess argument list for a backend."""
    if backend_id == "claude":
        return ["claude", "-p", prompt]
    if backend_id == "codex":
        return ["codex", "exec", prompt]
    if backend_id == "agy":
        return ["agy", "-p", prompt, "--output-format", "text"]
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

    def _worker() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
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
