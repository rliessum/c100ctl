"""Named catalogs for media, mouse, and lighting host actions."""

from __future__ import annotations

MEDIA_KEYS: list[tuple[str, str, str]] = [
    ("playpause", "Play / Pause", "KEY_PLAYPAUSE"),
    ("play", "Play", "KEY_PLAYCD"),
    ("pause", "Pause", "KEY_PAUSECD"),
    ("stop", "Stop", "KEY_STOPCD"),
    ("next", "Next track", "KEY_NEXTSONG"),
    ("prev", "Previous track", "KEY_PREVIOUSSONG"),
    ("mute", "Mute", "KEY_MUTE"),
    ("volup", "Volume up", "KEY_VOLUMEUP"),
    ("voldown", "Volume down", "KEY_VOLUMEDOWN"),
    ("micmute", "Mic mute", "KEY_MICMUTE"),
    ("brightnessup", "Brightness up", "KEY_BRIGHTNESSUP"),
    ("brightnessdown", "Brightness down", "KEY_BRIGHTNESSDOWN"),
    ("eject", "Eject", "KEY_EJECTCD"),
    ("www", "Browser", "KEY_WWW"),
    ("mail", "Mail", "KEY_MAIL"),
    ("calculator", "Calculator", "KEY_CALC"),
    ("homepage", "Home page", "KEY_HOMEPAGE"),
    ("screenshot", "Screenshot", "KEY_SYSRQ"),
]

MOUSE_ACTIONS: list[tuple[str, str]] = [
    ("left", "Left click"),
    ("right", "Right click"),
    ("middle", "Middle click"),
    ("back", "Back"),
    ("forward", "Forward"),
    ("wheelup", "Scroll up"),
    ("wheeldown", "Scroll down"),
]

LIGHT_ACTIONS: list[tuple[str, str]] = [
    ("next", "Next effect"),
    ("prev", "Previous effect"),
    ("brighter", "Brighter"),
    ("dimmer", "Dimmer"),
    ("toggle", "Toggle lights"),
    ("perkey", "Per-key RGB"),
    ("mix", "Mix RGB"),
]

DEBOUNCE_TYPES: list[tuple[int, str]] = [
    (0, "Defer global"),
    (1, "Defer per row"),
    (2, "Defer per key"),
    (3, "Eager per row"),
    (4, "Eager per key"),
    (5, "Eager defer per key"),
    (6, "None"),
]

POLL_RATES = (8000, 4000, 2000, 1000, 500, 250, 125)

PER_KEY_TYPES: list[tuple[int, str]] = [
    (0, "Solid"),
    (1, "Breathing"),
    (2, "Reactive"),
    (3, "Reactive wide"),
    (4, "Splash"),
]


def media_evdev(name: str) -> str | None:
    for ident, _label, key in MEDIA_KEYS:
        if ident == name:
            return key
    return None


def media_label(name: str) -> str:
    for ident, label, _key in MEDIA_KEYS:
        if ident == name:
            return label
    return name


def mouse_label(name: str) -> str:
    for ident, label in MOUSE_ACTIONS:
        if ident == name:
            return label
    return name


def light_label(name: str) -> str:
    for ident, label in LIGHT_ACTIONS:
        if ident == name:
            return label
    return name
