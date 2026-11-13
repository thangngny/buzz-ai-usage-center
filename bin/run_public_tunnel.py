import subprocess
import time
import os
import re
import sys
import urllib.request

ROOT = r"C:\Users\Admin\buzz-ai-usage-center"
CLOUDFLARED = r"C:\Users\Admin\.buzz\tools\cloudflared.exe"
LOG_FILE = os.path.join(ROOT, "tunnel.log")
URL_FILE = os.path.join(ROOT, "PUBLIC_URL.txt")
DASHBOARD_SCRIPT = os.path.join(ROOT, "bin", "dashboard.py")
PYTHON_EXE = r"C:\Users\Admin\marketing-ai-system\.venv\Scripts\python.exe"

def check_dashboard():
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False

def ensure_dashboard():
    if not check_dashboard():
        print("Starting dashboard.py...")
        subprocess.Popen(
            [PYTHON_EXE, DASHBOARD_SCRIPT],
            cwd=ROOT,
            creationflags=0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        )
        for _ in range(25):
            time.sleep(1)
            if check_dashboard():
                print("Dashboard is UP on http://127.0.0.1:8787")
                return True
        print("Failed to start dashboard")
        return False
    print("Dashboard already running on http://127.0.0.1:8787")
    return True

def start_tunnel():
    if not os.path.exists(CLOUDFLARED):
        print(f"Error: {CLOUDFLARED} does not exist.")
        return None

    # Kill existing cloudflared if running
    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
    time.sleep(1)

    print("Launching Cloudflare Quick Tunnel...")
    log_fp = open(LOG_FILE, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://127.0.0.1:8787"],
        cwd=ROOT,
        stderr=log_fp,
        stdout=log_fp,
        creationflags=0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    )

    tunnel_url = None
    start_time = time.time()
    
    # Read log file until URL is found
    while time.time() - start_time < 30:
        time.sleep(1)
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                    if matches:
                        tunnel_url = matches[0]
                        break
            except Exception:
                pass

    if tunnel_url:
        print(f"\n==========================================")
        print(f"PUBLIC DASHBOARD URL: {tunnel_url}")
        print(f"LOCAL DASHBOARD URL:  http://127.0.0.1:8787")
        print(f"==========================================\n")
        with open(URL_FILE, "w", encoding="utf-8") as f:
            f.write(tunnel_url.strip() + "\n")
        return tunnel_url
    else:
        print("Failed to obtain Cloudflare tunnel URL within timeout. Check tunnel.log.")
        return None

if __name__ == "__main__":
    if ensure_dashboard():
        start_tunnel()
