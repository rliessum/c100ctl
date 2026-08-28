"""Recover a Wayland/Hyprland environment for a systemd user daemon."""

from __future__ import annotations

import os
from pathlib import Path


def graphical_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    uid = os.getuid()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    env.setdefault("XDG_CURRENT_DESKTOP", "Hyprland")

    if not env.get("WAYLAND_DISPLAY"):
        for name in ("wayland-1", "wayland-0", "wayland-2"):
            if Path(runtime, name).exists():
                env["WAYLAND_DISPLAY"] = name
                break

    hypr = Path(runtime) / "hypr"
    if hypr.is_dir() and not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        sigs = sorted(
            (p.name for p in hypr.iterdir() if p.is_dir() and not p.name.startswith(".")),
            reverse=True,
        )
        if sigs:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sigs[0]

    bus = Path(runtime) / "bus"
    if bus.exists():
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")

    env.setdefault("DISPLAY", ":0")
    env.setdefault("HOME", str(Path.home()))
    path = env.get("PATH", "")
    extras = [
        str(Path.home() / ".local/bin"),
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
