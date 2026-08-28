import io
import unittest
from unittest.mock import MagicMock, patch

from c100ctl.doctor import run
from c100ctl.hid import HidInfo


class DoctorTest(unittest.TestCase):
    def test_all_fail_returns_nonzero(self):
        with patch("c100ctl.doctor.enumerate_devices", return_value=[]):
            with patch("c100ctl.doctor.find_c100", return_value=None):
                with patch("c100ctl.doctor.daemon_available", return_value=False):
                    with patch("c100ctl.doctor.hyprctl_available", return_value=False):
                        with patch("c100ctl.doctor.graphical_env", return_value={}):
                            with patch("sys.stdout", new=io.StringIO()) as out:
                                code = run()
        self.assertEqual(code, 1)
        self.assertIn("[NO ]", out.getvalue())

    def test_via_ok(self):
        hid = [HidInfo("/dev/hidraw1", 0x3434, 0x042C, "", "C100", 0xFF60, 0x61, 0)]
        found = MagicMock()
        found.evdev_paths = ["/dev/input/event1"]
        found.via_path = "/dev/hidraw1"
        client = MagicMock()
        client.protocol_version.return_value = 12
        client.layer_count.return_value = 4
        with patch("c100ctl.doctor.enumerate_devices", return_value=hid):
            with patch("c100ctl.doctor.find_c100", return_value=found):
                with patch("c100ctl.via.ViaClient", return_value=client):
                    with patch("c100ctl.doctor.daemon_available", return_value=True):
                        with patch("c100ctl.doctor.hyprctl_available", return_value=True):
                            with patch(
                                "c100ctl.doctor.graphical_env",
                                return_value={"WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc"},
                            ):
                                with patch("sys.stdout", new=io.StringIO()) as out:
                                    code = run()
        self.assertIn("VIA protocol", out.getvalue())
        self.assertIn(code, (0, 1))
