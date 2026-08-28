# C100 Control

Linux controller for the **Keychron C100 8K** 10×10 macropad. Built for [Omarchy](https://omarchy.org/) (Hyprland / Wayland), usable on any Linux desktop that can run GTK4.

Keychron Launcher remaps firmware keys in a browser. Keychron Assistant (Windows/macOS only) can launch apps. This fills the Linux gap: a native app that binds each key to an **app**, **command**, **key combination**, **macro**, or **typed text**, and keeps working after you close the window.

![C100 Control](docs/screenshot.png)

## What it talks to

The C100 enumerates as USB `3434:042c` and speaks **VIA protocol 12** on HID usage page `0xFF60`. Four corner keys are firmware lighting controls and stay that way. The other 96 keys are yours.

```
C100 8K ── USB ──► kernel hidraw / evdev
                      │
                      ├─ VIA raw HID     firmware keymap + RGB
                      └─ evdev grab      host bindings (apps / combos / macros)
```

The daemon **exclusively grabs** the C100 input nodes so pad keys never leak into the focused window (and never collide with another Keychron, such as a Q1). Combos and typed text are injected through a virtual `uinput` keyboard.

On first connect, if the pad still has the factory map (every programmable key = `KC_1`), the daemon writes a unique identity keycode to each of the 96 keys so it can tell them apart. The previous map is saved under `~/.config/c100ctl/backups/`.

## Install

Omarchy already has the Python/GTK stack. On Arch-like systems:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita python-evdev python-pyudev hidapi
```

Then:

```bash
git clone https://github.com/rliessum/c100ctl.git
cd c100ctl
bash install.sh
```

That installs:

- `c100ctl` on your PATH (`~/.local/bin`)
- a desktop entry in the app launcher
- a systemd **user** service that starts with the graphical session

You need write access to `/dev/uinput` and to Keychron `/dev/hidraw*` nodes. A udev example lives in [`packaging/70-c100ctl.rules`](packaging/70-c100ctl.rules):

```bash
sudo cp packaging/70-c100ctl.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the pad (or log out and back in if `uaccess` needs a new session).

```bash
c100ctl doctor    # hidraw, VIA, evdev, uinput, Wayland
```

## Use

```bash
c100ctl              # GUI
c100ctl status
c100ctl list

c100ctl bind 2 3 --app kitty.desktop --label Kitty
c100ctl bind 0 1 --combo 'Super+Return' --label Terminal
c100ctl bind 0 2 --command 'omarchy launch browser' --label Browser
c100ctl bind 4 4 --macro 'ctrl+c, delay:80, ctrl+v' --label Paste
c100ctl bind 5 0 --text 'hello' --label Hi
c100ctl bind 1 1 --url 'https://omarchy.org' --label Web
c100ctl bind 1 2 --media playpause --label Play
c100ctl bind 1 3 --mouse wheelup
c100ctl bind 1 4 --light-action next
c100ctl bind 2 0 --app kitty.desktop --hold-profile gaming --hold-momentary
c100ctl bind 2 3 --clear

c100ctl light --brightness 200 --effect 1 --speed 180 --effect-color '#ff8800'
c100ctl light --key 2,3 --color '#ff8800'
c100ctl light --key 0,1 --key 0,2 --key 0,3 --color '#00ff00'
c100ctl light --key 2,3 --color off
c100ctl advanced --poll 8000 --debounce-type 4 --debounce-ms 5 --nkro 1
c100ctl profile --create gaming
c100ctl profile --use gaming
```

The GUI has four pages: **Keys**, **Mix RGB**, **Advanced**, **Test**.

**Keys.** Click a cell or press the physical key. Ctrl/Shift/drag for multi-select. Bindings:

- App / command / combo / macro / text / profile (as before)
- **Open URL**, **media** (play, volume, brightness…), **mouse** (click / scroll), **lighting control** (next effect, brighter, toggle…)
- **On hold**: a second action after 400ms, including momentary profile (layer-style)
- **Chord**: select two or more keys, set the action, “Bind selected keys as a chord”
- App keys: **tap launches**, **double-tap closes** the matching Hyprland window
- Macro **Record** captures keystrokes in the window

**Lighting.** Brightness, effect, speed, global effect color, per-key FX (solid / breathing / reactive / splash). Paint per-key colors with the palette; undo/redo; select same color; clear all. Mix RGB is its own page: two zones, five timeline slots each (1–99s). Lighting can be saved into the active binding profile.

**Advanced.** USB polling rate (125–8000 Hz), debounce mode/time, NKRO, idle-dim timeout. Applied only when you click Apply (not on every daemon start).

**Test.** Heatmap of physical key hits.

Menu: import/export `config.json`, provision identity map, new profile.

Per-key colors use the C100 **Per Key RGB** effect (23). Mix RGB is effect 24.

- Click a key to select it
- **Ctrl+click** to add or remove keys
- **Shift+click** to fill a rectangle from the last key
- **Drag** across the pad to select a block
- **Ctrl+A** selects all, **Esc** clears the selection
- The chosen color is written to every selected key

Corner keys stay on the firmware lighting controls.

Macro syntax is comma-separated steps:

- `ctrl+c` — combo
- `delay:80` — milliseconds
- `text:hello` or a bare word — typed text
- `down:shift` / `up:shift` — hold
- `repeat: hold` on a macro binding repeats while the key is down

## Files

| Path | Purpose |
|------|---------|
| `~/.config/c100ctl/config.json` | bindings and profiles |
| `~/.config/c100ctl/backups/` | VIA keymap snapshots |
| `$XDG_RUNTIME_DIR/c100ctl/c100ctl.sock` | GUI/CLI ↔ daemon |

## Uninstall

```bash
systemctl --user disable --now c100ctl.service
rm -f ~/.local/bin/c100ctl
rm -rf ~/.local/share/c100ctl
rm -f ~/.local/share/applications/c100ctl.desktop
rm -f ~/.config/systemd/user/c100ctl.service
```

## License

MIT. Keychron is a trademark of its respective owner; this project is not affiliated with Keychron.
