# ⚛ AI Native OS

> **By Dheeraj and Dhruv**
>
> An AI-native Linux environment integrating an on-device local multimodal model (**Gemma-3n-E2B-IT**) with kernel-level cgroups v2 resource guarantees, a safeguard interception layer, and a desktop-integrated PyQt6 workspace cockpit running natively on Windows via WSLg.

---

## Architecture Overview

```
Windows 10 Host (DirectX 1.6 vGPU Hardware Acceleration)
  └─ Native Windows Desktop
       ├─ PyQt6 AI Sidebar (Docked to right screen edge, real-time GPU/RAM telemetry, multimodal vision dropzone)
       ├─ Native Linux Terminal (xfce4-terminal / bash, direct command execution)
       ├─ Native Linux File Manager (Thunar, visual file exploration & drag-and-drop into AI)
       └─ Dynamic Cgroups v2 Resource Allocator (Interactive RAM ceiling tuning)
            ▲
            │ (Unix Domain Socket /tmp/nexus.sock + DISPLAY=:0 / WSLg)
            ▼
       WSL2 Debian Subsystem
         ├─ cgroups v2 (allocator binary: dynamic % RAM ceiling, 4GB OS floor)
         ├─ llama.cpp server (Gemma-3n-E2B-IT Q4_K_M + mmproj, CUDA offloaded to RTX 4060)
         ├─ Nexus Socket Server (Unix socket at /tmp/nexus.sock)
         │    ├─ Context Store (SQLite: ~/.local/share/nexus/context.db)
         │    ├─ Safeguard Filter (path-aware, confirmation-gated)
         │    └─ Agent Loop (State machine: THINKING → CONFIRM → EXECUTE)
```

---

## Hardware & System Requirements

- **GPU**: NVIDIA GeForce RTX 4060 Laptop (8 GB VRAM) — hardware hard cap respected.
- **RAM**: 32 GB RAM (24 GB allocated to WSL2).
- **Host OS**: Windows 10 (WSL2 with WSLg vGPU acceleration).
- **Target Guest**: Debian Linux (tested on Debian 12 Bookworm).

---

## 1. Quick Start (1-Click Launch)

From Windows PowerShell (Run as Administrator or standard user):

```powershell
.\run_antigravity.ps1
```

Or double-click `run_antigravity.bat`.

This automatically:
1. Pings the Debian WSL2 kernel.
2. Synchronizes source code into `~/antigravity`.
3. Initializes the Cgroups v2 dynamic resource manager (`/sys/fs/cgroup/nexus`).
4. Starts `llama-server` with CUDA acceleration on the RTX 4060.
5. Launches the PyQt6 AI Sidebar directly onto your Windows desktop via WSLg (`DISPLAY=:0`).

---

## 2. Interactive OS Cockpit Features

- **📟 Integrated Linux Terminal**: Click the **Terminal** button in the sidebar to spawn an interactive bash terminal directly on your Windows desktop.
- **📁 Integrated File Manager**: Click the **Files** button to open the Thunar file manager, allowing visual directory navigation and drag-and-drop into the AI.
- **⚙️ Dynamic Cgroups v2 Allocator**: Click the **Allocator** button to open a live slider dialog. Dynamically adjust the RAM ceiling (e.g., 50% to 90% of host RAM) without rebooting.
- **⚡ Direct Shell Command Runner**: Type `/run <command>` (or `/sh <command>`) in the chat prompt. The command is evaluated by the safeguard engine and executed live with real-time output in the sidebar.
- **📷 Multimodal Vision**: Drag and drop any image (`.png`, `.jpg`, `.webp`) from Windows Explorer or Thunar directly into the sidebar to query Gemma-3n multimodal reasoning.
- **🛡️ Safeguard Protection**: Dangerous commands (`rm -rf /`, `/etc`, `/usr`) are blocked automatically. Modifying files prompts visual `[Authorize]` and `[Reject]` approval cards.
- **📊 Real-time Telemetry**: Live gauges for Cgroup RAM usage, RTX 4060 VRAM, GPU temperatures, and token throughput.

---

## 3. Debian WSL2 Manual Setup

If configuring a clean Debian WSL2 machine from scratch:

### 3.1 Install Base Dependencies & GUI Tools
```bash
cd ~/antigravity
make deps
sudo apt install -y xfce4-terminal thunar
```

### 3.2 Build C Allocator & CUDA-Enabled llama.cpp
```bash
make build
```

### 3.3 Download Gemma-3n Model & Multimodal Projector
```bash
make model
```
Downloads:
- `gemma-3n-e2b-it-q4_k_m.gguf` (quantized weights, ~1.5–2 GB VRAM footprint)
- `mmproj-google_gemma-3n-e2b-it-f16.gguf` (multimodal vision projector)

### 3.4 Launch Session
```bash
./start.sh
```

---

## 4. Diagnostics & Deep Logging

Consolidated cross-platform log readers are included:

- **Windows PowerShell**:
  ```powershell
  # View all subsystem logs
  .\read_logs.ps1

  # View specific component log
  .\read_logs.ps1 -Target llama
  .\read_logs.ps1 -Target socket
  .\read_logs.ps1 -Target sidebar

  # Follow live master log
  .\read_logs.ps1 -Follow
  ```

- **Linux / WSL**:
  ```bash
  ./read_logs.sh
  ```
