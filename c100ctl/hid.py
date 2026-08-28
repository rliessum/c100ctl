"""Minimal hidapi-hidraw wrapper. Keeps one C100 VIA interface open."""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass


class HidError(RuntimeError):
    pass


class _DeviceInfo(ctypes.Structure):
    pass


_DeviceInfo._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(_DeviceInfo)),
]


def _load() -> ctypes.CDLL:
    lib = ctypes.CDLL("libhidapi-hidraw.so.0")
    lib.hid_init.restype = ctypes.c_int
    lib.hid_exit.restype = ctypes.c_int
    lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
    lib.hid_enumerate.restype = ctypes.POINTER(_DeviceInfo)
    lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_DeviceInfo)]
    lib.hid_open_path.argtypes = [ctypes.c_char_p]
    lib.hid_open_path.restype = ctypes.c_void_p
    lib.hid_close.argtypes = [ctypes.c_void_p]
    lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.hid_write.restype = ctypes.c_int
    lib.hid_read_timeout.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    lib.hid_read_timeout.restype = ctypes.c_int
    lib.hid_error.argtypes = [ctypes.c_void_p]
    lib.hid_error.restype = ctypes.c_wchar_p
    if lib.hid_init() != 0:
        raise HidError("hid_init failed")
    return lib


_LIB = _load()


@dataclass(frozen=True)
class HidInfo:
    path: str
    vendor_id: int
    product_id: int
    serial: str
    product: str
    usage_page: int
    usage: int
    interface: int


def enumerate_devices(vid: int = 0, pid: int = 0) -> list[HidInfo]:
    ptr = _LIB.hid_enumerate(vid, pid)
    out: list[HidInfo] = []
    cur = ptr
    seen: set[tuple[str, int, int]] = set()
    while cur:
        d = cur.contents
        path = (d.path or b"").decode("utf-8", "replace")
        key = (path, d.usage_page, d.usage)
        if path and key not in seen:
            seen.add(key)
            out.append(
                HidInfo(
                    path=path,
                    vendor_id=d.vendor_id,
                    product_id=d.product_id,
                    serial=d.serial_number or "",
                    product=d.product_string or "",
                    usage_page=d.usage_page,
                    usage=d.usage,
                    interface=d.interface_number,
                )
            )
        cur = d.next
    if ptr:
        _LIB.hid_free_enumeration(ptr)
    return out


class HidDevice:
    def __init__(self, path: str):
        self.path = path
        self._h = _LIB.hid_open_path(path.encode())
        if not self._h:
            raise HidError(f"open {path}: {_LIB.hid_error(None)}")

    def close(self) -> None:
        if self._h:
            _LIB.hid_close(self._h)
            self._h = None

    def write(self, data: bytes) -> int:
        if not self._h:
            raise HidError("device closed")
        n = _LIB.hid_write(self._h, data, len(data))
        if n < 0:
            raise HidError(f"write: {_LIB.hid_error(self._h)}")
        return n

    def read(self, size: int = 32, timeout_ms: int = 400) -> bytes:
        if not self._h:
            raise HidError("device closed")
        buf = ctypes.create_string_buffer(size + 1)
        n = _LIB.hid_read_timeout(self._h, buf, size, timeout_ms)
        if n < 0:
            raise HidError(f"read: {_LIB.hid_error(self._h)}")
        if n == 0:
            return b""
        return buf.raw[:n]

    def __enter__(self) -> "HidDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
