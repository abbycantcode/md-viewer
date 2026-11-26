# md-viewer

Lightweight native GTK3 + WebKit2 Markdown Studio for Linux and local coding-agent workflows. Cold-starts in under 250ms, runs offline-first with bundled KaTeX and Mermaid, and requires zero Electron or Node runtimes.

## Why md-viewer

Most Linux Markdown tools split into two camps: heavy Electron workspaces that burn hundreds of megabytes of RAM, or minimal viewers that break on Mermaid diagrams, math, diffs, and live agent edits. `md-viewer` (`mdv`) sits in the middle as a fast native desktop studio built for reading, editing, and reviewing AI-generated plans and technical files.

| Capability | md-viewer (`mdv`) | Electron Apps (Obsidian / VS Code) | Terminal / Minimal Viewers |
|---|---|---|---|
| Cold start | <250 ms | 1.5 - 4 s | <50 ms |
| Memory footprint | ~45 - 65 MB RSS | 300 - 900 MB RSS | ~15 - 30 MB |
| Native GTK3 + WebKit2 | Yes | No (Chromium) | Terminal or basic widget |
| Offline KaTeX + Mermaid | Bundled locally | Plugin or network dependent | Usually unsupported |
| Agent Watch Mode + block diff highlight | Built-in (`-w`) | External extension | None |
| Portable `*.review.md` export | Built-in | None | None |
| Visual `--git-diff` & `--diff` | Built-in | Git extension | Text only |
| Local CLI agent (`claude`/`codex`/`agy`) | Built-in (`Ctrl+Shift+A`) | Paid add-on or extension | None |

Tradeoffs: `md-viewer` targets Linux desktops with GTK3 and WebKit2GTK 4.1. It has no cloud sync, vault graph, or third-party plugin marketplace.

## Signature Workflows

### Agent Watch Mode
Open a file with `mdv -w PLAN.md` or press `Ctrl+Shift+W`. When an external tool or coding agent rewrites the file on disk, `md-viewer` reloads automatically without modal confirmation popups and highlights changed blocks in place (`[data-changed="true"]`).

### Context and `SKILL.md` Token Inspector
Open the sidebar (`Ctrl+B` / `F9`) to inspect document word count, byte size, reading time, and heuristic token estimates split across prose (~4.2 chars/token) and fenced code (~3.4 chars/token). Each heading shows its token share, warns if a section exceeds 2,000 estimated tokens, and checks `SKILL.md` files for valid YAML frontmatter (`name` and `description`).

### Visual Diff Review
Press `Ctrl+D` or launch from the terminal with `--git-diff` or `--diff` to inspect changes against the previous revision, `git HEAD`, or another file. Diffs include hunk counts, nearest Markdown heading context, and inline word-level insertions and deletions.

### Portable Review Comments (`*.review.md`)
Select text in Preview and click **Add comment** to attach review feedback, then export a clean sidecar file (`<stem>.review.md`, headed `# Review: <filename>`). Any coding agent can read the quoted excerpt and `Feedback:` block directly without custom IDE integrations.

### Ask Local Agent
Press `Ctrl+Shift+A` to run a locally installed CLI agent (`claude`, `codex`, or `agy`) asynchronously against the active document (bounded to 32,000 chars) using built-in presets (`Summarize`, `Find Gaps`, `Check Architecture`, `Tighten Prose`) or a custom prompt.

### Terminal-first `mdv` CLI and Stdin Piping
Launch tabs, jump straight to `--line` or `--section`, open split/edit views, or pipe command output directly into a rendered tab with `... | mdv -`.

### Smart Clipboard Studio (`Super+Shift+M`)
Press `Super+Shift+M` globally (on GNOME) or run `md-viewer-clipboard` / `mdv --clipboard` to open clipboard contents in studio mode. Copied rich HTML from browsers or docs is converted cleanly to Markdown using a pure-Python streaming parser.

### Technical File Views
Open `.json`, `.jsonc`, `.yaml`, `.yml`, `.toml`, `.diff`, `.patch`, `.mmd`, `.mermaid`, and `.txt` files directly. JSON, JSONC, YAML, and TOML files show parse validity badges alongside syntax-highlighted or structured tree views.

## Installation

System prerequisites on Ubuntu / Debian:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-gtksource-3.0 python3-pygments
```

Ensure [`uv`](https://docs.astral.sh/uv/) is installed, then run:

```bash
bash setup.sh
```

`setup.sh` performs the following steps:
1. Marks `md-viewer`, `mdv`, `md-viewer-clipboard`, and `md_viewer.py` executable.
2. Creates `.venv` with `--system-site-packages` via `uv` and installs `markdown` and `pyyaml`.
3. Verifies GTK3, WebKit2 4.1, GtkSource 300, Pygments, `mdviewer` imports, and bundled KaTeX + Mermaid assets.
4. Symlinks `md-viewer`, `mdv`, and `md-viewer-clipboard` into `~/.local/bin/`.
5. Installs `.desktop` entries into `~/.local/share/applications/` and sets `md-viewer` as default handler for `text/markdown` and `text/x-markdown` (without altering `.json` or `.txt` defaults).
6. Registers `Super+Shift+M` as a GNOME custom keybinding when `gsettings` is writable (and skips cleanly on KDE, Sway, Hyprland, XFCE, or headless environments).

## `mdv` CLI Reference

`mdv` and `md-viewer` accept identical arguments.

```bash
# Open one or more files in tabs
mdv README.md docs/architecture.md

# Open in Agent Watch Mode at a specific heading or line
mdv -w --section "Rollout" PLAN.md
mdv -w --line 42 NOTES.md

# Open directly in Edit or Split view
mdv -e notes.md
mdv -s notes.md

# Minimal distraction-free reader or read-only mode
mdv -q spec.md
mdv --readonly release-notes.md

# Visual diff against git HEAD or between two files
mdv --git-diff README.md
mdv --diff PLAN.v1.md PLAN.v2.md

# Pipe command output or Markdown via stdin
git diff --stat | mdv -
cat report.md | mdv

# Launch Smart Clipboard Studio with theme override
mdv --clipboard --theme obsidian
```

| Flag | Description |
|---|---|
| `files` | Files to open, or `-` to read Markdown from `stdin` |
| `-e`, `--edit` | Open in source editor view |
| `-s`, `--split` | Open in side-by-side split edit/preview mode |
| `-w`, `--watch` | Enable Agent Watch Mode (live reload + changed-block highlight) |
| `-q`, `--quick` | Minimal distraction-free reader mode |
| `--readonly` | Disable editing and saving |
| `--clipboard` | Open system clipboard (with HTML-to-Markdown conversion) |
| `--diff FILE_A FILE_B` | Compare two files in diff view |
| `--git-diff FILE` | Compare working-tree file against `git HEAD` |
| `--line N` | Jump to 1-based line `N` on open |
| `--section NAME` | Jump to heading `NAME` on open |
| `--theme NAME` | Override theme: `auto`, `paper`, `obsidian`, `sepia`, `nordic` |
| `--version` | Print `md-viewer` version and exit |

## Keyboard Shortcuts

### Application & Editor

| Action | Shortcut |
|---|---|
| New Tab | `Ctrl+N` |
| Open | `Ctrl+O` |
| Close Tab | `Ctrl+W` |
| Save | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| Cycle View (Preview / Split / Edit) | `Ctrl+E` |
| Toggle Split | `Ctrl+\` |
| Refresh | `Ctrl+R` |
| Toggle Sidebar | `Ctrl+B` / `F9` |
| Find | `Ctrl+F` |
| Find & Replace | `Ctrl+H` |
| Toggle Agent Watch Mode | `Ctrl+Shift+W` |
| Diff View | `Ctrl+D` |
| Ask Local Agent | `Ctrl+Shift+A` |
| Cycle Theme (`Paper` / `Obsidian` / `Sepia` / `Nordic`) | `Ctrl+T` |
| Print / Export PDF | `Ctrl+P` |
| Zoom | `Ctrl++` / `Ctrl+-` / `Ctrl+0` |
| Link History | `Alt+Left` / `Alt+Right` |
| Switch Tabs | `Ctrl+Tab` / `Ctrl+Shift+Tab` |
| Copy File Path | `Ctrl+Shift+C` |
| Shortcuts | `Ctrl+?` / `F1` |
| Quit | `Ctrl+Q` |

### Preview Vim Navigation

| Action | Keys |
|---|---|
| Scroll down / up | `j` / `k` |
| Half-page down / up | `d` / `u` |
| Top / bottom of document | `gg` / `G` |
| Previous / next heading | `[` / `]` |
| Open find bar | `/` |

### Global

| Action | Shortcut |
|---|---|
| Global Clipboard Studio | `Super+Shift+M` |

## Security Architecture

`md-viewer` renders untrusted Markdown files inside a locked-down local WebKit2 context:

1. **Per-render cryptographic CSP nonces**: Every render generates a fresh `secrets.token_urlsafe(16)` nonce. The document CSP sets `default-src 'none'`, `script-src 'nonce-<nonce>'`, `connect-src 'none'`, `media-src 'none'`, `object-src 'none'`, and `frame-src 'none'`.
2. **HTML parser allowlist sanitization**: `mdviewer/sanitizer.py` parses rendered HTML with Python's `html.parser.HTMLParser` (never regex). It strips dangerous tags along with all inner content (`script`, `style`, `iframe`, `frame`, `frameset`, `object`, `embed`, `applet`, `noscript`, `template`, `textarea`, `select`, `form`, `meta`, `base`, `link`, `svg`), removes all `on*` event attributes, `srcdoc`, `formaction`, and arbitrary inline `style` (allowing only `text-align` on `th`/`td`), restricts `<input>` to task checkboxes, and rejects `javascript:`, `vbscript:`, `data:text/html`, and `data:image/svg+xml` URLs.
3. **Mermaid `securityLevel: 'strict'`**: KaTeX and Mermaid containers are restored from escaped attributes after HTML sanitization, and Mermaid runs with `securityLevel: "strict"`.
4. **WebKit2 isolation**: WebKit2 settings enforce `allow_universal_access_from_file_urls(False)` and `enable_page_cache(False)`. External links open in the system browser via `decide-policy`.
5. **Remote image privacy gate**: Remote `http:` and `https:` image sources are blocked by default (`allow_remote_images = False`), rewritten to `data-blocked-src` with a `.blocked-remote-img` placeholder until explicitly enabled.

## Agent Skill

Coding agents (Claude Code, Codex, OpenCode, Antigravity) can load [`skills/md-viewer/SKILL.md`](skills/md-viewer/SKILL.md) to learn how to open plans in Watch Mode, launch `--git-diff` reviews, pipe terminal output to `mdv -`, and act on exported `*.review.md` feedback files.

## Dependencies

- Python 3.12+ (system)
- PyGObject / GTK 3 (`python3-gi`, `gir1.2-gtk-3.0`)
- WebKit2GTK 4.1 (`gir1.2-webkit2-4.1`)
- GtkSourceView 300 (`gir1.2-gtksource-3.0`)
- Pygments (`python3-pygments`)
- `markdown` and `pyyaml` (installed into `.venv` via `uv`)
- Bundled offline assets in `assets/vendor/`: KaTeX and Mermaid
