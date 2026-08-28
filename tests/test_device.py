import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from c100ctl.device import C100Device, find_c100, find_evdev_paths, hidraw_exists
from c100ctl.hid import HidInfo


class DeviceTest(unittest.TestCase):
    def test_hidraw_exists(self):
        with tempfile.NamedTemporaryFile() as fh:
            self.assertTrue(hidraw_exists(fh.name))
        self.assertFalse(hidraw_exists("/no/such/hidraw"))

    def test_find_c100_none(self):
        with patch("c100ctl.device.find_via_interfaces", return_value=[]):
            self.assertIsNone(find_c100())

    def test_find_c100_with_via(self):
        info = HidInfo("/dev/hidraw9", 0x3434, 0x042C, "ser", "C100", 0xFF60, 0x61, 0)
        with patch("c100ctl.device.find_via_interfaces", return_value=[info]):
            with patch("c100ctl.device.find_evdev_paths", return_value=["/dev/input/event1"]):
                found = find_c100()
        self.assertIsInstance(found, C100Device)
        self.assertEqual(found.via_path, "/dev/hidraw9")
        self.assertEqual(found.evdev_paths, ["/dev/input/event1"])

    def test_find_evdev_filters(self):
        def fake_dev(path, name, vid, pid, uniq=""):
            d = MagicMock()
            d.name = name
            d.uniq = uniq
            d.info.vendor = vid
            d.info.product = pid
            return d

        paths = ["/dev/input/event1", "/dev/input/event2", "/dev/input/event3"]
        mapping = {
            "/dev/input/event1": fake_dev(paths[0], "Keychron C100 8K Keyboard", 0x3434, 0x042C),
            "/dev/input/event2": fake_dev(paths[1], "Keychron C100 8K Mouse", 0x3434, 0x042C),
            "/dev/input/event3": fake_dev(paths[2], "Keychron Q1", 0x3434, 0x0100),
        }

        def open_dev(path):
            return mapping[path]

        with patch("c100ctl.device.list_devices", return_value=paths):
            with patch("c100ctl.device.InputDevice", side_effect=open_dev):
                found = find_evdev_paths()
        self.assertEqual(found, ["/dev/input/event1"])
