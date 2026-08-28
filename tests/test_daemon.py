import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from c100ctl.config import Store
from c100ctl.daemon import CHORD_S, DOUBLE_TAP_S, Engine, HOLD_S
from tests.fakes import FakeVia, RecExecutor


class DaemonIpcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "config.json")
        self.eng = Engine(store=self.store)
        self.exec = RecExecutor(switch=self.eng._switch_profile)
        self.eng.executor = self.exec
        self.eng.via = FakeVia()
        self.eng.connected = True

    def tearDown(self):
        self.eng.stop()
        self.tmp.cleanup()

    def _wait_runs(self, n: int, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.exec.runs) >= n:
                return
            time.sleep(0.01)
        self.fail(f"expected {n} runs, got {self.exec.runs!r}")

    def test_ping_and_unknown(self):
        self.assertTrue(self.eng.handle({"op": "ping"})["ok"])
        r = self.eng.handle({"op": "no-such"})
        self.assertFalse(r["ok"])

    def test_status_and_config(self):
        st = self.eng.status()
        self.assertTrue(st["ok"])
        self.assertIn("effects", st)
        cfg = self.eng.handle({"op": "get_config"})
        self.assertTrue(cfg["ok"])
        self.assertEqual(cfg["config"]["version"], 2)

    def test_set_binding_and_locked(self):
        ok = self.eng.handle(
            {
                "op": "set_binding",
                "row": 1,
                "col": 1,
                "binding": {"type": "combo", "combo": "a", "label": "a"},
            }
        )
        self.assertTrue(ok["ok"])
        locked = self.eng.handle({"op": "set_binding", "row": 0, "col": 0, "binding": {"type": "text", "text": "x"}})
        self.assertFalse(locked["ok"])

    def test_profiles(self):
        self.eng.handle({"op": "ensure_profile", "name": "gaming"})
        self.eng.handle({"op": "set_profile", "name": "gaming"})
        self.assertEqual(self.store.active_profile_name(), "gaming")
        self.eng.handle({"op": "delete_profile", "name": "gaming"})
        self.assertEqual(self.store.active_profile_name(), "default")

    def test_lighting_and_colors(self):
        r = self.eng.handle({"op": "set_lighting", "brightness": 50, "effect": 2, "speed": 9, "color": "ff0000"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.store.data["lighting"]["color"], "#ff0000")
        r = self.eng.handle(
            {
                "op": "set_key_colors",
                "keys": [{"row": 1, "col": 1, "color": "#00ff00"}, {"row": 1, "col": 2, "color": "off"}],
            }
        )
        self.assertTrue(r["ok"])
        self.assertEqual(self.store.get_key_color(1, 1), "#00ff00")
        self.eng.handle({"op": "clear_key_colors"})
        self.assertEqual(self.store.lighting_keys(), {})

    def test_mix_and_advanced(self):
        r = self.eng.handle({"op": "set_mix", "regions": [1] * 10, "slots": [[{"effect": 2, "time_ms": 1000}]]})
        self.assertTrue(r["ok"])
        self.assertEqual(self.store.data["lighting"]["effect"], 24)
        r = self.eng.handle({"op": "set_advanced", "poll_hz": 1000, "nkro": 0, "idle_dim_s": 5})
        self.assertTrue(r["ok"])
        self.assertEqual(self.store.data["advanced"]["poll_hz"], 1000)
        self.assertFalse(self.store.data["advanced"]["nkro"])

    def test_chords_and_import(self):
        r = self.eng.handle(
            {
                "op": "set_chords",
                "chords": [{"keys": ["1,1", "1,2"], "binding": {"type": "media", "media": "mute"}}],
            }
        )
        self.assertEqual(len(r["chords"]), 1)
        r = self.eng.handle({"op": "import_config", "config": {"profiles": {"default": {"keys": {}}}}})
        self.assertTrue(r["ok"])
        bad = self.eng.handle({"op": "import_config", "config": "nope"})
        self.assertFalse(bad["ok"])

    def test_save_profile_lighting(self):
        self.store.set_key_color(2, 2, "#ffffff")
        r = self.eng.handle({"op": "save_profile_lighting"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.store.profile()["lighting"]["keys"]["2,2"], "#ffffff")

    def test_combo_fires_on_press(self):
        self.store.set_binding(4, 4, {"type": "combo", "combo": "ctrl+c", "label": "c"})
        self.eng._on_key(4, 4, True)
        self._wait_runs(1)
        self.assertEqual(self.exec.runs[0]["combo"], "ctrl+c")

    def test_locked_key_ignored(self):
        self.store.set_binding(1, 1, {"type": "text", "text": "x"})
        self.eng._on_key(0, 0, True)
        time.sleep(0.05)
        self.assertEqual(self.exec.runs, [])

    def test_unbound_key_ignored(self):
        self.eng._on_key(5, 5, True)
        time.sleep(0.05)
        self.assertEqual(self.exec.runs, [])

    def test_app_double_tap_closes(self):
        self.store.set_binding(2, 2, {"type": "app", "desktop_id": "x.desktop", "label": "x"})
        self.eng._on_key(2, 2, True)
        self.eng._on_key(2, 2, False)
        self.eng._on_key(2, 2, True)
        self._wait_runs(1)
        self.assertTrue(self.exec.runs[0].get("_close"))

    def test_app_single_tap_launches(self):
        with patch("c100ctl.daemon.DOUBLE_TAP_S", 0.05):
            self.store.set_binding(2, 3, {"type": "app", "desktop_id": "x.desktop", "label": "x"})
            self.eng._on_key(2, 3, True)
            time.sleep(0.12)
            self._wait_runs(1)
            self.assertFalse(self.exec.runs[0].get("_close"))

    def test_chord_fires_once(self):
        self.store.set_chords(
            [{"keys": ["3,3", "3,4"], "binding": {"type": "media", "media": "mute", "label": "m"}}]
        )
        self.eng._on_key(3, 3, True)
        self.eng._on_key(3, 4, True)
        self._wait_runs(1)
        self.assertEqual(self.exec.runs[0]["media"], "mute")

    def test_hold_profile(self):
        self.store.ensure_profile("gaming")
        self.store.set_binding(
            6,
            6,
            {
                "type": "combo",
                "combo": "a",
                "hold": {"type": "profile", "profile": "gaming", "momentary": True},
            },
        )
        with patch("c100ctl.daemon.HOLD_S", 0.05):
            self.eng._on_key(6, 6, True)
            time.sleep(0.12)
            self.assertEqual(self.store.active_profile_name(), "gaming")
            self.eng._on_key(6, 6, False)
            self.assertEqual(self.store.active_profile_name(), "default")

    def test_hold_tap_fires_on_release(self):
        self.store.set_binding(
            7,
            7,
            {
                "type": "text",
                "text": "tap",
                "hold": {"type": "text", "text": "hold"},
            },
        )
        self.eng._on_key(7, 7, True)
        self.eng._on_key(7, 7, False)
        self._wait_runs(1)
        self.assertEqual(self.exec.runs[0]["text"], "tap")

    def test_light_action(self):
        self.store.data["lighting"]["effect"] = 1
        self.store.data["lighting"]["brightness"] = 100
        self.eng._light_action("next")
        self.assertEqual(self.store.data["lighting"]["effect"], 2)
        self.eng._light_action("brighter")
        self.assertGreater(self.store.data["lighting"]["brightness"], 100)
        self.eng._light_action("toggle")
        self.assertEqual(self.store.data["lighting"]["brightness"], 0)
        self.eng._light_action("toggle")
        self.assertGreater(self.store.data["lighting"]["brightness"], 0)
        self.eng._light_action("perkey")
        self.assertEqual(self.store.data["lighting"]["effect"], 23)
        self.eng._light_action("mix")
        self.assertEqual(self.store.data["lighting"]["effect"], 24)

    def test_macro_repeat(self):
        self.store.set_binding(8, 8, {"type": "macro", "macro": "a", "repeat": 3, "label": "a"})
        self.eng._on_key(8, 8, True)
        self._wait_runs(3)

    def test_reload(self):
        self.store.set_binding(1, 1, {"type": "text", "text": "z"})
        r = self.eng.handle({"op": "reload"})
        self.assertTrue(r["ok"])

    def test_probe_hardware(self):
        hw = self.eng._probe_hardware()
        self.assertEqual(hw["firmware"], "v1.0.1 test")
        self.assertTrue(hw["poll_supported"])

    def test_idle_dim(self):
        class Immediate:
            def __init__(self, interval, func):
                self.func = func
                self.daemon = False

            def start(self):
                self.func()

            def cancel(self):
                pass

        self.store.data["lighting"]["brightness"] = 200
        self.store.data["advanced"]["idle_dim_s"] = 5
        with patch("c100ctl.daemon.threading.Timer", Immediate):
            self.eng._arm_idle()
        self.assertTrue(self.eng._dimmed)
        self.eng._bump_idle()
        self.assertFalse(self.eng._dimmed)

    def test_macro_while_held(self):
        self.store.set_binding(
            4,
            5,
            {"type": "macro", "macro": "a", "repeat": "hold", "label": "a"},
        )
        self.eng._on_key(4, 5, True)
        time.sleep(0.12)
        self.eng._on_key(4, 5, False)
        self.assertGreaterEqual(len(self.exec.runs), 1)

    def test_light_dimmer_prev(self):
        self.store.data["lighting"]["effect"] = 5
        self.store.data["lighting"]["brightness"] = 40
        self.eng._light_action("prev")
        self.assertEqual(self.store.data["lighting"]["effect"], 4)
        self.eng._light_action("dimmer")
        self.assertLess(self.store.data["lighting"]["brightness"], 40)
        with self.assertRaises(Exception):
            self.eng._light_action("nope")

    def test_apply_lighting_per_key(self):
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["effect"] = 23
        self.store.data["lighting"]["per_key_type"] = 2
        self.eng._apply_lighting()
        self.assertTrue(any(c[0] == "enable_per_key" for c in self.eng.via.calls))
        self.assertTrue(self.eng.via.hsv_writes)

    def test_matrix_effect_ignores_saved_key_colors(self):
        self.store.set_key_color(1, 1, "#ff0000")
        r = self.eng.handle({"op": "set_lighting", "effect": 2})
        self.assertEqual(r["lighting"]["effect"], 2)
        self.assertEqual(self.store.data["lighting"]["effect"], 2)
        self.assertEqual(self.store.get_key_color(1, 1), "#ff0000")
        effects = [c for c in self.eng.via.calls if c[0] == "set_effect"]
        self.assertEqual(effects[-1][1], 2)
        self.assertFalse(any(c[0] == "enable_per_key" for c in self.eng.via.calls))
        st = self.eng.status()
        self.assertEqual(st["lighting"]["effect"], 2)

    def test_set_key_color_single(self):
        r = self.eng.handle({"op": "set_key_color", "row": 2, "col": 2, "color": "#00ff00"})
        self.assertTrue(r["ok"])
        r = self.eng.handle({"op": "set_key_color", "row": 2, "col": 2, "color": ""})
        self.assertTrue(r["ok"])

    def test_heatmap_paints_and_restores(self):
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["effect"] = 23
        self.eng._apply_lighting()
        self.eng.via.calls.clear()
        self.eng.via.hsv_writes.clear()
        r = self.eng.handle({"op": "heatmap", "active": True})
        self.assertTrue(r["ok"])
        self.assertTrue(r["active"])
        self.assertTrue(self.eng.status()["heatmap"])
        self.assertTrue(any(c[0] == "write_all_rgb" and c[2] is False for c in self.eng.via.calls))
        self.assertEqual(self.store.get_key_color(1, 1), "#ff0000")
        self.eng._on_key(3, 3, True)
        self.eng._on_key(3, 3, False)
        once = [w for w in self.eng.via.hsv_writes if w[0] == 33]
        self.assertTrue(once)
        self.eng._on_key(3, 3, True)
        twice = [w for w in self.eng.via.hsv_writes if w[0] == 33]
        self.assertGreater(len(twice), len(once))
        self.assertNotEqual(twice[-1][1], once[-1][1])
        r = self.eng.handle({"op": "heatmap", "active": True})
        self.assertEqual(r["hits"]["3,3"], 2)
        self.assertTrue(any(c[0] == "enable_per_key" for c in self.eng.via.calls))
        r = self.eng.handle({"op": "heatmap", "reset": True})
        self.assertEqual(r["hits"], {})
        self.assertTrue(r["active"])
        r = self.eng.handle({"op": "heatmap", "active": False})
        self.assertFalse(r["active"])
        self.assertEqual(self.store.get_key_color(1, 1), "#ff0000")
        self.assertTrue(any(c[0] == "enable_per_key" for c in self.eng.via.calls))
        self.assertFalse(self.eng.status()["heatmap"])
