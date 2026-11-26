"""Command-line argument parsing and application launcher for md-viewer."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TextIO

try:
    from mdviewer import __version__
except ImportError:  # pragma: no cover
    __version__ = "2.0.0"

THEME_CHOICES = ("auto", "paper", "obsidian", "sepia", "nordic")


@dataclass
class LaunchOptions:
    """Parsed CLI launch configuration for md-viewer."""

    files: list[str]
    stdin_text: str | None = None
    stdin_label: str = "stdin.md"
    mode: str = "preview"
    watch: bool = False
    quick: bool = False
    readonly: bool = False
    clipboard: bool = False
    diff_files: tuple[str, str] | None = None
    git_diff_file: str | None = None
    line: int | None = None
    section: str | None = None
    theme: str | None = None


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for Markveil."""
    parser = argparse.ArgumentParser(
        prog="markveil",
        description="Markveil — Native Markdown studio for Linux and local coding-agent workflows.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Markdown or technical files to open, or '-' to read from stdin.",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="Open directly in source editor mode.",
    )
    mode_group.add_argument(
        "-s",
        "--split",
        action="store_true",
        help="Open in side-by-side split edit/preview mode.",
    )

    parser.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Enable Agent Watch Mode (highlight changed blocks on reload).",
    )
    parser.add_argument(
        "-q",
        "--quick",
        action="store_true",
        help="Open in minimal distraction-free reader mode.",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="Open files in read-only mode (disable editing/saving).",
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Open with current system clipboard contents (smart HTML-to-Markdown).",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("FILE_A", "FILE_B"),
        help="Compare two files in diff view.",
    )
    parser.add_argument(
        "--git-diff",
        metavar="FILE",
        help="Compare a working-tree file against git HEAD.",
    )
    parser.add_argument(
        "--line",
        type=int,
        default=None,
        help="Jump to a 1-based line number on open.",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=None,
        help="Jump to the specified heading/section on open.",
    )
    parser.add_argument(
        "--theme",
        choices=THEME_CHOICES,
        default=None,
        help="Override configured color theme.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Markveil {__version__}",
    )
    return parser


def _safe_is_tty(stream: TextIO | None) -> bool:
    if stream is None:
        return True
    try:
        return bool(stream.isatty())
    except Exception:
        return True


def _safe_read_stream(stream: TextIO) -> str | None:
    try:
        return stream.read()
    except (OSError, ValueError):
        return None


def parse_args(
    argv: list[str],
    stdin_stream: TextIO | None = None,
) -> LaunchOptions:
    """Parse CLI arguments and optional piped stdin into LaunchOptions."""
    parser = build_parser()
    ns = parser.parse_args(argv)

    raw_files: list[str] = list(ns.files or [])
    read_explicit_stdin = "-" in raw_files
    files = [f for f in raw_files if f != "-"]

    stream = sys.stdin if stdin_stream is None else stdin_stream
    stdin_text: str | None = None

    if read_explicit_stdin:
        data = _safe_read_stream(stream)
        stdin_text = data if data is not None else ""
    elif (
        not files
        and not ns.clipboard
        and not ns.diff
        and not ns.git_diff
        and not _safe_is_tty(stream)
    ):
        data = _safe_read_stream(stream)
        if data:
            stdin_text = data

    mode = "preview"
    if ns.edit:
        mode = "edit"
    elif ns.split:
        mode = "split"

    diff_files = (ns.diff[0], ns.diff[1]) if ns.diff else None

    return LaunchOptions(
        files=files,
        stdin_text=stdin_text,
        stdin_label="stdin.md",
        mode=mode,
        watch=bool(ns.watch),
        quick=bool(ns.quick),
        readonly=bool(ns.readonly),
        clipboard=bool(ns.clipboard),
        diff_files=diff_files,
        git_diff_file=ns.git_diff,
        line=ns.line,
        section=ns.section,
        theme=ns.theme,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for Markveil CLI."""
    full_argv = sys.argv if argv is None else argv
    prog = full_argv[0] if full_argv else "markveil"
    options = parse_args(full_argv[1:])

    from mdviewer.app import MarkdownViewerApp

    app = MarkdownViewerApp(launch_options=options)
    return int(app.run([prog]))
