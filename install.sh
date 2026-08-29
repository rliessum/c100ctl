#!/usr/bin/env bash
# Install c100ctl locally, as an Arch package, and/or as an Omarchy plugin.
#
# Usage:
#   ./install.sh                   # user-local install (~/.local)
#   ./install.sh --arch            # build + pacman -U from this checkout
#   ./install.sh --arch --update   # git pull then build + install
#   ./install.sh --plugin          # install Omarchy plugin from this repo
#   ./install.sh --arch --plugin   # Arch package + Omarchy plugin
#   ./install.sh --help
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

do_local=0
do_arch=0
do_update=0
do_plugin=0
arch_stable=0
arch_ask=0

usage() {
  cat <<EOF
Usage: ${0##*/} [OPTIONS]

Install c100ctl on Linux.

Options:
  (no flags)         User-local install (~/.local/bin, ~/.local/share)
  --arch             Build and install the Arch package from this checkout
  --arch --update    Pull latest changes then build and install Arch package
  --plugin           Install the Omarchy bar widget plugin from this repo
  --stable           (with --arch) Build from the latest git tag
  --ask              (with --arch) Prompt before pacman -U
  -h, --help         Show this help

Examples:
  ./install.sh                   # user-local install
  ./install.sh --arch --plugin   # Arch package + Omarchy plugin
  ./install.sh --arch --update   # pull then rebuild Arch package
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)   do_arch=1; shift ;;
    --update) do_update=1; shift ;;
    --plugin) do_plugin=1; shift ;;
    --stable) arch_stable=1; shift ;;
    --ask)    arch_ask=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Run '${0##*/} --help' for usage." >&2
      exit 1
      ;;
  esac
done

# Default: user-local install if no flags given
if (( !do_arch && !do_plugin )); then
  do_local=1
fi

# --update requires --arch
if (( do_update && !do_arch )); then
  echo "--update requires --arch" >&2
  exit 1
fi

# --stable/--ask require --arch
if (( (arch_stable || arch_ask) && !do_arch )); then
  echo "--stable and --ask require --arch" >&2
  exit 1
fi

install_local() {
  local SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/c100ctl"
  local BIN="${HOME}/.local/bin"
  local APPDIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  local ICONDIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
  local UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

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

  systemctl --user import-environment WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true

  systemctl --user daemon-reload
  systemctl --user enable --now c100ctl.service

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPDIR" 2>/dev/null || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
  fi

  echo "Installed C100 Control (user-local)."
  echo "  command : c100ctl"
  echo "  daemon  : systemctl --user status c100ctl.service"
  echo "  doctor  : c100ctl doctor"
  echo
  "$BIN/c100ctl" doctor || true
}

install_arch() {
  local args=()
  if (( !do_update )); then
    args+=(--no-pull)
  fi
  if (( arch_stable )); then
    args+=(--stable)
  fi
  if (( arch_ask )); then
    args+=(--ask)
  fi
  "$ROOT/packaging/arch/update.sh" "${args[@]}"
}

install_plugin() {
  local PLUGIN_ID="io.github.rliessum.c100ctl"
  local PLUGINS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
  local TARGET="$PLUGINS_DIR/$PLUGIN_ID"
  local SOURCE="$ROOT/omarchy-plugin"

  if [[ ! -d "$SOURCE" ]]; then
    echo "Plugin source not found: $SOURCE" >&2
    return 1
  fi

  mkdir -p "$PLUGINS_DIR"

  if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
    echo "Replacing existing directory with symlink: $TARGET"
    rm -rf "$TARGET"
  fi

  ln -sfn "$SOURCE" "$TARGET"
  echo "Installed Omarchy plugin: $PLUGIN_ID"
  echo "  symlink: $TARGET -> $SOURCE"

  if command -v omarchy >/dev/null 2>&1; then
    omarchy plugin enable "$PLUGIN_ID" 2>/dev/null || true
    echo "  enabled via omarchy plugin enable"
  else
    echo "  (omarchy not found; enable manually: omarchy plugin enable $PLUGIN_ID)"
  fi

  if command -v omarchy-shell >/dev/null 2>&1; then
    omarchy-shell shell rescanPlugins 2>/dev/null || true
    echo "  rescanned via omarchy-shell"
  else
    echo "  (omarchy-shell not found; rescan manually: omarchy-shell shell rescanPlugins)"
  fi
}

# Execute requested installs
if (( do_arch )); then
  install_arch
fi

if (( do_plugin )); then
  install_plugin
fi

if (( do_local )); then
  install_local
fi
