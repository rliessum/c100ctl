# macOS implementation

c100ctl on Darwin is the same daemon, VIA client, GTK UI, and binding engine as on Linux. The host-specific pieces are HID open, pad grab, key injection, app launch/close, and how the daemon is started.

Linux remains the primary target. `c100ctl.host.is_macos()` selects the Darwin path at runtime so type checkers do not fold `sys.platform` and mark the other OS unreachable.

## Linux → macOS map

| Role | Linux | macOS |
|------|--------|--------|
| VIA raw HID | `libhidapi-hidraw.so.0`, `/dev/hidraw*` | Homebrew `libhidapi.dylib` (IOKit backend), `DevSrvsID:…` paths |
| Find keyboard nodes | evdev `list_devices()`, VID/PID + name | hidapi enumerate, usage page `0x01` usage `0x06`/`0x07` |
| Exclusive grab | `evdev.InputDevice.grab()` | `IOHIDManagerOpen(kIOHIDOptionsTypeSeizeDevice)` |
| Identity → cell | evdev `KEY_*` via `identity_evdev_map()` | HID keyboard usage via `identity_hid_map()` |
| Grab fallback | VIA `matrix_pressed()` for one unmapped code | same, plus a full VIA matrix poll loop if seize is denied |
| Inject combos/text/mouse | `/dev/uinput` | Quartz `CGEventPost` |
| Media keys | evdev consumer codes | `NSEvent` system-defined NX aux keys, or `open` for www/mail/calc |
| Open URL | `xdg-open` (via `uwsm app` when present) | `/usr/bin/open` |
| Launch app | `.desktop` / `uwsm` / `gtk-launch` | `open -b <bundle id>` or `open -a <name>` |
| Double-tap close | Hyprland `hyprctl` | `osascript` `tell application … to quit` |
| Daemon | systemd user unit | LaunchAgent `net.liessum.c100ctl` |
| Device permission | udev `uaccess` on hidraw + uinput | TCC Input Monitoring + Accessibility |
| Runtime socket | `$XDG_RUNTIME_DIR/c100ctl/` | `$TMPDIR/c100ctl-$UID/` unless `XDG_RUNTIME_DIR` is set |
| Config | `~/.config/c100ctl/config.json` | same |

The Omarchy bar plugin, Hyprland window matching, and `.desktop` catalog are Linux-only.

## USB layout

The C100 8K (`3434:042c`) enumerates several HID collections. A typical hidapi listing on macOS:

| Interface | Usage page / usage | Role |
|-----------|-------------------|------|
| 0 | `0x0001` / `0x0006` (keyboard) | Boot keyboard — seized so pad keys do not type into the focused app |
| 1 | `0xFF60` / `0x0061` | VIA raw HID — lighting, keymap, matrix, advanced |
| 2 | keyboard, mouse, consumer, sys control | NKRO keyboard (also seized) plus mouse/consumer (not seized) |

VIA is a vendor page, so opening it does **not** require Input Monitoring. Opening or seizing the keyboard collections does.

`device.find_macos_input_paths()` keeps unique hidapi paths whose primary usage is Generic Desktop keyboard (`0x06`) or keypad (`0x07`), filtered by serial when the VIA interface reports one. Mouse and consumer collections are ignored so a Q1 or other Keychron on the same bus is not touched.

Disconnect detection cannot use `Path(via_path).exists()`: hidapi paths are IOService IDs. `hidraw_exists()` re-enumerates VID/PID and looks for that path.

## Module layout

```
c100ctl/host.py          is_macos()
c100ctl/hid.py           hidapi load + enumerate + open
c100ctl/via.py           VIA protocol; strips a leading report-id byte if hidapi prefixes one
c100ctl/device.py        find_c100(); macOS keyboard paths vs Linux evdev
c100ctl/pad.py           open_pad() → pad_macos.PadGrab or Linux PadGrab
c100ctl/pad_macos.py     IOHID seize + VIA matrix fallback
c100ctl/inject.py        VirtualKeyboard facade
c100ctl/inject_macos.py  Quartz / AppKit VirtualKeyboard
c100ctl/identity.py      identity_hid_map() — QMK basic code == HID usage
c100ctl/actions.py       open / Launch Services / osascript
c100ctl/doctor.py        hidapi, VIA, Input Monitoring, Accessibility
c100ctl/config.py        runtime dir under $TMPDIR
c100ctl/session.py       Homebrew PATH; no Hyprland defaults
```

The daemon (`daemon.py`) is shared. It calls `open_pad()` and `VirtualKeyboard` through the facades.

## VIA

`hid.py` lazy-loads hidapi. On Darwin it tries `ctypes.util.find_library("hidapi")`, then `libhidapi.dylib` / `libhidapi.0.dylib`, then `/opt/homebrew/lib` and `/usr/local/lib`.

Writes always send report id `0` plus a 32-byte VIA payload. Reads request 33 bytes. `_strip_report_id()` in `via.py` keeps a payload that already starts with the command (or `0xFF` unsupported) and drops a leading `0x00` when hidapi includes a report id. Current Homebrew hidapi (0.15) returns 32 bytes starting at the command; the strip is defensive.

The rest of VIA (keymap, RGB, Mix RGB, poll, debounce, NKRO, matrix) is byte-for-byte the Linux client.

## Pad grab

`open_pad()` on Darwin constructs `pad_macos.PadGrab` and starts it.

### IOHID seize (preferred)

1. If `IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)` is denied, call `IOHIDRequestAccess` so macOS can prompt.
2. `IOHIDManagerCreate` + `IOHIDManagerSetDeviceMatchingMultiple` for VID `0x3434`, PID `0x042c`, Generic Desktop keyboard **and** keypad. That matches boot (iface 0) and NKRO (iface 2) without claiming VIA, mouse, or consumer.
3. Register `IOHIDManagerRegisterInputValueCallback`.
4. Schedule the manager on the pad thread’s `CFRunLoop` and `IOHIDManagerOpen(…, kIOHIDOptionsTypeSeizeDevice)`.
5. If seize fails, retry a shared open. If that fails too, drop to matrix poll.

Callbacks deliver HID keyboard-page usages (`0x07`). Usages `0…3` are error rollover and are ignored. QMK basic keycodes **are** those usages, so `identity_hid_map()` is `{qmk_code: (row, col)}`. Press/release, 8 ms debounce, and a one-key VIA `matrix_pressed()` fallback for an unmapped usage match the Linux evdev grabber.

Seizing the C100 keyboard is what stops pad keys leaking into the focused window. It is the analog of `evdev` `grab()`.

### VIA matrix poll (fallback)

Used when Input Monitoring is missing or `IOHIDManagerOpen` fails, and a VIA client is already open.

Every 8 ms the loop reads `ViaClient.matrix_pressed(10, 10)` and emits edge transitions. Bindings still fire. Firmware identity keycodes still reach macOS, so keys also type into the focused app. The daemon logs this. `c100ctl doctor` reports Input Monitoring as missing.

Corner RGB keys (`0x7821` / `0x7822`) stay firmware-side either way.

## Injection

`inject.VirtualKeyboard` is `inject_macos.VirtualKeyboard` on Darwin.

| Binding | Mechanism |
|---------|-----------|
| Key / combo / typed text | `CGEventCreateKeyboardEvent` + `CGEventPost(kCGHIDEventTap)` using ANSI virtual keycodes from HIToolbox `Events.h`. Super/Meta is Command (`0x37`). Alt is Option. |
| Mouse click | `CGEventCreateMouseEvent` at the current cursor. Back/forward use other-mouse buttons 3 and 4. |
| Scroll | `CGEventCreateScrollWheelEvent2` in line units. |
| Play/pause, next/prev, mute, volume, brightness, eject | `NSEvent` type 14, subtype 8 (`NX_SUBTYPE_AUX_CONTROL_BUTTONS`), posted as a CGEvent. Mic-mute maps to mute. |
| Browser / homepage | `open https://` |
| Mail / Calculator | `open -a Mail` / `open -a Calculator` |
| Screenshot | injected ⌘⇧3 |

`KEY_F21`–`KEY_F24` have no Mac virtual keycode; tapping them raises `ValueError`, same as an unknown Linux evdev name.

Injection into other apps requires **Accessibility** (`AXIsProcessTrusted`). Without it, Quartz posts are dropped.

## Actions

Shared binding types (`app`, `command`, `combo`, …) are unchanged. Darwin-only behavior:

**Launch app.** `desktop_id` is a bundle id (`com.apple.Safari` → `open -b`), an `.app` path/name (`Kitty.app` → `open -a`), or a short name (`Music` → `open -a`). A trailing `.desktop` is stripped so a Linux config still tries `open -a firefox`.

**App list.** `list_desktop_apps()` scans `/Applications`, `/System/Applications`, `/System/Cryptexes/App/System/Applications`, and `~/Applications` (one extra directory level for Utilities-style nesting). `Info.plist` supplies `CFBundleIdentifier` and display name. `LSUIElement` / `LSBackgroundOnly` bundles are skipped. Gio `.desktop` scanning is the fallback if the scan is empty.

**Double-tap close.** Lists foreground processes via System Events and `tell application "<name>" to quit` when the name matches bundle-id last component, `.app` stem, or command token. This quits the app, not a single window, and is not Hyprland `class` matching.

**URL.** `open`. **Command.** `bash -lc`. **TUI helper.** `Terminal.app` `do script` instead of `xdg-terminal-exec`.

## Permissions

Two independent TCC grants. Grant them to the **same Python** `install.sh` put in the wrapper and LaunchAgent (`$(command -v python3)`).

| Grant | Setting | Needed for |
|-------|---------|------------|
| Input Monitoring | Privacy & Security → Input Monitoring | IOHID listen/seize of the C100 keyboard. Without it: matrix fallback, keys leak. |
| Accessibility | Privacy & Security → Accessibility | `CGEventPost` into other apps. Without it: combos, text, macros, mouse, media do nothing useful. |

VIA lighting and `c100ctl light` / Mix RGB / Advanced work with neither grant.

After changing TCC, unplug and replug the pad (or restart the LaunchAgent) so the next `IOHIDManagerOpen` runs as a trusted process.

`c100ctl doctor` checks hidapi, USB, VIA `0xFF60`, keyboard HID paths, `IOHIDCheckAccess(ListenEvent)`, `AXIsProcessTrusted`, and the daemon socket.

## Install and daemon

`install.sh` on Darwin (`uname -s` = `Darwin`):

- Copies `c100ctl/`, `data/`, `README.md` to `~/.local/share/c100ctl`
- Writes `~/.local/bin/c100ctl` with `PYTHONPATH`, Homebrew `PATH`, `GI_TYPELIB_PATH`, `DYLD_FALLBACK_LIBRARY_PATH`
- Writes `~/Library/LaunchAgents/net.liessum.c100ctl.plist` (`RunAtLoad`, `KeepAlive`) and `bootstrap`s it into `gui/$(id -u)`
- Logs: `~/Library/Logs/c100ctl.log`
- Refuses `--arch` and `--plugin` (Linux-only)

The GUI is GTK4 + libadwaita via Homebrew `pygobject3`. The daemon does not import GTK.

```bash
brew install python gtk4 libadwaita pygobject3 hidapi
bash install.sh
c100ctl doctor
```

Reload the agent after a code update:

```bash
launchctl kickstart -k gui/$(id -u)/net.liessum.c100ctl
```

## Paths

| Path | Purpose |
|------|---------|
| `~/.config/c100ctl/config.json` | Bindings, lighting, profiles (same schema as Linux, version 2) |
| `~/.config/c100ctl/backups/` | VIA keymap snapshots from provision |
| `$TMPDIR/c100ctl-$UID/c100ctl.sock` | GUI/CLI ↔ daemon (`AF_UNIX`, mode `0600`) |
| `$TMPDIR/c100ctl-$UID/c100ctl.lock` | `fcntl` single-instance lock |
| `~/.local/share/c100ctl/` | Installed package |
| `~/Library/LaunchAgents/net.liessum.c100ctl.plist` | Daemon |
| `~/Library/Logs/c100ctl.log` | LaunchAgent stdout/stderr |

`XDG_CONFIG_HOME` / `XDG_RUNTIME_DIR` override config and runtime dirs when set.

## What is not ported

- Omarchy plugin, `uwsm`, `hyprctl`, `.desktop` launchers as the primary app catalog
- Per-window close (double-tap quits the application)
- `F21`–`F24` injection
- A `.app` bundle / notarization / sandboxed HID access. This is a user-local CLI + LaunchAgent, same trust model as the Linux user unit.

## Tests

`tests/test_macos.py` covers identity HID mapping, Quartz `VirtualKeyboard` with CG/AppKit mocked, pad usage handling and matrix edges, `open` / `open -b` / osascript close, and app-plist scanning. IOKit and CoreGraphics FFI is `pragma: no cover`; Linux CI still runs those tests.

`tests/test_pad.py` and `tests/test_uinput.py` `pytest.importorskip("evdev")` so they skip on a Mac without python-evdev. Coverage omits `c100ctl/pad.py` and `c100ctl/uinput_kb.py` because they sit at 0% on Darwin; they are still executed on Linux CI.
