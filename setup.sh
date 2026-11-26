#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Making launchers and entrypoint executable..."
chmod +x \
    "$SCRIPT_DIR/markveil" \
    "$SCRIPT_DIR/md-viewer" \
    "$SCRIPT_DIR/mdv" \
    "$SCRIPT_DIR/md-viewer-clipboard" \
    "$SCRIPT_DIR/md_viewer.py"

SYS_PYTHON="${PYTHON:-/usr/bin/python3}"
if [ ! -x "$SYS_PYTHON" ]; then
    SYS_PYTHON="$(command -v python3)"
fi

echo "[*] Creating venv with system-site-packages (for GTK/WebKit bindings)..."
if command -v uv >/dev/null 2>&1; then
    uv venv --allow-existing --system-site-packages --python "$SYS_PYTHON" "$SCRIPT_DIR/.venv"
else
    if [ ! -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        "$SYS_PYTHON" -m venv --system-site-packages "$SCRIPT_DIR/.venv"
    fi
fi

if "$SCRIPT_DIR/.venv/bin/python" -c "import markdown, yaml" >/dev/null 2>&1; then
    echo "[+] markdown and pyyaml already available via system packages or venv."
else
    echo "[*] Installing markdown and pyyaml into venv..."
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$SCRIPT_DIR/.venv/bin/python" markdown pyyaml
    else
        "$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade markdown pyyaml
    fi
fi

echo "[*] Verifying dependencies, mdviewer package, and bundled assets..."
PYTHONPATH="$SCRIPT_DIR" "$SCRIPT_DIR/.venv/bin/python" -c "
import os
import sys
import py_compile

try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    for _ver in ('300', '3.0', '4'):
        try:
            gi.require_version('GtkSource', _ver)
            break
        except ValueError:
            continue
    else:
        gi.require_version('GtkSource', '3.0')
    from gi.repository import Gtk, WebKit2, GtkSource
    import markdown
    import yaml
    from pygments.formatters import HtmlFormatter
except Exception as exc:
    sys.stderr.write(
        f'[!] Missing system dependency: {exc}\n'
        '    Ubuntu/Debian: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-gtksource-3.0 python3-pygments\n'
        '    Fedora:        sudo dnf install gtk3 webkit2gtk4.1 gtksourceview3 python3-gobject python3-pygments python3-markdown python3-pyyaml\n'
        '    Arch Linux:    sudo pacman -S gtk3 webkit2gtk-4.1 gtksourceview3 python-gobject python-pygments python-markdown python-yaml\n'
    )
    sys.exit(1)

import mdviewer
import mdviewer.markdown_engine
import mdviewer.sanitizer
import mdviewer.cli

root = '$SCRIPT_DIR'
py_compile.compile(os.path.join(root, 'md_viewer.py'), doraise=True)

assets_dir = os.path.join(root, 'assets', 'vendor')
katex_js = os.path.join(assets_dir, 'katex', 'katex.min.js')
katex_css = os.path.join(assets_dir, 'katex', 'katex.min.css')
katex_auto = os.path.join(assets_dir, 'katex', 'contrib', 'auto-render.min.js')
mermaid_js = os.path.join(assets_dir, 'mermaid', 'mermaid.min.js')
icon_svg = os.path.join(root, 'assets', 'icons', 'markveil.svg')
assert os.path.isfile(katex_js), f'Missing KaTeX bundle at {katex_js}'
assert os.path.isfile(katex_css), f'Missing KaTeX CSS at {katex_css}'
assert os.path.isfile(katex_auto), f'Missing KaTeX auto-render at {katex_auto}'
assert os.path.isfile(mermaid_js), f'Missing Mermaid bundle at {mermaid_js}'
assert os.path.isfile(icon_svg), f'Missing Markveil icon at {icon_svg}'
print('[+] All dependencies, mdviewer modules, and bundled assets verified.')
"

echo "[*] Adding launchers to ~/.local/bin..."
mkdir -p ~/.local/bin
ln -sf "$SCRIPT_DIR/markveil" ~/.local/bin/markveil
ln -sf "$SCRIPT_DIR/mdv" ~/.local/bin/mdv
ln -sf "$SCRIPT_DIR/md-viewer" ~/.local/bin/md-viewer
ln -sf "$SCRIPT_DIR/md-viewer-clipboard" ~/.local/bin/md-viewer-clipboard

echo "[*] Installing Markveil icons into ~/.local/share/icons/hicolor..."
ICON_BASE="$HOME/.local/share/icons/hicolor"
mkdir -p \
    "$ICON_BASE/scalable/apps" \
    "$ICON_BASE/256x256/apps" \
    "$ICON_BASE/128x128/apps" \
    "$ICON_BASE/48x48/apps"
cp "$SCRIPT_DIR/assets/icons/markveil.svg" "$ICON_BASE/scalable/apps/markveil.svg"
cp "$SCRIPT_DIR/assets/icons/markveil-256.png" "$ICON_BASE/256x256/apps/markveil.png"
cp "$SCRIPT_DIR/assets/icons/markveil-128.png" "$ICON_BASE/128x128/apps/markveil.png"
cp "$SCRIPT_DIR/assets/icons/markveil-48.png" "$ICON_BASE/48x48/apps/markveil.png"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
fi

echo "[*] Installing desktop entries..."
mkdir -p ~/.local/share/applications
rm -f ~/.local/share/applications/md-viewer.desktop
sed \
    -e "s|^Exec=markveil|Exec=$HOME/.local/bin/markveil|" \
    -e "s|^TryExec=markveil|TryExec=$HOME/.local/bin/markveil|" \
    "$SCRIPT_DIR/markveil.desktop" > ~/.local/share/applications/markveil.desktop
sed \
    -e "s|^Exec=md-viewer-clipboard|Exec=$HOME/.local/bin/md-viewer-clipboard|" \
    -e "s|^TryExec=md-viewer-clipboard|TryExec=$HOME/.local/bin/md-viewer-clipboard|" \
    "$SCRIPT_DIR/md-viewer-clipboard.desktop" > ~/.local/share/applications/md-viewer-clipboard.desktop
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
fi

if command -v xdg-mime >/dev/null 2>&1; then
    echo "[*] Setting Markveil as default handler for Markdown MIME types..."
    xdg-mime default markveil.desktop text/markdown text/x-markdown || true
else
    echo "[!] xdg-mime not found; skipping MIME default registration."
fi

# -- Clipboard quick-launch keybinding (Super+Shift+M on GNOME) ----------------
KEYBINDING_SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KEYBINDING_NAME="Markveil Clipboard Studio"
LEGACY_KEYBINDING_NAME="md-viewer Clipboard Editor"
KEYBINDING_BINDING="<Super><Shift>m"
KEYBINDING_COMMAND="$HOME/.local/bin/md-viewer-clipboard"

if command -v gsettings >/dev/null 2>&1 && gsettings writable "$KEYBINDING_SCHEMA" custom-keybindings >/dev/null 2>&1; then
    echo "[*] Registering GNOME clipboard keybinding (Super+Shift+M)..."
    existing=$(gsettings get "$KEYBINDING_SCHEMA" custom-keybindings 2>/dev/null || true)

    next_slot=0
    already_registered=false
    if [ "$existing" != "@as []" ] && [ -n "$existing" ]; then
        clean=$(echo "$existing" | tr -d "[]' ")
        IFS=',' read -ra paths <<< "$clean"
        for p in "${paths[@]}"; do
            p=$(echo "$p" | xargs)
            [ -z "$p" ] && continue
            slot_num=$(echo "$p" | grep -oP 'custom\K[0-9]+' || true)
            name=$(gsettings get "${CUSTOM_SCHEMA}:${p}" name 2>/dev/null || true)
            if [ "$name" = "'${KEYBINDING_NAME}'" ] || [ "$name" = "'${LEGACY_KEYBINDING_NAME}'" ]; then
                already_registered=true
                gsettings set "${CUSTOM_SCHEMA}:${p}" name "$KEYBINDING_NAME"
                gsettings set "${CUSTOM_SCHEMA}:${p}" binding "$KEYBINDING_BINDING"
                gsettings set "${CUSTOM_SCHEMA}:${p}" command "$KEYBINDING_COMMAND"
                break
            fi
            if [ -n "$slot_num" ] && [ "$slot_num" -ge "$next_slot" ]; then
                next_slot=$((slot_num + 1))
            fi
        done
    fi

    if [ "$already_registered" = false ]; then
        new_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${next_slot}/"
        gsettings set "${CUSTOM_SCHEMA}:${new_path}" name "$KEYBINDING_NAME"
        gsettings set "${CUSTOM_SCHEMA}:${new_path}" binding "$KEYBINDING_BINDING"
        gsettings set "${CUSTOM_SCHEMA}:${new_path}" command "$KEYBINDING_COMMAND"

        if [ "$existing" = "@as []" ] || [ -z "$existing" ]; then
            gsettings set "$KEYBINDING_SCHEMA" custom-keybindings "['${new_path}']"
        else
            updated=$(echo "$existing" | sed "s|]$|, '${new_path}']|")
            gsettings set "$KEYBINDING_SCHEMA" custom-keybindings "$updated"
        fi
    fi
else
    echo "[!] GNOME keybinding schema unavailable; skipping Super+Shift+M registration (bind md-viewer-clipboard in your DE/WM)."
fi

echo "[+] Done. Markveil (markveil, mdv, and md-viewer alias) is installed."
echo "[+] Run: markveil <file.md> | mdv -w PLAN.md | md-viewer <file.md>"
echo "[+] Clipboard quick studio: Super+Shift+M (or md-viewer-clipboard)"
