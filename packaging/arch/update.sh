#!/usr/bin/env bash
# Pull latest c100ctl, build the Arch package, install it with pacman.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VARIANT="git"
NCON="--noconfirm"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--stable] [--ask]

  git pull --ff-only in the repo, makepkg the Arch package, then
  sudo pacman -U the built archive.

  --stable   build packaging/arch/c100ctl (tagged release)
  --ask      do not pass --noconfirm to makepkg / pacman
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stable) VARIANT="stable"; shift ;;
    --ask) NCON=""; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -eq 0 ]]; then
  echo "run as your user, not root (pacman will sudo)" >&2
  exit 1
fi

if ! command -v makepkg >/dev/null || ! command -v pacman >/dev/null; then
  echo "makepkg and pacman are required" >&2
  exit 1
fi

cd "$ROOT"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "not a git repo: $ROOT" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "working tree is dirty; commit or stash first" >&2
  git status -sb >&2
  exit 1
fi

echo ">>> git pull --ff-only"
git pull --ff-only

if [[ "$VARIANT" == "stable" ]]; then
  PKGDIR="$ROOT/packaging/arch/c100ctl"
  GLOB="c100ctl-[0-9]*.pkg.tar.*"
else
  PKGDIR="$ROOT/packaging/arch/c100ctl-git"
  GLOB="c100ctl-git-*.pkg.tar.*"
fi

if [[ ! -f "$PKGDIR/PKGBUILD" ]]; then
  echo "missing PKGBUILD: $PKGDIR/PKGBUILD" >&2
  exit 1
fi

echo ">>> makepkg in $PKGDIR"
cd "$PKGDIR"
# mise/asdf shims hide Arch python; keep /usr/bin first for makepkg.
export PATH="/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export PYTHONNOUSERSITE=1
makepkg_args=(-fC --syncdeps --rmdeps --needed)
if [[ -n "$NCON" ]]; then
  makepkg_args+=("$NCON")
fi
makepkg "${makepkg_args[@]}"

shopt -s nullglob
pkgs=($GLOB)
if [[ ${#pkgs[@]} -eq 0 ]]; then
  echo "makepkg produced no package matching $GLOB" >&2
  exit 1
fi
pkg="$(ls -t "${pkgs[@]}" | head -n1)"
echo ">>> pacman -U $pkg"
sudo pacman -U ${NCON:+$NCON} --needed "$PWD/$pkg"

if systemctl --user --quiet is-enabled c100ctl.service 2>/dev/null \
   || systemctl --user --quiet is-active c100ctl.service 2>/dev/null; then
  echo ">>> restart c100ctl.service"
  systemctl --user daemon-reload
  systemctl --user try-restart c100ctl.service
else
  echo ">>> enable the daemon when you want it:"
  echo "    systemctl --user enable --now c100ctl.service"
fi

echo "installed $pkg"
