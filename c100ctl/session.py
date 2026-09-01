"""Recover a graphical session environment for the user daemon."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .host import is_macos

_HOMEBREW_PREFIXES = ("/opt/homebrew", "/usr/local")


def gtk_argv(argv: list[str] | None = None) -> list[str]:
    """Arguments safe to pass to Gio.Application.run.

    GApplication treats extra argv entries as files unless HANDLES_OPEN is set.
    `c100ctl gui` would otherwise print "This application can not open files"
    and exit before activate.
    """
    argv = list(sys.argv if argv is None else argv)
    if not argv:
        return ["c100ctl"]
    return [argv[0]]


def _prepend_path_env(env: dict[str, str], key: str, extras: list[str]) -> None:
    current = [p for p in env.get(key, "").split(":") if p]
    for extra in reversed(extras):
        if extra in current:
            current.remove(extra)
        current.insert(0, extra)
    env[key] = ":".join(current)


def homebrew_prefixes() -> list[str]:
    prefixes: list[str] = []
    brew = os.environ.get("HOMEBREW_PREFIX")
    if brew:
        prefixes.append(brew.rstrip("/"))
    for prefix in _HOMEBREW_PREFIXES:
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def prepare_gtk_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Point GLib/GTK at Homebrew share, typelibs, and dylibs on macOS.

    Ghostty (and some other terminals) set XDG_DATA_DIRS to their own prefix.
    GLib then never sees /opt/homebrew/share/glib-2.0/schemas, schema source
    is NULL, and Adwaita/GTK widgets fail or warn on every lookup.
    Must run before Gtk/Adw are imported.
    """
    target = os.environ if env is None else env
    if not is_macos():
        return target
    shares: list[str] = []
    typelibs: list[str] = []
    libs: list[str] = []
    for prefix in homebrew_prefixes():
        share = f"{prefix}/share"
        if env is not None or Path(share).is_dir():
            shares.append(share)
        tl = f"{prefix}/lib/girepository-1.0"
        if env is not None or Path(tl).is_dir():
            typelibs.append(tl)
        lib = f"{prefix}/lib"
        if env is not None or Path(lib).is_dir():
            libs.append(lib)
    if shares:
        if not target.get("XDG_DATA_DIRS"):
            shares = [*shares, "/usr/local/share", "/usr/share"]
        _prepend_path_env(target, "XDG_DATA_DIRS", shares)
    if typelibs:
        _prepend_path_env(target, "GI_TYPELIB_PATH", typelibs)
    if libs:
        _prepend_path_env(target, "DYLD_FALLBACK_LIBRARY_PATH", libs)
    return target


def graphical_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    uid = os.getuid()
    if is_macos():
        runtime = env.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    else:
        runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    if not is_macos():
        env.setdefault("XDG_CURRENT_DESKTOP", "Hyprland")

    if not env.get("WAYLAND_DISPLAY"):
        for name in ("wayland-1", "wayland-0", "wayland-2"):
            if Path(runtime, name).exists():
                env["WAYLAND_DISPLAY"] = name
                break

    hypr = Path(runtime) / "hypr"
    if hypr.is_dir() and not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        sigs = sorted(
            (p for p in hypr.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if sigs:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sigs[0].name

    bus = Path(runtime) / "bus"
    if bus.exists():
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")

    if not is_macos():
        env.setdefault("DISPLAY", ":0")
    env.setdefault("HOME", str(Path.home()))
    path = env.get("PATH", "")
    extras = [
        str(Path.home() / ".local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    for extra in extras:
        if extra not in path.split(":"):
            path = f"{path}:{extra}" if path else extra
    env["PATH"] = path
    return env


def hyprctl_available(env: dict[str, str] | None = None) -> bool:
    env = graphical_env(env)
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return False
    from shutil import which

    return which("hyprctl", path=env.get("PATH")) is not None
