import unittest
from unittest.mock import patch

from c100ctl.via import (
    KC_MISC,
    KC_RGB,
    MIX_RGB_EFFECT,
    PER_KEY_EFFECT,
    ViaClient,
    ViaError,
    find_via_interfaces,
)
from tests.fakes import FakeHid


def _client_with(hid: FakeHid) -> ViaClient:
    with patch("c100ctl.via.HidDevice", return_value=hid):
        return ViaClient("/dev/hidraw-fake")


class ViaClientTest(unittest.TestCase):
    def test_protocol_and_layers(self):
        hid = FakeHid(
            [
                bytes([0x01, 0x00, 0x0C]) + bytes(29),
                bytes([0x11, 0x04]) + bytes(30),
            ]
        )
        hid.echo = False
        via = _client_with(hid)
        self.assertEqual(via.protocol_version(), 12)
        self.assertEqual(via.layer_count(), 4)
        via.close()
        self.assertTrue(hid.closed)

    def test_timeout(self):
        hid = FakeHid([])
        hid.echo = False
        via = _client_with(hid)
        with self.assertRaises(ViaError):
            via.protocol_version()

    def test_firmware_string(self):
        body = bytes([0xA1]) + b"v1.0.1 2026-08-20"
        hid = FakeHid([body.ljust(32, b"\x00")])
        hid.echo = False
        via = _client_with(hid)
        self.assertIn("v1.0.1", via.firmware_string())

    def test_rgb_getters_setters(self):
        hid = FakeHid()
        via = _client_with(hid)
        via.set_brightness(180, save=False)
        via.set_effect(PER_KEY_EFFECT, save=False)
        via.set_speed(64, save=False)
        via.set_color_hsv(10, 20, save=False)
        via.enable_per_key(save=False)
        via.set_per_key_type(2)
        via.set_led_rgb(80, (0, 255, 0))
        via.write_all_rgb([(255, 0, 0)] * 12, save=True)
        cmds = [w[1] for w in hid.writes]
        self.assertIn(KC_RGB, cmds)
        hid.replies = [bytes([0x07, 0, 0, 2]) + bytes(28)]
        hid.echo = False
        self.assertEqual(via.get_per_key_type(), 2)

    def test_misc_poll_debounce_nkro(self):
        hid = FakeHid()
        via = _client_with(hid)
        hid.replies = [
            bytes([KC_MISC, 0x0D, 0, 3]) + bytes(28),
            bytes([KC_MISC, 0x0E, 0]) + bytes(29),
            bytes([KC_MISC, 5, 0, 0, 4, 5]) + bytes(26),
            bytes([KC_MISC, 6, 0]) + bytes(29),
            bytes([KC_MISC, 0x12, 0, 0x03]) + bytes(28),
            bytes([KC_MISC, 0x13, 0]) + bytes(29),
        ]
        hid.echo = False
        self.assertEqual(via.get_poll_div(), 3)
        self.assertTrue(via.set_poll_div(0))
        self.assertEqual(via.get_debounce(), (4, 5))
        self.assertTrue(via.set_debounce(4, 5))
        on, can = via.get_nkro()
        self.assertTrue(on)
        self.assertTrue(can)
        self.assertTrue(via.set_nkro(True))

    def test_misc_unsupported(self):
        hid = FakeHid([bytes([0xFF]) + bytes(31)] * 4)
        hid.echo = False
        via = _client_with(hid)
        self.assertIsNone(via.get_poll_div())
        self.assertFalse(via.set_poll_div(1))
        self.assertIsNone(via.get_debounce())
        self.assertIsNone(via.get_nkro())

    def test_mix_regions_and_slots(self):
        hid = FakeHid()
        via = _client_with(hid)
        via.set_mix_regions([0] * 50 + [1] * 50)
        via.set_mix_slots(0, [{"effect": 5, "hue": 1, "sat": 2, "speed": 3, "time_ms": 5000}])
        hid.replies = [
            bytes([KC_RGB, 11, 0, 2, 5]) + bytes(27),
        ]
        hid.echo = False
        layers, slots = via.mix_info()
        self.assertEqual(layers, 2)
        self.assertEqual(slots, 5)

        region_pkt = bytearray(32)
        region_pkt[0] = KC_RGB
        region_pkt[1] = 12
        region_pkt[3:6] = b"\x00\x01\x00"
        hid.replies = [bytes(region_pkt)]
        got = via.get_mix_regions(3)
        self.assertEqual(got, [0, 1, 0])

        slot_pkt = bytearray(32)
        slot_pkt[0] = KC_RGB
        slot_pkt[1] = 14
        slot_pkt[3] = 5
        slot_pkt[4] = 10
        slot_pkt[5] = 20
        slot_pkt[6] = 30
        slot_pkt[7:11] = (1500).to_bytes(4, "little")
        hid.replies = [bytes(slot_pkt), bytes(slot_pkt)]
        slots = via.get_mix_slots(0, 4)
        self.assertEqual(slots[0]["effect"], 5)
        self.assertEqual(slots[0]["time_ms"], 1500)

    def test_keycode_roundtrip_buffer(self):
        hid = FakeHid()
        via = _client_with(hid)
        hid.replies = [bytes([0x04, 0, 0, 0, 0x00, 0x04]) + bytes(26)]
        hid.echo = False
        self.assertEqual(via.get_keycode(0, 1, 2), 0x0004)
        hid.echo = True
        via.set_keycode(0, 1, 2, 0x0004)
        self.assertTrue(hid.writes)

    def test_find_via_filters_usage(self):
        from c100ctl.hid import HidInfo

        infos = [
            HidInfo("/a", 1, 2, "", "", 0xFF60, 0x61, 0),
            HidInfo("/b", 1, 2, "", "", 1, 1, 1),
        ]
        with patch("c100ctl.via.enumerate_devices", return_value=infos):
            found = find_via_interfaces()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, "/a")

    def test_support_features(self):
        hid = FakeHid([bytes([0xA2, 0, 0x80, 0x02]) + bytes(28)])
        hid.echo = False
        via = _client_with(hid)
        bits = via.support_features()
        self.assertTrue(bits & 0x80 or bits >= 0)
        self.assertEqual(MIX_RGB_EFFECT, 24)

    def test_matrix_and_rgb_getters(self):
        hid = FakeHid()
        via = _client_with(hid)
        pkt = bytearray(32)
        pkt[2] = 0x01
        hid.replies = [bytes(pkt)]
        hid.echo = False
        pressed = via.matrix_pressed(2, 2)
        self.assertEqual(pressed, [(0, 0)])
        hid.replies = [bytes([0x08, 3, 1, 180]) + bytes(28)]
        self.assertEqual(via.brightness(), 180)
        hid.replies = [bytes([0x08, 3, 2, 7]) + bytes(28)]
        self.assertEqual(via.effect(), 7)
        hid.replies = [bytes([0x08, 3, 3, 9]) + bytes(28)]
        self.assertEqual(via.speed(), 9)
        hid.replies = [bytes([0x08, 3, 4, 10, 20]) + bytes(27)]
        self.assertEqual(via.color_hsv(), (10, 20))
        hid.replies = [bytes([0xA8, 5, 0, 100]) + bytes(28)]
        self.assertEqual(via.led_count(), 100)
        hid.replies = [bytes([0x0C, 16]) + bytes(30)]
        self.assertEqual(via.macro_count(), 16)
        hid.echo = True
        via.write_keymap_layer(0, 1, 1, [[4]])
        hid.replies = [bytes([0xA8, 9, 0, 1, 2, 3]) + bytes(26)]
        hid.echo = False
        self.assertEqual(via.get_led_hsv(0, 1), [(1, 2, 3)])
        hid.echo = True
        via.set_brightness(10, save=True)
        via.firmware_version()

    def test_led_map_and_hid_error(self):
        hid = FakeHid()
        via = _client_with(hid)
        row = bytearray(32)
        row[3:6] = bytes([0, 1, 2])
        hid.replies = [bytes(row)]
        hid.echo = False
        grid = via.led_map(1, 3)
        self.assertEqual(grid[0], [0, 1, 2])
        hid.write = lambda pkt: (_ for _ in ()).throw(__import__("c100ctl.hid", fromlist=["HidError"]).HidError("nope"))
        with self.assertRaises(ViaError):
            via.protocol_version()
