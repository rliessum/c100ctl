"""VIA protocol client for QMK Keychron boards (protocol 11+ / v3)."""

from __future__ import annotations

import colorsys
import math
import threading
from collections.abc import Sequence

from . import PID, VID
from .hid import HidDevice, HidError, HidInfo, enumerate_devices

VIA_USAGE_PAGE = 0xFF60
VIA_USAGE = 0x61
REPORT_LEN = 32

# Firmware replies with this in byte 0 for a command it does not implement.
UNSUPPORTED = 0xFF

CMD_GET_PROTOCOL_VERSION = 0x01
CMD_GET_KEYBOARD_VALUE = 0x02
CMD_SET_KEYBOARD_VALUE = 0x03
CMD_DYNAMIC_KEYMAP_GET_KEYCODE = 0x04
CMD_DYNAMIC_KEYMAP_SET_KEYCODE = 0x05
CMD_CUSTOM_SET_VALUE = 0x07
CMD_CUSTOM_GET_VALUE = 0x08
CMD_CUSTOM_SAVE = 0x09
CMD_EEPROM_RESET = 0x0A
CMD_MACRO_GET_COUNT = 0x0C
CMD_MACRO_GET_BUFFER_SIZE = 0x0D
CMD_MACRO_GET_BUFFER = 0x0E
CMD_MACRO_SET_BUFFER = 0x0F
CMD_MACRO_RESET = 0x10
CMD_GET_LAYER_COUNT = 0x11
CMD_KEYMAP_GET_BUFFER = 0x12
CMD_KEYMAP_SET_BUFFER = 0x13

VALUE_UPTIME = 0x01
VALUE_LAYOUT_OPTIONS = 0x02
VALUE_SWITCH_MATRIX = 0x03
VALUE_FIRMWARE_VERSION = 0x04

RGB_CHANNEL = 3
RGB_BRIGHTNESS = 1
RGB_EFFECT = 2
RGB_SPEED = 3
RGB_COLOR = 4

# Keychron custom RGB (HID command 0xA8), used for per-key colors.
KC_RGB = 0xA8
KC_RGB_SAVE = 2
KC_RGB_LED_COUNT = 5
KC_RGB_LED_NUMBER = 6
KC_RGB_GET_EFFECT = 7
KC_RGB_SET_EFFECT = 8
KC_RGB_GET_COLOR = 9
KC_RGB_SET_COLOR = 10
PER_KEY_EFFECT = 23
MIX_RGB_EFFECT = 24
PER_KEY_RGB_SOLID = 0
LEDS_PER_PACKET = 9
MIX_REGION_CHUNK = 28
MIX_EFFECT_CHUNK = 3
MIX_EFFECT_BYTES = 8
MIX_LAYERS = 2
MIX_SLOTS = 5

KC_FIRMWARE_VERSION = 0xA1
KC_GET_SUPPORT_FEATURE = 0xA2
KC_MISC = 0xA7
MISC_DEBOUNCE_GET = 5
MISC_DEBOUNCE_SET = 6
MISC_REPORT_RATE_GET = 0x0D
MISC_REPORT_RATE_SET = 0x0E
MISC_NKRO_GET = 0x12
MISC_NKRO_SET = 0x13
KC_RGB_MIX_INFO = 11
KC_RGB_MIX_GET_REGIONS = 12
KC_RGB_MIX_SET_REGIONS = 13
KC_RGB_MIX_GET_EFFECTS = 14
KC_RGB_MIX_SET_EFFECTS = 15

POLL_HZ = (8000, 4000, 2000, 1000, 500, 250, 125)

BUFFER_CHUNK = 28


class ViaError(RuntimeError):
    pass


def find_via_interfaces(vid: int = VID, pid: int = PID) -> list[HidInfo]:
    return [
        info
        for info in enumerate_devices(vid, pid)
        if info.usage_page == VIA_USAGE_PAGE and info.usage == VIA_USAGE
    ]


class ViaClient:
    def __init__(self, path: str):
        self.path = path
        self._dev = HidDevice(path)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._dev.close()

    def _cmd(self, payload: Sequence[int], timeout_ms: int = 500) -> bytes:
        data = bytes(payload[:REPORT_LEN]).ljust(REPORT_LEN, b"\x00")
        pkt = b"\x00" + data
        with self._lock:
            try:
                self._dev.write(pkt)
                raw = self._dev.read(REPORT_LEN, timeout_ms)
            except HidError as e:
                raise ViaError(str(e)) from e
        if not raw:
            raise ViaError(f"timeout waiting for VIA response to {payload[:4]!r}")
        # The firmware echoes the command byte. A different byte means the
        # response stream is out of step with the requests, and parsing it
        # would silently yield another command's payload as this one's.
        # UNSUPPORTED is the firmware's own reply for a command it lacks.
        if raw[0] not in (data[0], UNSUPPORTED):
            raise ViaError(
                f"VIA response out of sync: sent {data[0]:#04x}, got {raw[0]:#04x}"
            )
        # Short reads would otherwise surface as IndexError from the callers
        # that index fixed offsets into the reply.
        return raw[:REPORT_LEN].ljust(REPORT_LEN, b"\x00")

    def protocol_version(self) -> int:
        r = self._cmd([CMD_GET_PROTOCOL_VERSION])
        return (r[1] << 8) | r[2]

    def layer_count(self) -> int:
        r = self._cmd([CMD_GET_LAYER_COUNT])
        return r[1]

    def firmware_version(self) -> int:
        r = self._cmd([CMD_GET_KEYBOARD_VALUE, VALUE_FIRMWARE_VERSION])
        return (r[2] << 24) | (r[3] << 16) | (r[4] << 8) | r[5]

    def get_keycode(self, layer: int, row: int, col: int) -> int:
        r = self._cmd([CMD_DYNAMIC_KEYMAP_GET_KEYCODE, layer, row, col])
        return (r[4] << 8) | r[5]

    def set_keycode(self, layer: int, row: int, col: int, keycode: int) -> None:
        self._cmd(
            [
                CMD_DYNAMIC_KEYMAP_SET_KEYCODE,
                layer,
                row,
                col,
                (keycode >> 8) & 0xFF,
                keycode & 0xFF,
            ]
        )

    def read_keymap(self, layers: int, rows: int, cols: int) -> list[list[list[int]]]:
        total = layers * rows * cols * 2
        buf = bytearray()
        offset = 0
        while offset < total:
            size = min(BUFFER_CHUNK, total - offset)
            r = self._cmd(
                [CMD_KEYMAP_GET_BUFFER, (offset >> 8) & 0xFF, offset & 0xFF, size]
            )
            buf.extend(r[4 : 4 + size])
            offset += size
        keymap: list[list[list[int]]] = []
        i = 0
        for _layer in range(layers):
            layer_map: list[list[int]] = []
            for _row in range(rows):
                row_map: list[int] = []
                for _col in range(cols):
                    row_map.append((buf[i] << 8) | buf[i + 1])
                    i += 2
                layer_map.append(row_map)
            keymap.append(layer_map)
        return keymap

    def write_keymap_layer(self, layer: int, rows: int, cols: int, matrix: list[list[int]]) -> None:
        flat: list[int] = []
        for r in range(rows):
            for c in range(cols):
                kc = matrix[r][c]
                flat.append((kc >> 8) & 0xFF)
                flat.append(kc & 0xFF)
        base = layer * rows * cols * 2
        offset = 0
        while offset < len(flat):
            chunk = flat[offset : offset + BUFFER_CHUNK]
            payload = [
                CMD_KEYMAP_SET_BUFFER,
                ((base + offset) >> 8) & 0xFF,
                (base + offset) & 0xFF,
                len(chunk),
                *chunk,
            ]
            self._cmd(payload)
            offset += len(chunk)

    def matrix_pressed(self, rows: int, cols: int) -> list[tuple[int, int]]:
        r = self._cmd([CMD_GET_KEYBOARD_VALUE, VALUE_SWITCH_MATRIX])
        bits = r[2:]
        pressed: list[tuple[int, int]] = []
        bit_i = 0
        for row in range(rows):
            for col in range(cols):
                byte = bits[bit_i // 8]
                if byte & (1 << (bit_i % 8)):
                    pressed.append((row, col))
                bit_i += 1
        return pressed

    def macro_count(self) -> int:
        return self._cmd([CMD_MACRO_GET_COUNT])[1]

    def get_rgb(self, value_id: int) -> bytes:
        r = self._cmd([CMD_CUSTOM_GET_VALUE, RGB_CHANNEL, value_id])
        return r[3:]

    def set_rgb(self, value_id: int, data: Sequence[int], save: bool = False) -> None:
        self._cmd([CMD_CUSTOM_SET_VALUE, RGB_CHANNEL, value_id, *data])
        if save:
            self._cmd([CMD_CUSTOM_SAVE])

    def brightness(self) -> int:
        return self.get_rgb(RGB_BRIGHTNESS)[0]

    def set_brightness(self, value: int, save: bool = True) -> None:
        self.set_rgb(RGB_BRIGHTNESS, [max(0, min(255, value))], save=save)

    def effect(self) -> int:
        return self.get_rgb(RGB_EFFECT)[0]

    def set_effect(self, value: int, save: bool = True) -> None:
        self.set_rgb(RGB_EFFECT, [max(0, min(255, value))], save=save)

    def speed(self) -> int:
        return self.get_rgb(RGB_SPEED)[0]

    def set_speed(self, value: int, save: bool = True) -> None:
        self.set_rgb(RGB_SPEED, [max(0, min(255, value))], save=save)

    def color_hsv(self) -> tuple[int, int]:
        d = self.get_rgb(RGB_COLOR)
        return d[0], d[1]

    def set_color_hsv(self, hue: int, sat: int, save: bool = True) -> None:
        self.set_rgb(RGB_COLOR, [hue & 0xFF, sat & 0xFF], save=save)

    def led_count(self) -> int:
        r = self._cmd([KC_RGB, KC_RGB_LED_COUNT])
        return r[3]

    def led_map(self, rows: int = 10, cols: int = 10) -> list[list[int]]:
        """Matrix row/col → LED index.  C100 is identity (row * cols + col)."""
        grid: list[list[int]] = []
        for row in range(rows):
            r = self._cmd([KC_RGB, KC_RGB_LED_NUMBER, row, 255, 255, 255])
            indices = [int(x) for x in r[3 : 3 + cols]]
            grid.append(indices)
        return grid

    def enable_per_key(self, save: bool = True) -> None:
        self.set_effect(PER_KEY_EFFECT, save=save)

    def save_leds(self) -> None:
        self._cmd([KC_RGB, KC_RGB_SAVE])

    def get_led_hsv(self, start: int, count: int) -> list[tuple[int, int, int]]:
        count = max(1, min(LEDS_PER_PACKET, count))
        r = self._cmd([KC_RGB, KC_RGB_GET_COLOR, start & 0xFF, count])
        out: list[tuple[int, int, int]] = []
        for i in range(count):
            o = 3 + i * 3
            out.append((r[o], r[o + 1], r[o + 2]))
        return out

    def set_led_hsv(self, index: int, hsv: tuple[int, int, int]) -> None:
        h, s, v = hsv
        self._cmd([KC_RGB, KC_RGB_SET_COLOR, index & 0xFF, 1, h & 0xFF, s & 0xFF, v & 0xFF])

    def set_leds_hsv(self, start: int, colors: Sequence[tuple[int, int, int]]) -> None:
        chunk = list(colors)[:LEDS_PER_PACKET]
        payload: list[int] = [KC_RGB, KC_RGB_SET_COLOR, start & 0xFF, len(chunk)]
        for h, s, v in chunk:
            payload.extend([h & 0xFF, s & 0xFF, v & 0xFF])
        self._cmd(payload)

    def set_led_rgb(self, index: int, rgb: tuple[int, int, int]) -> None:
        self.set_led_hsv(index, rgb_to_hsv255(*rgb))

    def write_all_rgb(self, colors: Sequence[tuple[int, int, int]], save: bool = True) -> None:
        i = 0
        hsv = [rgb_to_hsv255(*c) for c in colors]
        while i < len(hsv):
            self.set_leds_hsv(i, hsv[i : i + LEDS_PER_PACKET])
            i += LEDS_PER_PACKET
        if save:
            self.save_leds()

    def set_per_key_type(self, type_id: int) -> None:
        self._cmd([KC_RGB, KC_RGB_SET_EFFECT, max(0, min(4, type_id))])

    def get_per_key_type(self) -> int:
        r = self._cmd([KC_RGB, KC_RGB_GET_EFFECT])
        return int(r[3])

    def firmware_string(self) -> str:
        r = self._cmd([KC_FIRMWARE_VERSION])
        return r[1:].split(b"\x00", 1)[0].decode("ascii", "replace").strip()

    def support_features(self) -> int:
        r = self._cmd([KC_GET_SUPPORT_FEATURE])
        return int(r[2]) | (int(r[3]) << 8)

    def get_poll_div(self) -> int | None:
        r = self._cmd([KC_MISC, MISC_REPORT_RATE_GET])
        if r[0] == 0xFF or r[2] not in (0, 1):
            return None
        return int(r[3])

    def set_poll_div(self, div: int) -> bool:
        r = self._cmd([KC_MISC, MISC_REPORT_RATE_SET, max(0, min(6, div))])
        return r[0] != 0xFF and r[2] == 0

    def get_debounce(self) -> tuple[int, int] | None:
        r = self._cmd([KC_MISC, MISC_DEBOUNCE_GET, 255])
        if r[0] == 0xFF:
            return None
        return int(r[4]), int(r[5])

    def set_debounce(self, type_id: int, ms: int) -> bool:
        r = self._cmd([KC_MISC, MISC_DEBOUNCE_SET, type_id & 0xFF, max(0, min(255, ms))])
        return r[0] != 0xFF and r[2] == 0

    def get_nkro(self) -> tuple[bool, bool] | None:
        r = self._cmd([KC_MISC, MISC_NKRO_GET])
        if r[0] == 0xFF:
            return None
        flags = int(r[3])
        return bool(flags & 1), bool(flags & 2)

    def set_nkro(self, enabled: bool) -> bool:
        r = self._cmd([KC_MISC, MISC_NKRO_SET, 1 if enabled else 0])
        return r[0] != 0xFF and r[2] == 0

    def mix_info(self) -> tuple[int, int]:
        r = self._cmd([KC_RGB, KC_RGB_MIX_INFO])
        return int(r[3] or MIX_LAYERS), int(r[4] or MIX_SLOTS)

    def get_mix_regions(self, count: int = 100) -> list[int]:
        out: list[int] = []
        i = 0
        while i < count:
            n = min(MIX_REGION_CHUNK, count - i)
            r = self._cmd([KC_RGB, KC_RGB_MIX_GET_REGIONS, i, n])
            out.extend(int(x) for x in r[3 : 3 + n])
            i += n
        return out[:count]

    def set_mix_regions(self, regions: Sequence[int]) -> None:
        i = 0
        vals = [max(0, min(1, int(x))) for x in regions]
        while i < len(vals):
            chunk = vals[i : i + MIX_REGION_CHUNK]
            self._cmd([KC_RGB, KC_RGB_MIX_SET_REGIONS, i, len(chunk), *chunk])
            i += len(chunk)

    def get_mix_slots(self, layer: int, slots: int = MIX_SLOTS) -> list[dict[str, int]]:
        out: list[dict[str, int]] = []
        start = 0
        while start < slots:
            n = min(MIX_EFFECT_CHUNK, slots - start)
            r = self._cmd([KC_RGB, KC_RGB_MIX_GET_EFFECTS, layer & 0xFF, start, n])
            for i in range(n):
                o = 3 + i * MIX_EFFECT_BYTES
                time_ms = int.from_bytes(bytes(r[o + 4 : o + 8]), "little")
                out.append(
                    {
                        "effect": int(r[o]),
                        "hue": int(r[o + 1]),
                        "sat": int(r[o + 2]),
                        "speed": int(r[o + 3]),
                        "time_ms": time_ms,
                    }
                )
            start += n
        return out

    def set_mix_slots(self, layer: int, slots: Sequence[dict[str, int]]) -> None:
        packed: list[int] = []
        for slot in list(slots)[:MIX_SLOTS]:
            time_ms = max(0, int(slot.get("time_ms", 5000)))
            packed.extend(
                [
                    int(slot.get("effect", 0)) & 0xFF,
                    int(slot.get("hue", 0)) & 0xFF,
                    int(slot.get("sat", 255)) & 0xFF,
                    int(slot.get("speed", 127)) & 0xFF,
                    *time_ms.to_bytes(4, "little"),
                ]
            )
        while len(packed) < MIX_SLOTS * MIX_EFFECT_BYTES:
            packed.extend([0, 0, 255, 127, * (5000).to_bytes(4, "little")])
        start = 0
        while start < MIX_SLOTS:
            n = min(MIX_EFFECT_CHUNK, MIX_SLOTS - start)
            chunk = packed[start * MIX_EFFECT_BYTES : (start + n) * MIX_EFFECT_BYTES]
            self._cmd([KC_RGB, KC_RGB_MIX_SET_EFFECTS, layer & 0xFF, start, n, *chunk])
            start += n


def poll_hz_from_div(div: int) -> int:
    div = max(0, min(6, int(div)))
    return 8000 // (1 << div)


def poll_div_from_hz(hz: int) -> int:
    best = 0
    for i, value in enumerate(POLL_HZ):
        if abs(value - hz) < abs(POLL_HZ[best] - hz):
            best = i
    return best


def rgb_to_hsv255(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    h8 = int(round(h * 255)) % 256
    s8 = int(round(s * 255))
    v8 = int(round(v * 255))
    h8, s8 = _led_green(h8, s8)
    return h8, s8, v8


def _led_green(h: int, s: int) -> tuple[int, int]:
    """Map mint/spring sRGB greens onto a hue the C100 LEDs read as green.

    Firmware stores HSV and renders with hsv_to_rgb(), then replaces V with
    global brightness.  iOS-style greens (~hue 96, sat ~74%) therefore show
    as washed teal.  Pull that band onto QMK green and max saturation.
    Yellow, teal, and other hues are left alone.
    """
    if s < 64 or not 86 <= h <= 115:
        return h, s
    h = 78 + int(round((h - 86) * 7 / 29))
    if s >= 80:
        s = 255
    return h, s


def hsv255_to_rgb(h: int, s: int, v: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h / 255.0, s / 255.0, v / 255.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def parse_hex_color(value: str) -> tuple[int, int, int]:
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"invalid color {value!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


# Cold → hot, all high saturation so C100 LEDs still read a ramp when they
# ignore per-key V and substitute global brightness.
HEAT_CAP = 12
_HEAT_STOPS = (
    (0.00, (24, 56, 200)),
    (0.22, (0, 180, 255)),
    (0.42, (40, 230, 90)),
    (0.62, (255, 210, 0)),
    (0.82, (255, 72, 0)),
    (1.00, (255, 32, 32)),
)


def heatmap_rgb(hits: int, cap: int = HEAT_CAP) -> tuple[int, int, int]:
    """RGB for a key-hit heatmap. 0 is off; more hits run blue → red."""
    if hits <= 0:
        return (0, 0, 0)
    t = min(1.0, math.log1p(hits) / math.log1p(max(1, cap)))
    prev_t, prev_c = _HEAT_STOPS[0]
    for nxt_t, nxt_c in _HEAT_STOPS[1:]:
        if t <= nxt_t:
            span = nxt_t - prev_t
            u = (t - prev_t) / span if span else 1.0
            return (
                int(round(prev_c[0] + (nxt_c[0] - prev_c[0]) * u)),
                int(round(prev_c[1] + (nxt_c[1] - prev_c[1]) * u)),
                int(round(prev_c[2] + (nxt_c[2] - prev_c[2]) * u)),
            )
        prev_t, prev_c = nxt_t, nxt_c
    return _HEAT_STOPS[-1][1]


def heatmap_hex(hits: int, cap: int = HEAT_CAP) -> str | None:
    if hits <= 0:
        return None
    return rgb_to_hex(*heatmap_rgb(hits, cap))
