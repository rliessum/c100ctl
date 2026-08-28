#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/c100ctl"
BIN="${HOME}/.local/bin"
APPDIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONDIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$SHARE" "$BIN" "$APPDIR" "$ICONDIR" "$UNITDIR"

rm -rf "$SHARE"
mkdir -p "$SHARE"
cp -a "$ROOT/c100ctl" "$ROOT/data" "$ROOT/README.md" "$SHARE/"

cat > "$BIN/c100ctl" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SHARE}\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 -m c100ctl "\$@"
EOF
chmod +x "$BIN/c100ctl"

install -m 644 "$ROOT/packaging/c100ctl.desktop" "$APPDIR/c100ctl.desktop"
install -m 644 "$ROOT/packaging/c100ctl.svg" "$ICONDIR/c100ctl.svg"
install -m 644 "$ROOT/packaging/c100ctl.service" "$UNITDIR/c100ctl.service"

# Make Hyprland/Wayland env visible to the user systemd instance.
systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now c100ctl.service

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPDIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
fi

echo "Installed C100 Control."
echo "  command : c100ctl"
echo "  daemon  : systemctl --user status c100ctl.service"
echo "  doctor  : c100ctl doctor"
echo
"$BIN/c100ctl" doctor || true
