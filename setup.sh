#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Making scripts executable..."
chmod +x "$SCRIPT_DIR/md-viewer" "$SCRIPT_DIR/md_viewer.py"

echo "[*] Creating venv with system-site-packages (for GTK/WebKit bindings)..."
uv venv --allow-existing --system-site-packages --python /usr/bin/python3 "$SCRIPT_DIR/.venv"

echo "[*] Installing markdown and pyyaml into venv via uv..."
uv pip install --python "$SCRIPT_DIR/.venv/bin/python" markdown pyyaml

echo "[*] Verifying dependencies & bundled assets (KaTeX + Mermaid)..."
"$SCRIPT_DIR/.venv/bin/python" -c "
import os
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
gi.require_version('GtkSource', '300')
from gi.repository import Gtk, WebKit2, GtkSource
import markdown
import yaml
from pygments.formatters import HtmlFormatter

assets_dir = os.path.join('$SCRIPT_DIR', 'assets', 'vendor')
katex_js = os.path.join(assets_dir, 'katex', 'katex.min.js')
katex_css = os.path.join(assets_dir, 'katex', 'katex.min.css')
katex_auto = os.path.join(assets_dir, 'katex', 'contrib', 'auto-render.min.js')
mermaid_js = os.path.join(assets_dir, 'mermaid', 'mermaid.min.js')
assert os.path.isfile(katex_js), f'Missing KaTeX bundle at {katex_js}'
assert os.path.isfile(katex_css), f'Missing KaTeX CSS at {katex_css}'
assert os.path.isfile(katex_auto), f'Missing KaTeX auto-render at {katex_auto}'
assert os.path.isfile(mermaid_js), f'Missing Mermaid bundle at {mermaid_js}'
print('[+] All dependencies & bundled assets verified.')
"

echo "[*] Adding to PATH (symlink)..."
mkdir -p ~/.local/bin
ln -sf "$SCRIPT_DIR/md-viewer" ~/.local/bin/md-viewer

echo "[*] Installing desktop entry..."
mkdir -p ~/.local/share/applications
cp "$SCRIPT_DIR/md-viewer.desktop" ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "[*] Setting as default handler for Markdown files..."
xdg-mime default md-viewer.desktop text/markdown text/x-markdown

echo "[+] Done. md-viewer is configured as default markdown viewer!"
echo "[+] Run: md-viewer <file.md>"
