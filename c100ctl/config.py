"""Persistent bindings. Atomic JSON under ~/.config/c100ctl/."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_NAME = "c100ctl"
CONFIG_VERSION = 2

BINDING_TYPES = (
    "app",
    "command",
    "combo",
    "macro",
    "text",
    "profile",
    "url",
    "media",
    "mouse",
    "light",
)


def xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def xdg_runtime() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / APP_NAME
    return Path(f"/run/user/{os.getuid()}") / APP_NAME


def config_path() -> Path:
    return xdg_config() / "config.json"


def socket_path() -> Path:
    return xdg_runtime() / "c100ctl.sock"


def lock_path() -> Path:
    return xdg_runtime() / "c100ctl.lock"


def backup_dir() -> Path:
    return xdg_config() / "backups"


def default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "provisioned": False,
        "active_profile": "default",
        "lighting": default_lighting(),
        "advanced": default_advanced(),
        "chords": [],
        "profiles": {
            "default": {"label": "Default", "keys": {}},
        },
    }


def default_lighting() -> dict[str, Any]:
    return {
        "brightness": 255,
        "effect": 1,
        "speed": 127,
        "color": "#ff3b30",
        "per_key_type": 0,
        "keys": {},
        "mix": default_mix(),
    }


def default_mix() -> dict[str, Any]:
    empty = {"effect": 0, "hue": 0, "sat": 255, "speed": 127, "time_ms": 5000}
    a = [{"effect": 5, "hue": 0, "sat": 255, "speed": 127, "time_ms": 5000}]
    b = [{"effect": 2, "hue": 0, "sat": 255, "speed": 127, "time_ms": 5000}]
    return {
        "regions": [0] * 100,
        "slots": [a + [dict(empty) for _ in range(4)], b + [dict(empty) for _ in range(4)]],
    }


def default_advanced() -> dict[str, Any]:
    return {
        "poll_hz": 8000,
        "debounce_type": 4,
        "debounce_ms": 5,
        "nkro": True,
        "idle_dim_s": 0,
    }


def key_id(row: int, col: int) -> str:
    return f"{row},{col}"


def parse_key_id(value: str) -> tuple[int, int]:
    r, c = value.split(",", 1)
    return int(r), int(c)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".c100ctl.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.data = default_config()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = default_config()
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        cfg = default_config()
        cfg.update({k: raw[k] for k in raw if k in cfg or k in ("serial",)})
        if "profiles" in raw and isinstance(raw["profiles"], dict) and raw["profiles"]:
            cfg["profiles"] = raw["profiles"]
        if "lighting" in raw and isinstance(raw["lighting"], dict):
            lighting = default_lighting()
            lighting.update(raw["lighting"])
            if not isinstance(lighting.get("keys"), dict):
                lighting["keys"] = {}
            mix = default_mix()
            raw_mix = raw["lighting"].get("mix")
            if isinstance(raw_mix, dict):
                mix.update(raw_mix)
                if not isinstance(mix.get("regions"), list):
                    mix["regions"] = [0] * 100
                if not isinstance(mix.get("slots"), list):
                    mix["slots"] = default_mix()["slots"]
            lighting["mix"] = mix
            cfg["lighting"] = lighting
        if "advanced" in raw and isinstance(raw["advanced"], dict):
            adv = default_advanced()
            adv.update(raw["advanced"])
            cfg["advanced"] = adv
        if "chords" in raw and isinstance(raw["chords"], list):
            cfg["chords"] = raw["chords"]
        cfg["version"] = CONFIG_VERSION
        self.data = cfg

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    def active_profile_name(self) -> str:
        name = self.data.get("active_profile", "default")
        if name not in self.data["profiles"]:
            name = next(iter(self.data["profiles"]))
            self.data["active_profile"] = name
        return name

    def profile(self, name: str | None = None) -> dict[str, Any]:
        name = name or self.active_profile_name()
        return self.data["profiles"][name]

    def keys(self, name: str | None = None) -> dict[str, Any]:
        return self.profile(name).setdefault("keys", {})

    def get_binding(self, row: int, col: int, name: str | None = None) -> dict[str, Any] | None:
        return self.keys(name).get(key_id(row, col))

    def set_binding(self, row: int, col: int, binding: dict[str, Any] | None, name: str | None = None) -> None:
        keys = self.keys(name)
        kid = key_id(row, col)
        if binding is None:
            keys.pop(kid, None)
        else:
            kind = binding.get("type")
            if kind not in BINDING_TYPES:
                raise ValueError(f"unknown binding type {kind!r}")
            hold = binding.get("hold")
            if isinstance(hold, dict) and hold.get("type") not in BINDING_TYPES:
                raise ValueError(f"unknown hold type {hold.get('type')!r}")
            keys[kid] = binding
        self.save()

    def set_chords(self, chords: list[dict[str, Any]]) -> None:
        cleaned: list[dict[str, Any]] = []
        for chord in chords:
            keys = chord.get("keys") or []
            binding = chord.get("binding")
            if not isinstance(keys, list) or len(keys) < 2 or not isinstance(binding, dict):
                continue
            if binding.get("type") not in BINDING_TYPES:
                continue
            cleaned.append({"keys": [str(k) for k in keys], "binding": binding})
        self.data["chords"] = cleaned
        self.save()

    def replace_config(self, data: dict[str, Any]) -> None:
        _atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")
        self.load()
        self.save()

    def set_profile(self, name: str) -> None:
        if name not in self.data["profiles"]:
            raise KeyError(name)
        self.data["active_profile"] = name
        self.save()

    def ensure_profile(self, name: str, label: str | None = None) -> None:
        if name not in self.data["profiles"]:
            self.data["profiles"][name] = {"label": label or name.title(), "keys": {}}
            self.save()

    def delete_profile(self, name: str) -> None:
        if name == "default":
            raise ValueError("cannot delete the default profile")
        self.data["profiles"].pop(name, None)
        if self.data["active_profile"] == name:
            self.data["active_profile"] = "default"
        self.save()

    def lighting_keys(self) -> dict[str, str]:
        lighting = self.data.setdefault("lighting", {})
        keys = lighting.setdefault("keys", {})
        if not isinstance(keys, dict):
            lighting["keys"] = {}
            return lighting["keys"]
        return keys

    def get_key_color(self, row: int, col: int) -> str | None:
        value = self.lighting_keys().get(key_id(row, col))
        return value if isinstance(value, str) and value else None

    def set_key_color(self, row: int, col: int, color: str | None) -> None:
        self.set_key_colors([(row, col, color)])

    def set_key_colors(self, updates: list[tuple[int, int, str | None]]) -> None:
        keys = self.lighting_keys()
        for row, col, color in updates:
            kid = key_id(row, col)
            if color:
                keys[kid] = color
            else:
                keys.pop(kid, None)
        self.save()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.data)
