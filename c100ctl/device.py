"""Locate C100 8K hidraw and evdev nodes without touching the Q1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evdev import InputDevice, list_devices

from . import PID, PRODUCT, VID
from .hid import HidInfo
from .via import find_via_interfaces


@dataclass
class C100Device:
    serial: str
    via: HidInfo
    evdev_paths: list[str] = field(default_factory=list)
    product: str = PRODUCT

    @property
    def via_path(self) -> str:
        return self.via.path


def _is_c100_evdev(dev: InputDevice) -> bool:
    try:
        info = dev.info
    except OSError:
        return False
    if info.vendor != VID or info.product != PID:
        return False
    name = dev.name or ""
    if name == "C100 Control":
        return False
    return "C100" in name


def find_evdev_paths(serial: str | None = None) -> list[str]:
    paths: list[str] = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        try:
            if not _is_c100_evdev(dev):
                continue
            phys = getattr(dev, "phys", "") or ""
            if phys == "py-evdev-uinput":
                continue
            if serial and dev.uniq and dev.uniq != serial:
                continue
            # Prefer keyboard-like nodes; skip mouse.
            name = (dev.name or "").lower()
            if "mouse" in name:
                continue
            paths.append(path)
        finally:
            try:
                dev.close()
            except OSError:
                pass
    # Boot protocol (event-kbd) + NKRO (if02-event-kbd) + consumer.
    # Grab all of them so nothing leaks to the focused window.
    return sorted(set(paths))


def find_c100() -> C100Device | None:
    vias = find_via_interfaces()
    if not vias:
        return None
    via = vias[0]
    evdev = find_evdev_paths(via.serial or None)
    return C100Device(serial=via.serial, via=via, evdev_paths=evdev)


def hidraw_exists(path: str) -> bool:
    return Path(path).exists()
