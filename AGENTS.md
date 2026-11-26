# Repository guidelines

**Markveil** (`markveil` / `mdv`) is a native Linux GTK3 + WebKit2 Markdown studio with modular Python engines under `mdviewer/` and unit/GUI tests under `tests/`.

## Directory layout

```text
.
├── md_viewer.py                  # Top-level executable entrypoint -> mdviewer.cli.main()
├── markveil                      # Primary Bash launcher -> .venv/bin/python md_viewer.py
├── mdv                           # Short CLI alias launcher -> .venv/bin/python md_viewer.py
├── md-viewer                     # Backward-compatible launcher -> .venv/bin/python md_viewer.py
├── md-viewer-clipboard           # Clipboard launcher -> md_viewer.py --clipboard
├── markveil.desktop              # Main desktop entry (text/markdown;text/x-markdown)
├── md-viewer-clipboard.desktop   # Hidden clipboard action desktop entry
├── setup.sh                      # Venv, dependency check, icons, symlinks, MIME, GNOME keybind
├── assets/
│   ├── icons/                    # Markveil SVG + raster PNG icons (48, 128, 256)
│   └── vendor/                   # Bundled offline KaTeX and Mermaid assets
├── docs/screenshots/             # Live GTK3 + WebKit2 screenshots referenced in README.md
├── skills/markveil/SKILL.md      # Agent-agnostic skill for mdv workflows & *.review.md
├── mdviewer/
│   ├── __init__.py               # __app_name__, __cli_name__, __version__
│   ├── app.py                    # Multi-tab GTK3 + WebKit2 studio window & shortcuts
│   ├── tab.py                    # DocumentTab: preview/split/edit, Watch Mode, diff overlay, search
│   ├── sidebar.py                # Collapsible sidebar: Outline, Context Inspector, Comments, Agentic Env
│   ├── dialogs.py                # WelcomeView, AskAgentDialog, DiffPicker, Preferences, Shortcuts
│   ├── cli.py                    # Argparse CLI, stdin detection, LaunchOptions
│   ├── config.py                 # Atomic XDG config.json (~/.config/markveil/) + legacy fallback
│   ├── markdown_engine.py        # Code-first Markdown/math/Mermaid/technical/source renderer + CSP
│   ├── sanitizer.py              # HTMLParser allowlist sanitizer & remote image gate
│   ├── themes.py                 # 5 editorial themes (Folio, Paper, Obsidian, Sepia, Nordic) + doc CSS
│   ├── gtk_styles.py             # Harmonized GTK3 chrome CSS + WebKit RGBA background helper
│   ├── client_js.py              # Nonced client JS (Mermaid strict, KaTeX, copy, scroll, highlights)
│   ├── agentic_env.py            # Offline global/project agentic discovery, classification & denylists
│   ├── context_inspector.py      # Heuristic token counts, section stats, agentic artifact checks
│   ├── diff_engine.py            # Line/word diffs, nearest-heading hunks, git HEAD diffing
│   ├── review_comments.py        # Anchored ReviewSession, *.review.md export & sidecar loading
│   ├── agent_cli.py              # Non-blocking local CLI agent wrapper (9 CLIs, desktop PATH discovery)
│   └── clipboard.py              # Smart clipboard I/O, bounded history & HTMLParser HTML-to-Markdown
└── tests/
    ├── test_sanitizer.py         # Sanitizer allowlist, XSS, SVG/script stripping, image gate tests
    ├── test_markdown_engine.py   # Fences, math, task lists, technical/source renderers, CSP nonce tests
    ├── test_agentic_env.py       # Agentic env discovery, classification, denylists & cache tests
    ├── test_features.py          # Config, context inspector, diff, review comments, agent CLI, CLI tests
    └── test_gui_smoke.py         # Live GTK3 + WebKit2 multi-tab, Watch Mode, theme, quick/readonly tests
```

## Verification commands

Run all checks from the repository root after editing code or scripts:

```bash
# Unit + GUI smoke test suite
.venv/bin/python -m pytest -v

# Linter
ruff check mdviewer tests md_viewer.py

# Python bytecode syntax check
.venv/bin/python -m py_compile md_viewer.py mdviewer/*.py tests/*.py

# Bash launcher & installer syntax check
bash -n setup.sh markveil mdv md-viewer md-viewer-clipboard
```

Note: In worktrees without a local `.venv`, use `/home/abby/Tools/md-viewer/.venv/bin/python -m pytest` (with `PYTHONPATH=.` if needed) or `pytest` on PATH.

## GUI smoke test

Run a quick startup check when a display (or `xvfb-run`) is available:

```bash
# CLI parse check (works headless)
.venv/bin/python md_viewer.py --help

# Headless GUI launch smoke test (requires xvfb-run)
xvfb-run -a timeout 5 .venv/bin/python md_viewer.py README.md || true
```

## Invariants

- **Dependencies.** Zero new third-party Python packages beyond `markdown` and `pyyaml` (plus system `gi`, GTK3, WebKit2 4.1, GtkSource 300, and Pygments). Keep everything offline-first.
- **Security.** Never bypass `mdviewer/sanitizer.py` with regex HTML cleaning, never weaken `_build_csp` (`connect-src 'none'`, per-render nonces), never enable `allow_universal_access_from_file_urls`, and keep Mermaid at `securityLevel: "strict"`.
- **MIME scope.** Register only `text/markdown` and `text/x-markdown` in `markveil.desktop` and `setup.sh` so user `.json` or `.txt` defaults are untouched.
- **Desktop portability.** Keep GNOME `gsettings` calls guarded behind writability checks in `setup.sh`.
