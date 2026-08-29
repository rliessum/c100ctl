import argparse
import io
import unittest
from unittest.mock import MagicMock, patch

from c100ctl.cli import (
    _pretty_binding,
    build_parser,
    cmd_advanced,
    cmd_bind,
    cmd_light,
    cmd_list,
    cmd_profile,
    cmd_provision,
    cmd_status,
)


class PrettyBindingTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(_pretty_binding(None), "—")
        self.assertIn("(app)", _pretty_binding({"type": "app", "desktop_id": "x.desktop"}))
        self.assertIn("(cmd)", _pretty_binding({"type": "command", "command": "ls"}))
        self.assertIn("(combo)", _pretty_binding({"type": "combo", "combo": "a"}))
        self.assertIn("(macro)", _pretty_binding({"type": "macro", "macro": "a"}))
        self.assertIn("(text)", _pretty_binding({"type": "text", "text": "hello world"}))
        self.assertIn("profile:", _pretty_binding({"type": "profile", "profile": "g"}))
        self.assertIn("(url)", _pretty_binding({"type": "url", "url": "https://x"}))
        self.assertIn("(media)", _pretty_binding({"type": "media", "media": "mute"}))
        self.assertIn("(mouse)", _pretty_binding({"type": "mouse", "mouse": "left"}))
        self.assertIn("(light)", _pretty_binding({"type": "light", "light": "next"}))
        self.assertIn("mystery", _pretty_binding({"type": "mystery"}))


class ParserTest(unittest.TestCase):
    def test_bind_and_light_flags(self):
        p = build_parser()
        args = p.parse_args(["bind", "1", "2", "--url", "https://x", "--label", "w"])
        self.assertEqual(args.cmd, "bind")
        self.assertEqual(args.url, "https://x")
        args = p.parse_args(["light", "--brightness", "10", "--per-key-type", "2"])
        self.assertEqual(args.brightness, 10)
        args = p.parse_args(["advanced", "--poll", "1000", "--nkro", "0"])
        self.assertEqual(args.poll, 1000)


class CmdTest(unittest.TestCase):
    def _client(self, resp=None):
        c = MagicMock()
        c.request.return_value = resp or {"ok": True}
        return c

    def test_status(self):
        client = self._client(
            {
                "ok": True,
                "connected": True,
                "version": "1.4.0",
                "protocol": 12,
                "serial": "abc",
                "layers": 4,
                "profile": "default",
                "provisioned": True,
                "lighting": {"brightness": 1, "effect": 23, "speed": 2},
                "hardware": {"firmware": "v1"},
                "advanced": {"poll_hz": 8000, "debounce_type": 4, "debounce_ms": 5, "nkro": True},
            }
        )
        with patch("c100ctl.cli._client", return_value=client):
            self.assertEqual(cmd_status(argparse.Namespace()), 0)

    def test_list_and_bind(self):
        client = self._client(
            {
                "ok": True,
                "config": {
                    "active_profile": "default",
                    "profiles": {"default": {"keys": {"1,1": {"type": "text", "text": "hi", "label": "hi"}}}},
                },
            }
        )
        with patch("c100ctl.cli._client", return_value=client):
            self.assertEqual(cmd_list(argparse.Namespace()), 0)
        client.request.return_value = {"ok": True}
        ns = argparse.Namespace(
            row=1,
            col=1,
            clear=False,
            app=None,
            command=None,
            combo=None,
            macro=None,
            text=None,
            profile=None,
            url="https://x",
            media=None,
            mouse=None,
            light_action=None,
            hold_profile=None,
            hold_momentary=False,
            label="w",
        )
        with patch("c100ctl.cli._client", return_value=client):
            self.assertEqual(cmd_bind(ns), 0)
        ns.row, ns.col = 0, 0
        with self.assertRaises(SystemExit):
            cmd_bind(ns)

    def test_bind_types(self):
        client = self._client({"ok": True})
        base = dict(
            row=1,
            col=2,
            clear=False,
            app=None,
            command=None,
            combo=None,
            macro=None,
            text=None,
            profile=None,
            url=None,
            media=None,
            mouse=None,
            light_action=None,
            hold_profile=None,
            hold_momentary=False,
            label="",
        )
        cases = [
            {"app": "x.desktop"},
            {"command": "ls"},
            {"combo": "a"},
            {"macro": "a"},
            {"text": "z"},
            {"profile": "g"},
            {"media": "mute"},
            {"mouse": "left"},
            {"light_action": "next"},
            {"clear": True},
        ]
        with patch("c100ctl.cli._client", return_value=client):
            for extra in cases:
                ns = argparse.Namespace(**{**base, **extra})
                self.assertEqual(cmd_bind(ns), 0)
            empty = argparse.Namespace(**base)
            with self.assertRaises(SystemExit):
                cmd_bind(empty)

    def test_bind_hold(self):
        client = self._client({"ok": True})
        ns = argparse.Namespace(
            row=1,
            col=1,
            clear=False,
            app="a.desktop",
            command=None,
            combo=None,
            macro=None,
            text=None,
            profile=None,
            url=None,
            media=None,
            mouse=None,
            light_action=None,
            hold_profile="gaming",
            hold_momentary=True,
            label="a",
        )
        with patch("c100ctl.cli._client", return_value=client):
            self.assertEqual(cmd_bind(ns), 0)
        binding = client.request.call_args.kwargs["binding"]
        self.assertEqual(binding["hold"]["profile"], "gaming")

    def test_light(self):
        client = self._client({"ok": True, "lighting": {}})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(
                key=["1,1", "1,2"],
                color="#00ff00",
                brightness=None,
                effect=None,
                speed=None,
                effect_color=None,
                per_key_type=None,
            )
            self.assertEqual(cmd_light(ns), 0)
            ns = argparse.Namespace(
                key=None,
                color=None,
                brightness=10,
                effect=2,
                speed=3,
                effect_color="#f00",
                per_key_type=1,
            )
            self.assertEqual(cmd_light(ns), 0)
            ns = argparse.Namespace(
                key=None,
                color=None,
                brightness=None,
                effect=None,
                speed=None,
                effect_color=None,
                per_key_type=None,
            )
            with self.assertRaises(SystemExit):
                cmd_light(ns)
            ns = argparse.Namespace(key=["bad"], color="#f00", brightness=None, effect=None, speed=None, effect_color=None, per_key_type=None)
            with self.assertRaises(SystemExit):
                cmd_light(ns)

    def test_advanced_and_profile(self):
        client = self._client({"ok": True, "advanced": {}, "config": {"active_profile": "default", "profiles": {"default": {}}}})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(poll=8000, debounce_type=4, debounce_ms=5, nkro=1, idle_dim=0)
            self.assertEqual(cmd_advanced(ns), 0)
            empty = argparse.Namespace(poll=None, debounce_type=None, debounce_ms=None, nkro=None, idle_dim=None)
            with self.assertRaises(SystemExit):
                cmd_advanced(empty)
            self.assertEqual(cmd_profile(argparse.Namespace(create="g", use=None, delete=None, clone=True, json=False)), 0)
            self.assertEqual(cmd_profile(argparse.Namespace(create=None, use="g", delete=None, clone=True, json=False)), 0)
            self.assertEqual(cmd_profile(argparse.Namespace(create=None, use=None, delete=None, clone=True, json=False)), 0)
            self.assertEqual(cmd_provision(argparse.Namespace()), 0)

    def test_profile_json_output(self):
        import json as json_mod
        client = self._client({
            "ok": True,
            "config": {
                "active_profile": "gaming",
                "profiles": {"default": {}, "gaming": {}, "work": {}},
            },
        })
        with patch("c100ctl.cli._client", return_value=client):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                ns = argparse.Namespace(create=None, use=None, delete=None, clone=True, json=True)
                result = cmd_profile(ns)
                self.assertEqual(result, 0)
                output = mock_stdout.getvalue().strip()
                data = json_mod.loads(output)
                self.assertTrue(data["ok"])
                self.assertEqual(data["active"], "gaming")
                self.assertIn("default", data["profiles"])
                self.assertIn("gaming", data["profiles"])
                self.assertIn("work", data["profiles"])

    def test_profile_create_with_clone(self):
        client = self._client({"ok": True, "config": {"active_profile": "default", "profiles": {"default": {}}}})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(create="gaming", use=None, delete=None, clone=True, json=False)
            self.assertEqual(cmd_profile(ns), 0)
            call_args = client.request.call_args
            self.assertEqual(call_args.kwargs.get("clone_from"), "__current__")

    def test_profile_create_no_clone(self):
        client = self._client({"ok": True, "config": {"active_profile": "default", "profiles": {"default": {}}}})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(create="empty", use=None, delete=None, clone=False, json=False)
            self.assertEqual(cmd_profile(ns), 0)
            call_args = client.request.call_args
            self.assertIsNone(call_args.kwargs.get("clone_from"))

    def test_profile_delete(self):
        client = self._client({"ok": True, "config": {"active_profile": "default", "profiles": {"default": {}}}})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(create=None, use=None, delete="gaming", clone=True, json=False)
            self.assertEqual(cmd_profile(ns), 0)
            client.request.assert_called_with("delete_profile", name="gaming")

    def test_profile_delete_failure(self):
        client = self._client({"ok": False, "error": "cannot delete the default profile"})
        with patch("c100ctl.cli._client", return_value=client):
            ns = argparse.Namespace(create=None, use=None, delete="default", clone=True, json=False)
            with self.assertRaises(SystemExit):
                cmd_profile(ns)

    def test_client_requires_daemon(self):
        with patch("c100ctl.cli.daemon_available", return_value=False):
            with self.assertRaises(SystemExit):
                from c100ctl.cli import _client

                _client()

    def test_bind_failure(self):
        client = self._client({"ok": False, "error": "nope"})
        ns = argparse.Namespace(
            row=1,
            col=1,
            clear=True,
            app=None,
            command=None,
            combo=None,
            macro=None,
            text=None,
            profile=None,
            url=None,
            media=None,
            mouse=None,
            light_action=None,
            hold_profile=None,
            hold_momentary=False,
            label="",
        )
        with patch("c100ctl.cli._client", return_value=client):
            with self.assertRaises(SystemExit):
                cmd_bind(ns)
