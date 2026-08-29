import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules["evdev"] = MagicMock()
sys.modules["evdev.ecodes"] = MagicMock()

c100ctl_hid = MagicMock()
c100ctl_hid.HidInfo = MagicMock
sys.modules["c100ctl.hid"] = c100ctl_hid

c100ctl_device = MagicMock()
c100ctl_device.find_c100 = MagicMock(return_value=None)
c100ctl_device.hidraw_exists = MagicMock(return_value=False)
sys.modules["c100ctl.device"] = c100ctl_device

c100ctl_pad = MagicMock()
c100ctl_pad.PadGrab = MagicMock
sys.modules["c100ctl.pad"] = c100ctl_pad

c100ctl_via = MagicMock()
c100ctl_via.ViaClient = MagicMock
c100ctl_via.ViaError = Exception
c100ctl_via.MIX_RGB_EFFECT = 24
c100ctl_via.PER_KEY_EFFECT = 23
c100ctl_via.heatmap_hex = MagicMock(return_value="#000000")
c100ctl_via.heatmap_rgb = MagicMock(return_value=(0, 0, 0))
c100ctl_via.parse_hex_color = MagicMock(return_value=(0, 0, 0))
c100ctl_via.poll_div_from_hz = MagicMock(return_value=1)
c100ctl_via.poll_hz_from_div = MagicMock(return_value=8000)
c100ctl_via.rgb_to_hsv255 = MagicMock(return_value=(0, 0, 0))
sys.modules["c100ctl.via"] = c100ctl_via

from c100ctl.config import Store
from c100ctl.daemon import Engine


class DaemonProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "config.json")
        with patch.object(Engine, "__init__", lambda self, store=None: None):
            self.engine = Engine()
        self.engine.store = self.store
        self.engine.via = None
        self.engine.ipc = MagicMock()
        self.engine.connected = False

    def tearDown(self):
        self.tmp.cleanup()

    def test_ensure_profile_broadcasts(self):
        resp = self.engine.handle({"op": "ensure_profile", "name": "gaming", "clone_from": "__current__"})
        self.assertTrue(resp["ok"])
        self.engine.ipc.broadcast.assert_called()
        call_args = self.engine.ipc.broadcast.call_args[0][0]
        self.assertEqual(call_args["event"], "config")
        self.assertIn("gaming", call_args["config"]["profiles"])

    def test_delete_profile_broadcasts(self):
        self.store.ensure_profile("temp")
        resp = self.engine.handle({"op": "delete_profile", "name": "temp"})
        self.assertTrue(resp["ok"])
        self.engine.ipc.broadcast.assert_called()
        call_args = self.engine.ipc.broadcast.call_args[0][0]
        self.assertEqual(call_args["event"], "config")
        self.assertNotIn("temp", call_args["config"]["profiles"])

    def test_save_profile_persists_lighting(self):
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["brightness"] = 200
        self.store.save()

        resp = self.engine.handle({"op": "save_profile"})
        self.assertTrue(resp["ok"])

        profile = self.store.profile("default")
        self.assertEqual(profile["lighting"]["keys"]["1,1"], "#ff0000")
        self.assertEqual(profile["lighting"]["brightness"], 200)

    def test_save_profile_broadcasts(self):
        resp = self.engine.handle({"op": "save_profile"})
        self.assertTrue(resp["ok"])
        self.engine.ipc.broadcast.assert_called()
        call_args = self.engine.ipc.broadcast.call_args[0][0]
        self.assertEqual(call_args["event"], "profile")
        self.assertEqual(call_args["name"], "default")

    def test_save_profile_named(self):
        self.store.ensure_profile("gaming")
        self.store.set_key_color(2, 2, "#00ff00")
        self.store.data["lighting"]["brightness"] = 255
        self.store.save()

        resp = self.engine.handle({"op": "save_profile", "name": "gaming"})
        self.assertTrue(resp["ok"])

        gaming = self.store.profile("gaming")
        self.assertEqual(gaming["lighting"]["keys"]["2,2"], "#00ff00")
        self.assertEqual(gaming["lighting"]["brightness"], 255)

    def test_ensure_profile_clone_includes_global_lighting(self):
        """ensure_profile via IPC should clone global lighting when profile has none."""
        self.store.set_binding(2, 2, {"type": "combo", "combo": "ctrl+c", "label": "copy"})
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["brightness"] = 200
        self.store.data["lighting"]["effect"] = 5
        self.store.save()

        resp = self.engine.handle({
            "op": "ensure_profile",
            "name": "gaming",
            "label": "Gaming",
            "clone_from": "__current__",
        })
        self.assertTrue(resp["ok"])

        gaming = self.store.profile("gaming")
        self.assertEqual(gaming["keys"]["2,2"]["combo"], "ctrl+c")
        self.assertEqual(gaming["lighting"]["keys"]["1,1"], "#ff0000")
        self.assertEqual(gaming["lighting"]["brightness"], 200)
        self.assertEqual(gaming["lighting"]["effect"], 5)

    def test_ensure_profile_no_clone(self):
        self.store.set_binding(1, 1, {"type": "text", "text": "hi", "label": "hi"})
        resp = self.engine.handle({"op": "ensure_profile", "name": "empty"})
        self.assertTrue(resp["ok"])
        self.assertEqual(self.store.profile("empty")["keys"], {})


if __name__ == "__main__":
    unittest.main()
