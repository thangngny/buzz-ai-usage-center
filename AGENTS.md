# 🤖 AGENT DIRECTIVE & RUNBOOK — BUZZ ECOSYSTEM SUITE

> **For AI Coding Agents (Claude Code, Antigravity/AGY, Cursor, Codex, OpenClaw, Hermes, Roo)**  
> This file is the authoritative specification and operational manual for this repository. When you clone or open this project, read and execute according to these instructions.

---

## ⚡ 1. AGENT QUICKSTART (ZERO-THINKING BOOTSTRAP)

Whenever you are asked to install, repair, test, or inspect this project on any machine, execute these deterministic commands:

```bash
# Step 1: Diagnose environment and detect OS/components (returns machine-readable JSON)
python3 bin/agent-doctor.py --json

# Step 2: If status == "needs_setup", run autonomous platform-native installer
python3 bin/agent-doctor.py --install

# Step 3: Run comprehensive End-to-End health check (exit code 0 = 100% PASS)
python3 bin/agent-doctor.py --verify
```

---

## 🏛️ 2. SYSTEM ARCHITECTURE & COMPONENTS

This repository houses the complete **Buzz Desktop Enhancer Suite** + **AI Usage Center**:

| Component | Path | Role / Platform |
| :--- | :--- | :--- |
| **Agent Doctor** | `bin/agent-doctor.py` | Universal diagnostic, auto-installer, and E2E verifier. |
| **Linux/WSL Installer** | `install.sh` | 1-Click bash installer for Linux and Windows WSL2. |
| **Windows Installer** | `bin/install-windows.ps1` | PowerShell installer for Windows Native. |
| **Frontend UI Enhancer** | `desktop-enhancer/buzz_ui_enhancer.js` | Glassmorphic Raycast Drawer (`Alt+M`), AI TL;DR (`Alt+S`), Quick Reply chips, Active Viewport Auto-read, Spotlight Aura. |
| **Real-time Notifier** | `desktop-enhancer/buzz_sound_notifier.py` | Multi-relay WebSocket Nostr daemon with `paplay` (Linux) / `winsound` (Windows) and desktop notifications. |
| **WebKit Injector** | `desktop-enhancer/injector/` | C source (`libbuzz_enhancer.c`), Makefile, and precompiled `libbuzz_enhancer.so` (`LD_PRELOAD`). |
| **Audio Library** | `desktop-enhancer/sounds/` | Clean sound assets (`elevenlabs_thang.wav`, `mention.wav`, `pop.wav`...). |
| **Backend Daemon** | `bin/dashboard.py` | Local HTTP server (`127.0.0.1:8787`), Unified Message Hub, AI Catch-up summary generator, and RPC bridge. |
| **Systemd Services** | `systemd/` | User unit definitions using dynamic `%h` specifiers. |

---

## 🛡️ 3. CORE OPERATING PRINCIPLES FOR AGENTS

1. **Non-Invasive Integration**:
   - Never overwrite or patch the original Buzz executable (`buzz-desktop-bin` on Linux, `buzz.exe` on Windows).
   - On Linux/WSL, we inject via `LD_PRELOAD="/path/to/libbuzz_enhancer.so"`.
   - On Windows, we use WebView2 DevTools Protocol / DLL proxy.
2. **Universal Paths (Zero Hardcoded Usernames)**:
   - Always use `os.path.expanduser("~")`, `$HOME`, `%USERPROFILE%`, or systemd `%h` / `%U`.
   - Never write hardcoded paths like `/home/ncthang/` into repository code.
3. **Data Security & Privacy**:
   - `usage.db`, `.env`, Nostr private keys, and API credentials must NEVER be committed to version control.
   - Always check `git status` and `git diff` before committing.
4. **Notification Scope**:
   - Notifications must alert for **ALL human messages across ANY community/channel**, not just DMs or mentions.
   - Mentions and DMs trigger VIP chime (`sound_mention`), while standard community messages trigger clean chime (`sound_message`).
5. **Port 8787 Port Invariant**:
   - `dashboard.py` MUST maintain `allow_reuse_address = True` in `DashboardServer` to prevent `[Errno 98] Address already in use` upon fast daemon restarts.

---

## 🔍 4. PLATFORM-SPECIFIC EXECUTION MATRIX

### A. Linux & Windows WSL2 (Recommended)
- **Runtime:** Python 3.10+, glibc, GCC (optional, precompiled `.so` available).
- **Execution:**
  ```bash
  ./install.sh
  ```
- **Service Management:**
  ```bash
  systemctl --user restart buzz-usage-dashboard.service buzz-sound-notifier.service
  ```

### B. Windows Native (Pure Windows)
- **Runtime:** Python 3.10+ for Windows.
- **Execution:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\bin\install-windows.ps1
  ```
- **Audio Subsystem:** Uses built-in `winsound.PlaySound()`.
- **Notifications:** Uses Windows PowerShell Toast Notification API.

---

## 🧪 5. VERIFICATION COMMANDS

After making any code changes, always run:

```bash
# 1. Check Python syntax
python3 -m py_compile bin/dashboard.py desktop-enhancer/buzz_sound_notifier.py

# 2. Check JavaScript syntax
node -c desktop-enhancer/buzz_ui_enhancer.js

# 3. Check Bash scripts syntax
bash -n install.sh uninstall.sh

# 4. Run Doctor verification
python3 bin/agent-doctor.py --verify
```
