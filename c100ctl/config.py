"""Persistent bindings. Atomic JSON under ~/.config/c100ctl/."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger("c100ctl.config")

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


# Binding types that launch or run something when the key is pressed. An
# imported config carrying these is arbitrary code the user has not written,
# so the importer shows them before the config is trusted.
EXECUTABLE_TYPES = ("app", "command", "url")


def _binding_detail(binding: dict[str, Any]) -> str:
    for field in ("command", "url", "desktop_id"):
        value = binding.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def executable_bindings(data: Any) -> list[tuple[str, str, str]]:
    """Every binding in a config that would run something on a keypress.

    Returns (where, type, detail) triples — the detail being the command,
    URL, or desktop id that would be executed. Used to show the contents of
    an imported config before accepting it.
    """
    found: list[tuple[str, str, str]] = []
    if not isinstance(data, dict):
        return found

    def visit(where: str, binding: Any) -> None:
        if not isinstance(binding, dict):
            return
        if binding.get("type") in EXECUTABLE_TYPES:
            found.append((where, str(binding.get("type")), _binding_detail(binding)))
        visit(f"{where} (hold)", binding.get("hold"))

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            keys = profile.get("keys")
            if not isinstance(keys, dict):
                continue
            for kid in sorted(keys, key=str):
                visit(f"{name} · key {kid}", keys[kid])

    chords = data.get("chords")
    if isinstance(chords, list):
        for chord in chords:
            if not isinstance(chord, dict):
                continue
            keys = chord.get("keys")
            label = "+".join(str(k) for k in keys) if isinstance(keys, list) else "?"
            visit(f"chord {label}", chord.get("binding"))

    return found


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


def _as_int(value: Any, fallback: int, lo: int | None = None, hi: int | None = None) -> int:
    """Coerce to int, clamped when bounds are given. Non-numeric falls back."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    out = int(value)
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def merge_lighting(raw: Any) -> dict[str, Any]:
    """Merge a raw lighting block over the defaults, dropping bad types."""
    lighting = default_lighting()
    if not isinstance(raw, dict):
        return lighting
    lighting["brightness"] = _as_int(raw.get("brightness"), 255, 0, 255)
    lighting["effect"] = _as_int(raw.get("effect"), 1, 0)
    lighting["speed"] = _as_int(raw.get("speed"), 127, 0, 255)
    lighting["per_key_type"] = _as_int(raw.get("per_key_type"), 0, 0, 4)
    if isinstance(raw.get("color"), str):
        lighting["color"] = raw["color"]
    if "_prev_brightness" in raw:
        lighting["_prev_brightness"] = _as_int(raw.get("_prev_brightness"), 255, 0, 255)
    keys = raw.get("keys")
    if isinstance(keys, dict):
        lighting["keys"] = {
            str(kid): color for kid, color in keys.items() if isinstance(color, str) and color
        }
    lighting["mix"] = merge_mix(raw.get("mix"))
    return lighting


def merge_mix(raw: Any) -> dict[str, Any]:
    mix = default_mix()
    if not isinstance(raw, dict):
        return mix
    regions = raw.get("regions")
    if isinstance(regions, list):
        cleaned = [1 if _as_int(x, 0) else 0 for x in regions[:100]]
        mix["regions"] = cleaned + [0] * (100 - len(cleaned))
    slots = raw.get("slots")
    if isinstance(slots, list):
        layers: list[list[dict[str, int]]] = []
        for layer in slots[:2]:
            if not isinstance(layer, list):
                continue
            layers.append([_merge_slot(s) for s in layer[:5] if isinstance(s, dict)])
        if layers:
            mix["slots"] = layers
    return mix


def _merge_slot(raw: dict[str, Any]) -> dict[str, int]:
    return {
        "effect": _as_int(raw.get("effect"), 0, 0, 255),
        "hue": _as_int(raw.get("hue"), 0, 0, 255),
        "sat": _as_int(raw.get("sat"), 255, 0, 255),
        "speed": _as_int(raw.get("speed"), 127, 0, 255),
        "time_ms": _as_int(raw.get("time_ms"), 5000, 0),
    }


def merge_advanced(raw: Any) -> dict[str, Any]:
    adv = default_advanced()
    if not isinstance(raw, dict):
        return adv
    adv["poll_hz"] = _as_int(raw.get("poll_hz"), 8000, 1)
    adv["debounce_type"] = _as_int(raw.get("debounce_type"), 4, 0, 255)
    adv["debounce_ms"] = _as_int(raw.get("debounce_ms"), 5, 0, 255)
    adv["idle_dim_s"] = _as_int(raw.get("idle_dim_s"), 0, 0)
    adv["nkro"] = bool(raw.get("nkro", True))
    return adv


def merge_profiles(raw: Any) -> dict[str, Any]:
    """Keep only well-formed profiles. Falls back to a lone default profile."""
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for name, profile in raw.items():
            if not isinstance(name, str) or not name or not isinstance(profile, dict):
                continue
            keys = profile.get("keys")
            entry: dict[str, Any] = {
                "label": profile["label"] if isinstance(profile.get("label"), str) else name.title(),
                "keys": (
                    {str(k): v for k, v in keys.items() if isinstance(v, dict)}
                    if isinstance(keys, dict)
                    else {}
                ),
            }
            if isinstance(profile.get("lighting"), dict):
                entry["lighting"] = merge_lighting(profile["lighting"])
            out[name] = entry
    return out or default_config()["profiles"]


def merge_chords(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for chord in raw:
        if not isinstance(chord, dict):
            continue
        keys = chord.get("keys")
        binding = chord.get("binding")
        if not isinstance(keys, list) or len(keys) < 2 or not isinstance(binding, dict):
            continue
        if binding.get("type") not in BINDING_TYPES:
            continue
        out.append({"keys": [str(k) for k in keys], "binding": binding})
    return out


def merge_config(raw: Any) -> dict[str, Any]:
    """Merge raw config data over the defaults, rejecting wrongly-typed fields.

    Every field is checked against the type it is expected to hold; anything
    that does not match falls back to its default instead of being carried
    through. Callers may hand this untrusted data (an imported config file),
    so a bad value must never reach the rest of the app.
    """
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg
    cfg["provisioned"] = bool(raw.get("provisioned", False))
    if isinstance(raw.get("active_profile"), str):
        cfg["active_profile"] = raw["active_profile"]
    if isinstance(raw.get("serial"), str):
        cfg["serial"] = raw["serial"]
    cfg["profiles"] = merge_profiles(raw.get("profiles"))
    cfg["lighting"] = merge_lighting(raw.get("lighting"))
    cfg["advanced"] = merge_advanced(raw.get("advanced"))
    cfg["chords"] = merge_chords(raw.get("chords"))
    cfg["version"] = CONFIG_VERSION
    return cfg


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.data = default_config()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = default_config()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("config at %s is unreadable (%s); starting from defaults", self.path, e)
            self._quarantine()
            self.data = default_config()
            return
        self.data = merge_config(raw)

    def _quarantine(self, suffix: str = ".corrupt") -> None:
        """Move an unreadable config aside so it is not silently overwritten."""
        try:
            self.path.replace(self.path.with_name(self.path.name + suffix))
        except OSError:
            pass

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

    def ensure_profile(
        self,
        name: str,
        label: str | None = None,
        clone_from: str | None = None,
    ) -> None:
        """Create a profile if it doesn't exist.

        Args:
            name: Profile name (slug).
            label: Display label (defaults to titlecased name).
            clone_from: If set, clone keys and lighting from this profile.
                       Pass "__current__" to clone from the active profile.
                       When "__current__", also captures global lighting.
        """
        if name not in self.data["profiles"]:
            source_name = clone_from
            clone_global_lighting = clone_from == "__current__"
            if clone_from == "__current__":
                source_name = self.active_profile_name()

            if source_name and source_name in self.data["profiles"]:
                source = self.data["profiles"][source_name]
                new_profile: dict[str, Any] = {
                    "label": label or name.title(),
                    "keys": deepcopy(source.get("keys", {})),
                }
                if "lighting" in source:
                    new_profile["lighting"] = deepcopy(source["lighting"])
                elif clone_global_lighting and self.data.get("lighting"):
                    new_profile["lighting"] = deepcopy(self.data["lighting"])
            else:
                new_profile = {"label": label or name.title(), "keys": {}}
                if clone_global_lighting and self.data.get("lighting"):
                    new_profile["lighting"] = deepcopy(self.data["lighting"])

            self.data["profiles"][name] = new_profile
            self.save()

    def delete_profile(self, name: str) -> None:
        if name == "default":
            raise ValueError("cannot delete the default profile")
        self.data["profiles"].pop(name, None)
        if self.data["active_profile"] == name:
            self.data["active_profile"] = "default"
        self.save()

    def save_profile(self, name: str | None = None) -> None:
        """Persist current global lighting into the profile.

        The profile's keys are already updated via set_binding, so this
        captures the current global lighting state into the profile.
        """
        name = name or self.active_profile_name()
        if name not in self.data["profiles"]:
            raise KeyError(name)
        profile = self.data["profiles"][name]
        if self.data.get("lighting"):
            profile["lighting"] = deepcopy(self.data["lighting"])
        self.save()

    def list_profile_names(self) -> list[str]:
        """Return list of profile names in consistent order (default first)."""
        names = list(self.data.get("profiles", {}).keys())
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")
        return names if names else ["default"]

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
