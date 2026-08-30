"""Locate C100 8K VIA and input interfaces without touching the Q1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import PID, PRODUCT, VID
from .hid import HidError, HidInfo, enumerate_devices
from .host import is_macos
from .via import find_via_interfaces

try:
    from evdev import InputDevice, list_devices
except ImportError:  # pragma: no cover
    InputDevice = None
    list_devices = None


KEYBOARD_USAGE_PAGE = 0x01
KEYBOARD_USAGE = 0x06
KEYPAD_USAGE = 0x07


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
    if list_devices is None or InputDevice is None:
        return []
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


def find_macos_input_paths(serial: str | None = None) -> list[str]:
    paths: list[str] = []
    try:
        hid = enumerate_devices(VID, PID)
    except HidError:
        return []
    for info in hid:
        if serial and info.serial and info.serial != serial:
            continue
        keyboard = info.usage_page == KEYBOARD_USAGE_PAGE and info.usage in {
            KEYBOARD_USAGE,
            KEYPAD_USAGE,
        }
        if keyboard:
            paths.append(info.path)
    return sorted(set(paths))


def find_input_paths(serial: str | None = None) -> list[str]:
    if is_macos():
        return find_macos_input_paths(serial)
    return find_evdev_paths(serial)


def find_c100() -> C100Device | None:
    vias = find_via_interfaces()
    if not vias:
        return None
    via = vias[0]
    return C100Device(serial=via.serial, via=via, evdev_paths=find_input_paths(via.serial or None))


def hidraw_exists(path: str) -> bool:
    if Path(path).exists():
        return True
    # macOS hidapi paths are IOService IDs, not filesystem nodes.
    try:
        return any(d.path == path for d in enumerate_devices(VID, PID))
    except HidError:
        return False
