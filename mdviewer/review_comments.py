"""Review comments data model, Markdown export, and sidecar round-trip loading."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_FEEDBACK_LABEL_RE = re.compile(r"^(?:\*\*)?Feedback:(?:\*\*)?[ \t]*(.*)$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$")


@dataclass
class ReviewComment:
    """A single anchored review comment attached to a section and quoted excerpt."""

    id: str
    heading: str
    quote: str
    feedback: str
    created_at: str
    line: int | None = None


class ReviewSession:
    """In-memory collection of review comments for the active document."""

    def __init__(self, comments: list[ReviewComment] | None = None) -> None:
        self._comments: list[ReviewComment] = list(comments) if comments else []
        self._has_unexported_changes: bool = False

    def __len__(self) -> int:
        return len(self._comments)

    @property
    def has_unexported_changes(self) -> bool:
        """True when comments have been added, edited, or deleted since last export/load."""
        return self._has_unexported_changes

    def mark_exported(self) -> None:
        """Mark the current review session state as exported/saved."""
        self._has_unexported_changes = False

    def add(
        self,
        heading: str,
        quote: str,
        feedback: str,
        line: int | None = None,
    ) -> ReviewComment:
        """Create and append a new review comment."""
        comment = ReviewComment(
            id=uuid.uuid4().hex[:8],
            heading=(heading or "").strip() or "Document",
            quote=(quote or "").strip(),
            feedback=(feedback or "").strip(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            line=line,
        )
        self._comments.append(comment)
        self._has_unexported_changes = True
        return comment

    def update(
        self,
        comment_id: str,
        feedback: str | None = None,
        heading: str | None = None,
        quote: str | None = None,
    ) -> ReviewComment | None:
        """Update an existing review comment by ID; return None if not found."""
        for comment in self._comments:
            if comment.id == comment_id:
                changed = False
                if feedback is not None:
                    new_feedback = feedback.strip()
                    if new_feedback != comment.feedback:
                        comment.feedback = new_feedback
                        changed = True
                if heading is not None:
                    new_heading = heading.strip() or "Document"
                    if new_heading != comment.heading:
                        comment.heading = new_heading
                        changed = True
                if quote is not None:
                    new_quote = quote.strip()
                    if new_quote != comment.quote:
                        comment.quote = new_quote
                        changed = True
                if changed:
                    self._has_unexported_changes = True
                return comment
        return None

    def delete(self, comment_id: str) -> bool:
        """Delete a review comment by ID, returning True if removed."""
        for idx, comment in enumerate(self._comments):
            if comment.id == comment_id:
                del self._comments[idx]
                self._has_unexported_changes = True
                return True
        return False

    def clear(self) -> None:
        """Remove all review comments and reset unexported change tracking."""
        self._comments.clear()
        self._has_unexported_changes = False

    def list(self) -> list[ReviewComment]:
        """Return a shallow copy of all comments in insertion order."""
        return list(self._comments)

    def load_from_sidecar(self, review_path: str | Path) -> int:
        """Replace session comments with those parsed from a *.review.md sidecar file."""
        loaded = load_review_markdown(review_path)
        self._comments = list(loaded)
        self._has_unexported_changes = False
        return len(self._comments)


def _format_blockquote(quote: str) -> str:
    lines = quote.splitlines() or [quote]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def export_markdown(source_name: str, comments: list[ReviewComment]) -> str:
    """Format review comments as clean portable Markdown."""
    display_name = Path(source_name).name if source_name else "Document"
    parts: list[str] = [f"# Review: {display_name}"]

    if not comments:
        parts.append("")
        parts.append("_No review comments._")
        return "\n".join(parts) + "\n"

    for comment in comments:
        heading = (comment.heading or "").strip() or "Document"
        parts.append("")
        parts.append(f"## {heading}")
        if comment.quote.strip():
            parts.append("")
            parts.append(_format_blockquote(comment.quote.strip()))
        parts.append("")
        parts.append("Feedback:")
        parts.append(comment.feedback.strip() if comment.feedback else "")

    return "\n".join(parts) + "\n"


def default_review_path(source_path: str | None) -> str:
    """Compute default sidecar review filename (e.g. PLAN.md -> PLAN.review.md)."""
    if not source_path or not source_path.strip():
        return "untitled.review.md"
    p = Path(source_path)
    stem = p.stem or p.name
    return str(p.with_name(f"{stem}.review.md"))


def find_sidecar_review_path(doc_path: str | Path | None) -> Path | None:
    """Return the existing companion *.review.md sidecar path for doc_path, if present."""
    if not doc_path:
        return None
    doc = Path(doc_path).expanduser()
    if doc.name.lower().endswith(".review.md"):
        return None
    candidate = Path(default_review_path(str(doc)))
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _parse_comment_block(heading: str, block_lines: list[str], created_at: str) -> ReviewComment | None:
    quote_lines: list[str] = []
    feedback_lines: list[str] = []
    in_feedback = False
    saw_quote = False

    for line in block_lines:
        if not in_feedback:
            fb_match = _FEEDBACK_LABEL_RE.match(line.strip())
            if fb_match:
                in_feedback = True
                inline_text = fb_match.group(1).strip()
                if inline_text:
                    feedback_lines.append(inline_text)
                continue

            stripped = line.lstrip()
            if stripped.startswith(">"):
                saw_quote = True
                after = stripped[1:]
                if after.startswith(" "):
                    after = after[1:]
                quote_lines.append(after)
                continue

            # Tolerate non-blank prose lines before an explicit Feedback: marker
            if stripped:
                if saw_quote:
                    in_feedback = True
                    feedback_lines.append(line)
                else:
                    feedback_lines.append(line)
        else:
            feedback_lines.append(line)

    quote = "\n".join(quote_lines).strip()
    feedback = "\n".join(feedback_lines).strip()
    if not quote and not feedback:
        return None

    return ReviewComment(
        id=uuid.uuid4().hex[:8],
        heading=heading.strip() or "Document",
        quote=quote,
        feedback=feedback,
        created_at=created_at,
        line=None,
    )


def load_review_markdown(
    review_path: str | Path,
    target_path: str | Path | None = None,
) -> list[ReviewComment]:
    """Parse Markveil's *.review.md sidecar format back into ReviewComment objects."""
    _ = target_path  # Reserved for optional target association / caller parity.
    path = Path(review_path).expanduser()
    try:
        raw_text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
        created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return []

    if not raw_text.strip() or "_No review comments._" in raw_text:
        return []

    comments: list[ReviewComment] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in raw_text.splitlines():
        hm = _SECTION_HEADING_RE.match(line)
        if hm:
            if current_heading is not None:
                parsed = _parse_comment_block(current_heading, current_lines, created_at)
                if parsed is not None:
                    comments.append(parsed)
            current_heading = hm.group(1).strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        parsed = _parse_comment_block(current_heading, current_lines, created_at)
        if parsed is not None:
            comments.append(parsed)

    return comments
