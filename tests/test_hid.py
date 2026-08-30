import unittest
from unittest.mock import patch

from c100ctl.hid import HidDevice, HidError


class FakeLib:
    def hid_open_path(self, path):
        return None if path == b"fail" else 42

    def hid_close(self, h):
        pass

    def hid_write(self, h, data, n):
        return -1 if n == 0 else n

    def hid_read_timeout(self, h, buf, size, timeout):
        if timeout == 1:
            return -1
        return 0

    def hid_error(self, h):
        return "boom"


class HidDeviceTest(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("c100ctl.hid._LIB", FakeLib())
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_open_fail(self):
        with self.assertRaises(HidError):
            HidDevice("fail")

    def test_write_read_close(self):
        dev = HidDevice("/ok")
        n = dev.write(b"\x00\x01")
        self.assertEqual(n, 2)
        self.assertEqual(dev.read(32, timeout_ms=10), b"")
        with self.assertRaises(HidError):
            dev.write(b"")
        with self.assertRaises(HidError):
            dev.read(8, timeout_ms=1)
        dev.close()
        with self.assertRaises(HidError):
            dev.write(b"x")
        with self.assertRaises(HidError):
            dev.read(8)
        with HidDevice("/ok") as d:
            self.assertEqual(d.path, "/ok")
