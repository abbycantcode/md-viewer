# Repository Guidelines for Agents

`md-viewer` is a native Linux GTK3 + WebKit2 Markdown studio with modular pure-Python engines under `mdviewer/` and unit tests under `tests/`.

## Directory Layout

```text
.
├── md_viewer.py                  # Top-level executable entrypoint
├── md-viewer                     # Bash launcher -> .venv/bin/python md_viewer.py
├── mdv                           # Short CLI alias launcher -> .venv/bin/python md_viewer.py
├── md-viewer-clipboard           # Clipboard launcher -> md_viewer.py --clipboard
├── md-viewer.desktop             # Main desktop entry (text/markdown;text/x-markdown)
├── md-viewer-clipboard.desktop   # Hidden clipboard action desktop entry
├── setup.sh                      # Venv, dependency check, symlinks, MIME, optional GNOME keybind
├── assets/vendor/                # Bundled offline KaTeX and Mermaid assets
├── skills/md-viewer/SKILL.md     # Agent-agnostic skill for mdv workflows & *.review.md
├── mdviewer/
│   ├── __init__.py               # Package version (__version__)
│   ├── app.py                    # GTK3 + WebKit2 studio application (when present/landed)
│   ├── cli.py                    # Argparse CLI, stdin detection, LaunchOptions
│   ├── config.py                 # Atomic XDG config.json persistence (~/.config/md-viewer/)
│   ├── markdown_engine.py        # Code-first Markdown/math/Mermaid/technical-file renderer + CSP
│   ├── sanitizer.py              # HTMLParser allowlist sanitizer & remote image gate
│   ├── themes.py                 # 4 editorial themes (Paper, Obsidian, Sepia, Nordic) + doc CSS
│   ├── gtk_styles.py             # Harmonized GTK3 chrome CSS + WebKit RGBA background helper
│   ├── client_js.py              # Nonced client JS (Mermaid strict, KaTeX, copy, scroll, highlights)
│   ├── context_inspector.py      # Heuristic token counts, section stats, SKILL.md metadata checks
│   ├── diff_engine.py            # Line/word diffs, nearest-heading hunks, git HEAD diffing
│   ├── review_comments.py        # Anchored ReviewSession & *.review.md Markdown export
│   ├── agent_cli.py              # Non-blocking claude / codex / agy subprocess wrapper
│   └── clipboard.py              # Smart clipboard I/O & HTMLParser HTML-to-Markdown converter
└── tests/
    ├── test_sanitizer.py         # Sanitizer allowlist, XSS, SVG/script stripping, image gate tests
    ├── test_markdown_engine.py   # Fences, math, task lists, technical renderers, CSP nonce tests
    └── test_features.py          # Config, context inspector, diff, review comments, agent CLI, CLI tests
```

## Verification Commands

Run all non-GUI checks from the repository root after editing code or scripts:

```bash
# Unit test suite (run inside project venv or with pytest)
.venv/bin/python -m pytest -q

# Linter
ruff check mdviewer tests md_viewer.py

# Python bytecode syntax check
.venv/bin/python -m py_compile md_viewer.py mdviewer/*.py tests/*.py

# Bash launcher & installer syntax check
bash -n setup.sh md-viewer mdv md-viewer-clipboard
```

Note: In worktrees without a local `.venv`, use `/home/abby/Tools/md-viewer/.venv/bin/python -m pytest` (with `PYTHONPATH=.` if needed) or `pytest` on PATH.

## GUI Smoke Test

Run a quick startup check when a display (or `xvfb-run`) is available:

```bash
# CLI parse check (works headless)
.venv/bin/python md_viewer.py --help

# Headless GUI launch smoke test (requires xvfb-run)
xvfb-run -a timeout 5 .venv/bin/python md_viewer.py README.md || true
```

## Invariants

- **Dependencies**: Zero new third-party Python packages beyond `markdown` and `pyyaml` (plus system `gi` / GTK3 / WebKit2 4.1 / GtkSource 300 / Pygments). Keep everything offline-first.
- **Security**: Never bypass `mdviewer/sanitizer.py` with regex HTML cleaning, never weaken `_build_csp` (`connect-src 'none'`, per-render nonces), never enable `allow_universal_access_from_file_urls`, and keep Mermaid at `securityLevel: "strict"`.
- **MIME scope**: Register only `text/markdown` and `text/x-markdown` in `md-viewer.desktop` and `setup.sh` so user `.json` or `.txt` defaults are untouched.
- **Desktop portability**: Keep GNOME `gsettings` calls guarded behind writability checks in `setup.sh`.
