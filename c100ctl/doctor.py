"""Health check for HID, VIA, input grab, injection, and the daemon."""

from __future__ import annotations

import os
from pathlib import Path

from . import PID, VID
from .device import find_c100
from .hid import HidError, enumerate_devices, hidapi_candidates
from .host import is_macos
from .ipc import daemon_available
from .session import graphical_env, hyprctl_available


def _ax_trusted() -> bool | None:
    if not is_macos():
        return None
    try:
        import ctypes

        ax = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(ax.AXIsProcessTrusted())
    except (OSError, AttributeError):
        return None


def run() -> int:
    lines: list[str] = []
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "OK " if passed else "NO "
        if not passed:
            ok = False
        extra = f" — {detail}" if detail else ""
        lines.append(f"[{mark}] {name}{extra}")

    try:
        hid = enumerate_devices(VID, PID)
        check("hidapi", True, hidapi_candidates()[0] if hidapi_candidates() else "")
    except HidError as e:
        hid = []
        check("hidapi", False, str(e))

    check("USB C100 8K", bool(hid), f"{len(hid)} HID interface(s)" if hid else "not plugged in")
    via = [h for h in hid if h.usage_page == 0xFF60]
    check("VIA raw HID (0xFF60)", bool(via), via[0].path if via else "")

    found = find_c100()
    if found:
        if is_macos():
            check("keyboard HID", bool(found.evdev_paths), ", ".join(found.evdev_paths) or "none")
        else:
            check("evdev nodes", bool(found.evdev_paths), ", ".join(found.evdev_paths))
        try:
            from .via import ViaClient

            client = ViaClient(found.via_path)
            proto = client.protocol_version()
            layers = client.layer_count()
            client.close()
            check("VIA protocol", proto >= 11, f"v{proto}, {layers} layers")
        except Exception as e:
            check("VIA protocol", False, str(e))
    else:
        if is_macos():
            check("keyboard HID", False, "C100 not found")
        else:
            check("evdev nodes", False, "C100 not found")

    if is_macos():
        from .pad_macos import hid_listen_granted

        listen = hid_listen_granted()
        check(
            "Input Monitoring (pad grab)",
            listen is not False,
            "granted"
            if listen
            else "System Settings → Privacy & Security → Input Monitoring",
        )
        ax = _ax_trusted()
        check(
            "Accessibility (key inject)",
            ax is not False,
            "granted" if ax else "System Settings → Privacy & Security → Accessibility",
        )
    else:
        uinput = Path("/dev/uinput")
        can_uinput = False
        if uinput.exists():
            try:
                fd = os.open(uinput, os.O_RDWR)
                os.close(fd)
                can_uinput = True
            except OSError as e:
                check("/dev/uinput", False, str(e))
        check("/dev/uinput writable", can_uinput, str(uinput) if can_uinput else "need uaccess/input group")

        env = graphical_env()
        check("Wayland display", bool(env.get("WAYLAND_DISPLAY")), env.get("WAYLAND_DISPLAY", ""))
        check("Hyprland socket", hyprctl_available(env), env.get("HYPRLAND_INSTANCE_SIGNATURE", "")[:12])

    check("daemon socket", daemon_available(), "c100ctl daemon")

    print("\n".join(lines))
    return 0 if ok else 1
