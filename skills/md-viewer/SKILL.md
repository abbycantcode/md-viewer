---
name: md-viewer
description: >-
  Use when presenting generated Markdown plans, reports, or specs for human review in Watch Mode,
  launching visual Git or file diffs, piping command output to mdv, or reading and acting on
  exported *.review.md human feedback files.
---

# md-viewer (`mdv`) Workflow for Coding Agents

`mdv` (alias for `md-viewer`) is a native Linux Markdown studio for human-in-the-loop review. Use it to hand off plans, reports, diffs, and terminal output visually, and to ingest structured human review comments back into your workflow.

## 1. Open Plans and Reports in Watch Mode

Launch `mdv -w` in the background whenever you write or iterate on a Markdown plan, architecture note, or report the user wants to read live:

```bash
mdv -w PLAN.md >/dev/null 2>&1 &
```

- **Live reload**: Watch Mode reloads automatically whenever you edit the file on disk, without modal reload prompts.
- **Change highlights**: Modified and newly added blocks are highlighted in place so the user sees what changed between agent edits.
- **Targeted jumps**: Open directly at a heading or 1-based line when directing attention to a specific section:

```bash
mdv -w --section "Migration Plan" PLAN.md >/dev/null 2>&1 &
mdv -w --line 84 REPORT.md >/dev/null 2>&1 &
```

- **Read-only presentation**: Pass `--readonly` when showing an immutable artifact or snapshot.

## 2. Launch Visual Diff Reviews

Use `mdv` instead of asking the human to read raw unified diffs in the terminal:

```bash
# Compare working-tree changes against git HEAD
mdv --git-diff docs/architecture.md >/dev/null 2>&1 &

# Compare two Markdown or text files side by side / unified
mdv --diff PLAN.v1.md PLAN.v2.md >/dev/null 2>&1 &
```

`mdv` renders hunk headers with nearest-heading context, addition/deletion counts, and inline word-level diffs.

## 3. Pipe Terminal Summaries and Logs

Pipe stdout directly into `mdv -` (or omit `-` when stdin is piped and no file path is given) to turn verbose test output, build logs, or generated Markdown summaries into a readable document tab:

```bash
pytest -q | mdv - >/dev/null 2>&1 &
git log -n 20 --stat | mdv - >/dev/null 2>&1 &
python3 scripts/summarize.py | mdv >/dev/null 2>&1 &
```

Note: `mdv` launches a GUI window, so background (`&`) or detach when your shell session should continue immediately. Skip `mdv` in headless/SSH sessions without `DISPLAY` or `WAYLAND_DISPLAY`.

## 4. Read and Act on `*.review.md` Feedback

Humans can attach review comments to sections and quoted excerpts inside `md-viewer`, then export a portable sidecar file named `<stem>.review.md` (for example, `PLAN.review.md` next to `PLAN.md`).

Exported files follow this structure:

```markdown
# Review: PLAN.md

## Rollout Strategy

> Phase 2 swaps the primary table without a shadow read period.

Feedback:
Add a dual-read verification step before cutting over traffic.
```

When a user tells you to address review comments or points to a `*.review.md` file:

1. Check for `<stem>.review.md` alongside the target document (or read the path the user named).
2. Parse every `## <Heading>` block, using the `>` blockquote excerpt to locate the exact target paragraph or code block in the source document.
3. Apply each `Feedback:` item directly in the source document (or codebase, if the feedback targets implementation).
4. If the target document is open in Watch Mode, write the updated file cleanly in place so the user immediately sees the changed-block highlights.
5. Summarize which comments you addressed and ask before deleting the `.review.md` file unless the user asked you to clean it up.
