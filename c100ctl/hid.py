"""Minimal hidapi wrapper. Keeps one C100 VIA interface open.

Linux uses libhidapi-hidraw; macOS uses the IOKit hidapi dylib.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass

from .host import is_macos


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


def hidapi_candidates() -> list[str]:
    """Library names to try, first match wins."""
    names: list[str] = []
    if is_macos():
        found = ctypes.util.find_library("hidapi")
        if found:
            names.append(found)
        names.extend(
            [
                "libhidapi.dylib",
                "libhidapi.0.dylib",
                "/opt/homebrew/lib/libhidapi.dylib",
                "/usr/local/lib/libhidapi.dylib",
            ]
        )
    else:
        for key in ("hidapi-hidraw", "hidapi-libusb", "hidapi"):
            found = ctypes.util.find_library(key)
            if found:
                names.append(found)
        names.extend(
            [
                "libhidapi-hidraw.so.0",
                "libhidapi-hidraw.so",
                "libhidapi-libusb.so.0",
                "libhidapi.so.0",
            ]
        )
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _bind(lib: ctypes.CDLL) -> None:
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


def _load() -> ctypes.CDLL:
    tried: list[str] = []
    last: OSError | None = None
    for name in hidapi_candidates():
        tried.append(name)
        try:
            lib = ctypes.CDLL(name)
        except OSError as e:
            last = e
            continue
        _bind(lib)
        if lib.hid_init() != 0:
            raise HidError("hid_init failed")
        return lib
    detail = f": {last}" if last else ""
    raise HidError("hidapi not found (tried " + ", ".join(tried) + ")" + detail)


_LIB: ctypes.CDLL | None = None


def _lib() -> ctypes.CDLL:
    global _LIB
    if _LIB is None:
        _LIB = _load()
    return _LIB


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
    lib = _lib()
    ptr = lib.hid_enumerate(vid, pid)
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
        lib.hid_free_enumeration(ptr)
    return out


class HidDevice:
    def __init__(self, path: str):
        self.path = path
        lib = _lib()
        self._h = lib.hid_open_path(path.encode())
        if not self._h:
            raise HidError(f"open {path}: {lib.hid_error(None)}")

    def close(self) -> None:
        if self._h:
            _lib().hid_close(self._h)
            self._h = None

    def write(self, data: bytes) -> int:
        if not self._h:
            raise HidError("device closed")
        n = _lib().hid_write(self._h, data, len(data))
        if n < 0:
            raise HidError(f"write: {_lib().hid_error(self._h)}")
        return n

    def read(self, size: int = 32, timeout_ms: int = 400) -> bytes:
        if not self._h:
            raise HidError("device closed")
        buf = ctypes.create_string_buffer(size + 1)
        n = _lib().hid_read_timeout(self._h, buf, size, timeout_ms)
        if n < 0:
            raise HidError(f"read: {_lib().hid_error(self._h)}")
        if n == 0:
            return b""
        return buf.raw[:n]

    def __enter__(self) -> HidDevice:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
