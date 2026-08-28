"""VIA protocol client for QMK Keychron boards (protocol 11+ / v3)."""

from __future__ import annotations

import threading
from typing import Sequence

from .hid import HidDevice, HidError, HidInfo, enumerate_devices
from . import PID, VID

VIA_USAGE_PAGE = 0xFF60
VIA_USAGE = 0x61
REPORT_LEN = 32

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
        return raw[:REPORT_LEN]

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
