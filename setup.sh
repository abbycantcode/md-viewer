#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Making scripts executable..."
chmod +x "$SCRIPT_DIR/md-viewer" "$SCRIPT_DIR/md_viewer.py" "$SCRIPT_DIR/md-viewer-clipboard"

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

echo "[*] Adding to PATH (symlinks)..."
mkdir -p ~/.local/bin
ln -sf "$SCRIPT_DIR/md-viewer" ~/.local/bin/md-viewer
ln -sf "$SCRIPT_DIR/md-viewer-clipboard" ~/.local/bin/md-viewer-clipboard

echo "[*] Installing desktop entries..."
mkdir -p ~/.local/share/applications
cp "$SCRIPT_DIR/md-viewer.desktop" ~/.local/share/applications/
cp "$SCRIPT_DIR/md-viewer-clipboard.desktop" ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "[*] Setting as default handler for Markdown files..."
xdg-mime default md-viewer.desktop text/markdown text/x-markdown

# -- Clipboard quick-launch keybinding (Super+Shift+M) ---------------------
echo "[*] Registering clipboard quick-launch keybinding (Super+Shift+M)..."
KEYBINDING_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KEYBINDING_NAME="md-viewer Clipboard Editor"
KEYBINDING_BINDING="<Super><Shift>m"
KEYBINDING_COMMAND="$HOME/.local/bin/md-viewer-clipboard"

# Read existing custom keybinding paths
existing=$(gsettings get "$KEYBINDING_SCHEMA" custom-keybindings 2>/dev/null)

# Find the next available custom slot, and check if we already registered
next_slot=0
already_registered=false
if [ "$existing" != "@as []" ] && [ -n "$existing" ]; then
    # Iterate existing slots to find our keybinding or the next free index
    clean=$(echo "$existing" | tr -d "[]' ")
    IFS=',' read -ra paths <<< "$clean"
    for p in "${paths[@]}"; do
        p=$(echo "$p" | xargs)  # trim whitespace
        slot_num=$(echo "$p" | grep -oP 'custom\K[0-9]+')
        name=$(gsettings get "${CUSTOM_SCHEMA}:${p}" name 2>/dev/null)
        if [ "$name" = "'${KEYBINDING_NAME}'" ]; then
            already_registered=true
            # Update in place
            gsettings set "${CUSTOM_SCHEMA}:${p}" binding "$KEYBINDING_BINDING"
            gsettings set "${CUSTOM_SCHEMA}:${p}" command "$KEYBINDING_COMMAND"
            break
        fi
        if [ "$slot_num" -ge "$next_slot" ]; then
            next_slot=$((slot_num + 1))
        fi
    done
fi

if [ "$already_registered" = false ]; then
    new_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${next_slot}/"
    gsettings set "${CUSTOM_SCHEMA}:${new_path}" name "$KEYBINDING_NAME"
    gsettings set "${CUSTOM_SCHEMA}:${new_path}" binding "$KEYBINDING_BINDING"
    gsettings set "${CUSTOM_SCHEMA}:${new_path}" command "$KEYBINDING_COMMAND"

    # Append the new path to the existing list
    if [ "$existing" = "@as []" ] || [ -z "$existing" ]; then
        gsettings set "$KEYBINDING_SCHEMA" custom-keybindings "['${new_path}']"
    else
        # Remove trailing ] and append
        updated=$(echo "$existing" | sed "s|]$|, '${new_path}']|")
        gsettings set "$KEYBINDING_SCHEMA" custom-keybindings "$updated"
    fi
fi

echo "[+] Done. md-viewer is configured as default markdown viewer!"
echo "[+] Run: md-viewer <file.md>"
echo "[+] Quick editor: Super+Shift+M (opens clipboard in editor mode)"
