#!/usr/bin/env python3
"""
AI Usage Center — LIVE Local Dashboard for Buzz AI Usage Control (v2.1 Enterprise).
Completely localized in Vietnamese with premium, data-focused UI/UX.

- Binds to 127.0.0.1:8787 ONLY (never 0.0.0.0).
- Pure standard library Python http.server, zero heavy external runtime dependencies.
- Read-only against the ledger except explicit owner actions (assign allowance profile, adjust policy numbers, ack alert).
- Contains no secrets: no private keys, no tokens, no account emails, no prompt text.
"""

import datetime as dt
import html
import json
import os
import socket
import subprocess
import re
import sys
import threading
import time
import datetime
import sqlite3
import urllib.parse
from typing import Any, Dict, List, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import analytics  # noqa: E402
import i18n  # noqa: E402
import ledger  # noqa: E402
import ui_components as ui  # noqa: E402

HOST = "127.0.0.1"
PORT = 8787
ICT = ZoneInfo("Asia/Ho_Chi_Minh")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _funnel_url() -> str:
    """8443 = dashboard. Khong dung 443 (dim0/fairies va site trungthu)."""
    env = (os.environ.get("BUZZ_FUNNEL_URL") or "").strip()
    if env:
        return env.rstrip("/")
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=8,
        )
        name = ((json.loads(r.stdout or "{}").get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
        if name:
            return "https://%s:8443" % name
    except Exception:
        pass
    return "https://trungthu.tailc0eb7b.ts.net:8443"


FUNNEL_URL = _funnel_url()
LOCAL_URL = "http://127.0.0.1:8787"

PROVIDER_NAMES = {
    "codex-openai": "ChatGPT",
    "codex-sales": "ChatGPT · sales",
    "codex-creative": "ChatGPT · creative",
    "codex-creative-lead": "ChatGPT · creative-lead",
    "codex-pm": "ChatGPT · PM/MARCOM",
    "codex-pm-lead": "ChatGPT · PM lead",
    "codex-ollama": "Ollama Cloud",
    "codex-t2": "Ollama Cloud T2",
    "claude-ollama": "Claude · Ollama",
    "hermes-pm": "Hermes PM",
    "hermes-t2": "Hermes T2",
    "hermes-ketoan": "Hermes kế toán",
    "hermes-creative": "Hermes creative",
    "hermes-hr": "Hermes HR",
    "hermes-ba": "Hermes BA",
    "hermes-dev": "Hermes Dev",
}

_MODEL_CACHE = {"at": 0.0, "by_backend": {}, "by_agent": {}}
REFRESH = {"last": 0.0, "ok": True, "msg": "", "running": False}
COLLECT = {"last": 0.0, "ok": True, "msg": "", "running": False, "n_req": None}
JOB = threading.Lock()
QUOTA_EVERY = 300
COLLECT_EVERY = 600
QUOTA_TIMEOUT = 300
# > buzz_collector.WSL_TIMEOUT (480) + 2 lan cho khoa SQLite 60 s: dashboard giet
# collector truoc thi `finally` cua no khong chay (file tam + tien trinh WSL mo coi).
COLLECT_TIMEOUT = 780


def _child_run(args, timeout):
    """Chay quota/collector: con ghi UTF-8, cha doc UTF-8. Dashboard do watchdog
    bat khong co PYTHONIOENCODING -> mac dinh cp1252, ten tieng Viet lam vo pipe."""
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )


def live_models() -> dict:
    now = time.time()
    if now - _MODEL_CACHE["at"] < 30:
        return _MODEL_CACHE
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT a.backend_kind, r.agent_id, r.model, MAX(r.started_at) AS ts "
            "FROM requests r JOIN agents a ON a.agent_id = r.agent_id "
            "WHERE r.model IS NOT NULL AND r.model != '' "
            "GROUP BY a.backend_kind, r.agent_id, r.model"
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    best_b, best_a = {}, {}
    for r in rows:
        kind, aid, model, ts = r[0], r[1], r[2], r[3] or 0
        if ts >= best_b.get(kind, (0, ""))[0]:
            best_b[kind] = (ts, model)
        if ts >= best_a.get(aid, (0, ""))[0]:
            best_a[aid] = (ts, model)
    _MODEL_CACHE.update(
        at=now,
        by_backend={k: v[1] for k, v in best_b.items()},
        by_agent={k: v[1] for k, v in best_a.items()},
    )
    return _MODEL_CACHE


def backend_label(kind: str) -> str:
    """Nha cung cap + model THAT (luot moi nhat), khong ghi cung gpt-oss."""
    name = PROVIDER_NAMES.get(kind) or kind or "?"
    model = live_models()["by_backend"].get(kind)
    return ("%s · %s" % (name, model)) if model else name


def owner_display_name() -> str:
    pk = (ledger.get_setting("owner_pubkeys") or "").split(",")[0].strip()
    if not pk:
        return "Chủ sở hữu"
    conn = ledger.connect()
    try:
        row = conn.execute(
            "SELECT display_name FROM principals WHERE principal_pubkey=?", (pk,)
        ).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if row and row["display_name"]:
        return row["display_name"]
    return pk[:8]


def _tail_text(r) -> str:
    return ((r.stderr or "") + "\n" + (r.stdout or "")).strip()[-600:]


def _parse_collect_n(text: str):
    for line in (text or "").splitlines():
        if "requests moi" in line.lower() or "requests mới" in line.lower():
            for part in reversed(line.replace(",", "").split()):
                if part.isdigit():
                    return int(part)
    return None


def refresh_quota(reason: str = "timer") -> None:
    if REFRESH["running"]:
        return
    REFRESH["running"] = True
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buzz_quota.py")
        with JOB:
            r = _child_run([sys.executable, script], QUOTA_TIMEOUT)
        REFRESH["ok"] = r.returncode == 0
        REFRESH["msg"] = _tail_text(r)
        REFRESH["last"] = time.time()
        REFRESH["reason"] = reason
    except Exception as e:
        REFRESH["ok"] = False
        REFRESH["msg"] = str(e)
        REFRESH["last"] = time.time()
    finally:
        REFRESH["running"] = False


def refresh_collect(reason: str = "timer") -> None:
    """Quet lai moi harness + file phien. --no-backup de poller khong ngap o .bak."""
    if COLLECT["running"]:
        return
    COLLECT["running"] = True
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buzz_collector.py")
        with JOB:
            r = _child_run([sys.executable, script, "--no-backup"], COLLECT_TIMEOUT)
        full = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()
        COLLECT["ok"] = r.returncode == 0
        COLLECT["msg"] = full[-600:]
        n_req = _parse_collect_n(full)
        if n_req is None:
            try:
                conn = ledger.connect()
                try:
                    n_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
                finally:
                    conn.close()
            except Exception:
                n_req = None
        COLLECT["n_req"] = n_req
        COLLECT["last"] = time.time()
        COLLECT["reason"] = reason
        _MODEL_CACHE["at"] = 0.0
        _AGENT_LABEL_CACHE["at"] = 0.0
        _COMM_CACHE["at"] = 0.0
    except Exception as e:
        COLLECT["ok"] = False
        COLLECT["msg"] = str(e)
        COLLECT["last"] = time.time()
    finally:
        COLLECT["running"] = False


def quota_poller() -> None:
    time.sleep(4)
    refresh_quota("startup")
    while True:
        time.sleep(QUOTA_EVERY)
        refresh_quota("timer")


def collect_poller() -> None:
    time.sleep(20)
    refresh_collect("startup")
    while True:
        time.sleep(COLLECT_EVERY)
        refresh_collect("timer")


_AGENT_LABEL_CACHE = {"at": 0.0, "map": {}}


def agent_label(a: str) -> str:
    """Ten hien thi cua agent, lay tu bang `agents`. Cache 30s de moi lan ve
    trang khong phai truy van lai cho tung dong."""
    import time
    now = time.time()
    if now - _AGENT_LABEL_CACHE["at"] > 30:
        try:
            m = {}
            for row in ledger.list_agents():
                nm = (row.get("display_name") or "").strip()
                if nm:
                    m[row["agent_id"]] = nm
            _AGENT_LABEL_CACHE["map"] = m
            _AGENT_LABEL_CACHE["at"] = now
        except Exception:
            pass
    return _AGENT_LABEL_CACHE["map"].get(a, a)


def community_short(cid: str) -> str:
    if not cid:
        return ""
    s = str(cid).replace("wss://", "").replace("https://", "")
    return s.replace(".communities.buzz.xyz", "")


_COMM_CACHE = {"at": 0.0, "map": {}}


def agent_home_community() -> dict:
    now = time.time()
    if now - _COMM_CACHE["at"] < 30:
        return _COMM_CACHE["map"]
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT agent_id, community_id, COUNT(*) AS n FROM requests "
            "WHERE community_id IS NOT NULL AND community_id != '' "
            "GROUP BY 1,2 ORDER BY n DESC"
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    m = {}
    for r in rows:
        if r["agent_id"] not in m:
            m[r["agent_id"]] = r["community_id"]
    _COMM_CACHE.update(at=now, map=m)
    return m


def name_counts(items, key="display_name") -> dict:
    out = {}
    for x in items:
        nm = (x.get(key) or "").strip() or "?"
        out[nm] = out.get(nm, 0) + 1
    return out


def agent_pretty(a, counts) -> str:
    nm = (a.get("display_name") or agent_label(a["agent_id"])).strip()
    comm = community_short(agent_home_community().get(a["agent_id"]) or "")
    if counts.get(nm, 0) > 1:
        if comm:
            return "%s · %s" % (nm, comm)
        return "%s · %s" % (nm, (a.get("agent_id") or "")[:8])
    if (a.get("backend_kind") or "-") in ("-",):
        return "%s · builtin" % nm
    return nm


def person_pretty(u, counts) -> str:
    nm = (u.get("display_name") or "").strip() or ((u.get("principal_pubkey") or "")[:10] + "…")
    comm = community_short(u.get("community_id") or "")
    if counts.get(nm, 0) > 1:
        # Trung ten + cung community (Manh doi khoa) -> cat pubkey, khong gan nham 1 nguoi.
        pk8 = (u.get("principal_pubkey") or "")[:8]
        if comm:
            return "%s · %s · %s" % (nm, comm, pk8)
        return "%s · %s" % (nm, pk8)
    return nm


def get_unread_alerts_count() -> int:
    try:
        alerts = ledger.owner_alerts_recent(100)
        return sum(1 for a in alerts if a.get("status") != "acknowledged")
    except Exception:
        return 0


# ===========================================================================
# Unified Multi-Source Real-Time Message Hub & Continuous Sync Engine
# ===========================================================================
import sqlite3
import threading
import subprocess
from typing import Set, Tuple

HOME = os.path.expanduser("~")
APP_DATA_DIR = os.path.join(HOME, ".local/share/xyz.block.buzz.app")
SOUNDS_DIR = os.path.join(APP_DATA_DIR, "sounds")
CONFIG_DIR = os.path.join(HOME, ".config/buzz")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sound-notifier.json")
DB_LOCALSTORAGE = os.path.join(APP_DATA_DIR, "localstorage", "tauri_localhost_0.localstorage")
DB_HEAD = os.path.join(APP_DATA_DIR, "channel-head-cache.db")
DB_ARCHIVE = os.path.join(HOME, ".buzz/archive/archive.db")
DB_UNREAD = os.path.join(APP_DATA_DIR, "observed-unread.db")
LATEST_MSGS_FILE = os.path.join(APP_DATA_DIR, "latest_messages.json")
MY_PUBKEY = "2da3184b999140883867865a09b97d61397a5265e209fe9c58b93c59f3f0001e"

LAST_SOUND_PLAY_TIME = 0.0
SOUND_LOCK = threading.Lock()

def load_sound_config() -> Dict[str, Any]:
    default_cfg = {
        "enabled": True,
        "sound_message": os.path.join(SOUNDS_DIR, "elevenlabs_thang.wav"),
        "sound_mention": os.path.join(SOUNDS_DIR, "mention.wav"),
        "debounce_ms": 350
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default_cfg.update(cfg)
        except Exception:
            pass
    return default_cfg

def play_audio_alert(is_mention: bool = False, custom_sound: str = None):
    global LAST_SOUND_PLAY_TIME
    with SOUND_LOCK:
        now = time.time()
        cfg = load_sound_config()
        if not cfg.get("enabled", True):
            return
        debounce_sec = max(0.1, cfg.get("debounce_ms", 350) / 1000.0)
        if (now - LAST_SOUND_PLAY_TIME) < debounce_sec:
            return
        LAST_SOUND_PLAY_TIME = now

    sound_path = custom_sound
    if not sound_path:
        sound_path = cfg.get("sound_mention") if is_mention else cfg.get("sound_message")
    
    if not sound_path or not os.path.exists(sound_path):
        sound_path = os.path.join(SOUNDS_DIR, "elevenlabs_thang.wav")
        if not os.path.exists(sound_path):
            sound_path = "/usr/share/sounds/Yaru/stereo/message-new-instant.oga"

    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

    def _play_proc():
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass
        try:
            res = subprocess.run(["paplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            if res.returncode != 0:
                subprocess.run(["pw-play", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        except Exception:
            try:
                subprocess.run(["aplay", "-q", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            except Exception:
                pass

    threading.Thread(target=_play_proc, daemon=True).start()

PENDING_CMDS = []
CMD_RESULTS = {}
CMD_LOCK = threading.Lock()

class UnifiedMessageHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.communities: Dict[str, str] = {
            "wss://dukickk.communities.buzz.xyz": "dukickk",
            "wss://platogroup.communities.buzz.xyz": "platogroup",
            "wss://ncthang04.communities.buzz.xyz": "ncthang04",
            "wss://ode.communities.buzz.xyz": "ode",
            "dukickk": "dukickk",
            "platogroup": "platogroup",
            "ncthang04": "ncthang04",
            "ode": "ode"
        }
        self.channel_names: Dict[str, str] = {}
        self.user_names: Dict[str, str] = {
            MY_PUBKEY: "NcThang"
        }
        self.dm_channels: Dict[str, Dict[str, Any]] = {} # chid -> {relay, participants}
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.seen_event_ids: Set[str] = set()
        self.running = True

        self.load_metadata()
        self.sync_all(initial=True)

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def load_metadata(self):
        if not os.path.exists(DB_LOCALSTORAGE):
            return
        try:
            conn = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
            c = conn.cursor()
            c.execute("SELECT value FROM ItemTable WHERE key='buzz-communities'")
            row = c.fetchone()
            if row:
                val = row[0].decode("utf-16le") if isinstance(row[0], bytes) else row[0]
                for comm in json.loads(val):
                    name = comm.get("name", "")
                    if comm.get("relayUrl"): self.communities[comm["relayUrl"]] = name
                    if comm.get("id"): self.communities[comm["id"]] = name

            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-user-labels%'")
            for k, v in c.fetchall():
                val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                try:
                    data = json.loads(val)
                    for pk, pinfo in data.get("profiles", {}).items():
                        dname = pinfo.get("displayName") or pinfo.get("name") or pinfo.get("nip05")
                        if dname: self.user_names[pk] = dname
                except Exception:
                    pass

            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-self-profile%'")
            for k, v in c.fetchall():
                val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                try:
                    data = json.loads(val)
                    if isinstance(data, dict) and data.get("displayName"):
                        self.user_names[MY_PUBKEY] = data["displayName"]
                except Exception:
                    pass

            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-channels.%'")
            for k, v in c.fetchall():
                val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                try:
                    data = json.loads(val)
                    for ch in data.get("channels", []):
                        cid = ch.get("id")
                        cname = ch.get("name")
                        if cid:
                            # Check for DM participants
                            participants = ch.get("participants", [])
                            partner_name = ""
                            for p in participants:
                                if p != MY_PUBKEY and p in self.user_names:
                                    partner_name = self.user_names[p]
                                    break
                            if partner_name:
                                self.dm_channels[cid] = partner_name
                                self.channel_names[cid] = f"DM ({partner_name})"
                            elif cname:
                                self.channel_names[cid] = cname
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass

    def resolve_community(self, scope: str) -> str:
        if not scope: return "Buzz"
        s_lower = scope.lower()
        for r_url, cname in self.communities.items():
            if r_url in scope or cname.lower() in s_lower:
                return cname
        if "dukick" in s_lower: return "dukickk"
        if "plato" in s_lower: return "platogroup"
        if "ncthang" in s_lower: return "ncthang04"
        if "ode" in s_lower: return "ode"
        return "Buzz"

    def normalize_timestamp(self, ts: Any) -> int:
        if not ts:
            return int(time.time())
        try:
            ts_val = int(ts)
            # If timestamp is in milliseconds (13 digits), convert to seconds
            if ts_val > 9999999999:
                ts_val = ts_val // 1000
            # Sanity check: between 2020-01-01 and 2035-01-01
            if ts_val < 1577836800 or ts_val > 2051222400:
                return int(time.time())
            return ts_val
        except Exception:
            return int(time.time())

    def is_synthetic_or_test(self, eid: str, content: str) -> bool:
        if not eid or not content:
            return True
        eid_str = str(eid).lower()
        if any(eid_str.startswith(p) for p in ("test_", "dummy_", "mock_", "voice_test_", "test-")):
            return True

        cnt = content.strip()
        if not cnt:
            return True

        # Base64 ciphertext / bot payload blobs (e.g. As2fFbm6...)
        if len(cnt) >= 20 and " " not in cnt and re.match(r"^[A-Za-z0-9+/=]+$", cnt):
            return True

        # Single word bot tokens
        cnt_upper = cnt.upper()
        if cnt_upper in ("ONE", "TWO", "THREE", "FOUR", "FIVE", "CLEAN", "READY", "MODEL-OK", "REG", "PING", "PONG", "TEST"):
            return True

        # Bot benchmark & test patterns
        test_patterns = (
            "channel ready", "concurrency pass", "routing verified", "verification test",
            "calibration regression test", "concurrency test", "model-capture verification",
            "live usage-control test", "spoof test", "gateway environment publication",
            "acp test success", "test với timeout", "test 07:56", "trace turn test",
            "second test message", "for this test session only", "test_repo",
            "needs configuration before it can respond", "execution timed out",
            "ai usage today", "test voice", "test alert", "test thông báo âm thanh"
        )
        cnt_lower = cnt.lower()
        if any(pat in cnt_lower for pat in test_patterns):
            return True

        return False

    def add_message(self, eid: str, kind: int, pubkey: str, content: str, chid: str, scope: str, created_at: Any, is_live: bool = False) -> bool:
        if not eid or not content:
            return False

        content = content.strip()
        if not content:
            return False

        if self.is_synthetic_or_test(eid, content):
            return False

        if content.startswith("{") and content.endswith("}"):
            try:
                obj = json.loads(content)
                if "text" in obj: content = obj["text"]
                elif "content" in obj: content = obj["content"]
                elif any(k in obj for k in ("ephemeral_channel_id", "has_more", "descendant_count", "actor", "target")):
                    return False
            except Exception:
                pass

        comm_name = self.resolve_community(scope)
        raw_ch_name = self.channel_names.get(chid, "")
        sender = self.user_names.get(pubkey, f"Thành viên {pubkey[:6]}" if pubkey else "Buzz")

        # Format channel name nicely
        if raw_ch_name:
            ch_name = raw_ch_name
        elif chid and chid in self.dm_channels:
            ch_name = f"DM ({self.dm_channels[chid]})"
        elif chid:
            ch_name = f"#{chid[:6]}"
        else:
            ch_name = "general"

        # Explicit DM check (strictly match DM without fuzzy substring on words like admin)
        is_dm = (raw_ch_name.upper() == "DM" or kind in (4, 1059) or ch_name.upper() == "DM" or ch_name.startswith("DM (") or ch_name.startswith("DM -"))
        if is_dm:
            if not ch_name.startswith("DM ("):
                if pubkey != MY_PUBKEY and sender and not sender.startswith("Thành viên"):
                    ch_name = f"DM ({sender})"
                elif chid and chid in self.dm_channels:
                    ch_name = f"DM ({self.dm_channels[chid]})"
                else:
                    ch_name = "DM"

        is_mention = False
        if "@" in content:
            for uname in self.user_names.values():
                if uname and f"@{uname}".lower() in content.lower():
                    is_mention = True
                    break

        norm_ts = self.normalize_timestamp(created_at)
        lt = time.localtime(norm_ts)

        item = {
            "id": eid,
            "time": time.strftime("%H:%M · %d/%m", lt),
            "full_time": time.strftime("%H:%M:%S · %d/%m/%Y", lt),
            "timestamp": norm_ts,
            "community": comm_name,
            "channel": ch_name,
            "channel_id": chid,
            "sender": sender,
            "pubkey": pubkey,
            "is_dm": is_dm,
            "is_mention": is_mention,
            "content": content
        }

        with self.lock:
            is_new = eid not in self.seen_event_ids
            self.seen_event_ids.add(eid)
            # If item already exists, preserve valid specific timestamp if existing is more accurate
            if eid in self.messages:
                existing = self.messages[eid]
                if existing.get("timestamp") and not is_live:
                    if norm_ts >= int(time.time()) - 5 and existing["timestamp"] < norm_ts:
                        item["timestamp"] = existing["timestamp"]
                        item["time"] = existing["time"]
                        item["full_time"] = existing.get("full_time", item["full_time"])
            self.messages[eid] = item

        if is_new and is_live and pubkey != MY_PUBKEY:
            self._notify(item)

        return is_new

    def _notify(self, item: Dict[str, Any]):
        try:
            cfg = load_sound_config()
            if not cfg.get("enabled", True):
                return

            # 1. Voice / Audio alert
            play_audio_alert(is_mention=item.get("is_mention", False))

            # 2. Visual desktop notification
            if not cfg.get("show_desktop_notification", True):
                return

            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            if "WAYLAND_DISPLAY" not in env:
                env["WAYLAND_DISPLAY"] = "wayland-0"
            env["XDG_RUNTIME_DIR"] = "/run/user/1000"
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

            comm = item.get("community", "Buzz")
            chan = item.get("channel", "general")
            sender = item.get("sender", "Buzz")
            cnt = item.get("content", "")[:100].replace("\n", " ")

            title = f"📢 [{comm.upper()}] #{chan}"
            body = f"👤 {sender}: {cnt}"
            subprocess.Popen([
                "notify-send", "-a", "Buzz", "-i", "dialog-information",
                "-u", "critical", "-t", "6000", title, body
            ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def sync_all(self, initial: bool = False):
        new_count = 0
        if os.path.exists(DB_HEAD):
            try:
                conn = sqlite3.connect(f"file:{DB_HEAD}?mode=ro", uri=True)
                c = conn.cursor()
                for scope, chid, events_str, saved_at in c.execute("SELECT scope, channel_id, events_json, saved_at FROM channel_head"):
                    try:
                        for ev in json.loads(events_str):
                            k = ev.get("kind", 0)
                            if k in (9, 40003, 4, 1, 1059) or (k == 7 and len(ev.get("content","")) < 10):
                                ts = ev.get("created_at") or ev.get("createdAt") or ev.get("timestamp") or saved_at
                                if self.add_message(ev.get("id"), k, ev.get("pubkey",""), ev.get("content",""), chid, scope, ts, is_live=(not initial)):
                                    new_count += 1
                    except Exception:
                        pass
                conn.close()
            except Exception:
                pass

        if os.path.exists(DB_LOCALSTORAGE):
            try:
                conn = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
                c = conn.cursor()
                for k, v in c.execute("SELECT key, value FROM ItemTable WHERE key LIKE '%thread-activity%'"):
                    val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                    try:
                        for item in json.loads(val):
                            ts = item.get("createdAt") or item.get("created_at") or item.get("timestamp") or item.get("saved_at")
                            if self.add_message(item.get("id"), item.get("kind", 9), item.get("pubkey",""), item.get("content",""), item.get("channelId",""), k, ts, is_live=(not initial)):
                                new_count += 1
                    except Exception:
                        pass
                conn.close()
            except Exception:
                pass

        if os.path.exists(DB_ARCHIVE):
            try:
                conn = sqlite3.connect(f"file:{DB_ARCHIVE}?mode=ro", uri=True)
                c = conn.cursor()
                for relay_url, eid, kind, pubkey, created_at, raw_json in c.execute("SELECT relay_url, id, kind, pubkey, created_at, raw_json FROM archived_events"):
                    try:
                        data = json.loads(raw_json)
                        chid = ""
                        for t in data.get("tags", []):
                            if t and t[0] in ("h", "e"):
                                chid = t[1]
                                break
                        ts = created_at or data.get("created_at") or data.get("createdAt") or data.get("timestamp")
                        if self.add_message(eid, kind, pubkey, data.get("content",""), chid, relay_url, ts, is_live=(not initial)):
                            new_count += 1
                    except Exception:
                        pass
                conn.close()
            except Exception:
                pass

        self.save_to_disk()
        return new_count

    def save_to_disk(self):
        try:
            sorted_msgs = self.get_sorted_messages()
            with open(LATEST_MSGS_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted_msgs, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_channel_read_states(self) -> Dict[str, int]:
        read_states: Dict[str, int] = {}
        if os.path.exists(DB_LOCALSTORAGE):
            try:
                conn = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
                c = conn.cursor()
                c.execute("SELECT value FROM ItemTable WHERE key LIKE 'buzz.channel-read-state.v2%'")
                row = c.fetchone()
                if row:
                    val = row[0].decode('utf-16le') if isinstance(row[0], bytes) else str(row[0])
                    for chid, iso_str in json.loads(val).items():
                        try:
                            dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                            read_states[chid] = int(dt.timestamp())
                        except Exception:
                            pass
                conn.close()
            except Exception:
                pass

        if os.path.exists(DB_UNREAD):
            try:
                conn_u = sqlite3.connect(f"file:{DB_UNREAD}?mode=ro", uri=True)
                cu = conn_u.cursor()
                cu.execute("SELECT context_id, read_at FROM read_markers")
                for chid, r_at in cu.fetchall():
                    if r_at and (chid not in read_states or r_at > read_states[chid]):
                        read_states[chid] = r_at
                conn_u.close()
            except Exception:
                pass

        return read_states

    def get_sorted_messages(self) -> List[Dict[str, Any]]:
        read_states = self.get_channel_read_states()
        now_ts = int(time.time())
        with self.lock:
            msgs = [dict(m) for m in self.messages.values()]

        for m in msgs:
            chid = m.get("channel_id")
            ts = m.get("timestamp", 0)
            read_ts = read_states.get(chid, 0)
            m["is_unread"] = bool(ts > read_ts and (read_ts > 0 or ts > (now_ts - 7 * 86400)))

        return sorted(msgs, key=lambda x: x["timestamp"], reverse=True)

    def _worker(self):
        loop_c = 0
        while self.running:
            try:
                loop_c += 1
                if loop_c % 30 == 0:
                    self.load_metadata()
                self.sync_all(initial=False)
                time.sleep(0.3)
            except Exception:
                time.sleep(1.0)

MSG_HUB = UnifiedMessageHub()


# ===========================================================================
# Capacity Helper Component
# ===========================================================================

def capacity_block(agent: dict) -> str:
    """Provider capacity — visually and semantically distinct from user allowance."""
    caps = agent.get("capacity") or []
    if not caps:
        return '<span class="text-muted">Dung lượng: Chưa có dữ liệu snapshot</span>'
    vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
    lowest = min(vals) if vals else None
    
    if lowest is not None:
        color = "var(--danger)" if lowest < 20 else ("var(--warning)" if lowest < 50 else "var(--capacity)")
        gauge = ui.render_radial_gauge(lowest, size=38, color_override=color)
        head = f"""<div style="display:flex;align-items:center;gap:10px;">
          {gauge}
          <div>
            <div style="color:{color};font-weight:700;font-size:13.5px;">Còn lại {lowest:.0f}%</div>
            <div class="text-muted" style="font-size:11.5px;">(mô hình thấp nhất)</div>
          </div>
        </div>"""
    else:
        head = '<span class="text-muted">Dung lượng: Chưa xác định</span>'
    
    rows = []
    for c in caps:
        rem = f"{c['remaining_percent']:.0f}%" if c.get("remaining_percent") is not None else "Chưa rõ"
        res_at = c.get("reset_at") or "—"
        rows.append(f"""<tr>
          <td><b>{html.escape(c.get('model') or 'Chưa xác định')}</b></td>
          <td class="td-num"><b>{rem}</b></td>
          <td style="font-size:12px;color:var(--text-muted);">{html.escape(res_at)}</td>
        </tr>""")
    
    table_html = f"""<table class="data-table" style="margin-top:8px;">
      <thead><tr><th>Mô hình</th><th class="th-num">Còn lại</th><th>Làm mới lúc</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""
    
    return f"""{head}
    <details class="custom-details" style="margin-top:8px;">
      <summary>Chi tiết từng mô hình ({len(caps)})</summary>
      <div class="details-content" style="padding:0;">{table_html}</div>
    </details>"""


# ===========================================================================
# PAGE 1: TỔNG QUAN (Overview)
# ===========================================================================

def codex_account_rows() -> list:
    """Chi tiet TUNG tai khoan Codex chinh hang, doc tu bang codex_account_limits
    (bin/buzz_quota.py ghi). User dang nhap nhieu tai khoan ChatGPT; han muc la
    rieng tung tai khoan nen phai hien rieng, khong gop."""
    try:
        conn = ledger.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM codex_account_limits ORDER BY account_id, window_minutes"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def _fmt_ts(ts) -> str:
    import datetime as _d
    try:
        return _d.datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M") if ts else "-"
    except Exception:
        return "-"


def _window_name(minutes) -> str:
    try:
        m = int(minutes or 0)
    except Exception:
        return "?"
    if m >= 1440:
        return "%d ngày" % (m // 1440)
    if m >= 60:
        return "%d giờ" % (m // 60)
    return "%d phút" % m if m else "-"


def provider_quota() -> dict:
    """Chon tai khoan Codex chinh hang DANG NGUY HIEM NHAT cho o chinh.

    Uu tien cua so con hieu luc (resets_at con o tuong lai), lay cai con it nhat.
    Neu moi cua so da qua moc reset thi so lieu khong con dung — lay ban doc gan
    nhat va ghi ro trong nhan de o chinh canh bao, khong trinh bay nhu hien tai.
    """
    import time as _t
    import datetime as _d
    now = _t.time()
    rows = [r for r in codex_account_rows() if r.get("used_percent") is not None]
    if not rows:
        return {}
    # Bo so doc cu hon 7 ngay: 11/09 co ban doc "30 ngay, dung 100%" tu 14/08
    # lam o chinh bao nham mot tai khoan het sach trong khi tai khoan van chay.
    live = [r for r in rows
            if (r.get("resets_at") or 0) > now and now - (r.get("read_at") or 0) <= 7 * 86400]
    if live:
        r = min(live, key=lambda x: 100.0 - float(x["used_percent"]))
        expired = False
    else:
        r = max(rows, key=lambda x: x.get("read_at") or 0)
        expired = True
    reset_iso = ""
    try:
        reset_iso = _d.datetime.fromtimestamp(int(r["resets_at"]), _d.timezone.utc).isoformat()
    except Exception:
        pass
    label = "tài khoản %s · cửa sổ %s · %d agent" % (
        r.get("account_id"), _window_name(r.get("window_minutes")), int(r.get("agent_count") or 0))
    if expired:
        label += " · ĐÃ QUA MỐC RESET, số liệu không còn đúng"
    return {
        "agent_id": r.get("account_id"),
        "label": label,
        "remaining_percent": max(0.0, 100.0 - float(r["used_percent"])),
        "reset_at": reset_iso,
        "captured_at": r.get("read_at"),
    }


def codex_accounts_section() -> str:
    """Bang chi tiet tung tai khoan Codex chinh hang x tung cua so han muc."""
    import time as _t
    import html as _h
    now = _t.time()
    rows = codex_account_rows()
    if not rows:
        return ('<div class="card-section"><div class="section-title">Tài khoản Codex chính hãng</div>'
                '<div class="text-muted" style="margin-top:8px;">Chưa có dữ liệu — chạy bin/buzz_quota.py</div></div>')
    trs = []
    for r in rows:
        used = r.get("used_percent")
        used_t = "-" if used is None else "%.0f%%" % float(used)
        rem_t = "-" if used is None else "%.0f%%" % (100.0 - float(used))
        rs = r.get("resets_at") or 0
        age_h = (now - (r.get("read_at") or now)) / 3600.0
        if used is None:
            st, color = "Không có số liệu", "var(--text-muted)"
        elif rs and rs < now:
            st, color = "Đã qua mốc reset", "#d97706"
        elif age_h > 24 * 7:
            st, color = "Số quá cũ %.0f ngày — chỉ tham khảo" % (age_h / 24.0), "var(--text-muted)"
        elif age_h > 6:
            st, color = "Số cũ %.0f giờ" % age_h, "#d97706"
        else:
            st, color = "Còn hiệu lực", "#16a34a"
        acc = _h.escape(str(r.get("account_id") or "-"))
        # Mot tai khoan (email) co the dung o nhieu noi: WSL qua harness Buzz va
        # Windows qua app Codex. Hien tat ca noi dung + harness duoi ten tai khoan.
        home = _h.escape(str(r.get("homes") or r.get("codex_home") or ""))
        if r.get("window_minutes") and r.get("source_home"):
            home = home + " · số đọc từ " + _h.escape(str(r.get("source_home")))
        agents = _h.escape(str(r.get("agents") or ""), quote=True)
        plan = _h.escape(str(r.get("plan") or "-"))
        trs.append(
            "<tr>"
            f"<td><b>{acc}</b><div class='text-muted' style='font-size:11px;'>{home}</div></td>"
            f"<td>{plan}</td>"
            f"<td>{_window_name(r.get('window_minutes'))}</td>"
            f"<td>{used_t}</td>"
            f"<td><b>{rem_t}</b></td>"
            f"<td>{_fmt_ts(rs)}</td>"
            f"<td>{_fmt_ts(r.get('read_at'))}</td>"
            f"<td style='color:{color};font-weight:600;'>{st}</td>"
            f"<td title='{agents}'>{int(r.get('agent_count') or 0)}"
            f"<div class='text-muted' style='font-size:11px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{agents}</div></td>"
            "</tr>")
    return (
        '<div class="card-section">'
        '<div class="section-header"><div>'
        '<div class="section-title">Tài khoản Codex chính hãng</div>'
        '<div class="section-subtitle">Gộp theo email — một tài khoản dùng ở nhiều nơi (WSL, app Windows) chỉ hiện một lần · bỏ qua Codex chạy qua Ollama</div>'
        '</div></div>'
        '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">'
        '<thead><tr style="text-align:left;color:var(--text-muted);">'
        '<th>Tài khoản</th><th>Gói</th><th>Cửa sổ</th><th>Đã dùng</th><th>Còn lại</th>'
        '<th>Reset lúc</th><th>Số liệu lúc</th><th>Trạng thái</th><th>Agent</th></tr></thead>'
        '<tbody>' + "".join(trs) + '</tbody></table></div></div>')


def _win_status(r: dict, now: float) -> tuple:
    used = r.get("used_percent")
    rs = r.get("resets_at") or 0
    age_h = (now - (r.get("read_at") or now)) / 3600.0
    src = str(r.get("source_home") or "")
    live = "live API" in src or (r.get("source") == "live-api")
    if used is None:
        return "Không có số", "var(--text-muted)", "#64748b"
    if live and age_h <= 2:
        return "Live API", "#16a34a", "#16a34a"
    if rs and rs < now:
        return "Đã qua mốc reset", "#d97706", "#d97706"
    if age_h > 24 * 7:
        return "Số quá cũ — tham khảo", "var(--text-muted)", "#64748b"
    if age_h > 6:
        return "Số cũ %.0f giờ" % age_h, "#d97706", "#d97706"
    return "Còn hiệu lực", "#16a34a", "#16a34a"


def account_cards_html() -> str:
    now = time.time()
    rows = [r for r in codex_account_rows()]
    by = {}
    for r in rows:
        by.setdefault(r.get("account_id") or "?", []).append(r)
    people_bd = ledger.codex_people_breakdown()
    codex_who = {}
    for p in (people_bd.get("people") or []):
        label = p["name"]
        if p["kind"] == "agent":
            label = "Agent gọi nhau"
        elif p["kind"] == "unknown":
            label = "Chưa rõ người"
        for em, cell in (p.get("by_email") or {}).items():
            if not cell.get("n"):
                continue
            codex_who.setdefault(em, []).append(
                {"name": label, "kind": p["kind"], "n": cell["n"], "tok": cell["tok"]}
            )
    for em in codex_who:
        codex_who[em].sort(key=lambda x: -x["tok"])
    if not by:
        return ('<div class="card-section"><div class="section-title">Tài khoản Codex</div>'
                '<div class="text-muted" style="margin-top:8px;">Chưa có số hạn mức — chờ bộ đọc chạy.</div></div>')
    cards = []
    for email in sorted(by):
        rs = by[email]
        head = rs[0]
        wins = [r for r in rs if r.get("used_percent") is not None]
        statuses = [_win_status(r, now) for r in wins] or [("Chưa có cửa sổ", "var(--text-muted)", "#64748b")]
        bar = statuses[0][2]
        if any(s[0] == "Còn hiệu lực" for s in statuses):
            live = [s for s in statuses if s[0] == "Còn hiệu lực"]
            bar = live[0][2]
        win_html = []
        for r in sorted(wins, key=lambda x: int(x.get("window_minutes") or 0)):
            used = float(r["used_percent"])
            rem = 100.0 - used
            st, color, _ = _win_status(r, now)
            win_html.append(
                f"<div class='acct-win'>"
                f"<div class='acct-win-row'><span>{html.escape(_window_name(r.get('window_minutes')))}</span>"
                f"<b>{used:.0f}% đã dùng · còn {rem:.0f}%</b></div>"
                f"{ui.render_progress_bar(used, rem, height=7, show_label=False)}"
                f"<div class='acct-meta' style='margin-top:6px;color:{color};'>{st}"
                f" · đọc {_fmt_ts(r.get('read_at'))} · reset {_fmt_ts(r.get('resets_at'))}</div>"
                f"</div>"
            )
        if not win_html:
            win_html.append("<div class='acct-meta' style='margin-top:10px;'>Chưa có phiên trả rate_limits</div>")
        has_live = any("live API" in str(r.get("source_home") or "") for r in wins)
        if wins and not has_live and all(s[0] != "Còn hiệu lực" and s[0] != "Live API" for s in statuses):
            win_html.append(
                "<div class='acct-meta' style='margin-top:8px;color:#d97706;'>"
                "Cần đăng nhập lại Codex (chatgpt.com) để lấy hạn mức live</div>"
            )
        n_ag = int(head.get("agent_count") or 0)
        agents = html.escape(str(head.get("agents") or ""), quote=True)
        homes = html.escape(str(head.get("homes") or ""))
        who_html = ""
        who_rows = []
        for p in (codex_who.get(email) or []):
            who_rows.append(
                "<div class='acct-meta' style='display:flex;justify-content:space-between;gap:8px;'>"
                "<span>%s</span><span><b>%s</b> · %s tok</span></div>"
                % (html.escape(p["name"]), i18n.fmt_number(p["n"]), i18n.fmt_number(p["tok"]))
            )
        if who_rows:
            who_html = ("<div style='margin-top:10px;padding-top:8px;border-top:1px solid var(--border-subtle);'>"
                        "<div class='acct-meta' style='margin-bottom:4px;'>Ai đốt acc này (toàn thời gian)</div>"
                        + "".join(who_rows[:6]) + "</div>")
        cards.append(
            f"<div class='acct-card' style='--acct-bar:{bar};'>"
            f"<div style='display:flex;justify-content:space-between;gap:8px;align-items:flex-start;'>"
            f"<div><div class='acct-mail'>{html.escape(str(email))}</div>"
            f"<div class='acct-meta'>gói {html.escape(str(head.get('plan') or '-'))}"
            f" · {n_ag} agent Buzz · hạn mức live ≠ tổng token lịch sử</div></div>"
            f"{ui.render_radial_gauge(100.0 - float(wins[0]['used_percent']) if wins else 0.0, size=52, color_override=bar)}"
            f"</div>"
            f"<div class='acct-meta' style='margin-top:8px;' title='{agents}'>{homes}</div>"
            f"{''.join(win_html)}{who_html}</div>"
        )
    last = REFRESH.get("last") or 0
    last_txt = dt.datetime.fromtimestamp(last).strftime("%d/%m %H:%M") if last else "chưa chạy"
    st = "đang đọc" if REFRESH.get("running") else ("ok" if REFRESH.get("ok") else "lỗi")
    clast = COLLECT.get("last") or 0
    clast_txt = dt.datetime.fromtimestamp(clast).strftime("%d/%m %H:%M") if clast else "chưa chạy"
    cst = "đang thu thập" if COLLECT.get("running") else ("ok" if COLLECT.get("ok") else "lỗi")
    cn = COLLECT.get("n_req")
    cextra = (" · %s lượt" % i18n.fmt_number(cn)) if cn else ""
    head_bar = (
        '<div class="section-header" style="margin-bottom:12px;">'
        '<div><div class="section-title">Hạn mức từng tài khoản Codex</div>'
        f'<div class="section-subtitle">Mỗi email một thẻ · live API /wham/usage · lần đọc {last_txt} ({st})'
        f' · thu thập lượt {clast_txt} ({cst}{cextra})</div></div>'
    )
    if not ui.request_public():
        head_bar += (
            '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
            '<form method="post" action="/refresh/quota">'
            '<button class="btn btn-primary btn-sm" type="submit">Đọc lại hạn mức</button></form>'
            '<form method="post" action="/refresh/collect">'
            '<button class="btn btn-secondary btn-sm" type="submit">Thu thập lượt</button></form>'
            '</div>'
        )
    head_bar += "</div>"
    return head_bar + '<div class="acct-grid">' + "".join(cards) + "</div>"


def _email_short(email: str) -> str:
    e = (email or "").strip()
    if "@" in e:
        return e.split("@", 1)[0]
    return e or "?"


def _kind_nick(kind: str) -> str:
    return {
        "codex-openai": "openai",
        "codex-sales": "sales",
        "codex-creative": "creative",
        "codex-creative-lead": "creative-lead",
        "codex-pm": "PM",
        "codex-pm-lead": "PM-lead",
    }.get(kind) or kind


def codex_people_html(limit: int = 0, compact: bool = False) -> str:
    """Bang Codex ChatGPT: tung nguoi dung acc nao. Khong gom Hermes/Ollama."""
    data = ledger.codex_people_breakdown()
    people = data.get("people") or []
    accounts = data.get("accounts") or []
    if limit:
        people = people[:limit]
    if not people:
        return ('<div class="card-section"><div class="section-title">Ai dùng Codex</div>'
                '<div class="text-muted" style="margin-top:8px;">Chưa có lượt Codex ChatGPT.</div></div>')
    name_n = {}
    for p in people:
        if p.get("kind") == "person":
            name_n[p["name"]] = name_n.get(p["name"], 0) + 1
    for p in people:
        if p.get("kind") == "person" and name_n.get(p["name"], 0) > 1:
            comm = community_short(p.get("community") or "")
            if comm:
                p["name"] = "%s · %s" % (p["name"], comm)
    name_n2 = {}
    for p in people:
        if p.get("kind") == "person":
            name_n2[p["name"]] = name_n2.get(p["name"], 0) + 1
    for p in people:
        if p.get("kind") == "person" and name_n2.get(p["name"], 0) > 1 and p.get("pubkey"):
            p["name"] = "%s · %s" % (p["name"], p["pubkey"][:8])
    nick = {kind: email for kind, email in (data.get("kind_email") or {}).items()}
    col_label = {}
    for em in accounts:
        kinds = sorted({k for k, v in nick.items() if v == em})
        tag = "/".join(_kind_nick(k) for k in kinds) if kinds else ""
        col_label[em] = "%s\n%s" % (_email_short(em), tag)

    def cell(n, tok):
        if not n:
            return "<td class='td-num text-muted'>—</td>"
        return ("<td class='td-num'><b>%s</b>"
                "<div class='text-muted' style='font-size:11px;'>%s tok</div></td>"
                % (i18n.fmt_number(n), i18n.fmt_number(tok)))

    rows = []
    for p in people:
        if p["kind"] == "person":
            href = "/users/" + urllib.parse.quote(p["pubkey"])
            name = '<a href="%s" style="color:var(--primary);text-decoration:none;"><b>%s</b></a>' % (
                html.escape(href), html.escape(p["name"]))
            badge = ""
        elif p["kind"] == "agent":
            name = "<b>%s</b>" % html.escape(p["name"])
            badge = ui.render_badge("agent gọi agent — vẫn trừ quota", "var(--bg-subtle)", "var(--text-muted)")
        else:
            name = "<b>%s</b>" % html.escape(p["name"])
            badge = ui.render_badge("phiên không ghi người gửi", "var(--warning-subtle)", "var(--warning)")
        if p.get("name_note"):
            badge += " " + ui.render_badge(p["name_note"], "var(--bg-subtle)", "var(--text-muted)")
        top = p.get("top_agents") or []
        top_s = ", ".join("%s (%s)" % (a["name"], i18n.fmt_number(a["n"])) for a in top[:3]) or "—"
        tds = "".join(cell(p["by_email"].get(em, {}).get("n"), p["by_email"].get(em, {}).get("tok"))
                      for em in accounts)
        rows.append(
            "<tr><td>%s %s<div class='text-muted' style='font-size:11px;max-width:280px;"
            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' title='%s'>%s</div></td>"
            "<td class='td-num'>%s<div class='text-muted' style='font-size:11px;'>%s tok</div></td>"
            "%s<td class='td-num'><b>%s</b><div class='text-muted' style='font-size:11px;'>%s tok</div></td></tr>"
            % (name, badge, html.escape(top_s, quote=True), html.escape(top_s),
               i18n.fmt_number(p.get("n_today") or 0), i18n.fmt_number(p.get("tok_today") or 0),
               tds, i18n.fmt_number(p["requests"]), i18n.fmt_number(p["tokens"]))
        )
    heads = "".join(
        "<th class='th-num' title='%s'>%s<div class='text-muted' style='font-size:10px;font-weight:500;'>%s</div></th>"
        % (html.escape(em, quote=True), html.escape(_email_short(em)),
           html.escape(col_label[em].split("\n")[-1]))
        for em in accounts
    )
    more = ""
    if compact and (data.get("people") or []) and limit and len(data["people"]) > limit:
        more = ('<div style="margin-top:12px;text-align:right;">'
                '<a href="/users" class="btn btn-secondary btn-sm">Xem hết người × acc →</a></div>')
    return (
        '<div class="card-section">'
        '<div class="section-header"><div>'
        '<div class="section-title">Ai dùng Codex ChatGPT</div>'
        '<div class="section-subtitle">Toàn thời gian (không phải hạn mức 5h/7 ngày) · ChatGPT Codex · '
        'bỏ Hermes/Ollama · %s lượt · %s token · cột Hôm nay = từ 0h ICT</div></div></div>'
        '<div class="table-wrapper" style="overflow-x:auto;"><table class="data-table">'
        '<thead><tr><th>Người</th><th class="th-num">Hôm nay</th>%s'
        '<th class="th-num">Tổng</th></tr></thead>'
        '<tbody>%s</tbody></table></div>%s</div>'
        % (i18n.fmt_number(data.get("total_requests") or 0),
           i18n.fmt_number(data.get("total_tokens") or 0),
           heads, "".join(rows), more)
    )


def codex_person_html(pubkey: str) -> str:
    data = ledger.codex_people_breakdown(pubkey=pubkey)
    people = data.get("people") or []
    if not people:
        return ('<div class="card-section"><div class="section-title">Codex ChatGPT</div>'
                '<p class="text-muted" style="margin-top:8px;">Người này chưa có lượt Codex ChatGPT '
                '(hoặc chỉ Hermes/Ollama).</p></div>')
    p = people[0]
    blocks = []
    by_em = {}
    for a in sorted(p.get("agents", {}).values(), key=lambda x: -x["tok"]):
        by_em.setdefault(a["email"], []).append(a)
    for em in (data.get("accounts") or []):
        ags = by_em.get(em) or []
        if not ags:
            continue
        n = sum(a["n"] for a in ags)
        tok = sum(a["tok"] for a in ags)
        trs = "".join(
            "<tr><td>%s</td><td class='text-muted'>%s</td>"
            "<td class='td-num'>%s</td><td class='td-num'><b>%s</b></td></tr>"
            % (html.escape(a["name"]), html.escape(_kind_nick(a["kind"])),
               i18n.fmt_number(a["n"]), i18n.fmt_number(a["tok"]))
            for a in ags
        )
        blocks.append(
            "<div style='margin-bottom:16px;'>"
            "<div style='font-weight:700;margin-bottom:6px;'>%s"
            "<span class='text-muted' style='font-weight:500;'> · %s lượt · %s token</span></div>"
            "<table class='data-table'><thead><tr><th>Agent</th><th>Harness</th>"
            "<th class='th-num'>Lượt</th><th class='th-num'>Token</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            % (html.escape(em), i18n.fmt_number(n), i18n.fmt_number(tok), trs)
        )
    return (
        '<div class="card-section">'
        '<div class="section-title">Codex ChatGPT của người này</div>'
        '<div class="section-subtitle">Acc nào · agent nào · không gồm Hermes/Ollama</div>'
        '<div style="margin-top:12px;">%s</div></div>' % "".join(blocks)
    )


def usage_trend_points(codex_only: bool = True) -> list:
    now = dt.datetime.now(ICT)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    kinds = ledger.CHATGPT_CODEX_KINDS
    conn = ledger.connect()
    points = []
    try:
        for i in range(6, -1, -1):
            s = midnight - dt.timedelta(days=i)
            e = s + dt.timedelta(days=1)
            if codex_only:
                row = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(r.normalized_units),0) AS u "
                    "FROM requests r JOIN agents a ON a.agent_id = r.agent_id "
                    "WHERE r.started_at >= ? AND r.started_at < ? "
                    "AND a.backend_kind IN (?,?,?,?,?,?)",
                    (int(s.timestamp()), int(e.timestamp())) + tuple(kinds),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(normalized_units),0) AS u "
                    "FROM requests WHERE started_at >= ? AND started_at < ?",
                    (int(s.timestamp()), int(e.timestamp())),
                ).fetchone()
            label = "Hôm nay" if i == 0 else s.strftime("%d/%m")
            points.append({"label": label, "value": float(row["u"] or 0), "requests": int(row["n"] or 0)})
    finally:
        conn.close()
    return points


def v_overview() -> str:
    o = ledger.overview()
    unread_alerts = get_unread_alerts_count()
    units_fmt = i18n.fmt_number(o.get("units_today", 0.0))
    hero_html = account_cards_html()
    hero_html += codex_people_html()
    cx = ledger.codex_people_breakdown()
    hero_html += f"""
    <div class="card-section" style="margin-bottom:22px;">
      <div class="text-muted" style="font-size:13px;">Hôm nay (0h ICT) Codex ChatGPT: <b>{i18n.fmt_number(cx.get('n_today') or 0)}</b> lượt ·
      <b>{i18n.fmt_number(cx.get('tok_today') or 0)}</b> token.
      Mọi harness kể cả Hermes/Ollama: <b>{units_fmt}</b> token — không phải hạn mức 5h/7 ngày.</div>
    </div>
    """

    # 4 Supporting KPIs — Codex ChatGPT, khong tron Hermes
    kpis_html = f"""
    <div class="kpi-grid">
      {ui.render_kpi_card("Người Codex", str(cx.get("n_person", 0)), "Người có lượt Codex ChatGPT (đã gộp trùng tên)")}
      {ui.render_kpi_card("Lượt Codex hôm nay", i18n.fmt_number(cx.get("n_today") or 0), "Từ 0h ICT · chỉ ChatGPT Codex")}
      {ui.render_kpi_card("Token Codex (cả lịch sử)", i18n.fmt_number(cx.get("total_tokens") or 0), "%s lượt toàn thời gian" % i18n.fmt_number(cx.get("total_requests") or 0))}
      {ui.render_kpi_card(i18n.t("overview.warnings"), str(unread_alerts), "Cảnh báo bất thường đang mở")}
    </div>
    """
    
    # System Mode Banner
    mode_banner = f"""
    <div class="mode-banner">
      <div style="font-weight:600;display:flex;align-items:center;gap:8px;">
        <span style="color:var(--text-primary);">Chế độ vận hành:</span>
      </div>
      <div class="mode-pills">
        <span class="mode-pill active">✓ Ghi nhận sử dụng: BẬT</span>
        <span class="mode-pill active">✓ Cảnh báo sớm: BẬT</span>
        <span class="mode-pill inactive">Giới hạn mềm: TẮT</span>
        <span class="mode-pill inactive">Giới hạn cứng: TẮT (Chỉ quan sát)</span>
      </div>
    </div>
    """
    
    # Trend Chart — token that / ngay, khong % han muc mot tai khoan
    trend_points = usage_trend_points()
    chart_svg = ui.render_svg_trend_chart(trend_points, height=200, y_format="units")
    
    trend_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("overview.usage_trend")}</div>
          <div class="section-subtitle">Token Codex ChatGPT theo ngày ICT — không gồm Hermes/Ollama, không phải % hạn mức acc</div>
        </div>
        <div class="filter-group">
          <span class="filter-pill active">7 ngày · Codex ChatGPT</span>
        </div>
      </div>
      {chart_svg}
    </div>
    """
    
    # 2-Column Section: Top Users & Agent Breakdown
    persons = [p for p in (cx.get("people") or []) if p.get("kind") == "person"]
    top_users_html = []
    if not persons:
        top_users_html.append(ui.render_empty_state("Chưa có người dùng Codex", "Chưa gắn được lượt Codex ChatGPT cho người."))
    else:
        tot_tok = sum(p["tokens"] for p in persons) or 1.0
        for p in persons[:6]:
            share = (p["tokens"] / tot_tok) * 100.0
            name = p["name"]
            href = "/users/" + urllib.parse.quote(p.get("pubkey") or "")
            avatar_html = ui.render_avatar(name, 24)
            top_users_html.append(f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:8px;">
                  {avatar_html}
                  <b><a href="{html.escape(href)}" style="color:var(--primary);text-decoration:none;">{html.escape(name)}</a></b>
                </div>
                <span><b>{i18n.fmt_number(p['tokens'])}</b> <span class="text-muted">({i18n.fmt_number(p['requests'])} lượt)</span></span>
              </div>
              {ui.render_progress_bar(share, show_label=False, height=7)}
            </div>
            """)
        top_users_html.append(f"""<div style="margin-top:16px;text-align:right;">
          <a href="/users" class="btn btn-secondary btn-sm">{i18n.t("overview.view_all_users")} →</a>
        </div>""")
    
    agents_list = ledger.codex_agent_totals()
    acounts = name_counts(agents_list)
    used_agents = [a for a in agents_list if a.get("requests", 0) > 0]
    total_agent_units = sum(a.get("units", 0.0) for a in used_agents) or 1.0
    agents_breakdown_html = []
    if not used_agents:
        agents_breakdown_html.append(ui.render_empty_state("Chưa có dữ liệu Agent", "Chưa có lượt gọi Agent nào."))
    else:
        for a in sorted(used_agents, key=lambda x: -x.get("units", 0.0))[:12]:
            ashare = (a.get("units", 0.0) / total_agent_units) * 100.0
            aname = agent_pretty(a, acounts)
            is_agy = a.get("backend_kind") == "agy"
            bcolor = "var(--capacity)" if is_agy else "var(--primary)"
            tag_label = backend_label(a.get("backend_kind"))
            tag_badge = f'<span class="badge" style="font-size:10.5px;padding:1px 6px;background:var(--bg-subtle);color:{bcolor};">{tag_label}</span>'
            
            agents_breakdown_html.append(f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:6px;">
                  <b>{html.escape(aname)}</b>
                  {tag_badge}
                </div>
                <span><b>{ashare:.1f}%</b> <span class="text-muted">({a.get('requests', 0)} reqs)</span></span>
              </div>
              {ui.render_progress_bar(ashare, show_label=False, height=7, color_override=bcolor)}
            </div>
            """)
    
    two_col_section = f"""
    <div class="grid-2col">
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-header">
          <div>
            <div class="section-title">Người dùng Codex</div>
            <div class="section-subtitle">Token ChatGPT Codex toàn thời gian — không phải % hạn nội bộ hôm nay</div>
          </div>
        </div>
        {''.join(top_users_html)}
      </div>
      
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-header">
          <div>
            <div class="section-title">Agent Codex</div>
            <div class="section-subtitle">Toàn thời gian · chỉ ChatGPT Codex (sales/creative/PM/openai)</div>
          </div>
        </div>
        {''.join(agents_breakdown_html)}
      </div>
    </div>
    """
    
    # Khoi rieng: Han muc nha cung cap (ChatGPT / Ollama Cloud)
    agy_cards = []
    for a in agents_list:
        if a.get("backend_kind") == "agy":
            aname = agent_label(a["agent_id"])
            caps = a.get("capacity") or []
            vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
            lowest = min(vals) if vals else None
            rem_str = f"{lowest:.0f}%" if lowest is not None else "Chưa rõ"
            p_val = lowest if lowest is not None else 0.0
            
            p_bar = ui.render_progress_bar(p_val, show_label=False, height=6, color_override="var(--capacity)")
            
            agy_cards.append(f"""
            <div class="capacity-card">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-weight:700;font-size:15px;color:var(--text-primary);">{html.escape(aname)}</span>
                <span style="font-weight:700;font-size:15px;color:var(--capacity);">{rem_str} còn lại</span>
              </div>
              {p_bar}
              <div style="margin-top:10px;">{capacity_block(a)}</div>
            </div>
            """)
            
    capacity_section = f"""
    <div class="capacity-box">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
        <div>
          <div class="capacity-title">🟣 {i18n.t("overview.capacity_title")}</div>
          <div style="font-size:13px;color:var(--text-secondary);margin-top:2px;">
            {i18n.t("overview.capacity_microcopy")}
          </div>
        </div>
        <span class="badge" style="background:var(--bg-surface);color:var(--capacity);border:1px solid var(--capacity-border);">
          Chu kỳ quét: 10 phút
        </span>
      </div>
      <div class="capacity-grid">
        {''.join(agy_cards)}
      </div>
    </div>
    """
    
    # Recent Activity Table
    recent_rows = ledger.activity_recent(15)
    if not recent_rows:
        activity_table = ui.render_empty_state("Chưa có hoạt động", i18n.t("overview.empty_activity"))
    else:
        tbody = []
        for r in recent_rows:
            st = r.get("status")
            st_text, st_fg, st_bg, st_border = i18n.translate_status(st)
            units_text = i18n.fmt_number(r.get("normalized_units")) if r.get("normalized_units") is not None else "—"
            user_name = r.get("display_name") or (r.get("request_id", "")[:12] and "Người dùng") or "—"
            t_str = i18n.fmt_datetime(r.get("started_at"))
            
            tbody.append(f"""<tr>
              <td>{t_str}</td>
              <td><b>{html.escape(agent_label(r.get('agent_id', '')))}</b></td>
              <td>{html.escape(user_name)}</td>
              <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
              <td class="td-num"><b>{units_text}</b></td>
              <td class="text-muted" style="font-size:12px;">{html.escape(r.get('dry_run_verdict') or '—')}</td>
            </tr>""")
            
        activity_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Agent</th>
                <th class="sortable">Người dùng</th>
                <th>Trạng thái</th>
                <th class="th-num sortable">Đơn vị AI</th>
                <th>Mô phỏng (Dry-run)</th>
              </tr>
            </thead>
            <tbody>{''.join(tbody)}</tbody>
          </table>
        </div>"""
    
    activity_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("overview.recent_activity")}</div>
          <div class="section-subtitle">{i18n.t("overview.recent_activity_desc")}</div>
        </div>
      </div>
      {activity_table}
    </div>
    """
    
    capacity_section = codex_accounts_section()
    body = f"{hero_html}\n{kpis_html}\n{mode_banner}\n{trend_section}\n{two_col_section}\n<div style='height:24px;'></div>\n{capacity_section}\n{activity_section}"
    return ui.render_page("Tổng quan", "/", body, i18n.t("app.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 2: NGƯỜI DÙNG (Users)
# ===========================================================================

def v_users(qs: dict) -> str:
    users = ledger.user_summaries()
    unread_alerts = get_unread_alerts_count()
    
    filter_status = (qs.get("status") or ["all"])[0]
    search_q = (qs.get("q") or [""])[0].strip().lower()
    sort_by = (qs.get("sort") or ["used"])[0]
    
    filtered_users = []
    for u in users:
        name = (u.get("display_name") or "").lower()
        pk = (u.get("principal_pubkey") or "").lower()
        if search_q and (search_q not in name and search_q not in pk):
            continue
        upct = u.get("used_pct", 0.0)
        if filter_status == "warning" and upct < 70:
            continue
        if filter_status == "critical" and upct < 95:
            continue
        if filter_status == "normal" and upct >= 70:
            continue
        filtered_users.append(u)
        
    if sort_by == "used":
        filtered_users.sort(key=lambda x: -x.get("used_pct", 0.0))
    elif sort_by == "remaining":
        filtered_users.sort(key=lambda x: x.get("used_pct", 0.0))
    elif sort_by == "requests":
        filtered_users.sort(key=lambda x: -x.get("requests", 0))
    elif sort_by == "name":
        filtered_users.sort(key=lambda x: (x.get("display_name") or "").lower())
    
    def filter_pill(key: str, label: str) -> str:
        active = " active" if filter_status == key else ""
        return f'<a href="/users?status={key}&sort={sort_by}&q={urllib.parse.quote(search_q)}" class="filter-pill{active}">{label}</a>'
    
    filter_bar_html = f"""
    <div class="filter-bar">
      <div class="filter-group">
        {filter_pill("all", i18n.t("users.filter_all"))}
        {filter_pill("normal", i18n.t("users.filter_normal"))}
        {filter_pill("warning", i18n.t("users.filter_warning"))}
        {filter_pill("critical", i18n.t("users.filter_critical"))}
      </div>
      
      <div class="form-inline">
        <input type="text" id="user-search-input" value="{html.escape(search_q)}" 
               placeholder="🔍 {i18n.t('users.search_placeholder')}..." 
               class="input-control" style="width:260px;"
               oninput="filterTable('user-search-input', '#users-data-table')">
      </div>
    </div>
    """
    
    if not filtered_users:
        table_content = ui.render_empty_state("Không tìm thấy người dùng", i18n.t("users.empty_users"))
    else:
        tbody = []
        ucounts = name_counts(filtered_users)
        for u in filtered_users:
            st = u.get("status")
            st_text, st_fg, st_bg, st_border = i18n.translate_threshold(st)
            upct = u.get("used_pct", 0.0)
            rem_pct = u.get("remaining_pct", 100.0 - upct)
            p_label = i18n.translate_profile(u.get("profile_id"))
            short_pk = u["principal_pubkey"][:14] + "…"
            d_name = person_pretty(u, ucounts)
            top_agent = agent_label(u.get("most_used_agent")) if u.get("most_used_agent") else "—"
            
            pbar = ui.render_progress_bar(upct, show_label=False, height=7)
            avatar_html = ui.render_avatar(d_name, 26)
            copyable_pk = ui.render_copyable(u["principal_pubkey"], short_pk)
            
            tbody.append(f"""<tr>
              <td>
                <div style="display:flex;align-items:center;gap:10px;">
                  {avatar_html}
                  <div>
                    <div style="font-weight:700;font-size:14px;">
                      <a href="/users/{u['principal_pubkey']}" style="color:var(--primary);text-decoration:none;">{html.escape(d_name)}</a>
                    </div>
                    <div class="text-muted" style="font-size:11px;margin-top:2px;">{copyable_pk}</div>
                  </div>
                </div>
              </td>
              <td><span class="badge" style="background:var(--bg-subtle);color:var(--text-secondary);border:1px solid var(--border-default);">{html.escape(p_label)}</span></td>
              <td style="min-width:140px;">
                <div style="font-weight:700;margin-bottom:4px;">{upct:.1f}%</div>
                {pbar}
              </td>
              <td class="td-num"><b>{rem_pct:.1f}%</b></td>
              <td class="td-num"><b>{u.get('requests', 0)}</b></td>
              <td>{html.escape(top_agent)}</td>
              <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
            </tr>""")
            
        table_content = f"""<div class="table-wrapper">
          <table id="users-data-table" class="data-table">
            <thead>
              <tr>
                <th class="sortable">{i18n.t("users.col_user")}</th>
                <th>{i18n.t("users.col_profile")}</th>
                <th class="sortable">{i18n.t("users.col_used")}</th>
                <th class="th-num sortable">{i18n.t("users.col_remaining")}</th>
                <th class="th-num sortable">{i18n.t("users.col_requests")}</th>
                <th>{i18n.t("users.col_top_agent")}</th>
                <th>{i18n.t("users.col_status")}</th>
              </tr>
            </thead>
            <tbody>{''.join(tbody)}</tbody>
          </table>
        </div>"""
        
    body = f"""
    {codex_people_html()}
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">Hạn mức nội bộ (không phải quota ChatGPT)</div>
          <div class="section-subtitle">% trên 3 triệu token/ngày do dashboard tự đặt — khác hạn mức 5 giờ / 7 ngày của từng acc Codex. NcThang/Audi = 0% nghĩa là hôm nay chưa gọi, không phải chưa từng dùng.</div>
        </div>
      </div>
      {filter_bar_html}
      {table_content}
    </div>
    """
    return ui.render_page(i18n.t("users.title"), "/users", body, i18n.t("users.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 2B: CHI TIẾT NGƯỜI DÙNG (User Detail)
# ===========================================================================

def v_user_detail(pubkey: str) -> str:
    rows = ledger.user_summaries()
    u = next((x for x in rows if x["principal_pubkey"] == pubkey), None)
    unread_alerts = get_unread_alerts_count()
    
    if not u:
        body = ui.render_empty_state("Không tìm thấy người dùng", i18n.t("errors.user_not_found"))
        return ui.render_page("Chi tiết người dùng", "/users", body, unread_alerts=unread_alerts)
        
    d = ledger.user_detail(u.get("community_id") or "", pubkey)
    upct = u.get("used_pct", 0.0)
    rem_pct = u.get("remaining_pct", 100.0 - upct)
    st_text, st_fg, st_bg, st_border = i18n.translate_threshold(u.get("status"))
    d_name = u.get("display_name") or "Người dùng"
    p_label = i18n.translate_profile(u.get("profile_id"))
    
    progress_bar = ui.render_progress_bar(upct, rem_pct, height=10, show_label=False)
    units_fmt = i18n.fmt_number(u.get("units", 0.0))
    eff_fmt = i18n.fmt_number(u.get("effective_units", 3000000.0))
    avatar_html = ui.render_avatar(d_name, 36)
    copyable_pk = ui.render_copyable(pubkey)
    
    hero_user = f"""
    <div class="hero-card">
      <div class="hero-header">
        <div style="display:flex;align-items:center;gap:14px;">
          {avatar_html}
          <div>
            <div style="display:flex;align-items:center;gap:10px;">
              <div class="hero-value" style="font-size:28px;">{html.escape(d_name)}</div>
              {ui.render_badge(st_text, st_bg, st_fg, st_border)}
            </div>
            <div class="text-muted" style="font-size:12px;margin-top:4px;">Khóa công khai: {copyable_pk}</div>
          </div>
        </div>
        <span class="badge" style="background:var(--bg-subtle);color:var(--text-secondary);border:1px solid var(--border-default);font-size:13px;padding:6px 12px;">
          Gói: <b>{html.escape(p_label)}</b> ({eff_fmt} đơn vị/ngày)
        </span>
      </div>
      
      <div class="hero-value-group">
        <div class="hero-value">{upct:.1f}% <span style="font-size:16px;font-weight:600;color:var(--text-muted);">{i18n.t('users.detail_used_label')}</span></div>
        <div class="hero-remaining">{rem_pct:.1f}% {i18n.t('users.detail_remaining_label')}</div>
      </div>
      
      {progress_bar}
      
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-top:12px;color:var(--text-secondary);">
        <span>Hạn nội bộ hôm nay: <b>{units_fmt}</b> / {eff_fmt} (không phải quota ChatGPT 5h/7 ngày)</span>
        <span>{u.get('requests', 0)} {i18n.t('users.detail_stats_requests')} · {u.get('running', 0)} {i18n.t('users.detail_stats_running')}</span>
      </div>
    </div>
    """
    
    # Assign Profile Form (Owner action)
    current_pid = u.get("profile_id", "full")
    options_html = []
    for pid, fraction in (("full", 1.0), ("high", 0.75), ("standard", 0.5), ("limited", 0.25)):
        selected = " selected" if pid == current_pid else ""
        plabel = i18n.t(f"profiles.{pid}")
        options_html.append(f'<option value="{pid}"{selected}>{plabel}</option>')
        
    assign_box = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.assign_profile_title")}</div>
      <div class="section-subtitle" style="margin-bottom:14px;">{i18n.t("users.assign_profile_desc")}</div>
      
      <form method="post" action="/users/{pubkey}/set-profile" class="form-inline">
        <select name="profile" class="select-control" style="min-width:240px;">
          {''.join(options_html)}
        </select>
        <button class="btn btn-primary">{i18n.t("common.assign")}</button>
      </form>
    </div>
    """
    
    # Usage by Agent
    by_agent_rows = []
    for a in d.get("by_agent", []):
        aname = agent_label(a["agent_id"])
        units_str = i18n.fmt_number(a.get("units", 0.0))
        by_agent_rows.append(f"""<tr>
          <td><b>{html.escape(aname)}</b></td>
          <td class="td-num"><b>{a.get('requests', 0)}</b></td>
          <td class="td-num"><b>{units_str}</b></td>
        </tr>""")
        
    if not by_agent_rows:
        agent_table = "<p class='text-muted'>Chưa có hoạt động qua Agent nào hôm nay.</p>"
    else:
        agent_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th class="sortable">Agent</th><th class="th-num sortable">Số yêu cầu</th><th class="th-num sortable">Đơn vị AI</th></tr></thead>
            <tbody>{''.join(by_agent_rows)}</tbody>
          </table>
        </div>"""
        
    by_agent_section = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.usage_by_agent")}</div>
      <div class="section-subtitle">Chỉ hôm nay (0h ICT) — xem Codex toàn thời gian ở khung phía trên</div>
      <div style="margin-top:12px;">{agent_table}</div>
    </div>
    """
    
    # Recent Requests History
    recent_req_rows = []
    for r in d.get("recent", []):
        st = r.get("status")
        st_text, st_fg, st_bg, st_border = i18n.translate_status(st)
        t_str = i18n.fmt_datetime(r.get("started_at"))
        dur_str = i18n.fmt_duration(r.get("runtime_ms"))
        units_str = i18n.fmt_number(r.get("normalized_units")) if r.get("normalized_units") is not None else "—"
        model_str = r.get("model") or "Chưa xác định"
        
        recent_req_rows.append(f"""<tr>
          <td>{t_str}</td>
          <td><b>{html.escape(agent_label(r.get('agent_id', '')))}</b></td>
          <td>{ui.render_badge(st_text, st_bg, st_fg, st_border)}</td>
          <td>{dur_str}</td>
          <td class="td-num"><b>{units_str}</b></td>
          <td class="text-muted">{html.escape(model_str)}</td>
        </tr>""")
        
    if not recent_req_rows:
        req_table = "<p class='text-muted'>Chưa có lịch sử yêu cầu gần đây.</p>"
    else:
        req_table = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Agent</th>
                <th>Trạng thái</th>
                <th class="sortable">Thời gian chạy</th>
                <th class="th-num sortable">Đơn vị AI</th>
                <th>Mô hình</th>
              </tr>
            </thead>
            <tbody>{''.join(recent_req_rows)}</tbody>
          </table>
        </div>"""
        
    recent_req_section = f"""
    <div class="card-section">
      <div class="section-title">{i18n.t("users.recent_requests")}</div>
      <div style="margin-top:12px;">{req_table}</div>
    </div>
    """
    
    # Collapsible Technical Details
    tech_rows = []
    for r in d.get("recent", []):
        t_str = i18n.fmt_datetime(r.get("started_at"))
        req_copy = ui.render_copyable(r.get('request_id', ''), r.get('request_id', '')[:14] + '…')
        tech_rows.append(f"""<tr>
          <td>{req_copy}</td>
          <td>{t_str}</td>
          <td>{html.escape(r.get('usage_quality') or 'Chưa rõ')}</td>
          <td>{html.escape(r.get('model') or '—')}</td>
          <td class="td-num">{i18n.fmt_number(r.get('normalized_units'))}</td>
        </tr>""")
        
    tech_details_html = f"""
    <details class="custom-details">
      <summary>{i18n.t("common.technical_details")} (Tokens, Models, IDs)</summary>
      <div class="details-content">
        <div style="font-size:12px;margin-bottom:12px;color:var(--text-secondary);">
          <div>Community ID: <code>{html.escape(u.get('community_id', ''))}</code></div>
          <div>Principal Pubkey: <code>{html.escape(pubkey)}</code></div>
        </div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Request ID</th>
                <th>Thời gian</th>
                <th>Độ tin cậy (Quality)</th>
                <th>Model</th>
                <th class="th-num">Normalized Units</th>
              </tr>
            </thead>
            <tbody>{''.join(tech_rows) or '<tr><td colspan="5" class="text-muted">Không có dữ liệu kỹ thuật</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </details>
    """
    
    back_link = f'<div style="margin-bottom:16px;"><a href="/users" class="btn btn-secondary btn-sm">{i18n.t("users.back_to_users")}</a></div>'
    
    body = f"{back_link}\n{hero_user}\n{codex_person_html(pubkey)}\n{assign_box}\n{by_agent_section}\n{recent_req_section}\n{tech_details_html}"
    return ui.render_page(f"Người dùng: {d_name}", "/users", body, f"Chi tiết tài nguyên và mức cấp của {d_name}", unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 3: AGENT (Agents)
# ===========================================================================

def v_agents() -> str:
    agents = ledger.agent_summaries()
    unread_alerts = get_unread_alerts_count()
    acounts = name_counts(agents)
    used = [a for a in agents if a.get("requests", 0) > 0]
    total_units = sum(a.get("units", 0.0) for a in used) or 1.0
    
    rows_html = []
    cards_html = []
    
    for a in sorted(agents, key=lambda x: -x.get("units", 0.0)):
        aname = agent_pretty(a, acounts)
        share_pct = (a.get("units", 0.0) / total_units) * 100.0
        b_kind = a.get("backend_kind")
        # Ban goc: chi harness "agy" moi duoc coi la co han muc nha cung cap.
        # He nay lay han muc tu chinh phien Codex (bin/buzz_quota.py ghi vao
        # account_capacity_snapshots), nen bat ky harness nao co snapshot deu
        # phai hien phan han muc.
        is_agy = bool(a.get("capacity"))

        if is_agy:
            backend_badge = f'<span class="badge" style="background:var(--capacity-subtle);color:var(--capacity);border:1px solid var(--capacity-border);">{backend_label(b_kind)}</span>'
            cap_html = capacity_block(a)
            caps = a.get("capacity") or []
            vals = [c["remaining_percent"] for c in caps if c.get("remaining_percent") is not None]
            lowest = min(vals) if vals else None
            gauge_html = ui.render_radial_gauge(lowest if lowest is not None else 100.0, size=46, color_override="var(--capacity)")
        else:
            backend_badge = f'<span class="badge" style="background:var(--primary-subtle);color:var(--primary);border:1px solid var(--primary-border);">{backend_label(b_kind)}</span>'
            cap_html = f'<span class="text-muted">{i18n.t("agents.local_cli_note")}</span>'
            gauge_html = ui.render_radial_gauge(100.0, size=46, color_override="var(--primary)")
            
        pbar = ui.render_progress_bar(share_pct, show_label=False, height=6, color_override="#2563eb")
        
        if a.get("requests", 0) > 0:
            cards_html.append(f"""
        <div class="kpi-card" style="border-left:3px solid {'var(--capacity)' if is_agy else 'var(--primary)'};">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
              <div style="font-weight:700;font-size:16px;color:var(--text-primary);">{html.escape(aname)}</div>
              <div style="margin-top:4px;">{backend_badge}</div>
            </div>
            {gauge_html}
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:14px;font-size:13px;">
            <span>Thị phần xử lý:</span>
            <b>{share_pct:.1f}%</b>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:13px;">
            <span>Yêu cầu:</span>
            <b>{i18n.fmt_number(a.get('requests', 0))}</b>
          </div>
        </div>
        """)
        
        rows_html.append(f"""<tr>
          <td>
            <div style="font-weight:700;font-size:14px;color:var(--text-primary);">{html.escape(aname)}</div>
            <div style="margin-top:4px;">{backend_badge}</div>
          </td>
          <td><span class="badge" style="background:var(--success-subtle);color:var(--success);border:1px solid var(--success-border);">🟢 {i18n.t("agents.status_active")}</span></td>
          <td style="min-width:140px;">
            <div style="font-weight:700;margin-bottom:4px;">{share_pct:.1f}%</div>
            {pbar}
          </td>
          <td class="td-num"><b>{i18n.fmt_number(a.get('requests', 0))}</b></td>
          <td class="td-num"><b>{i18n.fmt_number(a.get('units', 0.0))}</b></td>
          <td class="td-num"><span style="color:{'var(--danger)' if a.get('failures', 0) > 0 else 'inherit'};font-weight:600;">{a.get('failures', 0)}</span></td>
          <td style="min-width:260px;">{cap_html}</td>
        </tr>""")
        
    cards_section = f"""<div class="kpi-grid" style="margin-bottom:24px;">{''.join(cards_html[:18])}</div>"""
    
    table_content = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th class="sortable">{i18n.t("agents.col_agent")}</th>
            <th>Trạng thái</th>
            <th class="sortable">{i18n.t("agents.col_share")}</th>
            <th class="th-num sortable">{i18n.t("agents.col_requests")}</th>
            <th class="th-num sortable">Đơn vị AI</th>
            <th class="th-num sortable">{i18n.t("agents.col_failures")}</th>
            <th>{i18n.t("agents.col_capacity")}</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>"""
    
    note_box = f"""
    <div class="alert-box alert-info" style="margin-top:20px;">
      <div>
        <b>Phân biệt quan trọng:</b> {i18n.t("agents.distinction_note")}
      </div>
    </div>
    """
    
    body = f"""
    {cards_section}
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("agents.title")}</div>
          <div class="section-subtitle">{i18n.t("agents.subtitle")}</div>
        </div>
      </div>
      {table_content}
      {note_box}
    </div>
    """
    return ui.render_page(i18n.t("agents.title"), "/agents", body,
                          f"{len(used)} agent có lượt / {len(agents)} trong state · trùng tên gắn community",
                          unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 4: PHÂN TÍCH HẠN MỨC (Calibration)
# ===========================================================================

def v_calibration(qs: dict) -> str:
    # Gia tri that de mo phong bam theo, thay vi con so 3.000.000 ghi cung.
    sim_base = int(float(ledger.get_setting("base_units_daily", "3000000") or 3000000))
    sim_base_fmt = i18n.fmt_number(sim_base)
    sim_base_short = "%.1fM" % (sim_base / 1_000_000.0)
    window = (qs.get("window") or ["today"])[0]
    unread_alerts = get_unread_alerts_count()
    
    try:
        s, e, label = analytics.window_bounds(
            window, (qs.get("from") or [None])[0], (qs.get("to") or [None])[0])
    except ValueError:
        body = ui.render_error_state("Khoảng thời gian không hợp lệ", i18n.t("errors.custom_date_error"))
        return ui.render_page(i18n.t("calibration.title"), "/calibration", body, unread_alerts=unread_alerts)
        
    conf = analytics.data_confidence()
    mq = analytics.measurement_quality(s, e)
    dist = analytics.request_distribution(s, e)
    share = analytics.usage_share(s, e)
    base = analytics.base_allowance_calibration()
    profiles = analytics.profile_recommendations()
    ready = analytics.hard_limit_readiness()
    dry = analytics.concurrency_dry_run(s, e)
    
    def win_pill(key: str) -> str:
        active = " active" if key == window else ""
        return f'<a href="/calibration?window={key}" class="filter-pill{active}">{i18n.t(f"windows.{key}")}</a>'
        
    window_bar = f"""
    <div class="filter-bar" style="margin-bottom:20px;">
      <div class="filter-group">
        {win_pill("today")}
        {win_pill("24h")}
        {win_pill("3d")}
        {win_pill("7d")}
        {win_pill("30d")}
      </div>
      
      <form method="get" action="/calibration" class="form-inline">
        <input type="hidden" name="window" value="custom">
        <input type="date" name="from" class="input-control" style="width:140px;" placeholder="YYYY-MM-DD">
        <span>→</span>
        <input type="date" name="to" class="input-control" style="width:140px;" placeholder="YYYY-MM-DD">
        <button class="btn btn-secondary btn-sm">{i18n.t("common.apply")}</button>
      </form>
    </div>
    """
    
    # 1. Data Confidence Banner
    conf_level = conf.get("level", "INSUFFICIENT")
    conf_text, conf_fg, conf_bg, conf_border = i18n.translate_confidence(conf_level)
    conf_badge = ui.render_badge(conf_text, conf_bg, conf_fg, conf_border)
    
    confidence_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.confidence_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.confidence_insufficient_desc")}</div>
        </div>
        <div>{conf_badge}</div>
      </div>
      
      <div class="kpi-grid" style="margin-bottom:0;">
        {ui.render_kpi_card(i18n.t("calibration.obs_period"), f"{conf.get('observation_days', 0.0):.1f} ngày", f"Kể từ {i18n.fmt_datetime(conf.get('observation_start'))}")}
        {ui.render_kpi_card(i18n.t("calibration.completed_reqs"), str(conf.get("completed_requests", 0)), f"Thất bại: {conf.get('failed_requests', 0)}")}
        {ui.render_kpi_card(i18n.t("calibration.active_users"), str(conf.get("active_users", 0)), f"Tỷ lệ đo thực tế: {conf.get('actual_share', 100.0):.1f}%")}
        {ui.render_kpi_card("Khuyến nghị", "3–7 ngày", i18n.t("calibration.min_recommended"))}
      </div>
    </div>
    """
    
    # 2. Measurement Quality
    cov_val = mq.get("coverage")
    cov_str = f"{cov_val:.1f}%" if cov_val is not None else "Chưa có dữ liệu"
    
    agent_mq_rows = []
    for aid, d in sorted(mq.get("agents", {}).items()):
        c_pct = d.get("coverage")
        c_str = f"{c_pct:.1f}%" if c_pct is not None else "Chưa có dữ liệu"
        pbar = ui.render_progress_bar(c_pct or 0.0, show_label=False, height=6, color_override="var(--success)") if c_pct is not None else "—"
        agent_mq_rows.append(f"""<tr>
          <td><b>{html.escape(agent_label(aid))}</b></td>
          <td class="td-num"><b>{d.get('actual', 0)}</b></td>
          <td class="td-num">{d.get('unknown', 0)}</td>
          <td style="min-width:140px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
              <span><b>{c_str}</b></span>
            </div>
            {pbar if isinstance(pbar, str) else ''}
          </td>
        </tr>""")
        
    quality_table = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead><tr><th class="sortable">Agent</th><th class="th-num sortable">{i18n.t("common.actual")}</th><th class="th-num sortable">{i18n.t("common.unknown")}</th><th>{i18n.t("calibration.coverage_label")}</th></tr></thead>
        <tbody>{''.join(agent_mq_rows) or '<tr><td colspan="4" class="text-muted">Chưa có yêu cầu AI nào trong khoảng thời gian này.</td></tr>'}</tbody>
      </table>
    </div>"""
    
    quality_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.measurement_quality_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.quality_note")}</div>
        </div>
        <span class="badge" style="background:var(--success-subtle);color:var(--success);border:1px solid var(--success-border);">
          Độ phủ thực tế: {cov_str}
        </span>
      </div>
      {quality_table}
    </div>
    """
    
    # 3. Request Distribution
    ds = dist.get("summary", {})
    if not ds.get("count"):
        dist_content = "<p class='text-muted'>Chưa có yêu cầu hoàn tất nào trong khoảng thời gian này.</p>"
    else:
        dist_kpis = f"""
        <div class="kpi-grid">
          {ui.render_kpi_card(i18n.t("calibration.median_label"), i18n.fmt_units(ds.get('median'), short=True), f"P50: {i18n.fmt_number(ds.get('median'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.p75_label"), i18n.fmt_units(ds.get('p75'), short=True), f"P75: {i18n.fmt_number(ds.get('p75'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.p90_label"), i18n.fmt_units(ds.get('p90'), short=True), f"P90: {i18n.fmt_number(ds.get('p90'))} đơn vị")}
          {ui.render_kpi_card(i18n.t("calibration.max_label"), i18n.fmt_units(ds.get('max'), short=True), f"Lớn nhất: {i18n.fmt_number(ds.get('max'))} đơn vị")}
        </div>
        """
        bucket_rows = []
        for bk in dist.get("buckets", []):
            sh = bk.get("share", 0.0)
            pbar = ui.render_progress_bar(sh, show_label=False, height=6)
            bname = bk.get("name")
            if bname == "typical (≤ P50)":
                bname = "Thông thường (≤ P50)"
            elif bname == "moderate (P50–P75)":
                bname = "Khá lớn (P50–P75)"
            elif bname == "large (P75–P90)":
                bname = "Lớn (P75–P90)"
            elif bname == "very large (> P90)":
                bname = "Rất lớn (> P90)"
                
            bucket_rows.append(f"""<tr>
              <td><b>{html.escape(bname)}</b></td>
              <td style="min-width:140px;">
                <div style="font-weight:700;margin-bottom:4px;">{sh:.1f}%</div>
                {pbar}
              </td>
              <td class="td-num"><b>{bk.get('count', 0)}</b></td>
              <td class="td-num">≤ {i18n.fmt_number(bk.get('raw_upper'))} đơn vị</td>
            </tr>""")
            
        bucket_table = f"""<div class="table-wrapper" style="margin-top:16px;">
          <table class="data-table">
            <thead><tr><th class="sortable">Phân nhóm</th><th class="sortable">Tỷ lệ yêu cầu</th><th class="th-num sortable">Số lượng</th><th class="th-num sortable">Ngưỡng trên</th></tr></thead>
            <tbody>{''.join(bucket_rows)}</tbody>
          </table>
        </div>"""
        dist_content = f"{dist_kpis}\n{bucket_table}"
        
    dist_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.request_dist_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.request_dist_desc")}</div>
        </div>
      </div>
      {dist_content}
    </div>
    """
    
    # 4. Interactive Policy Simulator Sandbox
    sim_section = f"""
    <div class="card-section" style="border:1px solid var(--primary-border);">
      <div class="section-header">
        <div>
          <div class="section-title">🧪 Trình mô phỏng Chính sách & Hạn ngạch (Policy Sandbox)</div>
          <div class="section-subtitle">Kéo thanh trượt để thử nghiệm tác động khi thay đổi Hạn ngạch cơ sở hàng ngày đối với người dùng</div>
        </div>
      </div>
      
      <div style="background:var(--bg-subtle);padding:18px 22px;border-radius:var(--radius-lg);margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-weight:600;color:var(--text-primary);">Hạn mức cơ sở mô phỏng:</span>
          <span id="sim-val-display" style="font-size:18px;font-weight:800;color:var(--primary);">{sim_base_fmt} đơn vị</span>
        </div>
        <input type="range" id="sim-slider" min="500000" max="10000000" step="500000" value="{sim_base}" 
               style="width:100%;cursor:pointer;" oninput="updateSimulation(this.value)">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-muted);margin-top:6px;">
          <span>500K</span>
          <span>{sim_base_short} (hiện tại)</span>
          <span>5.0M</span>
          <span>10.0M</span>
        </div>
      </div>
      
      <div id="sim-result-box" style="font-size:13px;color:var(--text-secondary);line-height:1.6;">
        💡 Hạn ngạch hiện tại <b>{sim_base_fmt} đơn vị/ngày</b> — suy ra từ hạn mức thật của nhà cung cấp, không phải con số đặt tay.
      </div>
    </div>
    
    <script>
    function updateSimulation(val) {{
      const num = parseInt(val, 10);
      document.getElementById('sim-val-display').innerText = num.toLocaleString('vi-VN') + ' đơn vị';
      const box = document.getElementById('sim-result-box');
      if (num < 1000000) {{
        box.innerHTML = '⚠️ Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Mức tiêu thụ thực tế có thể chạm ngưỡng Cảnh báo (70%) đối với các truy vấn phức tạp hoặc prompt dài.';
      }} else if (num >= 5000000) {{
        box.innerHTML = '✨ Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Dư địa phân bổ rất thoải mái, phù hợp mở rộng thêm người dùng mới mà không lo chạm ngưỡng.';
      }} else {{
        box.innerHTML = '💡 Với hạn mức <b>' + num.toLocaleString('vi-VN') + ' đơn vị</b>: Tỷ lệ phân bổ tối ưu và an toàn cho toàn bộ thành viên hiện tại.';
      }}
    }}
    </script>
    """
    
    # 5. Base Allowance Calibration
    reasons_html = "".join(f"<li style='margin-bottom:4px;'>{html.escape(i18n.translate_reason(r))}</li>" for r in base.get("reasons", []))
    base_kpis = f"""
    <div class="kpi-grid">
      {ui.render_kpi_card(i18n.t("calibration.current_base"), f"{i18n.fmt_number(base.get('current_base'))} đơn vị", i18n.t("calibration.current_base_note"))}
      {ui.render_kpi_card(i18n.t("calibration.assessment_label"), "Chưa đủ dữ liệu", "Cần thêm dữ liệu quan sát")}
      {ui.render_kpi_card(i18n.t("calibration.recommendation_label"), "Tiếp tục quan sát", "Độ tin cậy: Thấp")}
    </div>
    """
    
    base_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.base_allowance_title")}</div>
          <div class="section-subtitle">Đánh giá hạn mức cơ sở dựa trên dữ liệu tiêu thụ thực tế</div>
        </div>
      </div>
      {base_kpis}
      <div style="font-size:13px;color:var(--text-secondary);background:var(--bg-subtle);padding:14px;border-radius:var(--radius-md);margin-top:12px;">
        <ul style="padding-left:20px;">{reasons_html}</ul>
      </div>
    </div>
    """
    
    # 6. Hard Limit Readiness
    ready_verdict = ready.get("verdict", "NOT READY")
    v_badge = ui.render_badge("CHƯA SẴN SÀNG", "var(--danger-subtle)", "var(--danger)", "var(--danger-border)") if ready_verdict == "NOT READY" else ui.render_badge("ĐÃ SẴN SÀNG", "var(--success-subtle)", "var(--success)", "var(--success-border)")
    
    ready_rows = []
    for c in ready.get("checks", []):
        st = c.get("status")
        st_t, st_fg, st_bg, st_b = i18n.translate_readiness_status(st)
        item_vn = i18n.translate_readiness_item(c.get("item", ""))
        evidence_vn = i18n.translate_evidence(c.get("evidence", ""))
        ready_rows.append(f"""<tr>
          <td><b>{html.escape(item_vn)}</b></td>
          <td>{ui.render_badge(st_t, st_bg, st_fg, st_b)}</td>
          <td class="text-muted" style="font-size:12px;">{html.escape(evidence_vn)}</td>
        </tr>""")
        
    readiness_table = f"""<div class="table-wrapper">
      <table class="data-table">
        <thead><tr><th>Tiêu chí an toàn</th><th>Trạng thái</th><th>Bằng chứng kỹ thuật</th></tr></thead>
        <tbody>{''.join(ready_rows)}</tbody>
      </table>
    </div>"""
    
    readiness_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.hard_limit_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.hard_limit_note")}</div>
        </div>
        <div>{v_badge}</div>
      </div>
      {readiness_table}
    </div>
    """
    
    # 7. Concurrency Dry-Run
    dry_counts = dry.get("counts", {})
    dry_note_vn = i18n.translate_dry_run_note(dry.get("note", ""))
    dry_kpis = f"""
    <div class="kpi-grid" style="margin-bottom:12px;">
      {ui.render_kpi_card("Đã mô phỏng", str(dry.get("replayed", 0)), "Yêu cầu hoàn tất trong kỳ")}
      {ui.render_kpi_card(i18n.t("calibration.would_allow"), str(dry_counts.get("WOULD_ALLOW", 0)), "Cho phép xử lý", badge_html=ui.render_badge("Bình thường", "var(--success-subtle)", "var(--success)"))}
      {ui.render_kpi_card(i18n.t("calibration.would_warn"), str(dry_counts.get("WOULD_WARN", 0)), "Gửi cảnh báo", badge_html=ui.render_badge("Cảnh báo", "var(--warning-subtle)", "var(--warning)"))}
      {ui.render_kpi_card(i18n.t("calibration.would_block"), str(dry_counts.get("WOULD_BLOCK", 0)), "Chặn thực thi", badge_html=ui.render_badge("Chặn", "var(--danger-subtle)", "var(--danger)"))}
    </div>
    <div class="text-muted" style="font-size:12px;">{html.escape(dry_note_vn)}</div>
    """
    
    dry_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("calibration.dry_run_title")}</div>
          <div class="section-subtitle">{i18n.t("calibration.dry_run_desc")}</div>
        </div>
      </div>
      {dry_kpis}
    </div>
    """
    
    body = f"{window_bar}\n{confidence_section}\n{quality_section}\n{sim_section}\n{dist_section}\n{base_section}\n{readiness_section}\n{dry_section}"
    return ui.render_page(i18n.t("calibration.title"), "/calibration", body, i18n.t("calibration.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 5: CẢNH BÁO (Alerts)
# ===========================================================================

def v_alerts(qs: dict) -> str:
    tab = (qs.get("tab") or ["all"])[0]
    filter_sev = (qs.get("sev") or ["all"])[0]
    
    all_alerts = ledger.owner_alerts_recent(100)
    unread_alerts = sum(1 for a in all_alerts if a.get("status") != "acknowledged")
    
    filtered = []
    for a in all_alerts:
        st = a.get("status")
        if tab == "open" and st == "acknowledged":
            continue
        if tab == "acknowledged" and st != "acknowledged":
            continue
        if filter_sev != "all" and a.get("severity") != filter_sev:
            continue
        filtered.append(a)
        
    def tab_link(key: str, label: str, count: int) -> str:
        active = " active" if tab == key else ""
        return f'<a href="/alerts?tab={key}&sev={filter_sev}" class="tab-item{active}">{label} ({count})</a>'
        
    tabs_html = f"""
    <div class="tabs-nav">
      {tab_link("all", i18n.t("alerts.tab_all"), len(all_alerts))}
      {tab_link("open", i18n.t("alerts.tab_open"), unread_alerts)}
      {tab_link("acknowledged", i18n.t("alerts.tab_acknowledged"), len(all_alerts) - unread_alerts)}
    </div>
    """
    
    if not filtered:
        alerts_content = ui.render_empty_state("Không có cảnh báo nào", i18n.t("alerts.empty_alerts"))
    else:
        rows = []
        for a in filtered:
            sev = a.get("severity")
            sev_text, sev_fg, sev_bg, sev_border = i18n.translate_severity(sev)
            kind_vn = i18n.translate_anomaly_kind(a.get("kind"))
            subj = a.get("subject_label") or a.get("subject_id") or "Hệ thống"
            reason_vn = i18n.translate_reason(a.get("reason", ""))
            f_seen = i18n.fmt_datetime(a.get("first_seen"))
            l_seen = i18n.fmt_datetime(a.get("last_seen"))
            occ = a.get("occurrences", 1)
            is_ack = a.get("status") == "acknowledged"
            
            if is_ack:
                action_btn = '<span class="text-muted" style="font-size:12px;">✓ Đã xác nhận</span>'
            else:
                action_btn = f"""<form method="post" action="/alerts/{a['id']}/ack" class="form-inline">
                  <button class="btn btn-secondary btn-sm">{i18n.t("alerts.btn_ack")}</button>
                </form>"""
                
            rows.append(f"""<tr>
              <td>
                <div style="font-weight:700;font-size:13px;">{html.escape(kind_vn)}</div>
                <div class="text-muted font-mono" style="font-size:11px;">{html.escape(a.get('kind', ''))}</div>
              </td>
              <td>{ui.render_badge(sev_text, sev_bg, sev_fg, sev_border)}</td>
              <td><b>{html.escape(subj)}</b></td>
              <td>{html.escape(reason_vn)}</td>
              <td>{f_seen}</td>
              <td>{l_seen}</td>
              <td class="td-num"><b>{occ}</b></td>
              <td>{action_btn}</td>
            </tr>""")
            
        alerts_content = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">{i18n.t("alerts.col_type")}</th>
                <th>{i18n.t("alerts.col_severity")}</th>
                <th class="sortable">{i18n.t("alerts.col_subject")}</th>
                <th>{i18n.t("alerts.col_reason")}</th>
                <th class="sortable">{i18n.t("alerts.col_first_seen")}</th>
                <th class="sortable">{i18n.t("alerts.col_last_seen")}</th>
                <th class="th-num sortable">{i18n.t("alerts.col_count")}</th>
                <th>{i18n.t("alerts.col_action")}</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>"""
        
    owner_alerts_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("alerts.owner_alerts_title")}</div>
          <div class="section-subtitle">{i18n.t("alerts.owner_alerts_desc")}</div>
        </div>
      </div>
      {tabs_html}
      {alerts_content}
    </div>
    """
    
    thresh_alerts = ledger.alerts_recent(50)
    if not thresh_alerts:
        thresh_content = f"<p class='text-muted'>{i18n.t('alerts.empty_thresholds')}</p>"
    else:
        t_rows = []
        for t in thresh_alerts:
            th_name = t.get("threshold")
            th_text, th_fg, th_bg, th_border = i18n.translate_threshold(th_name)
            who = t.get("display_name") or (t.get("principal_pubkey", "")[:16] + "…")
            t_str = i18n.fmt_datetime(t.get("triggered_at"))
            deliv = "Có" if t.get("delivered") else "Không"
            
            t_rows.append(f"""<tr>
              <td>{t_str}</td>
              <td><b>{html.escape(who)}</b></td>
              <td>{ui.render_badge(th_text, th_bg, th_fg, th_border)}</td>
              <td>{deliv}</td>
            </tr>""")
            
        thresh_content = f"""<div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable">Thời gian</th>
                <th class="sortable">Người dùng</th>
                <th>{i18n.t("alerts.col_threshold")}</th>
                <th>{i18n.t("alerts.col_delivered")}</th>
              </tr>
            </thead>
            <tbody>{''.join(t_rows)}</tbody>
          </table>
        </div>"""
        
    threshold_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("alerts.threshold_alerts_title")}</div>
          <div class="section-subtitle">{i18n.t("alerts.threshold_alerts_desc")}</div>
        </div>
      </div>
      {thresh_content}
    </div>
    """
    
    body = f"{owner_alerts_section}\n{threshold_section}"
    return ui.render_page(i18n.t("alerts.title"), "/alerts", body, i18n.t("alerts.subtitle"), unread_alerts=unread_alerts)


# ===========================================================================
# PAGE 6: CÀI ĐẶT (Settings)
# ===========================================================================

def v_settings() -> str:
    unread_alerts = get_unread_alerts_count()
    
    keys = [
        "mode", "warn_only_enabled", "hard_limit_enabled", "soft_limit_enabled",
        "base_units_daily", "threshold_warning", "threshold_high",
        "threshold_critical", "threshold_exhausted", "identity_freshness_seconds",
        "capacity_poll_interval_seconds", "normalization_version", "usage_command",
        "owner_pubkeys"
    ]
    
    settings_dict = {k: ledger.get_setting(k) for k in keys}
    last = REFRESH.get("last") or 0
    last_txt = dt.datetime.fromtimestamp(last).strftime("%d/%m %H:%M:%S") if last else "chưa chạy"
    quota_st = "đang đọc" if REFRESH.get("running") else ("ổn" if REFRESH.get("ok") else "lỗi")
    clast = COLLECT.get("last") or 0
    clast_txt = dt.datetime.fromtimestamp(clast).strftime("%d/%m %H:%M:%S") if clast else "chưa chạy"
    collect_st = "đang thu thập" if COLLECT.get("running") else ("ổn" if COLLECT.get("ok") else "lỗi")
    cn = COLLECT.get("n_req")
    collect_sub = "Tự chạy mỗi 10 phút · trạng thái: " + collect_st
    if cn is not None:
        collect_sub = ("%s lượt trong sổ · " % i18n.fmt_number(cn)) + collect_sub
    public = ui.request_public()
    owner = ui.request_owner()

    publish_section = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">Công khai & vận hành</div>
          <div class="section-subtitle">Dashboard lắng nghe loopback · Funnel cổng 8443 (443 giữ /dim0 /fairies)</div>
        </div>
      </div>
      <div class="kpi-grid" style="margin-bottom:0;">
        {ui.render_kpi_card("Chủ sở hữu", html.escape(owner), "Pubkey trong settings.owner_pubkeys")}
        {ui.render_kpi_card("Xem local", "8787", html.escape(LOCAL_URL))}
        {ui.render_kpi_card("Xem internet", "8443", html.escape(FUNNEL_URL))}
        {ui.render_kpi_card("Đọc hạn mức Codex", last_txt, "Live API mỗi 5 phút · trạng thái: " + quota_st)}
        {ui.render_kpi_card("Thu thập lượt", clast_txt, collect_sub)}
      </div>
      <div class="text-muted" style="margin-top:14px;font-size:13px;line-height:1.5;">
        Link gửi người ngoài: <a href="{html.escape(FUNNEL_URL)}/" style="color:var(--primary);">{html.escape(FUNNEL_URL)}/</a>
        · bản Funnel chỉ đọc (đổi cài đặt bị chặn).<br>
        Máy này: <a href="{html.escape(LOCAL_URL)}" style="color:var(--primary);">{html.escape(LOCAL_URL)}</a>
        · tự bật lại sau đăng nhập Windows (task BuzzUsageDashboard).
        Collector đọc mọi file trong custom_harnesses (Codex / Claude / Hermes) nên harness mới không bị miss.
      </div>
    </div>
    """
    
    mode_banner = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title" style="text-transform:uppercase;letter-spacing:0.04em;font-size:13px;color:var(--text-secondary);">{i18n.t("settings.mode_box_title")}</div>
          <div class="section-subtitle">{i18n.t("settings.mode_explanation")}</div>
        </div>
      </div>
      
      <div class="kpi-grid" style="margin-bottom:0;">
        {ui.render_kpi_card(i18n.t("settings.mode_meter"), i18n.t("settings.status_on"), "Ghi nhận mọi lượt sử dụng", badge_html=ui.render_badge("BẬT", "var(--success-subtle)", "var(--success)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_warn"), i18n.t("settings.status_on"), "Gửi cảnh báo qua kênh", badge_html=ui.render_badge("BẬT", "var(--success-subtle)", "var(--success)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_soft"), i18n.t("settings.status_off"), "Chưa áp dụng", badge_html=ui.render_badge("TẮT", "var(--bg-subtle)", "var(--text-muted)"))}
        {ui.render_kpi_card(i18n.t("settings.mode_hard"), i18n.t("settings.status_off"), "Giai đoạn quan sát", badge_html=ui.render_badge("TẮT", "var(--bg-subtle)", "var(--text-muted)"))}
      </div>
    </div>
    """
    
    if public:
        policy_form = """
    <div class="card-section">
      <div class="section-title">Chính sách hạn mức</div>
      <p class="text-muted" style="margin-top:8px;">Bản xem công khai — không đổi ngưỡng từ internet. Dùng bản local trên máy chủ.</p>
    </div>
    """
    else:
        policy_form = f"""
    <div class="card-section">
      <div class="section-header">
        <div>
          <div class="section-title">{i18n.t("settings.section_policy")}</div>
          <div class="section-subtitle">Điều chỉnh các thông số hạn mức và ngưỡng cảnh báo dành cho chủ sở hữu</div>
        </div>
      </div>
      
      <form method="post" action="/settings/policy">
        <div style="margin-bottom:18px;">
          <label style="display:block;font-weight:600;font-size:13px;margin-bottom:6px;">{i18n.t("settings.base_units_label")}</label>
          <input type="number" name="base_units_daily" class="input-control" value="{settings_dict.get('base_units_daily', '3000000')}" style="width:300px;">
          <div class="text-muted" style="font-size:12px;margin-top:4px;">{i18n.t("settings.base_units_help")}</div>
        </div>
        
        <div style="margin-bottom:20px;">
          <label style="display:block;font-weight:600;font-size:13px;margin-bottom:6px;">{i18n.t("settings.thresholds_label")}</label>
          <div style="display:flex;gap:16px;flex-wrap:wrap;">
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_warning")} (%)</span>
              <input type="number" name="th_w" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_warning', '70')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_high")} (%)</span>
              <input type="number" name="th_h" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_high', '85')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_critical")} (%)</span>
              <input type="number" name="th_c" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_critical', '95')}">
            </div>
            <div>
              <span class="text-muted" style="font-size:12px;display:block;">{i18n.t("settings.th_exhausted")} (%)</span>
              <input type="number" name="th_e" class="input-control" style="width:100px;" value="{settings_dict.get('threshold_exhausted', '100')}">
            </div>
          </div>
        </div>
        
        <button class="btn btn-primary">{i18n.t("settings.btn_save_policy")}</button>
      </form>
    </div>
    """
    
    owner_pk = settings_dict.get('owner_pubkeys', '')
    copy_pk_html = ui.render_copyable(owner_pk)
    
    timing_access = f"""
    <div class="grid-2col">
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-title">{i18n.t("settings.section_timing")}</div>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px;font-size:13px;">
          <div>
            <div class="text-muted">{i18n.t("settings.reset_time_label")}</div>
            <div style="font-weight:600;">{i18n.t("settings.reset_time_val")}</div>
          </div>
          <div>
            <div class="text-muted">{i18n.t("settings.freshness_label")}</div>
            <div style="font-weight:600;">{settings_dict.get('identity_freshness_seconds', '900')} giây (15 phút)</div>
          </div>
          <div>
            <div class="text-muted">{i18n.t("settings.poll_interval_label")}</div>
            <div style="font-weight:600;">300 giây (5 phút) — đọc hạn mức Codex</div>
          </div>
        </div>
      </div>
      
      <div class="card-section" style="margin-bottom:0;">
        <div class="section-title">{i18n.t("settings.section_access")}</div>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px;font-size:13px;">
          <div>
            <div class="text-muted">{i18n.t("settings.owner_pubkeys_label")}</div>
            <div style="margin-top:6px;">{copy_pk_html}</div>
          </div>
          <div style="margin-top:8px;">
            <div class="text-muted">Lệnh kiểm tra mức sử dụng (/usage)</div>
            <div style="font-weight:600;margin-top:2px;"><code>{html.escape(settings_dict.get('usage_command', '/usage'))}</code> (Không tốn token AI)</div>
          </div>
        </div>
      </div>
    </div>
    """
    
    debug_rows = []
    for k in keys:
        val = settings_dict.get(k)
        debug_rows.append(f"""<tr>
          <td class="font-mono"><b>{html.escape(k)}</b></td>
          <td class="font-mono">{html.escape(str(val))}</td>
        </tr>""")
        
    debug_section = f"""
    <details class="custom-details" style="margin-top:24px;">
      <summary>{i18n.t("settings.debug_section")}</summary>
      <div class="details-content" style="padding:0;">
        <table class="data-table">
          <thead><tr><th>{i18n.t("settings.col_key")}</th><th>{i18n.t("settings.col_val")}</th></tr></thead>
          <tbody>{''.join(debug_rows)}</tbody>
        </table>
      </div>
    </details>
    """
    
    body = f"{publish_section}\n{mode_banner}\n{policy_form}\n{timing_access}\n{debug_section}"
    return ui.render_page(i18n.t("settings.title"), "/settings", body, i18n.t("settings.subtitle"), unread_alerts=unread_alerts)


def v_messages(qs: Dict[str, List[str]]) -> str:
    unread_alerts = get_unread_alerts_count()
    messages = MSG_HUB.get_sorted_messages()

    comm_colors = {
        "dukickk": ("#3b82f6", "rgba(59,130,246,0.12)", "rgba(59,130,246,0.3)"),
        "platogroup": ("#a855f7", "rgba(168,85,247,0.12)", "rgba(168,85,247,0.3)"),
        "ode": ("#f59e0b", "rgba(245,158,11,0.12)", "rgba(245,158,11,0.3)"),
        "ncthang04": ("#10b981", "rgba(16,185,129,0.12)", "rgba(16,185,129,0.3)"),
    }

    rows_html = []
    for m in messages:
        time_str = m.get("time", "")
        comm = m.get("community", "Buzz")
        ch = m.get("channel", "")
        sender = m.get("sender", "")
        cnt = m.get("content", "")
        is_mention = m.get("is_mention", False)

        color, bg, border = comm_colors.get(comm.lower(), ("#94a3b8", "rgba(148,163,184,0.12)", "rgba(148,163,184,0.3)"))
        comm_badge = f'<span class="badge" style="background:{bg};color:{color};border:1px solid {border};font-weight:600;">{html.escape(comm.upper())}</span>'
        mention_badge = '<span class="badge" style="background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);margin-left:6px;">@Mention</span>' if is_mention else ""

        rows_html.append(f"""<tr>
          <td style="white-space:nowrap;font-size:12px;color:var(--text-muted);">{html.escape(time_str)}</td>
          <td>{comm_badge}</td>
          <td><b>#{html.escape(ch)}</b>{mention_badge}</td>
          <td><span style="font-weight:600;color:var(--text-primary);">{html.escape(sender)}</span></td>
          <td style="font-size:13px;line-height:1.4;">{html.escape(cnt)}</td>
        </tr>""")

    tbody = "".join(rows_html) if rows_html else '<tr><td colspan="5" style="text-align:center;padding:36px;color:var(--text-muted);">Chưa có tin nhắn mới nào được ghi nhận. Cứ mỗi khi có tin nhắn tới từ bất kỳ nhóm/kênh nào, nội dung sẽ hiển thị ngay tại đây.</td></tr>'

    stats_cards = f"""
    <div class="metrics-grid" style="margin-bottom:24px;">
      <div class="metric-card">
        <div class="metric-label">Tổng tin nhắn nhận được</div>
        <div class="metric-value">{len(messages)}</div>
        <div class="metric-subtext">Tổng hợp từ tất cả Workspace</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Số Workspace hoạt động</div>
        <div class="metric-value">4</div>
        <div class="metric-subtext">dukickk, platogroup, ode, ncthang04</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Chuông báo âm thanh</div>
        <div class="metric-value" style="color:var(--success);">BẬT 🔔</div>
        <div class="metric-subtext">Giọng ElevenLabs tiếng Việt</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Popup thông báo màn hình</div>
        <div class="metric-value" style="color:var(--primary);">BẬT 📢</div>
        <div class="metric-subtext">Hiển thị tên nhóm, kênh & người gửi</div>
      </div>
    </div>
    """

    table_card = f"""
    <div class="card" style="margin-top:20px;">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
        <div>
          <div class="card-title">Hộp thư & Luồng hoạt động tin nhắn tập trung</div>
          <div class="card-subtitle">Cập nhật liên tục — Biết ngay nhóm nào và kênh nào vừa có tin nhắn</div>
        </div>
        <div style="display:flex;gap:10px;align-items:center;">
          <input type="text" id="filter-messages" placeholder="🔍 Tìm kiếm theo kênh, người gửi, nội dung..." 
                 oninput="filterTable('filter-messages', '#messages-table')" 
                 style="padding:8px 14px;border-radius:8px;border:1px solid var(--border-default);background:var(--bg-surface);color:var(--text-primary);font-size:13px;min-width:280px;">
        </div>
      </div>
      <div class="table-wrapper">
        <table class="data-table" id="messages-table">
          <thead>
            <tr>
              <th style="width:130px;">Thời gian</th>
              <th style="width:150px;">Nhóm / Workspace</th>
              <th style="width:200px;">Kênh / Channel</th>
              <th style="width:170px;">Người gửi</th>
              <th>Nội dung tin nhắn</th>
            </tr>
          </thead>
          <tbody>
            {tbody}
          </tbody>
        </table>
      </div>
    </div>
    """

    body = f"{stats_cards}\n{table_card}"
    return ui.render_page("Hộp thư & Hoạt động", "/messages", body, "Bảng theo dõi tin nhắn tập trung từ tất cả các nhóm Buzz", unread_alerts=unread_alerts)


def generate_ai_catchup_summary() -> Dict[str, Any]:
    msgs = MSG_HUB.get_sorted_messages()
    unreads = [m for m in msgs if m.get("is_unread")]
    has_unread = True
    if not unreads:
        unreads = msgs[:8]
        has_unread = False

    if not unreads:
        return {
            "has_unread": False,
            "total_unread": 0,
            "total_channels": 0,
            "bulletins": []
        }

    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for m in unreads:
        comm = m.get("community") or "Chung"
        chan = m.get("channel") or "general"
        if comm not in groups:
            groups[comm] = {}
        if chan not in groups[comm]:
            groups[comm][chan] = []
        groups[comm][chan].append(m)

    bulletins = []
    for comm, ch_map in groups.items():
        for chan, items in ch_map.items():
            items.sort(key=lambda x: x.get("timestamp", 0))
            senders = list(dict.fromkeys(it.get("sender", "Thành viên") for it in items))
            senders_str = ", ".join(senders[:3])
            latest_m = items[-1]
            raw_cnt = latest_m.get("content", "").strip()
            preview = raw_cnt.replace("\n", " ")
            if len(preview) > 130:
                preview = preview[:127] + "..."
            bulletins.append({
                "community": comm,
                "channel": chan,
                "count": len(items),
                "senders": senders_str,
                "latest_preview": preview,
                "last_timestamp": latest_m.get("timestamp", 0),
                "channel_id": latest_m.get("channel_id") or chan,
                "is_dm": bool(latest_m.get("is_dm") or "dm" in chan.lower())
            })

    bulletins.sort(key=lambda b: (b["count"], b["last_timestamp"]), reverse=True)

    return {
        "has_unread": has_unread,
        "total_unread": len(unreads) if has_unread else 0,
        "total_channels": len(bulletins),
        "bulletins": bulletins
    }

# ===========================================================================
# HTTP Server Handler
# ===========================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep dashboard logs free of request telemetry

    def _is_public(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        return "ts.net" in host or proto == "https"

    def _bind_ctx(self) -> bool:
        public = self._is_public()
        try:
            owner = owner_display_name()
        except Exception:
            owner = "Chủ sở hữu"
        ui.set_request_ctx(owner=owner, public=public)
        return public

    def _send(self, code: int, content: str, ctype: str = "text/html; charset=utf-8"):
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        self._bind_ctx()
        global PENDING_NAV
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/calibration":
                self._send(200, v_calibration(qs))
            elif path == "/":
                self._send(200, v_overview())
            elif path == "/messages":
                self._send(200, v_messages(qs))
            elif path == "/users":
                self._send(200, v_users(qs))
            elif path.startswith("/users/"):
                parts = path.strip("/").split("/")
                if len(parts) == 2:
                    self._send(200, v_user_detail(urllib.parse.unquote(parts[1])))
                elif len(parts) == 3 and parts[2] == "summary.json":
                    rows = ledger.user_summaries()
                    u = next((x for x in rows if x["principal_pubkey"] == parts[1]), None)
                    self._send(200, json.dumps(u or {}), "application/json")
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/agents":
                self._send(200, v_agents())
            elif path == "/alerts":
                self._send(200, v_alerts(qs))
            elif path == "/settings":
                self._send(200, v_settings())
            elif path == "/api/overview.json":
                self._send(200, json.dumps(ledger.overview()), "application/json")
            elif path == "/api/agents.json":
                self._send(200, json.dumps(ledger.agent_summaries()), "application/json")
            elif path == "/api/users.json":
                self._send(200, json.dumps(ledger.user_summaries()), "application/json")
            elif path == "/api/latest_messages.json":
                msgs = MSG_HUB.get_sorted_messages()
                self._send(200, json.dumps(msgs), "application/json")
            elif path == "/api/poll_cmd":
                with CMD_LOCK:
                    cmd = PENDING_CMDS.pop(0) if PENDING_CMDS else None
                self._send(200, json.dumps(cmd or {}), "application/json")
            elif path.startswith("/api/cmd_result/"):
                cmd_id = path.split("/")[-1]
                with CMD_LOCK:
                    res = CMD_RESULTS.get(cmd_id)
                self._send(200, json.dumps(res or {}), "application/json")
            elif path == "/api/test_sound":
                try:
                    import subprocess
                    subprocess.Popen([os.path.join(HOME, ".local/bin/buzz-sound"), "test"])
                    self._send(200, json.dumps({"status": "ok"}), "application/json")
                except Exception as e:
                    self._send(500, json.dumps({"status": "error", "error": str(e)}), "application/json")
            elif path == "/api/sound_config":
                self._send(200, json.dumps(load_sound_config()), "application/json")
            elif path == "/api/ai_summary":
                summary_data = generate_ai_catchup_summary()
                self._send(200, json.dumps(summary_data, ensure_ascii=False), "application/json")
            elif path == "/health":
                self._send(200, "ok", "text/plain")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            err_html = ui.render_error_state(i18n.t("errors.generic_title"), i18n.t("errors.generic_desc"), str(e))
            self._send(500, ui.render_page("Lỗi hệ thống", "/", err_html))

    def do_POST(self):
        public = self._bind_ctx()
        global PENDING_NAV
        path = urllib.parse.urlparse(self.path).path
        if public:
            self._send(403, "Ban xem cong khai: khong doi cai dat tu internet.", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""

            if path == "/api/register_community":
                try:
                    data = json.loads(raw_body) if raw_body else {}
                    comms = data.get("communities", [])
                    added = 0
                    for c in comms:
                        name = c.get("name", "")
                        r_url = c.get("relayUrl", "")
                        cid = c.get("id", "")
                        if r_url and name:
                            if r_url not in MSG_HUB.communities or MSG_HUB.communities[r_url] != name:
                                MSG_HUB.communities[r_url] = name
                                added += 1
                        if cid and name:
                            if cid not in MSG_HUB.communities or MSG_HUB.communities[cid] != name:
                                MSG_HUB.communities[cid] = name
                                added += 1
                    if added > 0:
                        MSG_HUB.sync_all(initial=False)
                        MSG_HUB.save_to_disk()
                    self._send(200, json.dumps({"status": "ok", "added": added, "total": len(MSG_HUB.communities)}), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/ai_summary":
                try:
                    summary_data = generate_ai_catchup_summary()
                    self._send(200, json.dumps(summary_data, ensure_ascii=False), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/sync_now":
                new_c = MSG_HUB.sync_all(initial=False)
                self._send(200, json.dumps({"status": "synced", "new_messages": new_c, "total": len(MSG_HUB.messages)}), "application/json")
                return
            elif path == "/api/mark_read":
                try:
                    data = json.loads(raw_body) if raw_body else {}
                    target_chid = data.get("channel_id")
                    now_ts = int(time.time())
                    if os.path.exists(DB_UNREAD):
                        conn = sqlite3.connect(DB_UNREAD)
                        c = conn.cursor()
                        if target_chid:
                            c.execute("INSERT OR REPLACE INTO read_markers (scope, context_id, read_at) VALUES ('manual', ?, ?)", (target_chid, now_ts))
                        else:
                            for m in MSG_HUB.messages.values():
                                cid = m.get("channel_id")
                                if cid:
                                    c.execute("INSERT OR REPLACE INTO read_markers (scope, context_id, read_at) VALUES ('manual', ?, ?)", (cid, now_ts))
                        conn.commit()
                        conn.close()
                    MSG_HUB.save_to_disk()
                    self._send(200, json.dumps({"status": "ok", "marked_at": now_ts}), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/play_sound":
                try:
                    data = json.loads(raw_body) if raw_body else {}
                    is_mention = data.get("is_mention", False)
                    snd = data.get("sound")
                    play_audio_alert(is_mention=is_mention, custom_sound=snd)
                    self._send(200, json.dumps({"status": "ok", "played": True}), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/ingest_event":
                try:
                    data = json.loads(raw_body)
                    ev = data.get("event", {})
                    scope = data.get("scope") or data.get("relayUrl") or data.get("community") or ""
                    chid = data.get("channelId") or data.get("channel") or ""
                    if ev and ev.get("id"):
                        for t in ev.get("tags", []):
                            if t and t[0] in ("h", "e") and not chid:
                                chid = t[1]
                        k = ev.get("kind", 9)
                        pubk = ev.get("pubkey", "")
                        cnt = ev.get("content", "")
                        c_at = ev.get("created_at") or ev.get("createdAt") or ev.get("timestamp") or int(time.time())
                        is_live = not data.get("silent", False)
                        is_new = MSG_HUB.add_message(ev["id"], k, pubk, cnt, chid, scope, c_at, is_live=is_live)
                        if is_new:
                            MSG_HUB.save_to_disk()
                        self._send(200, json.dumps({"status": "ok", "is_new": is_new}), "application/json")
                    else:
                        self._send(400, json.dumps({"status": "invalid_event"}), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/nav_exec":
                try:
                    data = json.loads(raw_body)
                    comm = (data.get("community") or "").lower().strip()
                    chan = (data.get("channel") or "").strip()
                    snd = (data.get("sender") or "").strip()
                    PENDING_NAV = {"community": comm, "channel": chan, "sender": snd}
                    print(f"[NAV_EXEC_DOM_REQUEST] Workspace: {comm}, Channel: {chan}, Sender: {snd}", flush=True)
                    self._send(200, json.dumps({"status": "navigating", "community": comm, "channel": chan}), "application/json")
                except Exception as ex:
                    self._send(500, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/pending_nav":
                try:
                    data = json.loads(raw_body)
                    PENDING_NAV = data
                    print(f"[PENDING_NAV_QUEUED] {data}", flush=True)
                    self._send(200, json.dumps({"status": "queued", "data": data}), "application/json")
                except Exception as ex:
                    self._send(400, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/log":
                try:
                    data = json.loads(raw_body)
                    print(f"[BUZZ_DOM_LOG] {data}", flush=True)
                    log_dir = os.path.join(APP_DATA_DIR, "logs")
                    os.makedirs(log_dir, exist_ok=True)
                    with open(os.path.join(log_dir, "dom_debug.log"), "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {json.dumps(data, ensure_ascii=False)}\n")
                except Exception as ex:
                    print(f"[BUZZ_DOM_LOG] Raw: {raw_body[:200]} err={ex}", flush=True)
                self._send(200, json.dumps({"status": "ok"}), "application/json")
                return
            elif path in ("/api/exec_js", "/api/rpc"):
                try:
                    data = json.loads(raw_body)
                    cmd_id = f"cmd_{int(time.time()*1000)}"
                    cmd_obj = dict(data)
                    cmd_obj["id"] = cmd_id
                    with CMD_LOCK:
                        PENDING_CMDS.append(cmd_obj)
                    self._send(200, json.dumps({"status": "queued", "cmd_id": cmd_id}), "application/json")
                except Exception as ex:
                    self._send(400, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return
            elif path == "/api/cmd_result":
                try:
                    data = json.loads(raw_body)
                    cmd_id = data.get("id")
                    if cmd_id:
                        with CMD_LOCK:
                            CMD_RESULTS[cmd_id] = data
                    self._send(200, json.dumps({"status": "ok"}), "application/json")
                except Exception as ex:
                    self._send(400, json.dumps({"status": "error", "error": str(ex)}), "application/json")
                return

            form = urllib.parse.parse_qs(raw_body)
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "users" and parts[2] == "set-profile":
                pubkey = urllib.parse.unquote(parts[1])
                profile = (form.get("profile") or [""])[0]
                rows = ledger.user_summaries()
                u = next((x for x in rows if x["principal_pubkey"] == pubkey), None)
                if u and profile in ("full", "high", "standard", "limited"):
                    ledger.set_user_allowance(u.get("community_id") or "", pubkey, profile,
                                              by="owner-dashboard")
                self._redirect(f"/users/{pubkey}")
            elif len(parts) == 3 and parts[0] == "alerts" and parts[2] == "ack":
                try:
                    ledger.acknowledge_owner_alert(int(parts[1]), by="owner-dashboard")
                except ValueError:
                    pass
                self._redirect("/alerts")
            elif path == "/refresh/quota":
                threading.Thread(target=refresh_quota, args=("manual",), daemon=True).start()
                self._redirect("/")
            elif path == "/refresh/collect":
                threading.Thread(target=refresh_collect, args=("manual",), daemon=True).start()
                self._redirect("/")
            elif path == "/settings/policy":
                try:
                    base = int((form.get("base_units_daily") or [""])[0])
                    if base > 0:
                        ledger.set_setting("base_units_daily", base, by="owner-dashboard")
                    for key, fkey in (("threshold_warning", "th_w"), ("threshold_high", "th_h"),
                                      ("threshold_critical", "th_c"), ("threshold_exhausted", "th_e")):
                        val = int((form.get(fkey) or [""])[0])
                        if 0 <= val <= 1000:
                            ledger.set_setting(key, val, by="owner-dashboard")
                except ValueError:
                    pass
                self._redirect("/settings")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            err_html = ui.render_error_state(i18n.t("errors.generic_title"), i18n.t("errors.generic_desc"), str(e))
            self._send(500, ui.render_page("Lỗi hệ thống", "/", err_html))


class DashboardServer(ThreadingHTTPServer):
    """Chi mot dashboard giu cong 8787 (SPEC V5).

    HTTPServer mac dinh bat SO_REUSEADDR; tren Windows no cho tien trinh thu hai
    bind chung cong, nen watchdog (health cham > 3s) de ra nhieu dashboard, moi
    cai tu chay quota/collector ghi usage.db."""

    allow_reuse_address = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    # Bind truoc: ban thua thoat ngay, khong kip khoi tao DB hay chay poller.
    server = DashboardServer((HOST, PORT), Handler)
    ledger.init_db()
    ledger.ensure_canonical_agents()
    try:
        conn = ledger.connect()
        try:
            COLLECT["n_req"] = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        pass
    threading.Thread(target=quota_poller, name="quota-poller", daemon=True).start()
    threading.Thread(target=collect_poller, name="collect-poller", daemon=True).start()
    print(f"AI Usage Center listening on http://{HOST}:{PORT} (loopback; Funnel 8443 = xem cong khai)")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
