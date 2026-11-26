"""Review comments data model and Markdown export helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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

    def __len__(self) -> int:
        return len(self._comments)

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
                if feedback is not None:
                    comment.feedback = feedback.strip()
                if heading is not None:
                    comment.heading = heading.strip() or "Document"
                if quote is not None:
                    comment.quote = quote.strip()
                return comment
        return None

    def delete(self, comment_id: str) -> bool:
        """Delete a review comment by ID, returning True if removed."""
        for idx, comment in enumerate(self._comments):
            if comment.id == comment_id:
                del self._comments[idx]
                return True
        return False

    def clear(self) -> None:
        """Remove all review comments."""
        self._comments.clear()

    def list(self) -> list[ReviewComment]:
        """Return a shallow copy of all comments in insertion order."""
        return list(self._comments)


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
