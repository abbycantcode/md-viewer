---
name: markveil
description: >-
  Use when presenting generated Markdown plans, reports, or specs for human review in Watch mode
  (`markveil -w` or `mdv -w`), launching visual Git or file diffs, piping command output to
  Markveil, or reading and acting on exported *.review.md human feedback files.
---

# Markveil (`markveil` / `mdv`) workflow for coding agents

Markveil is a native Linux Markdown studio for human-in-the-loop review. Use `markveil` (or the short alias `mdv`) to open plans, reports, diffs, and terminal output visually, and to apply exported human review comments.

## 1. Open plans and reports in Watch mode

Launch `mdv -w` in the background when you write or update a Markdown plan, architecture note, or report the user wants to read live:

```bash
mdv -w PLAN.md >/dev/null 2>&1 &
```

- **Live reload.** Watch mode reloads automatically when you edit the file on disk, with no modal reload prompts.
- **Change highlights.** Modified and added blocks are highlighted in place so the user sees what changed between edits.
- **Targeted jumps.** Open directly at a heading or 1-based line when pointing to a specific section:

```bash
mdv -w --section "Migration Plan" PLAN.md >/dev/null 2>&1 &
mdv -w --line 84 REPORT.md >/dev/null 2>&1 &
```

- **Read-only mode.** Pass `--readonly` when showing an immutable artifact or snapshot.

## 2. Launch visual diff reviews

Use `mdv` instead of printing raw unified diffs in the terminal:

```bash
# Compare working-tree changes against git HEAD
mdv --git-diff docs/architecture.md >/dev/null 2>&1 &

# Compare two Markdown or text files
mdv --diff PLAN.v1.md PLAN.v2.md >/dev/null 2>&1 &
```

Markveil renders hunk headers with nearest-heading context, addition/deletion counts, and word-level diffs.

## 3. Pipe terminal summaries and logs

Pipe stdout into `mdv -` (or omit `-` when stdin is piped and no file path is passed) to open test output, build logs, or Markdown summaries in a rendered tab:

```bash
pytest -q | mdv - >/dev/null 2>&1 &
git log -n 20 --stat | mdv - >/dev/null 2>&1 &
python3 scripts/summarize.py | mdv >/dev/null 2>&1 &
```

Markveil opens a GUI window, so background (`&`) or detach it when your shell session should continue immediately. Skip `mdv` in headless or SSH sessions without `DISPLAY` or `WAYLAND_DISPLAY`.

## 4. Read and apply `*.review.md` feedback

Users can attach review comments to sections and quoted excerpts inside Markveil and export a sidecar file named `<stem>.review.md` (for example, `PLAN.review.md` next to `PLAN.md`).

Exported files use this format:

```markdown
# Review: PLAN.md

## Rollout Strategy

> Phase 2 swaps the primary table without a shadow read period.

Feedback:
Add a dual-read verification step before cutting over traffic.
```

When a user asks you to address review comments or points to a `*.review.md` file:

1. Read `<stem>.review.md` next to the target document (or the path the user gave).
2. Parse each `## <Heading>` block and use the `>` blockquote excerpt to locate the target paragraph or code block in the source document.
3. Apply each `Feedback:` item in the source document or codebase.
4. If the target document is open in Watch mode, write the updated file in place so the user sees the changed-block highlights.
5. Summarize which comments you addressed and ask before deleting the `.review.md` file unless the user asked to remove it.
