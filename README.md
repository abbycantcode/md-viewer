# md-viewer

Lightweight markdown viewer and editor for Ubuntu. GTK3 + WebKit2 native GUI — no Electron, no npm, no heavy frameworks.

## Setup

```bash
bash setup.sh
```

This will:
- Make scripts executable
- Create a lightweight `uv` virtual environment with `--system-site-packages` and install `markdown`
- Install the `md-viewer.desktop` entry into `~/.local/share/applications/`
- Register `md-viewer` as the default handler for Markdown files (`text/markdown` & `text/x-markdown`) in your desktop environment (Nautilus, "Open With", double-click)
- Symlink `md-viewer` into `~/.local/bin/`

## Usage

```bash
# Open a file directly
md-viewer notes.md

# Open without argument (shows file picker)
md-viewer
```

You can also double-click `.md` files or right-click and choose **Open With > Markdown Viewer** in GNOME / Ubuntu Files.

## Keyboard Shortcuts & Controls

| Action | Shortcut | HeaderBar Button |
|---|---|---|
| **Open File** | `Ctrl+O` | 📂 Open button (`document-open-symbolic`) |
| **Save** | `Ctrl+S` | 💾 Save button (`document-save-symbolic`) |
| **Save As** | `Ctrl+Shift+S` | 💾 Save As button (`document-save-as-symbolic`) |
| **Toggle Preview / Edit** | `Ctrl+E` | Segmented Switcher (`Preview` / `Edit`) |
| **Refresh Preview** | `Ctrl+R` | Re-renders preview from buffer |
| **Zoom In** | `Ctrl++` / `Ctrl+=` | 🔍+ Zoom In button |
| **Zoom Out** | `Ctrl+-` | 🔍- Zoom Out button |
| **Reset Zoom** | `Ctrl+0` | `100%` Zoom Reset button |
| **Toggle Light / Dark Theme** | `Ctrl+T` | 🌙 / ☀️ Theme icon button |
| **Quit** | `Ctrl+Q` | Window close |

### System-wide Shortcut

| Action | Shortcut |
|---|---|
| **Clipboard Quick Editor** | `Super+Shift+M` |

Opens a new md-viewer instance in editor mode with the current system clipboard content pre-loaded. Acts as a quick notepad for viewing and editing clipboard text as Markdown. Use `Ctrl+E` to toggle to rendered preview, `Ctrl+S` to save to a file.

You can also launch it from the terminal:

```bash
md-viewer --clipboard
```

## Key Features

- **Blazing Fast**: Native GTK3 + WebKit2GTK startup (<200ms cold start, ~40-60MB RSS)
- **Mermaid Diagrams**: Native rendering for flowcharts, sequence diagrams, state diagrams, class diagrams, and git graphs (` ```mermaid `) with theme synchronization (dark/light) and graceful error recovery
- **KaTeX Math Engine**: High-performance LaTeX formula rendering for inline expressions (`$E=mc^2$`, `\(...\)`) and display equations (`$$...$$`, `\[...\]`, ` ```math `) with offline bundled fonts
- **One-Click Code Copy**: Modern code block frames with language badges and animated "Copy" buttons
- **Reading Statistics**: Live word count and estimated reading time badge integrated into the HeaderBar
- **Refreshed Visual Polish**: Clean modern typography, refined dark/light color schemes, responsive table wrappers, styled checkboxes, and 3D keyboard badges
- **YAML Front-Matter Cards**: Automatically parses document front matter into an elegant, collapsible metadata card with tag badges and formatted key-value tables
- **GitHub Alert Callouts**: Native rendering for `> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`, and `> [!CAUTION]` with matching SVG icons
- **Segmented Mode Switcher**: Native GNOME `Gtk.StackSwitcher` linked controls for seamless switching between rendered preview and source editor
- **Full Zoom Controls**: Synchronized zoom for both rendered HTML preview and editor text size, complete with keyboard shortcuts and HeaderBar percentage indicator
- **GtkSourceView Editor**: Full-featured code editor with line numbers, current line highlighting, matching bracket detection, auto-indentation, and dark/light color schemes (`solarized-dark` / `oblivion` / `solarized-light` / `classic`)
- **Zero White-Flash Dark Theme**: Dynamic background matching between WebKit surface, HTML root/body, and GTK containers eliminates flashes during launches, view switching, or reloads
- **Save & Save As**: Direct file saving with dynamic `*` indicator and suggested-action styling on the Save button when dirty, plus unsaved changes confirmation prompts
- **Auto-Reload**: Automatically detects disk modifications and reloads when viewing files edited in external tools (inhibited while you have unsaved edits)
- **Security-First & 100% Offline**: Strict Content Security Policy (`connect-src 'none'`) blocking any network exfiltration, defensive script sanitization on untrusted inputs, and fully vendored local JS/CSS/font assets (no internet connection or Node/npm needed at runtime). External links safely open in the desktop default browser.
- **Seamless Desktop Integration**: Full MIME type association (`text/markdown`, `text/x-markdown`), Nautilus "Open With" menu, and desktop launcher icon

## Dependencies

- Python 3.12+ (system)
- PyGObject / GTK 3 (system)
- WebKit2GTK 4.1 (system)
- GtkSourceView 300 (system)
- Pygments (system)
- PyYAML (system / uv)
- `markdown` (managed via `uv`)
- Bundled vendor assets: KaTeX 0.16.x and Mermaid 10.x included in `assets/vendor/`

