# md-viewer

Lightweight markdown viewer and editor for Ubuntu. GTK3 and WebKit2 native GUI without Electron, npm, or extra runtimes.

## Setup

```bash
bash setup.sh
```

This will:
- Make scripts executable
- Create a `uv` virtual environment with `--system-site-packages` and install `markdown`
- Install `md-viewer.desktop` into `~/.local/share/applications/`
- Register `md-viewer` as the default handler for Markdown files (`text/markdown` and `text/x-markdown`) in your desktop environment
- Symlink `md-viewer` into `~/.local/bin/`

## Usage

```bash
# Open a file directly
md-viewer notes.md

# Open without argument (shows file picker)
md-viewer
```

You can also double-click `.md` files or right-click and choose **Open With > Markdown Viewer** in GNOME / Ubuntu Files.

## Keyboard shortcuts and controls

| Action | Shortcut | Header bar button |
|---|---|---|
| Open file | `Ctrl+O` | Open button (`document-open-symbolic`) |
| Save | `Ctrl+S` | Save button (`document-save-symbolic`) |
| Save as | `Ctrl+Shift+S` | Save As button (`document-save-as-symbolic`) |
| Toggle preview / edit | `Ctrl+E` | Segmented switcher (`Preview` / `Edit`) |
| Refresh preview | `Ctrl+R` | Re-renders preview from buffer |
| Zoom in | `Ctrl++` / `Ctrl+=` | Zoom In button |
| Zoom out | `Ctrl+-` | Zoom Out button |
| Reset zoom | `Ctrl+0` | Zoom reset button (`100%`) |
| Toggle light / dark theme | `Ctrl+T` | Theme button |
| Quit | `Ctrl+Q` | Window close |

### Global shortcut

| Action | Shortcut |
|---|---|
| Clipboard quick editor | `Super+Shift+M` |

Opens md-viewer in editor mode with current system clipboard contents. Use `Ctrl+E` to toggle preview and `Ctrl+S` to save to a file.

You can also launch it from the terminal:

```bash
md-viewer --clipboard
```

## Features

- Fast startup (<200ms cold start, ~40-60MB RSS) using GTK3 and WebKit2GTK.
- Mermaid diagrams for flowcharts, sequence diagrams, state diagrams, class diagrams, and git graphs, with dark and light theme styles.
- LaTeX math rendering with bundled KaTeX for inline (`$...$`, `\(...\)`) and display (`$$...$$`, `\[...\]`) expressions.
- Code blocks with syntax highlighting, language badges, and a copy button.
- Live word count and estimated reading time badge in the header bar.
- Collapsible metadata card for document front matter.
- GitHub alert callouts for `[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, and `[!CAUTION]`.
- Segmented mode switcher (`Ctrl+E`) for preview and source views.
- Synchronized zoom controls for both preview and source views (`Ctrl++`, `Ctrl+-`, `Ctrl+0`).
- Source editor using GtkSourceView with line numbers, current line highlighting, bracket matching, and auto-indent.
- Light and dark themes with matched window and webview backgrounds to avoid white flashes.
- Direct save and Save As with dirty state indicators and unsaved change confirmation dialogs.
- Automatic disk reload when external tools modify the current file.
- Strict Content Security Policy (`connect-src 'none'`) with bundled local assets and script sanitization. External links open in the system default browser.
- Desktop integration with MIME associations and application launchers.

## Dependencies

- Python 3.12+ (system)
- PyGObject / GTK 3 (system)
- WebKit2GTK 4.1 (system)
- GtkSourceView 300 (system)
- Pygments (system)
- PyYAML (system / uv)
- `markdown` (managed via `uv`)
- Bundled vendor assets: KaTeX 0.16.x and Mermaid 10.x in `assets/vendor/`
