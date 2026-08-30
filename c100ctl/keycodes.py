"""QMK basic keycodes, Linux evdev names, combo/text helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .host import is_macos

# QMK basic keycodes (HID keyboard page).
QMK: dict[str, int] = {
    "KC_NO": 0x0000,
    "KC_A": 0x0004,
    "KC_B": 0x0005,
    "KC_C": 0x0006,
    "KC_D": 0x0007,
    "KC_E": 0x0008,
    "KC_F": 0x0009,
    "KC_G": 0x000A,
    "KC_H": 0x000B,
    "KC_I": 0x000C,
    "KC_J": 0x000D,
    "KC_K": 0x000E,
    "KC_L": 0x000F,
    "KC_M": 0x0010,
    "KC_N": 0x0011,
    "KC_O": 0x0012,
    "KC_P": 0x0013,
    "KC_Q": 0x0014,
    "KC_R": 0x0015,
    "KC_S": 0x0016,
    "KC_T": 0x0017,
    "KC_U": 0x0018,
    "KC_V": 0x0019,
    "KC_W": 0x001A,
    "KC_X": 0x001B,
    "KC_Y": 0x001C,
    "KC_Z": 0x001D,
    "KC_1": 0x001E,
    "KC_2": 0x001F,
    "KC_3": 0x0020,
    "KC_4": 0x0021,
    "KC_5": 0x0022,
    "KC_6": 0x0023,
    "KC_7": 0x0024,
    "KC_8": 0x0025,
    "KC_9": 0x0026,
    "KC_0": 0x0027,
    "KC_ENTER": 0x0028,
    "KC_ESC": 0x0029,
    "KC_BSPC": 0x002A,
    "KC_TAB": 0x002B,
    "KC_SPC": 0x002C,
    "KC_MINS": 0x002D,
    "KC_EQL": 0x002E,
    "KC_LBRC": 0x002F,
    "KC_RBRC": 0x0030,
    "KC_BSLS": 0x0031,
    "KC_SCLN": 0x0033,
    "KC_QUOT": 0x0034,
    "KC_GRV": 0x0035,
    "KC_COMM": 0x0036,
    "KC_DOT": 0x0037,
    "KC_SLSH": 0x0038,
    "KC_CAPS": 0x0039,
    "KC_F1": 0x003A,
    "KC_F2": 0x003B,
    "KC_F3": 0x003C,
    "KC_F4": 0x003D,
    "KC_F5": 0x003E,
    "KC_F6": 0x003F,
    "KC_F7": 0x0040,
    "KC_F8": 0x0041,
    "KC_F9": 0x0042,
    "KC_F10": 0x0043,
    "KC_F11": 0x0044,
    "KC_F12": 0x0045,
    "KC_PSCR": 0x0046,
    "KC_SCRL": 0x0047,
    "KC_PAUS": 0x0048,
    "KC_INS": 0x0049,
    "KC_HOME": 0x004A,
    "KC_PGUP": 0x004B,
    "KC_DEL": 0x004C,
    "KC_END": 0x004D,
    "KC_PGDN": 0x004E,
    "KC_RIGHT": 0x004F,
    "KC_LEFT": 0x0050,
    "KC_DOWN": 0x0051,
    "KC_UP": 0x0052,
    "KC_NUM": 0x0053,
    "KC_PSLS": 0x0054,
    "KC_PAST": 0x0055,
    "KC_PMNS": 0x0056,
    "KC_PPLS": 0x0057,
    "KC_PENT": 0x0058,
    "KC_P1": 0x0059,
    "KC_P2": 0x005A,
    "KC_P3": 0x005B,
    "KC_P4": 0x005C,
    "KC_P5": 0x005D,
    "KC_P6": 0x005E,
    "KC_P7": 0x005F,
    "KC_P8": 0x0060,
    "KC_P9": 0x0061,
    "KC_P0": 0x0062,
    "KC_PDOT": 0x0063,
    "KC_NUBS": 0x0064,
    "KC_APP": 0x0065,
    "KC_F13": 0x0068,
    "KC_F14": 0x0069,
    "KC_F15": 0x006A,
    "KC_F16": 0x006B,
    "KC_F17": 0x006C,
    "KC_F18": 0x006D,
    "KC_F19": 0x006E,
    "KC_F20": 0x006F,
    "KC_F21": 0x0070,
    "KC_F22": 0x0071,
    "KC_F23": 0x0072,
    "KC_F24": 0x0073,
    "KC_LCTL": 0x00E0,
    "KC_LSFT": 0x00E1,
    "KC_LALT": 0x00E2,
    "KC_LGUI": 0x00E3,
    "KC_RCTL": 0x00E4,
    "KC_RSFT": 0x00E5,
    "KC_RALT": 0x00E6,
    "KC_RGUI": 0x00E7,
}

QMK_BY_CODE: dict[int, str] = {v: k for k, v in QMK.items()}

# Linux KEY_* names matching the QMK basics above.
EVDEV: dict[str, str] = {
    "KC_A": "KEY_A",
    "KC_B": "KEY_B",
    "KC_C": "KEY_C",
    "KC_D": "KEY_D",
    "KC_E": "KEY_E",
    "KC_F": "KEY_F",
    "KC_G": "KEY_G",
    "KC_H": "KEY_H",
    "KC_I": "KEY_I",
    "KC_J": "KEY_J",
    "KC_K": "KEY_K",
    "KC_L": "KEY_L",
    "KC_M": "KEY_M",
    "KC_N": "KEY_N",
    "KC_O": "KEY_O",
    "KC_P": "KEY_P",
    "KC_Q": "KEY_Q",
    "KC_R": "KEY_R",
    "KC_S": "KEY_S",
    "KC_T": "KEY_T",
    "KC_U": "KEY_U",
    "KC_V": "KEY_V",
    "KC_W": "KEY_W",
    "KC_X": "KEY_X",
    "KC_Y": "KEY_Y",
    "KC_Z": "KEY_Z",
    "KC_1": "KEY_1",
    "KC_2": "KEY_2",
    "KC_3": "KEY_3",
    "KC_4": "KEY_4",
    "KC_5": "KEY_5",
    "KC_6": "KEY_6",
    "KC_7": "KEY_7",
    "KC_8": "KEY_8",
    "KC_9": "KEY_9",
    "KC_0": "KEY_0",
    "KC_ENTER": "KEY_ENTER",
    "KC_ESC": "KEY_ESC",
    "KC_BSPC": "KEY_BACKSPACE",
    "KC_TAB": "KEY_TAB",
    "KC_SPC": "KEY_SPACE",
    "KC_MINS": "KEY_MINUS",
    "KC_EQL": "KEY_EQUAL",
    "KC_LBRC": "KEY_LEFTBRACE",
    "KC_RBRC": "KEY_RIGHTBRACE",
    "KC_BSLS": "KEY_BACKSLASH",
    "KC_SCLN": "KEY_SEMICOLON",
    "KC_QUOT": "KEY_APOSTROPHE",
    "KC_GRV": "KEY_GRAVE",
    "KC_COMM": "KEY_COMMA",
    "KC_DOT": "KEY_DOT",
    "KC_SLSH": "KEY_SLASH",
    "KC_CAPS": "KEY_CAPSLOCK",
    "KC_F1": "KEY_F1",
    "KC_F2": "KEY_F2",
    "KC_F3": "KEY_F3",
    "KC_F4": "KEY_F4",
    "KC_F5": "KEY_F5",
    "KC_F6": "KEY_F6",
    "KC_F7": "KEY_F7",
    "KC_F8": "KEY_F8",
    "KC_F9": "KEY_F9",
    "KC_F10": "KEY_F10",
    "KC_F11": "KEY_F11",
    "KC_F12": "KEY_F12",
    "KC_PSCR": "KEY_SYSRQ",
    "KC_SCRL": "KEY_SCROLLLOCK",
    "KC_PAUS": "KEY_PAUSE",
    "KC_INS": "KEY_INSERT",
    "KC_HOME": "KEY_HOME",
    "KC_PGUP": "KEY_PAGEUP",
    "KC_DEL": "KEY_DELETE",
    "KC_END": "KEY_END",
    "KC_PGDN": "KEY_PAGEDOWN",
    "KC_RIGHT": "KEY_RIGHT",
    "KC_LEFT": "KEY_LEFT",
    "KC_DOWN": "KEY_DOWN",
    "KC_UP": "KEY_UP",
    "KC_NUM": "KEY_NUMLOCK",
    "KC_PSLS": "KEY_KPSLASH",
    "KC_PAST": "KEY_KPASTERISK",
    "KC_PMNS": "KEY_KPMINUS",
    "KC_PPLS": "KEY_KPPLUS",
    "KC_PENT": "KEY_KPENTER",
    "KC_P1": "KEY_KP1",
    "KC_P2": "KEY_KP2",
    "KC_P3": "KEY_KP3",
    "KC_P4": "KEY_KP4",
    "KC_P5": "KEY_KP5",
    "KC_P6": "KEY_KP6",
    "KC_P7": "KEY_KP7",
    "KC_P8": "KEY_KP8",
    "KC_P9": "KEY_KP9",
    "KC_P0": "KEY_KP0",
    "KC_PDOT": "KEY_KPDOT",
    "KC_NUBS": "KEY_102ND",
    "KC_APP": "KEY_COMPOSE",
    "KC_F13": "KEY_F13",
    "KC_F14": "KEY_F14",
    "KC_F15": "KEY_F15",
    "KC_F16": "KEY_F16",
    "KC_F17": "KEY_F17",
    "KC_F18": "KEY_F18",
    "KC_F19": "KEY_F19",
    "KC_F20": "KEY_F20",
    "KC_F21": "KEY_F21",
    "KC_F22": "KEY_F22",
    "KC_F23": "KEY_F23",
    "KC_F24": "KEY_F24",
    "KC_LCTL": "KEY_LEFTCTRL",
    "KC_LSFT": "KEY_LEFTSHIFT",
    "KC_LALT": "KEY_LEFTALT",
    "KC_LGUI": "KEY_LEFTMETA",
    "KC_RCTL": "KEY_RIGHTCTRL",
    "KC_RSFT": "KEY_RIGHTSHIFT",
    "KC_RALT": "KEY_RIGHTALT",
    "KC_RGUI": "KEY_RIGHTMETA",
}

EVDEV_TO_QMK: dict[str, str] = {v: k for k, v in EVDEV.items()}

ALIASES: dict[str, str] = {
    "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "lctrl": "KEY_LEFTCTRL",
    "rctrl": "KEY_RIGHTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "lshift": "KEY_LEFTSHIFT",
    "rshift": "KEY_RIGHTSHIFT",
    "alt": "KEY_LEFTALT",
    "lalt": "KEY_LEFTALT",
    "ralt": "KEY_RIGHTALT",
    "super": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
    "win": "KEY_LEFTMETA",
    "gui": "KEY_LEFTMETA",
    "cmd": "KEY_LEFTMETA",
    "enter": "KEY_ENTER",
    "return": "KEY_ENTER",
    "esc": "KEY_ESC",
    "escape": "KEY_ESC",
    "space": "KEY_SPACE",
    "spc": "KEY_SPACE",
    "tab": "KEY_TAB",
    "backspace": "KEY_BACKSPACE",
    "bksp": "KEY_BACKSPACE",
    "bspc": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "del": "KEY_DELETE",
    "insert": "KEY_INSERT",
    "ins": "KEY_INSERT",
    "home": "KEY_HOME",
    "end": "KEY_END",
    "pageup": "KEY_PAGEUP",
    "pgup": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN",
    "pgdn": "KEY_PAGEDOWN",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "minus": "KEY_MINUS",
    "equal": "KEY_EQUAL",
    "comma": "KEY_COMMA",
    "dot": "KEY_DOT",
    "period": "KEY_DOT",
    "slash": "KEY_SLASH",
    "semicolon": "KEY_SEMICOLON",
    "quote": "KEY_APOSTROPHE",
    "grave": "KEY_GRAVE",
    "backslash": "KEY_BACKSLASH",
}

US_SHIFT = {
    "A": "a",
    "B": "b",
    "C": "c",
    "D": "d",
    "E": "e",
    "F": "f",
    "G": "g",
    "H": "h",
    "I": "i",
    "J": "j",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "O": "o",
    "P": "p",
    "Q": "q",
    "R": "r",
    "S": "s",
    "T": "t",
    "U": "u",
    "V": "v",
    "W": "w",
    "X": "x",
    "Y": "y",
    "Z": "z",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "~": "`",
    "<": ",",
    ">": ".",
    "?": "/",
}

CHAR_TO_KEY: dict[str, str] = {
    "a": "KEY_A",
    "b": "KEY_B",
    "c": "KEY_C",
    "d": "KEY_D",
    "e": "KEY_E",
    "f": "KEY_F",
    "g": "KEY_G",
    "h": "KEY_H",
    "i": "KEY_I",
    "j": "KEY_J",
    "k": "KEY_K",
    "l": "KEY_L",
    "m": "KEY_M",
    "n": "KEY_N",
    "o": "KEY_O",
    "p": "KEY_P",
    "q": "KEY_Q",
    "r": "KEY_R",
    "s": "KEY_S",
    "t": "KEY_T",
    "u": "KEY_U",
    "v": "KEY_V",
    "w": "KEY_W",
    "x": "KEY_X",
    "y": "KEY_Y",
    "z": "KEY_Z",
    "1": "KEY_1",
    "2": "KEY_2",
    "3": "KEY_3",
    "4": "KEY_4",
    "5": "KEY_5",
    "6": "KEY_6",
    "7": "KEY_7",
    "8": "KEY_8",
    "9": "KEY_9",
    "0": "KEY_0",
    " ": "KEY_SPACE",
    "\n": "KEY_ENTER",
    "\t": "KEY_TAB",
    "-": "KEY_MINUS",
    "=": "KEY_EQUAL",
    "[": "KEY_LEFTBRACE",
    "]": "KEY_RIGHTBRACE",
    "\\": "KEY_BACKSLASH",
    ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE",
    "`": "KEY_GRAVE",
    ",": "KEY_COMMA",
    ".": "KEY_DOT",
    "/": "KEY_SLASH",
}


def qmk_name(code: int) -> str:
    if code in QMK_BY_CODE:
        return QMK_BY_CODE[code]
    if 0x7700 <= code <= 0x770F:
        return f"MACRO{code - 0x7700}"
    return f"0x{code:04X}"


def resolve_key_name(token: str) -> str:
    t = token.strip().lower()
    if not t:
        raise ValueError("empty key name")
    if t in ALIASES:
        return ALIASES[t]
    compact = t.replace("-", "").replace("_", "")
    if compact in ALIASES:
        return ALIASES[compact]
    up = t.upper()
    if up.startswith("KEY_"):
        return up
    if up.startswith("KC_"):
        if up not in EVDEV:
            raise ValueError(f"unknown QMK key {token}")
        return EVDEV[up]
    if len(t) == 1:
        ch = t
        if ch in CHAR_TO_KEY:
            return CHAR_TO_KEY[ch]
        if ch in US_SHIFT and US_SHIFT[ch] in CHAR_TO_KEY:
            return CHAR_TO_KEY[US_SHIFT[ch]]
    if up in EVDEV:
        return EVDEV[up]
    guess = f"KEY_{up}"
    return guess


@dataclass(frozen=True)
class Combo:
    modifiers: tuple[str, ...]
    key: str

    def as_text(self) -> str:
        parts = [m.replace("KEY_", "") for m in self.modifiers] + [self.key.replace("KEY_", "")]
        pretty = []
        for p in parts:
            pretty.append(
                {
                    "LEFTCTRL": "Ctrl",
                    "RIGHTCTRL": "Ctrl",
                    "LEFTSHIFT": "Shift",
                    "RIGHTSHIFT": "Shift",
                    "LEFTALT": "Alt",
                    "RIGHTALT": "Alt",
                    "LEFTMETA": "Cmd" if is_macos() else "Super",
                    "RIGHTMETA": "Cmd" if is_macos() else "Super",
                }.get(p, p.title() if len(p) > 1 else p.upper())
            )
        return "+".join(pretty)


def parse_combo(text: str) -> Combo:
    text = text.strip()
    if "+" in text:
        raw = ["minus" if p.strip() == "" else p.strip() for p in text.split("+")]
        raw = [p for p in raw if p]
    elif "-" in text:
        raw = [p.strip() for p in text.split("-") if p.strip()]
    else:
        raw = [text] if text else []
    if not raw:
        raise ValueError("empty combo")
    keys = [resolve_key_name(p) for p in raw]
    mods = []
    main = None
    mod_set = {
        "KEY_LEFTCTRL",
        "KEY_RIGHTCTRL",
        "KEY_LEFTSHIFT",
        "KEY_RIGHTSHIFT",
        "KEY_LEFTALT",
        "KEY_RIGHTALT",
        "KEY_LEFTMETA",
        "KEY_RIGHTMETA",
    }
    for k in keys:
        if k in mod_set:
            mods.append(k)
        else:
            main = k
    if main is None:
        main = mods.pop()
    return Combo(tuple(mods), main)


@dataclass(frozen=True)
class MacroStep:
    kind: str  # tap, down, up, delay, text
    key: str = ""
    delay_ms: int = 0
    text: str = ""


def parse_macro(text: str) -> list[MacroStep]:
    """Parse `ctrl+c, delay:80, hello, enter`."""
    steps: list[MacroStep] = []
    for part in text.split(","):
        tok = part.strip()
        if not tok:
            continue
        low = tok.lower()
        if low.startswith("delay:") or low.startswith("wait:"):
            steps.append(MacroStep("delay", delay_ms=int(low.split(":", 1)[1])))
            continue
        if low.startswith("text:"):
            steps.append(MacroStep("text", text=tok.split(":", 1)[1]))
            continue
        if low.startswith("down:"):
            steps.append(MacroStep("down", key=resolve_key_name(tok.split(":", 1)[1])))
            continue
        if low.startswith("up:"):
            steps.append(MacroStep("up", key=resolve_key_name(tok.split(":", 1)[1])))
            continue
        if "+" in tok or ("-" in tok and not tok.startswith("-") and not tok.lower().startswith("delay")):
            combo = parse_combo(tok)
            for m in combo.modifiers:
                steps.append(MacroStep("down", key=m))
            steps.append(MacroStep("tap", key=combo.key))
            for m in reversed(combo.modifiers):
                steps.append(MacroStep("up", key=m))
            continue
        # bare word: key or literal text
        try:
            key = resolve_key_name(tok)
            if len(tok) == 1 and tok.isalpha():
                steps.append(MacroStep("text", text=tok))
            else:
                steps.append(MacroStep("tap", key=key))
        except ValueError:
            steps.append(MacroStep("text", text=tok))
    return steps


def chars_to_taps(text: str) -> list[tuple[str, bool]]:
    """Return (evdev_key, need_shift) taps for a US-layout string."""
    out: list[tuple[str, bool]] = []
    for ch in text:
        if ch in CHAR_TO_KEY:
            out.append((CHAR_TO_KEY[ch], False))
            continue
        if ch in US_SHIFT:
            base = US_SHIFT[ch]
            if base in CHAR_TO_KEY:
                out.append((CHAR_TO_KEY[base], True))
                continue
        raise ValueError(f"cannot type {ch!r} with the US layout helper")
    return out
