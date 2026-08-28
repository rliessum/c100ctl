"""Live tests against a plugged-in C100 8K. Skipped when the pad is missing."""

import unittest

from c100ctl.device import find_c100
from c100ctl.identity import looks_factory
from c100ctl.via import ViaClient


class HardwareTest(unittest.TestCase):
    def setUp(self):
        self.device = find_c100()
        if not self.device:
            self.skipTest("Keychron C100 8K not connected")

    def test_via_protocol(self):
        client = ViaClient(self.device.via_path)
        try:
            self.assertGreaterEqual(client.protocol_version(), 11)
            self.assertGreaterEqual(client.layer_count(), 1)
            keymap = client.read_keymap(1, 10, 10)
            self.assertEqual(len(keymap[0]), 10)
            self.assertEqual(len(keymap[0][0]), 10)
            corners = {
                keymap[0][0][0],
                keymap[0][0][9],
                keymap[0][9][0],
                keymap[0][9][9],
            }
            self.assertTrue(all(kc >= 0x7800 for kc in corners))
            looks_factory(keymap[0])
        finally:
            client.close()
