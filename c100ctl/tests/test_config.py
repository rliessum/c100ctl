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

    def test_ensure_profile_clone_from_current_with_global_lighting(self):
        """Clone from current should capture global lighting when profile has none."""
        self.store.set_binding(2, 2, {"type": "combo", "combo": "ctrl+c", "label": "copy"})
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["brightness"] = 200
        self.store.data["lighting"]["effect"] = 5
        self.store.save()

        self.store.ensure_profile("gaming", "Gaming", clone_from="__current__")

        gaming = self.store.profile("gaming")
        self.assertEqual(gaming["keys"]["2,2"]["combo"], "ctrl+c")
        self.assertEqual(gaming["lighting"]["keys"]["1,1"], "#ff0000")
        self.assertEqual(gaming["lighting"]["brightness"], 200)
        self.assertEqual(gaming["lighting"]["effect"], 5)

    def test_ensure_profile_clone_from_current_with_profile_lighting(self):
        """Clone from current should use profile's stored lighting if present."""
        self.store.set_binding(2, 2, {"type": "combo", "combo": "ctrl+c", "label": "copy"})
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["brightness"] = 200
        self.store.profile()["lighting"] = {"keys": {"1,1": "#00ff00"}, "brightness": 150}
        self.store.save()

        self.store.ensure_profile("gaming", "Gaming", clone_from="__current__")

        gaming = self.store.profile("gaming")
        self.assertEqual(gaming["keys"]["2,2"]["combo"], "ctrl+c")
        self.assertEqual(gaming["lighting"]["keys"]["1,1"], "#00ff00")
        self.assertEqual(gaming["lighting"]["brightness"], 150)

    def test_ensure_profile_clone_from_named(self):
        self.store.ensure_profile("work")
        self.store.set_profile("work")
        self.store.set_binding(3, 3, {"type": "url", "url": "https://x", "label": "x"})
        self.store.set_profile("default")

        self.store.ensure_profile("work-copy", clone_from="work")

        copy = self.store.profile("work-copy")
        self.assertEqual(copy["keys"]["3,3"]["url"], "https://x")

    def test_ensure_profile_clone_nonexistent_creates_empty(self):
        self.store.ensure_profile("fresh", clone_from="ghost")
        self.assertEqual(self.store.profile("fresh")["keys"], {})

    def test_ensure_profile_no_clone_is_empty(self):
        self.store.set_binding(1, 1, {"type": "text", "text": "hi", "label": "hi"})
        self.store.ensure_profile("empty")
        self.assertEqual(self.store.profile("empty")["keys"], {})

    def test_list_profile_names(self):
        self.assertEqual(self.store.list_profile_names(), ["default"])
        self.store.ensure_profile("z-last")
        self.store.ensure_profile("a-first")
        names = self.store.list_profile_names()
        self.assertEqual(names[0], "default")
        self.assertIn("z-last", names)
        self.assertIn("a-first", names)

    def test_delete_active_profile_falls_back_to_default(self):
        self.store.ensure_profile("temp")
        self.store.set_profile("temp")
        self.assertEqual(self.store.active_profile_name(), "temp")
        self.store.delete_profile("temp")
        self.assertEqual(self.store.active_profile_name(), "default")

    def test_missing_active_profile_falls_back(self):
        self.store.data["active_profile"] = "ghost"
        self.assertEqual(self.store.active_profile_name(), "default")

    def test_save_profile_captures_global_lighting(self):
        """save_profile should persist current global lighting into the profile."""
        self.store.set_key_color(1, 1, "#ff0000")
        self.store.data["lighting"]["brightness"] = 180
        self.store.data["lighting"]["effect"] = 7
        self.store.save()

        self.store.save_profile()

        profile = self.store.profile("default")
        self.assertEqual(profile["lighting"]["keys"]["1,1"], "#ff0000")
        self.assertEqual(profile["lighting"]["brightness"], 180)
        self.assertEqual(profile["lighting"]["effect"], 7)

    def test_save_profile_named(self):
        """save_profile with explicit name should target that profile."""
        self.store.ensure_profile("gaming")
        self.store.set_key_color(2, 2, "#00ff00")
        self.store.data["lighting"]["brightness"] = 255
        self.store.save()

        self.store.save_profile("gaming")

        gaming = self.store.profile("gaming")
        self.assertEqual(gaming["lighting"]["keys"]["2,2"], "#00ff00")
        self.assertEqual(gaming["lighting"]["brightness"], 255)

    def test_save_profile_invalid_name(self):
        with self.assertRaises(KeyError):
            self.store.save_profile("nonexistent")

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


if __name__ == "__main__":
    unittest.main()
