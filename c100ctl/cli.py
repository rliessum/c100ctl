"""Command-line interface for C100 Control."""

from __future__ import annotations

import argparse
import json
from typing import Any

from . import LOCKED_KEYS, LOCKED_LABELS, __version__
from .config import key_id
from .ipc import IpcClient, daemon_available


def _client() -> IpcClient:
    if not daemon_available():
        raise SystemExit("daemon is not running — start it with: c100ctl daemon")
    return IpcClient()


def _pretty_binding(binding: dict[str, Any] | None) -> str:
    if not binding:
        return "—"
    kind = binding.get("type", "?")
    label = binding.get("label") or ""
    if kind == "app":
        return f"{label or binding.get('desktop_id') or binding.get('command')}  (app)"
    if kind == "command":
        return f"{label or binding.get('command')}  (cmd)"
    if kind == "combo":
        return f"{label or binding.get('combo')}  (combo)"
    if kind == "macro":
        return f"{label or 'macro'}  (macro)"
    if kind == "text":
        return f"{(binding.get('text') or '')[:24]}  (text)"
    if kind == "profile":
        return f"profile:{binding.get('profile')}"
    if kind == "url":
        return f"{binding.get('url')}  (url)"
    if kind == "media":
        return f"{binding.get('media')}  (media)"
    if kind == "mouse":
        return f"{binding.get('mouse')}  (mouse)"
    if kind == "light":
        return f"{binding.get('light')}  (light)"
    return json.dumps(binding)


def cmd_status(_args: argparse.Namespace) -> int:
    c = _client()
    try:
        st = c.request("status")
    finally:
        c.close()
    connected = "yes" if st.get("connected") else "no"
    print(f"c100ctl {st.get('version', __version__)}")
    print(f"connected: {connected}")
    if st.get("connected"):
        print(f"protocol:  {st.get('protocol')}")
        print(f"serial:    {st.get('serial')}")
        print(f"layers:    {st.get('layers')}")
    print(f"profile:   {st.get('profile')}")
    print(f"provisioned: {st.get('provisioned')}")
    lighting = st.get("lighting") or {}
    if lighting:
        print(f"lighting:  brightness={lighting.get('brightness')} effect={lighting.get('effect')} speed={lighting.get('speed')}")
    hw = st.get("hardware") or {}
    if hw.get("firmware"):
        print(f"firmware:  {hw.get('firmware')}")
    adv = st.get("advanced") or {}
    if adv:
        print(f"advanced:  poll={adv.get('poll_hz')}Hz debounce={adv.get('debounce_type')}/{adv.get('debounce_ms')}ms nkro={adv.get('nkro')}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    c = _client()
    try:
        cfg = c.request("get_config")
    finally:
        c.close()
    data = cfg.get("config") or {}
    name = data.get("active_profile", "default")
    keys = data.get("profiles", {}).get(name, {}).get("keys", {})
    print(f"profile: {name}")
    for r in range(10):
        for col in range(10):
            cell = (r, col)
            if cell in LOCKED_KEYS:
                print(f"  {r},{col:1}  {LOCKED_LABELS[cell]}  [locked]")
                continue
            b = keys.get(key_id(r, col))
            if b:
                print(f"  {r},{col}  {_pretty_binding(b)}")
    return 0


def cmd_bind(args: argparse.Namespace) -> int:
    row, col = int(args.row), int(args.col)
    if (row, col) in LOCKED_KEYS:
        raise SystemExit("that corner key is a firmware lighting control")
    binding: dict[str, Any] | None
    if args.clear:
        binding = None
    elif args.app:
        binding = {"type": "app", "desktop_id": args.app, "label": args.label or args.app.replace(".desktop", "")}
        if args.command:
            binding["command"] = args.command
    elif args.command and not args.app:
        binding = {"type": "command", "command": args.command, "label": args.label or ""}
    elif args.combo:
        binding = {"type": "combo", "combo": args.combo, "label": args.label or args.combo}
    elif args.macro:
        binding = {"type": "macro", "macro": args.macro, "label": args.label or "macro"}
    elif args.text is not None:
        binding = {"type": "text", "text": args.text, "label": args.label or args.text[:12]}
    elif args.profile:
        binding = {"type": "profile", "profile": args.profile, "label": args.label or args.profile}
    elif args.url:
        binding = {"type": "url", "url": args.url, "label": args.label or args.url}
    elif args.media:
        binding = {"type": "media", "media": args.media, "label": args.label or args.media}
    elif args.mouse:
        binding = {"type": "mouse", "mouse": args.mouse, "label": args.label or args.mouse}
    elif args.light_action:
        binding = {"type": "light", "light": args.light_action, "label": args.label or args.light_action}
    else:
        raise SystemExit("specify an action type or --clear")
    if binding and args.hold_profile:
        binding["hold"] = {
            "type": "profile",
            "profile": args.hold_profile,
            "momentary": bool(args.hold_momentary),
            "label": args.hold_profile,
        }
    if binding and not binding.get("label"):
        binding["label"] = f"{row},{col}"
    c = _client()
    try:
        resp = c.request("set_binding", row=row, col=col, binding=binding)
    finally:
        c.close()
    if not resp.get("ok"):
        raise SystemExit(resp.get("error", "bind failed"))
    print("ok")
    return 0


def cmd_provision(_args: argparse.Namespace) -> int:
    c = _client()
    try:
        resp = c.request("provision", backup=True)
    finally:
        c.close()
    if not resp.get("ok"):
        raise SystemExit(resp.get("error", "provision failed"))
    print("identity map written (backup saved)")
    return 0


def cmd_light(args: argparse.Namespace) -> int:
    c = _client()
    try:
        if args.key:
            if args.color is None:
                raise SystemExit("--key requires --color (hex like #ff8800, or off)")
            cells = []
            for item in args.key:
                try:
                    row, col = (int(x) for x in item.split(",", 1))
                except ValueError as e:
                    raise SystemExit(f"expected --key row,col, got {item!r}") from e
                cells.append({"row": row, "col": col, "color": args.color})
            resp = c.request("set_key_colors", keys=cells)
        else:
            fields: dict[str, Any] = {}
            if args.brightness is not None:
                fields["brightness"] = args.brightness
            if args.effect is not None:
                fields["effect"] = args.effect
            if args.speed is not None:
                fields["speed"] = args.speed
            if args.effect_color:
                fields["color"] = args.effect_color
            if args.per_key_type is not None:
                fields["per_key_type"] = args.per_key_type
            if not fields:
                raise SystemExit("specify --brightness, --effect, --speed, --color, or --key")
            resp = c.request("set_lighting", **fields)
    finally:
        c.close()
    if not resp.get("ok"):
        raise SystemExit(resp.get("error", "lighting failed"))
    print(resp.get("lighting") or resp)
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    c = _client()
    try:
        if args.create:
            clone_from = "__current__" if getattr(args, "clone", True) else None
            c.request("ensure_profile", name=args.create, label=args.create, clone_from=clone_from)
            print("created", args.create)
            return 0
        if args.delete:
            resp = c.request("delete_profile", name=args.delete)
            if not resp.get("ok"):
                raise SystemExit(resp.get("error", "failed"))
            print("deleted", args.delete)
            return 0
        if args.use:
            resp = c.request("set_profile", name=args.use)
            if not resp.get("ok"):
                raise SystemExit(resp.get("error", "failed"))
            print("active profile:", args.use)
            return 0
        cfg = c.request("get_config")
    finally:
        c.close()
    data = cfg.get("config") or {}
    active = data.get("active_profile")
    profiles = list(data.get("profiles", {}).keys())
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "active": active, "profiles": profiles}))
        return 0
    for name in profiles:
        mark = "*" if name == active else " "
        print(f"{mark} {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="c100ctl",
        description="Control a Keychron C100 8K macropad on Linux or macOS.",
    )
    p.add_argument("--version", action="version", version=f"c100ctl {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="open the control window (default)")
    sub.add_parser("daemon", help="run the background daemon")
    sub.add_parser("status", help="show connection status")
    sub.add_parser("doctor", help="check HID, VIA, input grab, and injection")
    sub.add_parser("list", help="list bindings in the active profile")
    sub.add_parser("provision", help="write unique identity keycodes to the pad")

    b = sub.add_parser("bind", help="bind a key at row col")
    b.add_argument("row", type=int)
    b.add_argument("col", type=int)
    b.add_argument("--app", help="desktop id, e.g. firefox.desktop")
    b.add_argument("--command", help="shell command")
    b.add_argument("--combo", help="e.g. Super+Return")
    b.add_argument("--macro", help="e.g. ctrl+c, delay:80, ctrl+v")
    b.add_argument("--text", help="type this string")
    b.add_argument("--profile", help="switch to this profile")
    b.add_argument("--url", help="open this URL")
    b.add_argument("--media", help="playpause, next, mute, volup, …")
    b.add_argument("--mouse", help="left, right, wheelup, …")
    b.add_argument("--light-action", dest="light_action", help="next, prev, brighter, dimmer, toggle, perkey, mix")
    b.add_argument("--hold-profile", help="secondary profile on hold")
    b.add_argument("--hold-momentary", action="store_true", help="hold profile only while the key is down")
    b.add_argument("--label", help="short label shown on the pad")
    b.add_argument("--clear", action="store_true")

    lgt = sub.add_parser("light", help="set RGB brightness, effect, or per-key color")
    lgt.add_argument("--brightness", type=int)
    lgt.add_argument("--effect", type=int, help="0=off … 23=per-key RGB")
    lgt.add_argument("--speed", type=int)
    lgt.add_argument("--effect-color", help="global effect color hex")
    lgt.add_argument("--per-key-type", type=int, help="0 solid … 4 splash")
    lgt.add_argument("--key", action="append", help="cell as row,col; repeat to paint many")
    lgt.add_argument("--color", help="hex color like #ff8800, or off")

    adv = sub.add_parser("advanced", help="polling rate, debounce, NKRO, idle dim")
    adv.add_argument("--poll", type=int, help="125–8000 Hz")
    adv.add_argument("--debounce-type", type=int)
    adv.add_argument("--debounce-ms", type=int)
    adv.add_argument("--nkro", type=int, choices=[0, 1])
    adv.add_argument("--idle-dim", type=int, help="seconds, 0=off")

    pr = sub.add_parser("profile", help="list or switch profiles")
    pr.add_argument("--use", help="switch to this profile")
    pr.add_argument("--create", help="create a new profile (clones current by default)")
    pr.add_argument("--delete", help="delete a profile (cannot delete default)")
    pr.add_argument("--no-clone", dest="clone", action="store_false", default=True,
                    help="create an empty profile instead of cloning current")
    pr.add_argument("--json", action="store_true", help="output as JSON (for scripts)")
    return p


def cmd_advanced(args: argparse.Namespace) -> int:
    fields: dict[str, Any] = {}
    if args.poll is not None:
        fields["poll_hz"] = args.poll
    if args.debounce_type is not None:
        fields["debounce_type"] = args.debounce_type
    if args.debounce_ms is not None:
        fields["debounce_ms"] = args.debounce_ms
    if args.nkro is not None:
        fields["nkro"] = bool(args.nkro)
    if args.idle_dim is not None:
        fields["idle_dim_s"] = args.idle_dim
    if not fields:
        raise SystemExit("specify --poll, --debounce-type, --debounce-ms, --nkro, or --idle-dim")
    c = _client()
    try:
        resp = c.request("set_advanced", **fields)
    finally:
        c.close()
    if not resp.get("ok"):
        raise SystemExit(resp.get("error", "advanced failed"))
    print(resp.get("advanced") or resp)
    return 0
