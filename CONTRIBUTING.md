# Contributing to Markveil

Thanks for your interest in contributing to Markveil. Bug fixes, packaging contributions (AUR, Flatpak, Nix, RPM), accessibility improvements, and focused feature PRs are welcome.

## Development setup

1. Install the GTK3, WebKit2GTK 4.1, GtkSourceView 3, PyGObject, and Pygments prerequisites for your distribution (see [Installation](README.md#installation)).
2. Clone the repository and run the setup script:

```bash
git clone https://github.com/abbycantcode/Markveil.git
cd Markveil
bash setup.sh
```

3. Install dev tooling (`pytest` and `ruff`) into `.venv`:

```bash
uv pip install --python .venv/bin/python pytest ruff
# or: .venv/bin/python -m pip install pytest ruff
```

## Running tests and lint

Run the full test suite (unit tests plus real GTK3 + WebKit2 GUI smoke tests):

```bash
.venv/bin/python -m pytest -v
```

In a headless terminal or CI environment without a desktop session, run the GUI tests under Xvfb and D-Bus:

```bash
WEBKIT_DISABLE_COMPOSITING_MODE=1 LIBGL_ALWAYS_SOFTWARE=1 \
  xvfb-run -a -s "-screen 0 1440x900x24" \
  dbus-run-session -- .venv/bin/python -m pytest -v
```

Run lint and shell syntax checks before opening a PR:

```bash
ruff check mdviewer/ tests/ md_viewer.py
bash -n setup.sh markveil mdv md-viewer md-viewer-clipboard
```

## Architecture overview

| Path | Responsibility |
| --- | --- |
| `mdviewer/cli.py` | Argument parsing, stdin piping, lazy GTK import |
| `mdviewer/app.py` | Main window, tabs, theme switching, actions, shortcuts |
| `mdviewer/tab.py` | Per-tab Preview/Split/Edit widgets, Watch mode (`Gio.FileMonitor`), diff view |
| `mdviewer/sidebar.py` | Open documents list and 4-tab sidebar (Outline, Context, Comments, Agentic Env) |
| `mdviewer/markdown_engine.py` | Markdown, KaTeX, Mermaid, technical/source renderers, CSP assembly |
| `mdviewer/sanitizer.py` | `html.parser.HTMLParser` allowlist sanitizer and URL/image hardening |
| `mdviewer/agentic_env.py` | Offline agentic environment discovery, classification, and denylists |
| `mdviewer/context_inspector.py` | Heuristic token counts, section warnings, and artifact checks |
| `mdviewer/diff_engine.py` | Unified and side-by-side diffs with heading context and word highlights |
| `mdviewer/review_comments.py` | `*.review.md` sidecar creation, parsing, and round-trip export |
| `mdviewer/clipboard.py` | HTML-to-Markdown conversion, Wayland/X11 backends, bounded history |
| `mdviewer/agent_cli.py` | Async local coding-agent CLI runner (`shell=False`, desktop-safe `PATH`) |
| `mdviewer/themes.py` / `gtk_styles.py` | Folio, Paper, Obsidian, Sepia, and Nordic themes + scoped GTK3 CSS |
| `assets/vendor/` | Bundled offline KaTeX and Mermaid assets |
| `packaging/` | Distro packaging definitions (e.g. `packaging/aur/PKGBUILD`) |

## Security invariants to preserve

Markveil renders untrusted local Markdown and scans user agent directories. Pull requests must preserve the invariants documented in [`SECURITY.md`](SECURITY.md):

- **Per-render CSP nonces** (`default-src 'none'`, `script-src 'nonce-<nonce>'`, `connect-src 'none'`).
- **HTMLParser allowlist sanitization** in `mdviewer/sanitizer.py` (never regex HTML stripping).
- **Default remote-image blocking** and backslash URL normalization.
- **Strict Mermaid mode** (`securityLevel: "strict"`) with post-sanitization hydration.
- **Agentic scanner denylists**, depth cap (4), head-read cap (2,048 bytes), and no config body reads.
- **`shell=False`** for all local agent subprocesses.

If you discover a security issue, please report it privately as described in [`SECURITY.md`](SECURITY.md) rather than opening a public issue.

## Pull request checklist

- Keep PRs focused on a single bug fix, feature, or packaging target.
- Add or update tests in `tests/` for any behavioral change or bug fix.
- Verify `.venv/bin/python -m pytest -v` and `ruff check mdviewer/ tests/ md_viewer.py` pass locally.
- If you change CLI flags, keybindings, or install steps, update `README.md` (and `skills/markveil/SKILL.md` if agent workflows change).
