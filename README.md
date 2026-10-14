# ⚛ AI Native OS

> **By Dheeraj and Dhruv**
>
> An AI-native Linux environment integrating an on-device local multimodal model (**Gemma-3n-E2B-IT**) with kernel-level cgroups v2 resource guarantees, a safeguard interception layer, and a desktop-integrated PyQt6 telemetry sidebar.

---

## Architecture Overview

```
Windows 10 Host
  └─ Remote Desktop Connection (mstsc.exe → localhost:3390)
       └─ WSL2 Debian (xrdp + XFCE4 Desktop)
            ├─ cgroups v2 (allocator binary: 70% RAM ceiling, 4GB OS floor)
            ├─ llama.cpp server (Gemma-3n-E2B-IT Q4_K_M + mmproj, CUDA offloaded to RTX 4060)
            ├─ Nexus Socket Server (Unix socket at /tmp/nexus.sock)
            │    ├─ Context Store (SQLite: ~/.local/share/nexus/context.db)
            │    ├─ Safeguard Filter (path-aware, confirmation-gated)
            │    └─ Agent Loop (State machine: THINKING → CONFIRM → EXECUTE)
            └─ PyQt6 Sidebar UI (Live telemetry, chat, image drag & drop, system tray)
```

---

## Hardware & System Requirements

- **GPU**: NVIDIA GeForce RTX 4060 Laptop (8 GB VRAM) — hardware hard cap respected.
- **RAM**: 32 GB RAM (24 GB allocated to WSL2).
- **Host OS**: Windows 10 (WSL2 with NAT networking and xrdp for full GUI).
- **Target Guest**: Debian Linux (tested on Debian 12 Bookworm).

---

## 1. Windows Setup

### 1.1 `.wslconfig`
Create or update `%USERPROFILE%\.wslconfig` with:

```ini
[wsl2]
networkingMode = nat
memory         = 24GB
swap           = 4GB
processors     = 6
gpuSupport     = true

[boot]
systemd = true
```

Restart WSL:
```powershell
wsl --shutdown
```

### 1.2 Copy Source Files from Windows to WSL2

From PowerShell:
```powershell
wsl -d Debian -- bash -c "mkdir -p ~/nexus && cp -r '/mnt/c/Users/Dheeraj Sutram/Documents/projects/OS/AI OS idk/antigravity/'* ~/nexus/"
```

*(Note: Always build and execute within `~/nexus` on the native Linux ext4 filesystem rather than directly under `/mnt/c/` for maximum performance.)*

---

## 2. Debian WSL2 Setup

Inside your Debian WSL2 terminal:

### 2.1 Install Base Dependencies & Desktop Environment
```bash
cd ~/nexus
make deps
```

### 2.2 Configure xrdp for XFCE4
```bash
# Configure port 3390 to avoid conflict with host Windows RDP
sudo sed -i 's/^port=3389/port=3390/' /etc/xrdp/xrdp.ini

# Set default desktop session
echo "xfce4-session" > ~/.xsession
chmod +x ~/.xsession

# Start xrdp service
sudo /etc/init.d/xrdp start
```

### 2.3 Build C Allocator & CUDA-Enabled llama.cpp
```bash
make build
```

### 2.4 Download Gemma-3n Model & Multimodal Projector
```bash
make model
```

This downloads:
- `gemma-3n-e2b-it-q4_k_m.gguf` (quantized weights, ~1.5–2 GB VRAM footprint)
- `mmproj-google_gemma-3n-e2b-it-f16.gguf` (multimodal vision projector)

---

## 3. Running Nexus

### 3.1 Connect via Remote Desktop
1. On Windows, press `Win + R`, type `mstsc`, press Enter.
2. In the Computer field, enter: `localhost:3390`.
3. Log in with your Debian username and password.
4. You are now in the XFCE4 desktop!

### 3.2 Launch Developer Session
Open a terminal inside the XFCE desktop and run:
```bash
cd ~/nexus
make run
```
This initializes the cgroup allocator, starts the CUDA llama-server, spins up the socket bridge, and displays the PyQt6 sidebar docked to the right of your screen.

### 3.3 Or Install as Systemd User Services
To have Nexus start automatically on boot:
```bash
cd ~/nexus
make install
```

---

## 4. Key Features

- **Safe Command Execution**: Dangerous commands like recursive deletes (`rm -rf`) or system file modifications (`/etc`, `/usr`, `/boot`) are blocked. Safe user-space file modifications require interactive confirmation in the UI.
- **Multimodal Understanding**: Drag and drop any image directly onto the sidebar to query Gemma-3n with vision input.
- **Live Telemetry**: Real-time monitoring of RAM usage against cgroup quotas, GPU VRAM, CPU/GPU temperatures, and prompt/completion token counters.
- **Session Controls**: Type `/clear` to reset chat context, or `/unlock` to reset safety locks.

---

## 5. Known WSL2 & XRDP Troubleshooting (The "Airlock" Fixes)

Getting a full desktop environment running over XRDP inside WSL2 presents several extreme edge-case bugs due to WSL2's hybrid architecture. These have been solved in `run_nexus.bat` (and launcher scripts) and `dot_xsession.sh`, but here is a record of what fails natively:

1. **The Systemd/D-Bus Collision (Crash on Boot)**
   - **Bug**: `xfconfd` crashes instantly with `invalid (NULL) pointer instance`. WSL2's systemd integration breaks the standard user-level `dbus` socket setup that XFCE expects. 
   - **Solution**: We explicitly bypass standard X session startup. The launcher creates a strictly sandboxed `~/.xsession` file that unsets global dbus addresses and enforces specific XDG directories before booting `startxfce4`.

2. **The "Root Ownership" Config Trap**
   - **Bug**: If `sudo` or root commands create the user's `~/.config` directory first, XFCE is denied write access and the entire desktop boot sequence panics.
   - **Solution**: The `.xsession` script forcefully isolates XFCE config directories, and if this happens, running `sudo chown -R $USER:$USER ~` fixes the permission block.

3. **The Wayland Poison Pill**
   - **Bug**: `xfce4-panel` and `xfdesktop` log `Wayland detected without layer-shell support` and instantly terminate.
   - **Cause**: Windows 11 injects WSLg (a Wayland compositor) into the environment by forcefully setting `WAYLAND_DISPLAY=wayland-0` globally. When starting our X11 XRDP session, the GTK3 applications falsely detect Wayland, try to use it, fail to negotiate the layer-shell protocols, and crash.
   - **Solution**: In `dot_xsession.sh`, we use the absolute sledgehammer: `unset WAYLAND_DISPLAY` AND `export GDK_BACKEND=x11`. This forces GTK to blind itself to WSLg and strictly use X11.

4. **The ICE Socket Panic**
   - **Bug**: `_IceTransmkdir: ERROR: euid != 0,directory /tmp/.ICE-unix will not be created.` leading to session failure.
   - **Solution**: Similar to the X11 socket, the `.ICE-unix` directory must exist with `1777` permissions for Inter-Client Exchange (ICE) to work. The Windows launcher script automatically creates `mkdir -p /tmp/.ICE-unix; chmod 1777 /tmp/.ICE-unix` via WSL before connecting.

5. **The Pre-Boot Environment Leak (startwm.sh)**
   - **Bug**: `xfce4-session` successfully starts but terminates itself precisely 2.5 seconds later.
   - **Cause**: We initially tried to unset WSLg's `XDG_RUNTIME_DIR` in `~/.xsession`. However, Debian's global `/etc/xrdp/startwm.sh` executes several system-level session scripts *before* evaluating the user's local `.xsession`. These system scripts inherit the poisoned Wayland variables, silently fail during DBus registration, and cause the X server to abort the session.
   - **Solution**: We globally patched `/etc/xrdp/startwm.sh` to forcefully `unset DBUS_SESSION_BUS_ADDRESS`, `unset WAYLAND_DISPLAY`, and `unset XDG_RUNTIME_DIR` at the very top of the script, guaranteeing all downstream X11 scripts execute in a pristine environment.

6. **The Accessibility Bus (AT-SPI) Timeout**
   - **Bug**: The log is spammed with `AT-SPI: Error retrieving accessibility bus address: org.freedesktop.DBus.Error.ServiceUnknown`.
   - **Cause**: Every single GTK component attempts to connect to the accessibility toolkit on startup. Because we isolated the DBus environment, this service doesn't exist. Some components block waiting for a response, triggering session watchdogs.
   - **Solution**: We added `export NO_AT_BRIDGE=1` to `/etc/xrdp/startwm.sh`. This shuts off accessibility bus scanning in GTK3 applications globally.

7. **The Color Depth Desync (xserverbpp)**
   - **Bug**: The session terminates instantly, and `xrdp-sesman.log` reports `trans_check_wait_objs failed, removing trans`.
   - **Cause**: Windows Remote Desktop (`mstsc.exe`) often natively negotiates 24-bit or 32-bit color. If you explicitly force `xserverbpp=32` in `/etc/xrdp/xrdp.ini`, but the Linux `xorgxrdp` driver or client only negotiates 24-bit, the backend Xorg server segfaults on the first frame render and violently drops the socket.
   - **Solution**: We strictly enforce `max_bpp=32` but keep `xserverbpp=24` (the safe fallback default) in `/etc/xrdp/xrdp.ini` to guarantee cross-compatibility with the Windows compositor.

8. **The Zombie Process Lockout**
   - **Bug**: After a crash or a forced RDP disconnect, subsequent login attempts result in a black screen or instant connection drops.
   - **Cause**: `xrdp`, `Xorg`, and `dbus-daemon` processes from the previous failed session get orphaned (zombified) because WSL2's systemd doesn't properly track and reap their cgroups. They hold locks on `/tmp/.X11-unix/X10`.
   - **Solution**: The launcher now contains a dedicated zombie execution squad: `pkill -9 xrdp; pkill -9 xfce4; rm -f /tmp/.X*-lock /tmp/.X11-unix/X10`, which guarantees a perfectly pristine, cold-boot state before every connection.

---

## 6. October 2026 Stability Fixes

Recent updates applied to resolve a major session crash and improve agent stability:

- **D-Bus XRDP 5-Second Crash Fixed:** `dot_xsession.sh` now correctly wraps `startxfce4` with `dbus-run-session` and provides a valid `XDG_RUNTIME_DIR`. This solves the issue where the XFCE desktop would appear for 5 seconds and abruptly terminate due to missing IPC buses.
- **Removed Duplicate Configurations:** Deleted `startwm.sh` and `xsession_temp.sh` as they were causing configuration collisions with the primary `.xsession` flow.
- **Race Condition Mitigations:** `start.sh` no longer relies on hardcoded `sleep 1` timers. It loops and explicitly waits for `llama-server` health endpoints and the unix socket to become fully ready.
- **Robust SQLite Context:** The SQLite `context.db` now uses `WAL` (Write-Ahead Logging) mode with timeouts to safely allow concurrent Python async worker connections.
- **UI Thread Safety:** Telemetry data (like GPU memory parsing) is now polled in a PyQt6 background `QThread` rather than freezing the main UI event loop every 2 seconds. Screen geometry and system tray access are now safely null-checked for headless scenarios.

---

## 7. Deep Diagnostics & Modern SWE Architecture (Cgroup v2 & Process Lifecycle)

In-depth log analysis across subsystem sinks (`start.log`, `nexus-allocator.log`, `xsession.log`) revealed critical architectural and kernel-level constraints, which were solved to production-grade software engineering standards:

### 7.1 Cgroup v2 "No Internal Processes" Rule
* **The Root Cause:** In Linux cgroups v2 (`Documentation/admin-guide/cgroup-v2.rst`), an internal cgroup with controllers enabled in `cgroup.subtree_control` is strictly forbidden from hosting processes in its own `cgroup.procs`. When `allocator.c` wrote `+memory +pids` to `/sys/fs/cgroup/nexus/cgroup.subtree_control`, the kernel locked the group, actively rejecting any PID write with `EBUSY` (*Device or resource busy*).
* **The SWE Solution:** Redesigned `allocator.c` as a pure **leaf node**. The parent root cgroup (`/sys/fs/cgroup`) already delegates `cpu memory pids`. Leaving `cgroup.subtree_control` empty in `/sys/fs/cgroup/nexus` allows child processes to attach directly to `cgroup.procs` while enforcing dynamic `memory.max` (70% total RAM ceiling) and `memory.high` limits.

### 7.2 Native Cgroup Process Attachment & Elimination of `cgexec -u`
* **The Root Cause:** `start.sh` previously invoked `sudo cgexec -g memory:nexus -u $USER`. However, `cgexec` has no `-u` argument, resulting in `cgexec: invalid option -- 'u'` and an immediate startup crash of `llama-server`.
* **The SWE Solution:** Replaced brittle invocation wrappers with a clean `assign_cgroup(pid, name)` helper function. Processes (`llama-server`, `socket_server.py`, `sidebar.py`) start cleanly under their native user environment, and their PIDs are registered with `/sys/fs/cgroup/nexus/cgroup.procs` immediately upon spawn. Additionally, robust signal traps (`INT`, `TERM`, `EXIT`) guarantee graceful process termination and socket unlinking.

### 7.3 Modernized Systemd User Services
* **Decoupled from `cgexec`:** Replaced deprecated `cgexec` prefixes in [llama-server.service](systemd/llama-server.service) and [nexus-agent.service](systemd/nexus-agent.service) with native systemd lifecycle management via `ExecStartPost=/bin/sh -c 'echo $MAINPID > /sys/fs/cgroup/nexus/cgroup.procs'`.
* **XRDP Display Alignment:** [nexus-sidebar.service](systemd/nexus-sidebar.service) now defaults to `DISPLAY=:10.0` and `XDG_RUNTIME_DIR=/run/user/1000` to seamlessly match the xrdp desktop display server instead of conflicting with `:0`.

### 7.4 Deep Structured Logging Infrastructure
To enable full observability and telemetry across all Python services, C binaries, and shell wrappers:
* **Centralized Logger (`logger.py`):** Configures dual-sink rotating log files with timestamped, millisecond-accurate structured formatting (`[TIMESTAMP] [LEVEL] [PID:THREAD] [MODULE:FILE:LINE] - MSG`).
* **Multi-Sink Routing:**
  - Per-component logs: `~/.local/share/nexus/logs/<component>.log` (5 MB rotating).
  - Master system log: `~/.local/share/nexus/logs/nexus_master.log` (10 MB rotating).
  - Stderr stream output for real-time terminal review.
* **Global Crash Hooks:** Unhandled exceptions and background thread panics are automatically trapped and dumped to master logs with full stack traces.
* **Cross-Platform Log Readers:** Provided `read_logs.sh`, `read_logs.ps1`, and `read_logs.bat` for one-command consolidated log tailing from both Windows PowerShell and Linux terminals.

