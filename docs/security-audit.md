# Security Audit: c100ctl

**Audit Date:** August 2026  
**Version Audited:** 1.4.0  
**Auditor:** Cloud Agent Security Review

## Executive Summary

This document presents a comprehensive security audit of c100ctl, a Linux host application for the Keychron C100 8K macropad. The audit examined IPC mechanisms, action execution, configuration handling, device access, VIA/HID operations, and deployment artifacts (udev rules, systemd unit, installer).

**Overall Assessment:** The application follows reasonable security practices for its intended deployment model (single-user Omarchy/Hyprland desktop). Two findings require code changes:

| Severity | Count | Fixed in PR |
|----------|-------|-------------|
| Critical | 0 | — |
| High | 1 | Yes |
| Medium | 1 | Yes |
| Low | 1 | No (documented) |
| Info | 4 | — |

## Scope

### Components Audited

| Component | Files | Description |
|-----------|-------|-------------|
| IPC | `c100ctl/ipc.py`, `c100ctl/config.py` | Unix socket protocol, path, permissions |
| Daemon | `c100ctl/daemon.py` | Request handlers, key dispatch, action queuing |
| Actions | `c100ctl/actions.py` | App launch, command execution, URL opening |
| Config | `c100ctl/config.py` | JSON config load/save, atomic writes |
| uinput | `c100ctl/uinput_kb.py` | Virtual keyboard injection |
| Device | `c100ctl/device.py`, `c100ctl/pad.py` | evdev enumeration, grab, identity mapping |
| VIA/HID | `c100ctl/via.py`, `c100ctl/hid.py` | Firmware communication, keymap provision |
| CLI | `c100ctl/cli.py`, `c100ctl/__main__.py` | Command-line interface |
| Install | `install.sh` | User-space installation |
| udev | `packaging/70-c100ctl.rules` | Device access rules |
| systemd | `packaging/c100ctl.service` | User unit |

### Threat Model

The intended deployment is a single-user Linux desktop (Omarchy/Hyprland) where:

- The user runs c100ctl as their own UID
- The user has physical access to the Keychron C100 8K
- The user configures key bindings that may launch apps, run commands, type text, etc.
- Other processes running as the same UID are within the trust boundary

**Out of Scope Threats:**

- Root-level compromise (c100ctl has no setuid, capabilities, or privilege escalation)
- Remote network attacks (no network listeners)
- Physical attacks on the USB device itself
- Firmware vulnerabilities in the Keychron C100

### Multi-User System Considerations

On multi-user systems where multiple physical users share a machine, additional risks exist. These are documented in the Residual Risk section.

---

## Findings

### HIGH-001: Config File Permissions Not Explicitly Set

**Severity:** High  
**Location:** `c100ctl/config.py:_atomic_write()` (lines 111-125)  
**Status:** Fixed in this PR

**Description:**

The `_atomic_write()` function uses `tempfile.mkstemp()` to create a temporary file, then atomically replaces the config file via `os.replace()`. However, the file permissions depend on the process umask rather than being explicitly set.

```python
def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".c100ctl.", dir=str(path.parent))
    # ... write and replace ...
```

**Impact:**

If a user has a permissive umask (e.g., `0002` or `0000`), the config file at `~/.config/c100ctl/config.json` could be world-readable or group-readable. The config contains:

- Key binding definitions including shell commands
- Application identifiers
- Key labels (potentially sensitive shortcuts)

While not containing secrets, the binding configuration reveals user behavior patterns and configured commands.

**Fix:**

Explicitly set file permissions to `0o600` (owner read/write only) after the atomic write:

```python
os.replace(tmp, path)
os.chmod(path, 0o600)
```

Also ensure the config directory is created with restrictive permissions.

---

### MEDIUM-001: Backup Directory Permissions Not Explicitly Set

**Severity:** Medium  
**Location:** `c100ctl/daemon.py:provision()` (lines 794-810)  
**Status:** Fixed in this PR

**Description:**

When backing up the firmware keymap before provisioning, the backup directory and files are created without explicit permission settings:

```python
dest = backup_dir()
dest.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d-%H%M%S")
path = dest / f"keymap-{stamp}.json"
path.write_text(json.dumps({"layers": keymap}, indent=2))
```

**Impact:**

Backup files contain the raw keymap layer data from the keyboard firmware. While not sensitive in the same way as user commands, it reveals:

- The user's firmware customization state
- Key remapping patterns

On systems with permissive umask, these could be readable by other users.

**Fix:**

Use explicit permissions when creating the backup directory and files:

```python
dest.mkdir(parents=True, exist_ok=True, mode=0o700)
# ... create file with restricted permissions ...
```

---

### LOW-001: IPC Socket Accessible to Same-UID Processes

**Severity:** Low  
**Location:** `c100ctl/ipc.py:IpcServer.start()` (lines 28-42)  
**Status:** Not a vulnerability (documented)

**Description:**

The IPC socket at `$XDG_RUNTIME_DIR/c100ctl/c100ctl.sock` is created with mode `0o600`, restricting access to the owning user. Any process running as that UID can connect and send commands.

The socket accepts JSON commands including:
- `set_binding` — configure a key to run arbitrary commands
- `import_config` — replace the entire configuration
- `provision` — rewrite firmware keymap

**Analysis:**

This is **by design**. The IPC mechanism exists so the GUI, CLI, and daemon can communicate. The security boundary is the Unix user, not individual processes. A malicious process running as the same UID already has full access to:

- The user's home directory and all files
- The running graphical session (could inject input directly)
- All processes (could kill or trace the daemon)

Requiring additional authentication (tokens, passwords) would be security theater — any mechanism to store/transmit a secret would be accessible to the same processes we're trying to exclude.

**Recommendation:**

No code change needed. Document that c100ctl trusts all processes running as the same UID, which is the standard Unix security model.

---

### INFO-001: Shell Command Execution by Design

**Severity:** Info  
**Location:** `c100ctl/actions.py:run_command()` (lines 142-150)

**Description:**

User-configured commands are executed via:

```python
argv = ["bash", "-lc", command]
subprocess.Popen(argv, env=self.env, start_new_session=True)
```

**Analysis:**

This is the core feature — users bind keys to commands. The command is:

1. Configured by the user (via GUI or CLI)
2. Stored in the user's config file
3. Executed when the user presses the bound key

There is no "injection" because the user explicitly provided the command. The shell is invoked intentionally to support shell features (pipes, variables, etc.).

**No action required.** This is expected behavior, documented in README.

---

### INFO-002: URL Opening via xdg-open

**Severity:** Info  
**Location:** `c100ctl/actions.py:open_url()` (lines 85-95)

**Description:**

URLs are opened via `xdg-open`:

```python
if "://" not in url:
    url = "https://" + url
opener = self._which("xdg-open")
# ...
self._spawn([opener, url])
```

**Analysis:**

- URLs are prefixed with `https://` if no scheme is present
- `xdg-open` is the standard way to open URLs on Linux desktops
- The URL is passed as an argument, not through a shell

**No vulnerability.** Standard desktop integration.

---

### INFO-003: udev Rules Use uaccess Tag

**Severity:** Info  
**Location:** `packaging/70-c100ctl.rules`

**Description:**

The udev rules grant access via `TAG+="uaccess"`:

```udev
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3434", MODE="0660", TAG+="uaccess"
KERNEL=="uinput", MODE="0660", TAG+="uaccess"
```

**Analysis:**

The `uaccess` tag grants access to the "seat" owner — typically the user logged in at the physical console. This is the standard mechanism for consumer HID devices.

On **single-user systems**: Appropriate. The physical user should control their devices.

On **multi-user systems**: Any user at the physical console can access Keychron devices and uinput. This is standard for consumer peripherals but worth noting for shared workstations.

**Recommendation:**

For high-security multi-user environments, consider a group-based rule instead of `uaccess`. However, this is not the target deployment scenario.

---

### INFO-004: JSON Config Parsing (No Unsafe Deserialization)

**Severity:** Info  
**Location:** `c100ctl/config.py:Store.load()` (lines 134-165)

**Description:**

Configuration is loaded via:

```python
raw = json.loads(self.path.read_text(encoding="utf-8"))
```

**Analysis:**

- Uses `json.loads()` which is safe — no code execution
- No `pickle`, `eval()`, `yaml.load()`, or other unsafe deserialization
- No dynamic imports based on config values
- Binding types are validated against a fixed list (`BINDING_TYPES`)

**No vulnerability.** Safe JSON parsing throughout.

---

## Security Controls

### Positive Findings

| Control | Location | Description |
|---------|----------|-------------|
| Socket permissions | `ipc.py:37` | `os.chmod(self.path, 0o600)` restricts socket to owner |
| Lock file | `daemon.py:968-981` | `fcntl.flock()` prevents concurrent daemon instances |
| Atomic config writes | `config.py:111-125` | Temp file + `os.replace()` prevents partial writes |
| Binding type validation | `config.py:193-199` | Rejects unknown binding types |
| Device matching | `device.py:27-35` | Requires VID/PID match AND "C100" in name |
| evdev exclusive grab | `pad.py:59` | `dev.grab()` prevents key events leaking |
| Keymap backup | `daemon.py:799-803` | Backups before firmware keymap provision |
| No privilege escalation | systemd unit | User unit with no capabilities or setuid |

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| IPC trusts same-UID | Standard Unix model; additional auth would be theater |
| Shell execution enabled | Core feature; user explicitly configures commands |
| uaccess for device access | Standard for consumer HID; seat-based security |
| User-space installation | No root required; no system-wide attack surface |

---

## Residual Risk

### Accepted Risk: Same-UID Process Trust

Any process running as the user can:

- Connect to the IPC socket and trigger any binding
- Modify `~/.config/c100ctl/config.json` directly
- Read the config to learn bound commands

**Mitigation:** This is inherent to the Unix security model. Users must not run untrusted code as their UID.

### Accepted Risk: Console User Access (Multi-User)

On multi-user systems with `uaccess`, any console user can:

- Access any Keychron HID device (not just their own)
- Access `/dev/uinput` to inject input

**Mitigation:** For high-security multi-user environments, replace `uaccess` with group-based rules. However, such environments typically do not allow users to attach arbitrary USB devices anyway.

### Accepted Risk: Command Execution

Key bindings can execute arbitrary commands. A user who configures a binding like `--command 'rm -rf ~'` will lose their home directory.

**Mitigation:** This is the intended feature. The GUI shows the command before saving. Users are responsible for what they configure.

---

## Recommendations

### Implemented in This PR

1. **Explicit config file permissions** — Set `0o600` on config file and `0o700` on config directory
2. **Explicit backup permissions** — Set `0o700` on backup directory, `0o600` on backup files

### Documentation (No Code Change)

1. Document that c100ctl trusts all same-UID processes (already in README: "Files" section shows socket path)
2. Document multi-user system considerations in README

### Not Recommended

- **IPC authentication tokens** — Would be security theater; same-UID processes can read any token
- **Sandboxing with Flatpak/Snap** — Would break the core feature (running arbitrary commands)
- **Restricting shell execution** — Would break user expectations and documented functionality

---

## Verification

### Tests Run

```bash
python3 -m unittest discover -s tests -v
```

All tests pass (excluding those requiring hardware/evdev module).

### Manual Verification

| Check | Result |
|-------|--------|
| Socket created with 0o600 | ✓ Verified in `ipc.py:37` |
| Config uses atomic write | ✓ Verified in `config.py:111-125` |
| No pickle/eval/yaml | ✓ Only `json.loads()` used |
| No subprocess with shell=True | ✓ All subprocess calls use list args |
| Binding types validated | ✓ `BINDING_TYPES` check in `config.py:194` |
| Device matching requires VID/PID | ✓ `_is_c100_evdev()` in `device.py:27` |
| Lock prevents multiple daemons | ✓ `fcntl.flock()` in `daemon.py:974` |

---

## Appendix: Code References

### IPC Socket Creation

```python
# c100ctl/ipc.py:28-42
def start(self) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    if self.path.exists():
        try:
            self.path.unlink()
        except OSError:
            pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(self.path))
    os.chmod(self.path, 0o600)  # ← Socket restricted to owner
    sock.listen(8)
```

### Command Execution

```python
# c100ctl/actions.py:142-150
def run_command(self, command: str) -> None:
    command = command.strip()
    if not command:
        raise ActionError("empty command")
    if self._omarchy_terminal_alias(command):
        return
    argv = ["bash", "-lc", command]  # ← Intentional shell invocation
    if not self._uwsm_launch(argv[0], extra=argv, terminal=False):
        self._spawn(argv)
```

### Atomic Config Write

```python
# c100ctl/config.py:111-125
def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".c100ctl.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # ← Atomic replace
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```
