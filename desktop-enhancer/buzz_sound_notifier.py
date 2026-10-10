#!/usr/bin/env python3
"""
Buzz Multi-Source Sound & Visual Notifier Daemon (Real-Time WebSocket Edition)
==============================================================================
Monitors all incoming messages across all communities, channels, DMs, and threads in Buzz Desktop:
- Source 1: Real-time Nostr WebSocket streaming with NIP-42 Auth across all configured relays
- Source 2: channel-head-cache.db (Active & visited channel heads - fallback)
- Source 3: localstorage (Thread activities & timeline items - fallback)
- Source 4: observed-unread.db (Unread events & high-priority mentions - fallback)

Triggers:
- Instant audio chime (pop.wav / mention.wav / elevenlabs_thang.wav)
- GNOME Desktop Notification Banner with Buzz icon, community, channel, sender, and message preview
- Instant sync into UnifiedMessageHub in dashboard.py (127.0.0.1:8787)
"""

import os
import sys

# Ensure user / miniconda packages (coincurve, websockets) are accessible in systemd environment
HOME = os.path.expanduser("~")
for p in (
    os.path.join(HOME, "miniconda3/lib/python3.13/site-packages"),
    os.path.join(HOME, "miniconda3/lib/python3.12/site-packages"),
    os.path.join(HOME, ".local/lib/python3.12/site-packages"),
    os.path.join(HOME, ".local/lib/python3.13/site-packages"),
):
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)
import time
import json
import sqlite3
import subprocess
import signal
import threading
import asyncio
import hashlib
import re
import urllib.request
from typing import Dict, Any, Optional, Set, Tuple, List

try:
    import coincurve
    import websockets
    HAS_WEBSOCKET_STACK = True
except ImportError:
    HAS_WEBSOCKET_STACK = False

APP_DATA_DIR = os.path.join(HOME, ".local/share/xyz.block.buzz.app")
CONFIG_DIR = os.path.join(HOME, ".config/buzz")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sound-notifier.json")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "sound_notifier.log")
SOUNDS_DIR = os.path.join(APP_DATA_DIR, "sounds")
LATEST_MSGS_FILE = os.path.join(APP_DATA_DIR, "latest_messages.json")
BUZZ_ICON_PATH = os.path.join(HOME, ".local/share/icons/hicolor/128x128/apps/buzz-desktop.png")
KEY_ENV_FILE = os.path.join(HOME, ".buzz/.scratch/buzz-key.env")

DB_UNREAD = os.path.join(APP_DATA_DIR, "observed-unread.db")
DB_HEAD = os.path.join(APP_DATA_DIR, "channel-head-cache.db")
DB_LOCALSTORAGE = os.path.join(APP_DATA_DIR, "localstorage", "tauri_localhost_0.localstorage")

DEFAULT_CONFIG = {
    "enabled": True,
    "sound_message": os.path.join(SOUNDS_DIR, "pop.wav"),
    "sound_mention": os.path.join(SOUNDS_DIR, "pop.wav"),
    "system_fallback_sound": "/usr/share/sounds/Yaru/stereo/message-new-instant.oga",
    "show_desktop_notification": True,
    "debounce_ms": 300,
    "poll_interval_ms": 100,
    "my_pubkey": "2da3184b999140883867865a09b97d61397a5265e209fe9c58b93c59f3f0001e"
}

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_config() -> Dict[str, Any]:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(cfg)
            return merged
    except Exception as e:
        log(f"Error reading config: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def bech32_decode(bech: str) -> Optional[bytes]:
    """Decode a bech32 string (e.g. nsec...) into raw 32 bytes."""
    CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    bech = bech.lower().strip()
    pos = bech.rfind("1")
    if pos < 1:
        return None
    data = [CHARSET.find(x) for x in bech[pos + 1:]]
    if any(x == -1 for x in data):
        return None
    data5 = data[:-6] # strip checksum
    acc = 0
    bits = 0
    ret = bytearray()
    for val in data5:
        acc = (acc << 5) | val
        bits += 5
        while bits >= 8:
            bits -= 8
            ret.append((acc >> bits) & 0xff)
    return bytes(ret)

def load_nostr_private_key() -> Optional[bytes]:
    if not os.path.exists(KEY_ENV_FILE):
        return None
    try:
        with open(KEY_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if "BUZZ_PRIVATE_KEY" in line and "=" in line:
                    val = line.split("=", 1)[1].strip().strip("\"' ")
                    if val.startswith("nsec"):
                        return bech32_decode(val)
                    elif len(val) == 64:
                        return bytes.fromhex(val)
    except Exception as e:
        log(f"Error reading private key: {e}")
    return None

class BuzzSoundNotifier:
    def __init__(self):
        self.config = load_config()
        self.running = True
        self.last_sound_time = 0.0
        self.seen_event_ids: Set[str] = set()
        self.communities: Dict[str, str] = {}
        self.channel_names: Dict[str, str] = {}
        self.channel_community_map: Dict[str, str] = {}
        self.user_names: Dict[str, str] = {}
        self.recent_messages: List[Dict[str, Any]] = []
        self.my_pubkey = self.config.get("my_pubkey", "2da3184b999140883867865a09b97d61397a5265e209fe9c58b93c59f3f0001e")
        self.last_observed_rowid = 0
        self.coincurve_pk = None
        self.ws_thread = None

        self.load_recent_messages()
        self.refresh_metadata()

    def load_recent_messages(self):
        if os.path.exists(LATEST_MSGS_FILE):
            try:
                with open(LATEST_MSGS_FILE, "r", encoding="utf-8") as f:
                    self.recent_messages = json.load(f)
            except Exception:
                self.recent_messages = []

    def save_recent_messages(self):
        try:
            self.recent_messages.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            self.recent_messages = self.recent_messages[:100]
            with open(LATEST_MSGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.recent_messages, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def refresh_metadata(self):
        """Fetch communities, channel names, and user display names."""
        if not os.path.exists(DB_LOCALSTORAGE):
            return
        try:
            conn = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
            c = conn.cursor()

            # 1. Communities map
            c.execute("SELECT value FROM ItemTable WHERE key='buzz-communities'")
            row = c.fetchone()
            if row:
                val = row[0].decode("utf-16le") if isinstance(row[0], bytes) else row[0]
                try:
                    for comm in json.loads(val):
                        name = comm.get("name", "")
                        r_url = comm.get("relayUrl", "")
                        cid = comm.get("id", "")
                        if r_url: self.communities[r_url] = name
                        if cid: self.communities[cid] = name
                except Exception:
                    pass

            # 2. Channels map per relay
            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-channels.%'")
            for k, v in c.fetchall():
                try:
                    relay_match = ""
                    for r_url, cname in self.communities.items():
                        if r_url in k:
                            relay_match = cname
                            break
                    val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                    data = json.loads(val)
                    if isinstance(data, dict) and "channels" in data:
                        for ch in data["channels"]:
                            chid = ch.get("id")
                            chname = ch.get("name")
                            if chid and chname:
                                self.channel_names[chid] = chname
                                if relay_match:
                                    self.channel_community_map[chid] = relay_match
                except Exception:
                    pass

            # 3. User display names map
            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-user-labels%'")
            for k, v in c.fetchall():
                try:
                    val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                    data = json.loads(val)
                    profiles = data.get("profiles", {})
                    for pk, pinfo in profiles.items():
                        dname = pinfo.get("displayName") or pinfo.get("name")
                        if dname:
                            self.user_names[pk] = dname
                except Exception:
                    pass

            # Self profile
            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-self-profile%'")
            for k, v in c.fetchall():
                try:
                    val = v.decode("utf-16le") if isinstance(v, bytes) else str(v)
                    data = json.loads(val)
                    if isinstance(data, dict) and "displayName" in data and data["displayName"]:
                        self.user_names[self.my_pubkey] = data["displayName"]
                except Exception:
                    pass

            conn.close()
        except Exception:
            pass

    def play_audio(self, sound_path: str):
        now = time.time()
        debounce_sec = self.config.get("debounce_ms", 300) / 1000.0
        if (now - self.last_sound_time) < debounce_sec:
            return
        self.last_sound_time = now

        if not sound_path or not os.path.exists(sound_path):
            sound_path = self.config.get("system_fallback_sound", "/usr/share/sounds/Yaru/stereo/message-new-instant.oga")

        env = os.environ.copy()
        if "XDG_RUNTIME_DIR" not in env:
            env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

        def _play():
            try:
                res = subprocess.run(["paplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
                if res.returncode != 0:
                    subprocess.run(["pw-play", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            except Exception as ex:
                log(f"Audio playback error: {ex}")

        threading.Thread(target=_play, daemon=True).start()

    def show_notification(self, title: str, body: str):
        if not self.config.get("show_desktop_notification", True):
            return
        env = os.environ.copy()
        env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-0"
        if "XDG_RUNTIME_DIR" not in env:
            env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

        icon = BUZZ_ICON_PATH if os.path.exists(BUZZ_ICON_PATH) else "dialog-information"

        def _notify():
            try:
                subprocess.run([
                    "notify-send",
                    "-a", "Buzz",
                    "-i", icon,
                    "-u", "critical",
                    "-t", "8000",
                    title,
                    body
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            except Exception:
                pass
        threading.Thread(target=_notify, daemon=True).start()

    def init_baseline(self):
        """Seed all existing events into memory to avoid alerting old history on startup."""
        self.refresh_metadata()
        count = 0
        if os.path.exists(DB_HEAD):
            try:
                conn_h = sqlite3.connect(f"file:{DB_HEAD}?mode=ro", uri=True)
                ch = conn_h.cursor()
                ch.execute("SELECT events_json FROM channel_head")
                for (events_str,) in ch.fetchall():
                    try:
                        evs = json.loads(events_str)
                        for ev in evs:
                            eid = ev.get("id")
                            if eid:
                                self.seen_event_ids.add(eid)
                                count += 1
                    except Exception:
                        pass
                conn_h.close()
            except Exception:
                pass

        if os.path.exists(DB_UNREAD):
            try:
                conn_u = sqlite3.connect(f"file:{DB_UNREAD}?mode=ro", uri=True)
                cu = conn_u.cursor()
                cu.execute("SELECT COALESCE(MAX(rowid), 0) FROM observed_events")
                self.last_observed_rowid = cu.fetchone()[0]
                cu.execute("SELECT event_id FROM observed_events")
                for (eid,) in cu.fetchall():
                    if eid:
                        self.seen_event_ids.add(eid)
                        count += 1
                conn_u.close()
            except Exception:
                pass
        if os.path.exists(DB_LOCALSTORAGE):
            try:
                conn_ls = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
                cls = conn_ls.cursor()
                cls.execute("SELECT value FROM ItemTable WHERE key LIKE 'buzz-thread-activity.v1%'")
                for (val,) in cls.fetchall():
                    try:
                        s = val.decode("utf-16le") if isinstance(val, bytes) else val
                        items = json.loads(s)
                        if isinstance(items, list):
                            for item in items:
                                eid = item.get("id")
                                if eid:
                                    self.seen_event_ids.add(eid)
                                    count += 1
                    except Exception:
                        pass
                conn_ls.close()
            except Exception:
                pass

        log(f"✓ Initialized state. Cached {len(self.seen_event_ids)} baseline events.")

    def is_synthetic_or_test(self, eid: str, content: str) -> bool:
        """Filter bot ciphertext blobs, benchmarking logs, and synthetic tokens."""
        if not eid or not content:
            return True
        eid_str = str(eid).lower()
        if any(eid_str.startswith(p) for p in ("test_", "dummy_", "mock_", "voice_test_", "test-")):
            return True

        cnt = content.strip()
        if not cnt:
            return True

        # Base64 ciphertext / bot payload blobs
        if len(cnt) >= 20 and " " not in cnt and re.match(r"^[A-Za-z0-9+/=]+$", cnt):
            return True

        # Single word bot tokens
        cnt_upper = cnt.upper()
        if cnt_upper in ("ONE", "TWO", "THREE", "FOUR", "FIVE", "CLEAN", "READY", "MODEL-OK", "REG", "PING", "PONG", "TEST"):
            return True

        test_patterns = (
            "channel ready", "concurrency pass", "routing verified", "verification test",
            "calibration regression test", "concurrency test", "model-capture verification",
            "live usage-control test", "spoof test", "gateway environment publication",
            "acp test success"
        )
        cnt_lower = cnt.lower()
        if any(pat in cnt_lower for pat in test_patterns):
            return True

        return False

    def resolve_community_name(self, scope: str, channel_id: str) -> str:
        if scope:
            for r_url, cname in self.communities.items():
                if r_url in scope:
                    return cname
        if channel_id in self.channel_community_map:
            return self.channel_community_map[channel_id]
        return "Buzz"

    def handle_incoming_event(self, event_id: str, kind: int, pubkey: str, content: str, channel_id: str, scope: str = "", is_mention: bool = False):
        if event_id in self.seen_event_ids:
            return
        self.seen_event_ids.add(event_id)

        # Ignore self-authored events
        if pubkey and pubkey == self.my_pubkey:
            return

        if self.is_synthetic_or_test(event_id, content):
            return

        # Check mention in content
        cnt_lower = content.lower() if content else ""
        if not is_mention and cnt_lower:
            if any(alias in cnt_lower for alias in ("@ncthang", "@ncthangdz", "@you", "@thang", "@owner")):
                is_mention = True
            elif "@" in content:
                for uname in self.user_names.values():
                    if uname and f"@{uname}".lower() in cnt_lower:
                        is_mention = True
                        break

        community = self.resolve_community_name(scope, channel_id)
        raw_ch_name = self.channel_names.get(channel_id, "")
        if raw_ch_name:
            ch_name = raw_ch_name
        elif channel_id:
            ch_name = "Tin nhắn riêng" if "dm" in channel_id.lower() else f"#{channel_id[:6]}"
        else:
            ch_name = "general"

        sender = self.user_names.get(pubkey, f"Thành viên {pubkey[:6]}" if pubkey else "Buzz")

        # Record to recent messages
        item = {
            "id": event_id,
            "time": time.strftime("%H:%M · %d/%m"),
            "timestamp": int(time.time()),
            "community": community,
            "channel": ch_name,
            "sender": sender,
            "is_mention": is_mention,
            "content": content.strip() if content else "(Hình ảnh / Tệp đính kèm)"
        }
        self.recent_messages.append(item)
        self.save_recent_messages()

        log(f"🔔 [{community.upper()}] #{ch_name} | {sender}: {content[:60]}")

        # 1. Play sound
        sound_file = self.config.get("sound_mention") if is_mention else self.config.get("sound_message")
        self.play_audio(sound_file)

        # 2. Rich Desktop Notification Banner
        title = f"📢 [{community.upper()}] #{ch_name}"
        body_preview = f"👤 {sender}: {content.strip().replace(chr(10), ' ')[:100]}" if content else f"👤 {sender} vừa gửi một tin nhắn mới"
        self.show_notification(title, body_preview)

    def forward_to_dashboard(self, ev: Dict[str, Any], comm_name: str, chid: str):
        """Forward real-time event to local dashboard for In-App Drawer sync."""
        def _fwd():
            try:
                payload = json.dumps({
                    "event": ev,
                    "community": comm_name,
                    "channelId": chid,
                    "silent": True # Do not duplicate sound (handled above)
                }).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:8787/api/ingest_event",
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=1.5):
                    pass
            except Exception:
                pass
        threading.Thread(target=_fwd, daemon=True).start()

    def process_live_ws_event(self, ev: Dict[str, Any], relay_url: str, comm_name: str):
        eid = ev.get("id")
        if not eid or eid in self.seen_event_ids:
            return

        pubk = ev.get("pubkey", "")
        if pubk and pubk == self.my_pubkey:
            self.seen_event_ids.add(eid)
            return

        content = ev.get("content", "")
        if self.is_synthetic_or_test(eid, content):
            self.seen_event_ids.add(eid)
            return

        chid = ""
        is_mention = False
        for t in ev.get("tags", []):
            if not t or len(t) < 2:
                continue
            tag_name = t[0]
            tag_val = t[1]
            if tag_name in ("h", "root") and not chid:
                chid = tag_val
            elif tag_name == "p" and tag_val == self.my_pubkey:
                is_mention = True

        kind = ev.get("kind", 9)
        self.handle_incoming_event(
            event_id=eid,
            kind=kind,
            pubkey=pubk,
            content=content,
            channel_id=chid,
            scope=relay_url,
            is_mention=is_mention
        )

        self.forward_to_dashboard(ev, comm_name, chid)

    # --------------------------------------------------------------------------
    # Real-Time WebSocket Multi-Relay Engine
    # --------------------------------------------------------------------------
    async def _listen_single_relay(self, relay_url: str, comm_name: str):
        backoff = 3
        while self.running:
            try:
                log(f"Connecting WebSocket to {comm_name} ({relay_url})...")
                async with websockets.connect(
                    relay_url,
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=8
                ) as ws:
                    log(f"✓ Connected to {comm_name} ({relay_url})")
                    sub_active = False
                    backoff = 3

                    while self.running:
                        msg_str = await ws.recv()
                        try:
                            msg = json.loads(msg_str)
                        except Exception:
                            continue

                        mtype = msg[0] if isinstance(msg, list) and len(msg) > 0 else ""

                        if mtype == "AUTH":
                            challenge = msg[1]
                            now = int(time.time())
                            tags = [["relay", relay_url], ["challenge", challenge]]
                            ser = json.dumps([0, self.my_pubkey, now, 22242, tags, ""], separators=(",", ":"), ensure_ascii=False)
                            eid = hashlib.sha256(ser.encode("utf-8")).hexdigest()
                            sig = self.coincurve_pk.sign_schnorr(bytes.fromhex(eid)).hex()
                            auth_ev = {
                                "id": eid,
                                "pubkey": self.my_pubkey,
                                "created_at": now,
                                "kind": 22242,
                                "tags": tags,
                                "content": "",
                                "sig": sig
                            }
                            await ws.send(json.dumps(["AUTH", auth_ev]))

                        elif mtype == "OK":
                            if not sub_active:
                                sub_id = f"live_{comm_name}"
                                # Subscribe to kinds: 9 (chat), 40099 (buzz msg), 40003 (thread), 4 (DM), 1059 (gift wrap), 1 (note)
                                sub_filter = {
                                    "kinds": [9, 40099, 40003, 4, 1059, 1],
                                    "since": int(time.time()) - 15
                                }
                                await ws.send(json.dumps(["REQ", sub_id, sub_filter]))
                                sub_active = True
                                log(f"📡 Real-time message subscription ACTIVE on {comm_name.upper()}")

                        elif mtype == "EVENT":
                            if len(msg) >= 3 and isinstance(msg[2], dict):
                                ev = msg[2]
                                self.process_live_ws_event(ev, relay_url, comm_name)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log(f"⚠️ WebSocket {comm_name} error: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(30, backoff * 1.5)

    async def _relay_listener_manager(self):
        running_tasks = {}
        while self.running:
            active_relays = {}
            for k, name in self.communities.items():
                if k.startswith("wss://"):
                    active_relays[k] = name

            for r_url, name in active_relays.items():
                if r_url not in running_tasks or running_tasks[r_url].done():
                    running_tasks[r_url] = asyncio.create_task(self._listen_single_relay(r_url, name))

            await asyncio.sleep(10)

    def start_websocket_listeners(self):
        if not HAS_WEBSOCKET_STACK:
            log("⚠️ Missing websockets/coincurve library — running in local polling mode.")
            return

        priv_bytes = load_nostr_private_key()
        if not priv_bytes:
            log("⚠️ No Nostr private key found in buzz-key.env — running in local polling mode.")
            return

        try:
            self.coincurve_pk = coincurve.PrivateKey(priv_bytes)
            derived_pub = self.coincurve_pk.public_key.format(compressed=True)[1:].hex()
            if derived_pub:
                self.my_pubkey = derived_pub
        except Exception as e:
            log(f"⚠️ Error initializing private key: {e}")
            return

        log(f"🔑 Loaded Nostr identity {self.my_pubkey[:10]}... Launching real-time WebSocket listeners.")

        def _async_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._relay_listener_manager())

        self.ws_thread = threading.Thread(target=_async_loop, daemon=True)
        self.ws_thread.start()

    # --------------------------------------------------------------------------
    # Fallback Local SQLite Scanners
    # --------------------------------------------------------------------------
    def scan_channels(self):
        if not os.path.exists(DB_HEAD):
            return
        try:
            conn = sqlite3.connect(f"file:{DB_HEAD}?mode=ro", uri=True)
            c = conn.cursor()
            c.execute("SELECT scope, channel_id, events_json FROM channel_head")
            for scope, channel_id, events_str in c.fetchall():
                if not events_str:
                    continue
                try:
                    events = json.loads(events_str)
                    for ev in events:
                        eid = ev.get("id")
                        if not eid or eid in self.seen_event_ids:
                            continue
                        kind = ev.get("kind", 0)
                        if kind in (9, 40099, 40003, 4, 1, 1059):
                            pubkey = ev.get("pubkey", "")
                            content = ev.get("content", "")
                            self.handle_incoming_event(eid, kind, pubkey, content, channel_id, scope=scope)
                        else:
                            self.seen_event_ids.add(eid)
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass

    def scan_observed_unread(self):
        if not os.path.exists(DB_UNREAD):
            return
        try:
            conn = sqlite3.connect(f"file:{DB_UNREAD}?mode=ro", uri=True)
            c = conn.cursor()
            c.execute("""
                SELECT rowid, scope, event_id, channel_id, high_priority 
                FROM observed_events 
                WHERE rowid > ? 
                ORDER BY rowid ASC
            """, (self.last_observed_rowid,))
            rows = c.fetchall()
            conn.close()

            for rowid, scope, event_id, channel_id, high_priority in rows:
                self.last_observed_rowid = max(self.last_observed_rowid, rowid)
                if event_id in self.seen_event_ids:
                    continue
                self.handle_incoming_event(event_id, 9, "", "", channel_id, scope=scope, is_mention=(high_priority == 1))
        except Exception:
            pass

    def scan_thread_activity(self):
        if not os.path.exists(DB_LOCALSTORAGE):
            return
        try:
            conn = sqlite3.connect(f"file:{DB_LOCALSTORAGE}?mode=ro", uri=True)
            c = conn.cursor()
            c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'buzz-thread-activity.v1%'")
            for key, val in c.fetchall():
                try:
                    s = val.decode("utf-16le") if isinstance(val, bytes) else val
                    items = json.loads(s)
                    if isinstance(items, list):
                        for item in items:
                            eid = item.get("id")
                            if not eid or eid in self.seen_event_ids:
                                continue
                            kind = item.get("kind", 9)
                            pubkey = item.get("pubkey", "")
                            content = item.get("content", "")
                            chid = item.get("channelId", "")
                            self.handle_incoming_event(eid, kind, pubkey, content, chid, scope=key)
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass

    def run(self):
        log("🚀 Buzz Sound & Visual Notifier started.")
        self.init_baseline()
        self.start_websocket_listeners()

        poll_sec = max(0.05, self.config.get("poll_interval_ms", 100) / 1000.0)
        loop_count = 0

        while self.running:
            try:
                loop_count += 1
                if loop_count % 100 == 0:
                    self.config = load_config()
                    self.refresh_metadata()

                if not self.config.get("enabled", True):
                    time.sleep(1.0)
                    continue

                self.scan_channels()
                self.scan_observed_unread()
                if loop_count % 2 == 0:
                    self.scan_thread_activity()

                time.sleep(poll_sec)
            except Exception:
                time.sleep(0.3)

    def stop(self):
        self.running = False

def handle_signal(sig, frame):
    log(f"Received stop signal {sig}, exiting...")
    if notifier_instance:
        notifier_instance.stop()
    sys.exit(0)

notifier_instance: Optional[BuzzSoundNotifier] = None

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    notifier_instance = BuzzSoundNotifier()
    notifier_instance.run()
