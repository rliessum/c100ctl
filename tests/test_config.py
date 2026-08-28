import unittest

from c100ctl.config import Store, default_config, key_id


class ConfigTest(unittest.TestCase):
    def test_roundtrip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            store = Store(path)
            self.assertEqual(store.active_profile_name(), "default")
            store.set_binding(
                1,
                2,
                {"type": "app", "desktop_id": "kitty.desktop", "label": "Kitty"},
            )
            again = Store(path)
            b = again.get_binding(1, 2)
            self.assertEqual(b["desktop_id"], "kitty.desktop")
            again.set_binding(1, 2, None)
            self.assertIsNone(again.get_binding(1, 2))

    def test_key_id(self):
        self.assertEqual(key_id(9, 9), "9,9")

    def test_default_version(self):
        self.assertEqual(default_config()["version"], 2)

    def test_url_binding(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "config.json")
            store.set_binding(0, 1, {"type": "url", "url": "https://omarchy.org", "label": "web"})
            self.assertEqual(store.get_binding(0, 1)["url"], "https://omarchy.org")
