import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from c100ctl.config import (
    Store,
    _atomic_write,
    default_advanced,
    default_config,
    default_lighting,
    default_mix,
    key_id,
    parse_key_id,
    xdg_config,
    xdg_runtime,
)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_id(self):
        self.assertEqual(key_id(9, 9), "9,9")
        self.assertEqual(parse_key_id("3,4"), (3, 4))
        with self.assertRaises(ValueError):
            parse_key_id("nope")

    def test_default_version(self):
        self.assertEqual(default_config()["version"], 2)
        self.assertEqual(len(default_mix()["regions"]), 100)
        self.assertEqual(len(default_mix()["slots"]), 2)
        self.assertEqual(default_advanced()["poll_hz"], 8000)

    def test_roundtrip(self):
        self.assertEqual(self.store.active_profile_name(), "default")
        self.store.set_binding(
            1,
            2,
            {"type": "app", "desktop_id": "kitty.desktop", "label": "Kitty"},
        )
        again = Store(self.path)
        b = again.get_binding(1, 2)
        self.assertEqual(b["desktop_id"], "kitty.desktop")
        again.set_binding(1, 2, None)
        self.assertIsNone(again.get_binding(1, 2))

    def test_url_binding(self):
        self.store.set_binding(0, 1, {"type": "url", "url": "https://omarchy.org", "label": "web"})
        self.assertEqual(self.store.get_binding(0, 1)["url"], "https://omarchy.org")

    def test_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            self.store.set_binding(0, 1, {"type": "teleport"})

    def test_rejects_unknown_hold(self):
        with self.assertRaises(ValueError):
            self.store.set_binding(
                0,
                1,
                {"type": "combo", "combo": "a", "hold": {"type": "nope"}},
            )

    def test_accepts_hold_profile(self):
        self.store.set_binding(
            2,
            2,
            {
                "type": "app",
                "desktop_id": "x.desktop",
                "hold": {"type": "profile", "profile": "gaming", "momentary": True},
            },
        )
        self.assertTrue(self.store.get_binding(2, 2)["hold"]["momentary"])

    def test_profiles(self):
        self.store.ensure_profile("gaming", "Gaming")
        self.store.set_profile("gaming")
        self.assertEqual(self.store.active_profile_name(), "gaming")
        self.store.set_binding(1, 1, {"type": "text", "text": "hi", "label": "hi"})
        self.assertIsNone(self.store.get_binding(1, 1, "default"))
        self.assertEqual(self.store.get_binding(1, 1)["text"], "hi")
        self.store.delete_profile("gaming")
        self.assertEqual(self.store.active_profile_name(), "default")
        with self.assertRaises(ValueError):
            self.store.delete_profile("default")
        with self.assertRaises(KeyError):
            self.store.set_profile("missing")

    def test_missing_active_profile_falls_back(self):
        self.store.data["active_profile"] = "ghost"
        self.assertEqual(self.store.active_profile_name(), "default")

    def test_chords_filter(self):
        self.store.set_chords(
            [
                {"keys": ["1,1"], "binding": {"type": "combo", "combo": "a"}},
                {"keys": ["1,1", "1,2"], "binding": {"type": "nope"}},
                {"keys": ["2,2", "2,3"], "binding": {"type": "media", "media": "mute"}},
            ]
        )
        chords = self.store.data["chords"]
        self.assertEqual(len(chords), 1)
        self.assertEqual(chords[0]["binding"]["media"], "mute")

    def test_lighting_keys(self):
        self.store.set_key_color(3, 4, "#00ff00")
        self.assertEqual(self.store.get_key_color(3, 4), "#00ff00")
        self.store.set_key_colors([(3, 4, None), (0, 1, "#ff0000")])
        self.assertIsNone(self.store.get_key_color(3, 4))
        self.assertEqual(self.store.get_key_color(0, 1), "#ff0000")

    def test_lighting_keys_recovers_bad_dict(self):
        self.store.data["lighting"]["keys"] = "nope"
        keys = self.store.lighting_keys()
        self.assertEqual(keys, {})

    def test_load_merges_legacy(self):
        payload = {
            "version": 1,
            "serial": "abc",
            "lighting": {"brightness": 10, "keys": {"1,1": "#fff"}, "mix": {"regions": "bad"}},
            "advanced": {"poll_hz": 1000},
            "chords": [],
            "profiles": {"default": {"label": "D", "keys": {}}},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = Store(self.path)
        self.assertEqual(loaded.data["serial"], "abc")
        self.assertEqual(loaded.data["lighting"]["brightness"], 10)
        self.assertEqual(loaded.data["lighting"]["keys"]["1,1"], "#fff")
        self.assertEqual(len(loaded.data["lighting"]["mix"]["regions"]), 100)
        self.assertEqual(loaded.data["advanced"]["poll_hz"], 1000)
        self.assertEqual(loaded.data["version"], 2)

    def test_replace_config(self):
        self.store.replace_config(
            {
                "profiles": {"default": {"label": "X", "keys": {"0,1": {"type": "text", "text": "z"}}}},
                "lighting": default_lighting(),
            }
        )
        self.assertEqual(self.store.get_binding(0, 1)["text"], "z")

    def test_empty_file_creates_defaults(self):
        missing = Path(self.tmp.name) / "nope.json"
        s = Store(missing)
        self.assertEqual(s.data["version"], 2)

    def test_xdg_helpers(self):
        self.assertTrue(str(xdg_config()).endswith("c100ctl"))
        self.assertIn("c100ctl", str(xdg_runtime()))


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_file_permissions(self):
        subdir = Path(self.tmp.name) / "nested" / "deep"
        path = subdir / "config.json"
        store = Store(path)
        store.save()
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600, f"config file should be 0600, got {oct(mode)}")

    def test_config_directory_permissions(self):
        subdir = Path(self.tmp.name) / "nested" / "deep"
        path = subdir / "config.json"
        store = Store(path)
        store.save()
        mode = stat.S_IMODE(os.stat(subdir).st_mode)
        self.assertEqual(mode, 0o700, f"config dir should be 0700, got {oct(mode)}")

    def test_atomic_write_permissions(self):
        subdir = Path(self.tmp.name) / "atomicdir"
        path = subdir / "test.json"
        _atomic_write(path, '{"test": true}')
        file_mode = stat.S_IMODE(os.stat(path).st_mode)
        dir_mode = stat.S_IMODE(os.stat(subdir).st_mode)
        self.assertEqual(file_mode, 0o600, f"file should be 0600, got {oct(file_mode)}")
        self.assertEqual(dir_mode, 0o700, f"dir should be 0700, got {oct(dir_mode)}")
