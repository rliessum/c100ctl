import unittest

from c100ctl.catalog import (
    DEBOUNCE_TYPES,
    LIGHT_ACTIONS,
    MEDIA_KEYS,
    MOUSE_ACTIONS,
    PER_KEY_TYPES,
    POLL_RATES,
    light_label,
    media_evdev,
    media_label,
    mouse_label,
)


class CatalogTest(unittest.TestCase):
    def test_media_lookup(self):
        self.assertEqual(media_evdev("playpause"), "KEY_PLAYPAUSE")
        self.assertEqual(media_evdev("volup"), "KEY_VOLUMEUP")
        self.assertIsNone(media_evdev("not-a-key"))
        self.assertEqual(media_label("mute"), "Mute")
        self.assertEqual(media_label("xyz"), "xyz")

    def test_mouse_and_light_labels(self):
        self.assertEqual(mouse_label("wheelup"), "Scroll up")
        self.assertEqual(mouse_label("nope"), "nope")
        self.assertEqual(light_label("perkey"), "Per-key RGB")
        self.assertEqual(light_label("nope"), "nope")

    def test_catalogs_unique(self):
        media_ids = [i for i, _l, _k in MEDIA_KEYS]
        self.assertEqual(len(media_ids), len(set(media_ids)))
        self.assertEqual(len({i for i, _ in MOUSE_ACTIONS}), len(MOUSE_ACTIONS))
        self.assertEqual(len({i for i, _ in LIGHT_ACTIONS}), len(LIGHT_ACTIONS))
        self.assertEqual([i for i, _ in PER_KEY_TYPES], [0, 1, 2, 3, 4])
        self.assertEqual([i for i, _ in DEBOUNCE_TYPES], list(range(7)))
        self.assertEqual(POLL_RATES[0], 8000)
        self.assertEqual(POLL_RATES[-1], 125)
