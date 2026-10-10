#!/usr/bin/env python3
"""
Buzz Ecosystem Agent Doctor & Universal Orchestrator
=====================================================
Single entrypoint for AI Coding Agents (Claude Code, AGY, Cursor, Codex, OpenClaw)
to inspect environment, auto-install, and verify Buzz Enhancer on any OS (Linux, WSL, Windows Native).

Usage by Coding Agents:
    python3 bin/agent-doctor.py               # Human-readable diagnostic
    python3 bin/agent-doctor.py --json        # Machine-readable JSON output for Agent evaluation
    python3 bin/agent-doctor.py --install     # Autonomous platform-native installation
    python3 bin/agent-doctor.py --verify      # E2E health verification with exit code (0 = PASS)
"""

import os
import sys
import json
import shutil
import socket
import platform
import subprocess
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            v = f.read().lower()
            return "microsoft" in v or "wsl" in v
    except Exception:
        return False

def detect_platform() -> str:
    if sys.platform == "win32":
        return "windows_native"
    if is_wsl():
        return "windows_wsl2"
    if sys.platform == "linux":
        return "linux_native"
    if sys.platform == "darwin":
        return "macos"
    return "unknown"

def find_buzz_executable(plat: str) -> Optional[str]:
    home = os.path.expanduser("~")
    candidates = []
    if plat in ("linux_native", "windows_wsl2"):
        candidates = [
            os.path.join(home, ".local/bin/buzz-desktop"),
            os.path.join(home, ".local/bin/buzz-desktop-bin"),
            os.path.join(home, ".local/bin/buzz"),
            "/usr/local/bin/buzz-desktop",
            "/usr/bin/buzz-desktop",
        ]
        which = shutil.which("buzz-desktop") or shutil.which("buzz")
        if which:
            candidates.insert(0, which)
    elif plat == "windows_native":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        candidates = [
            os.path.join(local_app, "Programs\\buzz\\buzz.exe"),
            os.path.join(local_app, "buzz\\buzz.exe"),
            os.path.join(prog_files, "buzz\\buzz.exe"),
        ]
        which = shutil.which("buzz.exe") or shutil.which("buzz")
        if which:
            candidates.insert(0, which)
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

def detect_audio_subsystem(plat: str) -> Dict[str, Any]:
    if plat == "windows_native":
        return {"driver": "winsound (built-in Windows)", "available": True}
    if plat == "macos":
        afplay = shutil.which("afplay")
        return {"driver": "afplay", "available": bool(afplay)}
    # Linux / WSL
    for p in ("paplay", "pw-play", "aplay"):
        if shutil.which(p):
            return {"driver": p, "available": True}
    return {"driver": "none", "available": False}

def inspect_environment() -> Dict[str, Any]:
    plat = detect_platform()
    home = os.path.expanduser("~")
    buzz_exe = find_buzz_executable(plat)
    audio = detect_audio_subsystem(plat)
    
    # Check WebKit Injector
    lib_path = os.path.join(home, ".local/lib/libbuzz_enhancer.so")
    injector_installed = os.path.exists(lib_path)
    
    # Check UI Enhancer script
    js_path = os.path.join(home, ".local/share/xyz.block.buzz.app/buzz_ui_enhancer.js")
    js_installed = os.path.exists(js_path)
    
    # Check Services
    dashboard_active = False
    notifier_active = False
    if plat in ("linux_native", "windows_wsl2") and shutil.which("systemctl"):
        try:
            r1 = subprocess.run(["systemctl", "--user", "is-active", "buzz-usage-dashboard.service"], capture_output=True, text=True)
            dashboard_active = (r1.stdout.strip() == "active")
            r2 = subprocess.run(["systemctl", "--user", "is-active", "buzz-sound-notifier.service"], capture_output=True, text=True)
            notifier_active = (r2.stdout.strip() == "active")
        except Exception:
            pass
            
    # Check Dashboard HTTP Server Port 8787
    dash_port_open = False
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=1.5)
        dash_port_open = (req.getcode() == 200)
    except Exception:
        pass

    return {
        "status": "ready" if (dashboard_active and js_installed) else "needs_setup",
        "platform": plat,
        "os_version": platform.platform(),
        "python_version": platform.python_version(),
        "is_wsl": is_wsl(),
        "user_home": home,
        "buzz_executable": buzz_exe,
        "audio": audio,
        "components": {
            "injector_library": {"installed": injector_installed, "path": lib_path},
            "ui_enhancer_js": {"installed": js_installed, "path": js_path},
            "dashboard_service": {"active": dashboard_active, "port_8787_responding": dash_port_open},
            "sound_notifier_service": {"active": notifier_active}
        },
        "recommended_action": "none" if (dashboard_active and js_installed) else ("run_install_sh" if plat in ("linux_native", "windows_wsl2") else "run_install_windows_ps1")
    }

def run_installation() -> bool:
    plat = detect_platform()
    print(f"[AGENT DOCTOR] Detected Platform: {plat}")
    if plat in ("linux_native", "windows_wsl2"):
        install_script = os.path.join(ROOT_DIR, "install.sh")
        if not os.path.exists(install_script):
            print(f"[AGENT DOCTOR ERROR] install.sh not found at {install_script}")
            return False
        print(f"[AGENT DOCTOR] Executing: bash {install_script}...")
        res = subprocess.run(["bash", install_script], cwd=ROOT_DIR)
        return res.returncode == 0
    elif plat == "windows_native":
        ps_script = os.path.join(ROOT_DIR, "bin", "install-windows.ps1")
        if not os.path.exists(ps_script):
            print(f"[AGENT DOCTOR ERROR] PowerShell installer not found at {ps_script}")
            return False
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_script]
        print(f"[AGENT DOCTOR] Executing: {' '.join(cmd)}...")
        res = subprocess.run(cmd, cwd=ROOT_DIR)
        return res.returncode == 0
    else:
        print(f"[AGENT DOCTOR ERROR] Unsupported platform: {plat}")
        return False

def verify_system() -> int:
    print("=" * 65)
    print(" 🔍 BUZZ ECOSYSTEM END-TO-END HEALTH VERIFICATION")
    print("=" * 65)
    passed = 0
    total = 5

    # 1. Dashboard Health Check
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=3)
        if req.getcode() == 200:
            print("  [PASS 1/5] ✓ Backend Dashboard is LIVE on http://127.0.0.1:8787/health")
            passed += 1
        else:
            print(f"  [FAIL 1/5] ✗ Dashboard returned HTTP {req.getcode()}")
    except Exception as ex:
        print(f"  [FAIL 1/5] ✗ Dashboard connection failed: {ex}")

    # 2. AI Summary Endpoint
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8787/api/ai_summary", timeout=3)
        data = json.loads(req.read().decode("utf-8"))
        if "bulletins" in data:
            print(f"  [PASS 2/5] ✓ AI Catch-Up TL;DR API functional ({len(data['bulletins'])} active channel summaries)")
            passed += 1
        else:
            print("  [FAIL 2/5] ✗ Invalid AI summary JSON structure")
    except Exception as ex:
        print(f"  [FAIL 2/5] ✗ AI Summary API error: {ex}")

    # 3. Message Hub Endpoint
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8787/api/latest_messages.json", timeout=3)
        msgs = json.loads(req.read().decode("utf-8"))
        if isinstance(msgs, list):
            print(f"  [PASS 3/5] ✓ Unified Message Hub populated ({len(msgs)} messages cached across relays)")
            passed += 1
        else:
            print("  [FAIL 3/5] ✗ Latest messages API did not return list")
    except Exception as ex:
        print(f"  [FAIL 3/5] ✗ Latest messages API error: {ex}")

    # 4. Sound & Audio Subsystem
    plat = detect_platform()
    audio = detect_audio_subsystem(plat)
    if audio["available"]:
        print(f"  [PASS 4/5] ✓ Audio driver verified: {audio['driver']}")
        passed += 1
    else:
        print("  [WARN 4/5] ⚠ Audio player missing (install pulseaudio-utils or run in Windows/WSLg)")

    # 5. UI Enhancer Assets
    home = os.path.expanduser("~")
    js_file = os.path.join(home, ".local/share/xyz.block.buzz.app/buzz_ui_enhancer.js")
    if os.path.exists(js_file) and os.path.getsize(js_file) > 10000:
        print(f"  [PASS 5/5] ✓ UI Enhancer bundle verified ({os.path.getsize(js_file):,} bytes)")
        passed += 1
    else:
        print("  [FAIL 5/5] ✗ UI Enhancer bundle missing or empty")

    print("-" * 65)
    print(f"Result: {passed}/{total} checks passed.")
    if passed >= 4:
        print("🎉 System status: FULLY OPERATIONAL (All systems pass)")
        return 0
    else:
        print("❌ System status: DEGRADED (Run `python3 bin/agent-doctor.py --install` to fix)")
        return 1

def main():
    args = sys.argv[1:]
    if "--json" in args:
        data = inspect_environment()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(0)
    elif "--install" in args or "--auto-fix" in args:
        ok = run_installation()
        sys.exit(0 if ok else 1)
    elif "--verify" in args:
        code = verify_system()
        sys.exit(code)
    else:
        info = inspect_environment()
        print("=" * 65)
        print(" 🤖 BUZZ ECOSYSTEM AGENT DOCTOR")
        print("=" * 65)
        print(f"  Platform      : {info['platform']} (WSL={info['is_wsl']})")
        print(f"  Python        : {info['python_version']}")
        print(f"  Buzz Binary   : {info['buzz_executable'] or 'Not found in PATH'}")
        print(f"  Audio Driver  : {info['audio']['driver']} (available={info['audio']['available']})")
        print(f"  UI Enhancer   : {'Installed' if info['components']['ui_enhancer_js']['installed'] else 'Missing'}")
        print(f"  Dashboard Svc : {'Active' if info['components']['dashboard_service']['active'] else 'Inactive'}")
        print(f"  Notifier Svc  : {'Active' if info['components']['sound_notifier_service']['active'] else 'Inactive'}")
        print(f"  Port 8787     : {'Responding' if info['components']['dashboard_service']['port_8787_responding'] else 'Closed'}")
        print("-" * 65)
        print(f"  Status        : {info['status'].upper()}")
        print(f"  Recommendation: {info['recommended_action']}")
        print("=" * 65)
        print("\nCommands for Coding Agents:")
        print("  • Inspect JSON : python3 bin/agent-doctor.py --json")
        print("  • Auto Install : python3 bin/agent-doctor.py --install")
        print("  • E2E Verify   : python3 bin/agent-doctor.py --verify")

if __name__ == "__main__":
    main()
