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

is_macos() { [[ "$(uname -s)" == Darwin ]]; }

usage() {
  cat <<EOF
Usage: ${0##*/} [OPTIONS]

Install c100ctl on Linux or macOS.

Options:
  (no flags)         User-local install (~/.local/bin, ~/.local/share)
  --arch             Build and install the Arch package from this checkout (Linux)
  --arch --update    Pull latest changes then build and install Arch package
  --plugin           Install the Omarchy bar widget plugin from this repo (Linux)
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

if is_macos && (( do_arch || do_plugin )); then
  echo "Arch packaging and the Omarchy plugin are Linux-only." >&2
  exit 1
fi

install_macos() {
  local SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/c100ctl"
  local BIN="${HOME}/.local/bin"
  local LAUNCH="${HOME}/Library/LaunchAgents"
  local PYTHON
  PYTHON="$(command -v python3)"
  if [[ -z "$PYTHON" ]]; then
    echo "python3 not found on PATH. Install with: brew install python" >&2
    exit 1
  fi

  mkdir -p "$SHARE" "$BIN" "$LAUNCH" "$HOME/Library/Logs"

  rm -rf "$SHARE"
  mkdir -p "$SHARE"
  cp -a "$ROOT/c100ctl" "$ROOT/data" "$ROOT/README.md" "$SHARE/"

  local brew_prefix=""
  if command -v brew >/dev/null 2>&1; then
    brew_prefix="$(brew --prefix 2>/dev/null || true)"
  fi
  [[ -z "$brew_prefix" && -d /opt/homebrew ]] && brew_prefix=/opt/homebrew
  [[ -z "$brew_prefix" && -d /usr/local/Homebrew ]] && brew_prefix=/usr/local

  local path_val="${BIN}:${brew_prefix:+$brew_prefix/bin:}/usr/local/bin:/usr/bin:/bin"
  local gi_typelib=""
  local dyld=""
  if [[ -n "$brew_prefix" ]]; then
    gi_typelib="${brew_prefix}/lib/girepository-1.0"
    dyld="${brew_prefix}/lib"
  fi

  cat > "$BIN/c100ctl" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SHARE}\${PYTHONPATH:+:\$PYTHONPATH}"
export PATH="${path_val}\${PATH:+:\$PATH}"
${gi_typelib:+export GI_TYPELIB_PATH="${gi_typelib}\${GI_TYPELIB_PATH:+:\$GI_TYPELIB_PATH}"}
${dyld:+export DYLD_FALLBACK_LIBRARY_PATH="${dyld}\${DYLD_FALLBACK_LIBRARY_PATH:+:\$DYLD_FALLBACK_LIBRARY_PATH}"}
exec "${PYTHON}" -m c100ctl "\$@"
EOF
  chmod +x "$BIN/c100ctl"

  local plist="$LAUNCH/net.liessum.c100ctl.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>net.liessum.c100ctl</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>-m</string>
    <string>c100ctl</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>2</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${path_val}</string>
    <key>PYTHONPATH</key>
    <string>${SHARE}</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/c100ctl.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/c100ctl.log</string>
</dict>
</plist>
EOF

  local uid
  uid="$(id -u)"
  if launchctl bootstrap "gui/${uid}" "$plist" 2>/dev/null; then
    launchctl enable "gui/${uid}/net.liessum.c100ctl" 2>/dev/null || true
  else
    launchctl bootout "gui/${uid}/net.liessum.c100ctl" 2>/dev/null || true
    launchctl bootstrap "gui/${uid}" "$plist" 2>/dev/null || launchctl load -w "$plist"
  fi

  if ! "$PYTHON" -c "import ctypes; ctypes.CDLL('libhidapi.dylib')" >/dev/null 2>&1; then
    echo "Note: hidapi not loadable. Install with: brew install hidapi"
  fi
  if ! "$PYTHON" -c "import gi" >/dev/null 2>&1; then
    echo "Note: GTK GUI needs pygobject. Install with: brew install gtk4 libadwaita pygobject3"
  fi

  echo "Installed C100 Control (macOS user-local)."
  echo "  command : c100ctl"
  echo "  daemon  : launchctl print gui/${uid}/net.liessum.c100ctl"
  echo "  doctor  : c100ctl doctor"
  echo
  echo "Grant Input Monitoring (pad grab) and Accessibility (key injection) to"
  echo "this Python (${PYTHON}) in System Settings → Privacy & Security."
  echo
  "$BIN/c100ctl" doctor || true
}

install_local() {
  if is_macos; then
    install_macos
    return
  fi
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
exec python3 -m c100ctl "\$@"
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
