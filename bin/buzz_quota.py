#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Doc han muc THAT cua cac tai khoan Codex CHINH HANG, GOP THEO EMAIL.

Chay duoc tu Windows va tu WSL:
  - Windows: quet C:/Users/*/.codex* + goi chinh file nay trong WSL --dump-json
    --linux-only, roi gop. Ghi SQLite o phia Windows (cung process dashboard).
  - WSL: quet /home/*/.codex* (va /mnt/c neu khong --linux-only).

Token KHONG BAO GIO in ra hay ghi vao CSDL.

  python3 bin/buzz_quota.py
  python3 bin/buzz_quota.py --dry-run
  python3 bin/buzz_quota.py --dump-json --linux-only
"""
import base64
import datetime
import glob
import json
import os
import sqlite3
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import paths  # noqa: E402

DB_PATH = os.environ.get("BUZZ_USAGE_DB", os.path.join(ROOT, "usage.db"))
SOURCE_TAG = "codex-session-rate-limits"
# Giong 9router: GET han muc live, khong can doi phien Codex moi.
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
MAX_READING_AGE = 7 * 86400
DRY = "--dry-run" in sys.argv
DUMP_JSON = "--dump-json" in sys.argv
LINUX_ONLY = "--linux-only" in sys.argv
WIN_ONLY = "--windows-only" in sys.argv

COLS = ["account_id", "email", "plan", "account_short", "homes", "harnesses",
        "agent_count", "agents", "limit_id", "window_name", "window_minutes",
        "used_percent", "resets_at", "read_at", "source_home", "last_refresh",
        "sessions", "last_session_at"]

SCHEMA = """
CREATE TABLE codex_account_limits (
    account_id      TEXT NOT NULL,
    email           TEXT,
    plan            TEXT,
    account_short   TEXT,
    homes           TEXT,
    harnesses       TEXT,
    agent_count     INTEGER,
    agents          TEXT,
    limit_id        TEXT,
    window_name     TEXT NOT NULL,
    window_minutes  INTEGER,
    used_percent    REAL,
    resets_at       INTEGER,
    read_at         INTEGER,
    source_home     TEXT,
    last_refresh    TEXT,
    sessions        INTEGER,
    last_session_at INTEGER,
    PRIMARY KEY (account_id, window_name)
)
"""


def log(m):
    print(m, flush=True, file=sys.stderr)


def read_provider(home):
    try:
        for line in open(os.path.join(home, "config.toml"), encoding="utf-8"):
            t = line.strip()
            if "=" in t and t.split("=", 1)[0].strip() == "model_provider":
                return t.split("=", 1)[1].strip().strip('"').strip("'")
            if "=" in t and t.split("=", 1)[0].strip() == "model":
                pass
    except OSError:
        pass
    return ""


def read_model(home):
    try:
        for line in open(os.path.join(home, "config.toml"), encoding="utf-8"):
            t = line.strip()
            if "=" in t and t.split("=", 1)[0].strip() == "model":
                return t.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _claims(tok):
    try:
        part = tok.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _jwt_exp(tok):
    c = _claims(tok or "")
    try:
        return int(c.get("exp") or 0)
    except Exception:
        return 0


# Giong 9router: Codex access_token ~10 ngay; refresh som 5 ngay, va neu
# last_refresh > 8 ngay thi van xoay de tranh refresh_token chet.
REFRESH_LEAD_S = 5 * 86400
MAX_REFRESH_AGE_S = 8 * 86400


def _oauth_error_code(raw):
    """Lay ma loi OAuth, KHONG tra ve body (co the dinh token)."""
    try:
        obj = json.loads(raw or "")
    except Exception:
        return ""
    if not isinstance(obj, dict):
        return ""
    err = obj.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("message") or "")[:80]
    return str(err or obj.get("error_code") or "")[:80]


def _oauth_refresh_once(rt, encoding):
    """POST auth.openai.com/oauth/token. encoding=json (9router) hoac form."""
    if encoding == "json":
        body = json.dumps({
            "client_id": CODEX_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": rt,
        }).encode("utf-8")
        ctype = "application/json"
    else:
        # Codex CLI: form, KHONG gui them scope (scope thua de invalid_grant).
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": CODEX_CLIENT_ID,
        }).encode("utf-8")
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": ctype, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")), None, 200
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return None, _oauth_error_code(raw) or ("HTTP_%s" % e.code), e.code
    except Exception as e:
        return None, type(e).__name__, 0


def write_auth_tokens(auth_path, tokens):
    """Ghi tokens moi vao auth.json, giu nguyen quyen file va ghi nguyen khoi.

    Ba diem bat buoc:
    - `last_refresh` phai co hau to "Z". Codex doc truong nay bang chuan RFC3339;
      thieu mui gio thi ca file bi coi la hong ("premature end of input"), Codex bo qua
      dang nhap va goi API khong kem token -> 401 "Missing bearer" o MOI agent dung home
      nay (dieu tra 16/09/2026).
    - Giu quyen goc (thuong 0600) vi file chua refresh_token. Tao file tam bang open()
      thuong thi umask 0022 lam file thanh 0644 — moi user tren may doc duoc token.
    - Ten file tam co PID: hai lan quet chong nhau khong de nhau, tranh mat refresh_token
      moi (lan sau OpenAI tra invalid_grant).
    """
    with open(auth_path, encoding="utf-8") as fh:
        blob = json.load(fh)
    blob["tokens"] = tokens
    blob["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        mode = stat.S_IMODE(os.stat(auth_path).st_mode)
    except OSError:
        mode = 0o600
    tmp = "%s.tmp-refresh-%d" % (auth_path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(blob, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, auth_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return blob


def _refresh_codex_tokens(home, tokens):
    """Xoay access_token bang refresh_token (9router: JSON, persist RT moi).

    Khong in token. Tra ve tokens moi hoac None. Neu OpenAI xoay refresh_token
    ma ta khong ghi lai, lan sau se invalid_grant / refresh_token_reused.
    """
    rt = (tokens or {}).get("refresh_token")
    if not rt:
        return None
    data, err, code = _oauth_refresh_once(rt, "json")
    if not data or not data.get("access_token"):
        data2, err2, code2 = _oauth_refresh_once(rt, "form")
        if data2 and data2.get("access_token"):
            data, err, code = data2, err2, code2
        else:
            log("  live-api refresh loi (%s): %s/%s" % (
                home_label(home), err or "no_access", code))
            if (err or err2) in ("invalid_grant", "refresh_token_reused",
                                 "refresh_token_expired", "unrecoverable_refresh_error"):
                log("  -> RT chet, can dang nhap lai Codex mot lan cho home nay")
            return None
    out = dict(tokens)
    out["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        out["refresh_token"] = data["refresh_token"]
    if data.get("id_token"):
        out["id_token"] = data["id_token"]
    try:
        write_auth_tokens(os.path.join(home, "auth.json"), out)
    except Exception:
        log("  live-api ghi auth.json that bai (%s) — RT moi co the mat" % home_label(home))
        return None
    log("  live-api da xoay token (%s)" % home_label(home))
    return out


def _should_refresh(blob, tokens, now):
    """9router: het han som 5 ngay, hoac last_refresh > 8 ngay."""
    exp = _jwt_exp((tokens or {}).get("access_token"))
    if exp and exp < now + REFRESH_LEAD_S:
        return True
    last = to_epoch((blob or {}).get("last_refresh") or "")
    if not last or now - last >= MAX_REFRESH_AGE_S:
        return True
    return False


def _wham_request(tokens):
    """GET /wham/usage. Khong in body (co email)."""
    headers = {
        "Authorization": "Bearer " + tokens["access_token"],
        "Accept": "application/json",
        "originator": "codex_cli_rs",
        "User-Agent": "codex_cli_rs/0.154.0",
    }
    acc_id = tokens.get("account_id") or ""
    if acc_id:
        headers["ChatGPT-Account-ID"] = acc_id
        headers["chatgpt-account-id"] = acc_id
    req = urllib.request.Request(USAGE_URL, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _window_minutes(w, slot_name):
    try:
        mins = int(w.get("window_minutes") or 0)
    except Exception:
        mins = 0
    if mins <= 0:
        try:
            secs = int(w.get("limit_window_seconds") or w.get("window_seconds") or 0)
        except Exception:
            secs = 0
        if secs > 0:
            mins = max(1, int(round(secs / 60.0)))
    if mins <= 0:
        if slot_name == "primary":
            mins = 300
        elif slot_name == "secondary":
            mins = 10080
    return mins


def _reset_epoch(w):
    resets = w.get("resets_at") or w.get("reset_at") or 0
    try:
        resets = int(resets)
    except Exception:
        resets = to_epoch(str(resets)) if resets else 0
    if resets > 1e12:
        resets = int(resets / 1000)
    return resets


def live_windows(home):
    """Doc han muc live (9router: GET /wham/usage).

    Tra ve:
      dict cua so  — thanh cong (co the rong neu API khong tra window)
      None         — khong auth duoc / HTTP 401 sau refresh: can dang nhap lai
    """
    auth_path = os.path.join(home, "auth.json")
    try:
        blob = json.load(open(auth_path, encoding="utf-8"))
    except Exception:
        return None
    tokens = blob.get("tokens") if isinstance(blob, dict) else None
    if not tokens or not (tokens.get("access_token") or tokens.get("refresh_token")):
        return None
    now = int(time.time())
    if _should_refresh(blob, tokens, now) or not tokens.get("access_token"):
        tokens = _refresh_codex_tokens(home, tokens)
        if not tokens:
            log("  live-api can dang nhap lai (%s)" % home_label(home))
            return None

    def fetch(tok):
        try:
            return _wham_request(tok), None
        except urllib.error.HTTPError as e:
            return None, e
        except Exception as e:
            log("  live-api loi %s tai %s" % (type(e).__name__, home_label(home)))
            return None, e

    data, err = fetch(tokens)
    if data is None and isinstance(err, urllib.error.HTTPError) and err.code in (401, 403):
        tokens = _refresh_codex_tokens(home, tokens)
        if not tokens:
            log("  live-api can dang nhap lai (%s)" % home_label(home))
            return None
        data, err = fetch(tokens)
    if data is None:
        if isinstance(err, urllib.error.HTTPError):
            if err.code in (401, 403):
                log("  live-api can dang nhap lai (%s, HTTP %s)" % (home_label(home), err.code))
                return None
            log("  live-api HTTP %s tai %s" % (err.code, home_label(home)))
        return None

    rl = data.get("rate_limit") or data.get("rate_limits") or {}
    if not isinstance(rl, dict):
        rl = {}
    slots = [
        ("primary", rl.get("primary_window") or rl.get("primary") or data.get("primary")),
        ("secondary", rl.get("secondary_window") or rl.get("secondary") or data.get("secondary")),
    ]
    extra = data.get("additional_rate_limits")
    if isinstance(extra, list):
        for ent in extra:
            if isinstance(ent, dict):
                slots.append(("extra", ent.get("rate_limit") or ent))
    out = {}
    for name, w in slots:
        if not w or not isinstance(w, dict):
            continue
        used = w.get("used_percent")
        if used is None:
            used = w.get("percent_used")
        if used is None:
            continue
        mins = _window_minutes(w, name)
        if mins <= 0:
            continue
        key = "%dph" % mins
        out[key] = {
            "read_at": now,
            "used_percent": float(used),
            "window_minutes": mins,
            "resets_at": _reset_epoch(w),
            "limit_id": (rl.get("limit_id") or w.get("limit_id") or ""),
            "source": "live-api",
        }
    if out:
        log("  live-api %s: %s" % (home_label(home), ", ".join(sorted(out))))
    return out


def identity(home):
    try:
        a = json.load(open(os.path.join(home, "auth.json"), encoding="utf-8"))
    except Exception:
        return None
    t = a.get("tokens") if isinstance(a, dict) else None
    if not t:
        return None
    c = _claims(t.get("id_token") or "")
    au = c.get("https://api.openai.com/auth") or {}
    acc = t.get("account_id") or ""
    return {
        "email": c.get("email") or ("tai-khoan-" + acc[:8]),
        "plan": au.get("chatgpt_plan_type") or "",
        "account_short": acc[:8],
        "last_refresh": (a.get("last_refresh") or "")[:19],
    }


def linux_app():
    if paths.in_wsl():
        return os.path.expanduser("~") + "/" + paths.APP_REL
    return paths.linux_app()


def harness_map(app):
    linux_home = os.path.expanduser("~") if paths.in_wsl() else ("/home/" + paths.WSL_USER)
    wrap = {
        "codex-ollama": linux_home + "/.codex-ollama",
        "codex-t2": linux_home + "/.codex-t2",
    }
    reg = {}
    for f in sorted(glob.glob(app + "/custom_harnesses/*.json")):
        try:
            h = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        hid = h.get("id")
        env = h.get("env") or {}
        hhome = env.get("CODEX_HOME") or wrap.get(hid)
        if hid and hhome:
            reg.setdefault(os.path.normpath(hhome), []).append(hid)
    return reg


def agents_by_runtime(app):
    out = {}
    try:
        for a in json.load(open(app + "/agents/managed-agents.json", encoding="utf-8")):
            nm = a.get("display_name") or a.get("name")
            if nm:
                out.setdefault(a.get("runtime") or "-", set()).add(nm)
    except Exception:
        pass
    return out


def to_epoch(iso):
    try:
        return int(datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def latest_windows(files, scan=60):
    best = {}
    for path in files[:scan]:
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "rate_limits" not in line:
                    continue
                try:
                    x = json.loads(line)
                except Exception:
                    continue
                rl = (x.get("payload") or {}).get("rate_limits") or {}
                ts = to_epoch(x.get("timestamp"))
                for slot in ("primary", "secondary"):
                    w = rl.get(slot)
                    if not w or w.get("used_percent") is None:
                        continue
                    mins = int(w.get("window_minutes") or 0)
                    key = "%dph" % mins
                    if key not in best or ts > best[key]["read_at"]:
                        best[key] = {
                            "read_at": ts,
                            "used_percent": float(w.get("used_percent")),
                            "window_minutes": mins,
                            "resets_at": int(w.get("resets_at") or 0),
                            "limit_id": rl.get("limit_id") or "",
                            "source": "session",
                        }
    return best


def home_label(home):
    if home.startswith("/mnt/c/") or (len(home) > 1 and home[1] == ":"):
        return "Windows " + home.replace("\\", "/").replace("/mnt/c/", "C:/")
    lh = "/home/" + paths.WSL_USER
    if home.startswith(lh):
        return "WSL ~" + home[len(lh):]
    if home.startswith("/home/"):
        return "WSL " + home
    return home


def fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M") if ts else "-"


def window_txt(mins):
    if mins >= 1440:
        return "%d ngay" % (mins // 1440)
    if mins >= 60:
        return "%d gio" % (mins // 60)
    return "%d phut" % mins


def new_account(ident):
    return {
        "email": ident["email"], "plan": ident["plan"],
        "account_short": ident["account_short"], "last_refresh": ident["last_refresh"],
        "homes": [], "harnesses": set(), "agents": set(),
        "sessions": 0, "last_session_at": 0, "windows": {},
        "config_model": "", "need_login": False,
    }


def merge_accounts(dst, src):
    for email, acc in src.items():
        if email not in dst:
            dst[email] = acc
            continue
        cur = dst[email]
        if acc.get("last_refresh", "") > cur.get("last_refresh", ""):
            cur["last_refresh"] = acc["last_refresh"]
            if acc.get("plan"):
                cur["plan"] = acc["plan"]
            if acc.get("account_short"):
                cur["account_short"] = acc["account_short"]
        cur["homes"] = list(dict.fromkeys(list(cur.get("homes") or []) + list(acc.get("homes") or [])))
        cur["harnesses"].update(acc.get("harnesses") or [])
        cur["agents"].update(acc.get("agents") or [])
        cur["sessions"] += int(acc.get("sessions") or 0)
        cur["last_session_at"] = max(int(cur.get("last_session_at") or 0),
                                     int(acc.get("last_session_at") or 0))
        if acc.get("config_model") and not cur.get("config_model"):
            cur["config_model"] = acc["config_model"]
        for key, w in (acc.get("windows") or {}).items():
            old = cur["windows"].get(key)
            if old is None or w["read_at"] > old["read_at"]:
                cur["windows"][key] = w
        if any(w.get("source") == "live-api" for w in cur["windows"].values()):
            cur["need_login"] = False
        else:
            cur["need_login"] = bool(cur.get("need_login") or acc.get("need_login"))
    return dst


def account_from_dump(d):
    acc = new_account({
        "email": d["email"], "plan": d.get("plan") or "",
        "account_short": d.get("account_short") or "",
        "last_refresh": d.get("last_refresh") or "",
    })
    acc["homes"] = list(d.get("homes") or [])
    acc["harnesses"] = set(d.get("harnesses") or [])
    acc["agents"] = set(d.get("agents") or [])
    acc["sessions"] = int(d.get("sessions") or 0)
    acc["last_session_at"] = int(d.get("last_session_at") or 0)
    acc["config_model"] = d.get("config_model") or ""
    acc["windows"] = d.get("windows") or {}
    acc["need_login"] = bool(d.get("need_login"))
    return acc


def dump_accounts(accounts):
    out = {}
    for email, acc in accounts.items():
        out[email] = {
            "email": acc["email"], "plan": acc["plan"],
            "account_short": acc["account_short"],
            "last_refresh": acc["last_refresh"],
            "homes": list(acc["homes"]),
            "harnesses": sorted(acc["harnesses"]),
            "agents": sorted(acc["agents"]),
            "sessions": acc["sessions"],
            "last_session_at": acc["last_session_at"],
            "config_model": acc.get("config_model") or "",
            "windows": acc["windows"],
            "need_login": bool(acc.get("need_login")),
        }
    return out


def overlay_live_on_account(acc, homes):
    """Gan han muc live len so phien. Thu home co last_refresh moi nhat truoc."""
    def refresh_key(h):
        ident = identity(h) or {}
        return ident.get("last_refresh") or ""

    ordered = sorted([h for h in homes if h], key=refresh_key, reverse=True)
    got = None
    src_home = ""
    for home in ordered:
        lw = live_windows(home)
        # Phan biet hai ket qua khac nhau: None = khong auth duoc (phai thu home khac
        # va bao dang nhap lai); {} = goi API thanh cong nhung tai khoan khong co cua
        # so han muc nao. Neu gop lai bang "if not lw" thi truong hop {} bi hieu sai la
        # mat auth, bao cao giu so lieu cu va bao "can dang nhap lai" khong dung.
        if lw is None:
            continue
        got = lw
        src_home = home_label(home) + " · live API"
        for key, w in lw.items():
            acc["windows"][key] = dict(w, source_home=src_home)
        break
    if got is not None:
        acc["need_login"] = False
        prune_stale_windows(acc)
    elif ordered:
        acc["need_login"] = True
        log("  can dang nhap lai Codex cho %s (token het han / API tu choi)" % acc["email"])


def prune_stale_windows(acc):
    """Khi da co live API: bo cua so phien da qua reset hoac cu > 6 gio (vd 30 ngay 100% tu 14/08)."""
    wins = acc.get("windows") or {}
    if not any(w.get("source") == "live-api" for w in wins.values()):
        return
    now = int(time.time())
    for key in list(wins):
        w = wins[key]
        if w.get("source") == "live-api":
            continue
        if (w.get("resets_at") or 0) < now or now - int(w.get("read_at") or 0) > 6 * 3600:
            del wins[key]


def prune_stale_when_live(accounts):
    for acc in accounts.values():
        if any(w.get("source") == "live-api" for w in (acc.get("windows") or {}).values()):
            acc["need_login"] = False
            prune_stale_windows(acc)


def scan_homes(homes, app=None):
    app = app or (linux_app() if paths.in_wsl() else "")
    reg = harness_map(app) if app and os.path.isdir(app) else {}
    by_rt = agents_by_runtime(app) if app and os.path.isdir(app) else {}
    accounts = {}
    paths_by_email = {}
    for home in homes:
        if not os.path.isdir(home):
            continue
        sess = os.path.join(home, "sessions")
        files = []
        if os.path.isdir(sess):
            files = glob.glob(sess + "/**/*.jsonl", recursive=True)
        if not files:
            files = glob.glob(home + "/**/*.jsonl", recursive=True)
        if not files and not os.path.exists(os.path.join(home, "auth.json")):
            continue
        label = home_label(home)
        prov = read_provider(home)
        if "ollama" in prov.lower():
            log("--- %-44s bo qua: Codex qua Ollama" % label)
            continue
        ident = identity(home)
        if not ident:
            log("--- %-44s bo qua: khong phai tai khoan ChatGPT" % label)
            continue
        acc = accounts.setdefault(ident["email"], new_account(ident))
        paths_by_email.setdefault(ident["email"], []).append(home)
        if ident["last_refresh"] > acc["last_refresh"]:
            acc["last_refresh"] = ident["last_refresh"]
            acc["plan"] = ident["plan"] or acc["plan"]
        model = read_model(home)
        if model:
            acc["config_model"] = model
        ids = []
        npath = os.path.normpath(home)
        for k, v in reg.items():
            if os.path.normpath(k) == npath:
                ids = v
                break
        acc["homes"].append(label + (" (" + ", ".join(sorted(ids)) + ")" if ids else ""))
        acc["harnesses"].update(ids)
        for r in ids:
            acc["agents"].update(by_rt.get(r, set()))
        files = sorted(files, key=os.path.getmtime, reverse=True)
        acc["sessions"] += len(files)
        if files:
            acc["last_session_at"] = max(acc["last_session_at"], int(os.path.getmtime(files[0])))
        for key, w in latest_windows(files).items():
            cur = acc["windows"].get(key)
            if cur is None or w["read_at"] > cur["read_at"]:
                acc["windows"][key] = dict(w, source_home=label)
    for email, acc in accounts.items():
        overlay_live_on_account(acc, paths_by_email.get(email) or [])
    return accounts


def fetch_linux_via_wsl():
    script = paths.win_to_wsl(os.path.abspath(__file__))
    log("Goi WSL de doc Codex trong distro %s ..." % paths.DISTRO)
    r = paths.wsl_run(["python3", script, "--dump-json", "--linux-only"], timeout=300)
    errlog = (r.stderr or "").strip()
    if errlog:
        log(errlog[-2500:])
    if r.returncode != 0:
        log("WSL dump loi (code %s)" % r.returncode)
        return None
    raw = (r.stdout or "").strip()
    if not raw:
        log("WSL dump rong")
        return None
    try:
        data = json.loads(raw)
    except Exception as e:
        log("WSL dump khong phai JSON: %s" % e)
        return None
    out = {}
    for email, d in (data or {}).items():
        out[email] = account_from_dump(d)
    log("WSL: %d tai khoan" % len(out))
    return out


def collect_all():
    accounts = {}
    if paths.in_windows() and not LINUX_ONLY:
        if not WIN_ONLY:
            linux_accounts = fetch_linux_via_wsl()
            if linux_accounts is None:
                raise RuntimeError("WSL quota scan failed; keeping last-known-good database snapshot")
            accounts = merge_accounts(accounts, linux_accounts)
        accounts = merge_accounts(accounts, scan_homes(paths.windows_codex_homes(), app=""))
        prune_stale_when_live(accounts)
        return accounts
    homes = []
    if not WIN_ONLY:
        if paths.in_wsl():
            homes += glob.glob("/home/*/.codex*") + glob.glob("/root/.codex*")
        else:
            homes += glob.glob(os.path.expanduser("~") + "/.codex*")
    if not LINUX_ONLY and paths.in_wsl():
        homes += glob.glob("/mnt/c/Users/*/.codex*")
    homes = [h for h in sorted(set(homes)) if os.path.isdir(h)]
    accounts = scan_homes(homes, app=linux_app())
    prune_stale_when_live(accounts)
    return accounts


def rows_from_accounts(accounts):
    now = int(time.time())
    rows = []
    for email in sorted(accounts):
        acc = accounts[email]
        agents = sorted(acc["agents"])
        log("")
        log("=== TAI KHOAN %s  (goi %s, ma %s...)" % (email, acc["plan"] or "?", acc["account_short"]))
        for h in acc["homes"]:
            log("  dung o       : %s" % h)
        log("  phien        : %d  (moi nhat %s)" % (acc["sessions"], fmt(acc["last_session_at"])))
        log("  lam moi token: %s" % (acc["last_refresh"] or "-"))
        log("  model config : %s" % (acc.get("config_model") or "-"))
        log("  agent Buzz (%d): %s" % (len(agents), ", ".join(agents) or "(khong co - chi dung tay)"))
        if acc.get("need_login"):
            log("  canh bao     : can dang nhap lai Codex (chatgpt.com) de lay han muc live")
        base = {
            "account_id": email, "email": email, "plan": acc["plan"],
            "account_short": acc["account_short"], "homes": " | ".join(acc["homes"]),
            "harnesses": ",".join(sorted(acc["harnesses"])), "agent_count": len(agents),
            "agents": ", ".join(agents), "last_refresh": acc["last_refresh"],
            "sessions": acc["sessions"], "last_session_at": acc["last_session_at"],
        }
        if not acc["windows"]:
            log("  han muc      : (chua co phien nao tra rate_limits)")
            rows.append(dict(base, limit_id="", window_name="none", window_minutes=0,
                             used_percent=None, resets_at=0, read_at=0, source_home=""))
            continue
        for key in sorted(acc["windows"], key=lambda k: acc["windows"][k]["window_minutes"]):
            w = acc["windows"][key]
            if w["resets_at"] and w["resets_at"] < now:
                state = "DA QUA MOC RESET - so khong con dung"
            elif now - w["read_at"] > MAX_READING_AGE:
                state = "so qua cu %.0f ngay - khong dung de canh bao" % ((now - w["read_at"]) / 86400.0)
            elif now - w["read_at"] > 6 * 3600:
                state = "so cu %.0f gio" % ((now - w["read_at"]) / 3600.0)
            else:
                state = "con hieu luc"
            log("  cua so %-6s: da dung %5.1f%%  con %5.1f%%  reset %s  doc luc %s tu %s  [%s]" % (
                window_txt(w["window_minutes"]), w["used_percent"], 100.0 - w["used_percent"],
                fmt(w["resets_at"]), fmt(w["read_at"]), w.get("source_home") or "", state))
            rows.append(dict(base, limit_id=w["limit_id"], window_name=key,
                             window_minutes=w["window_minutes"], used_percent=w["used_percent"],
                             resets_at=w["resets_at"], read_at=w["read_at"],
                             source_home=w.get("source_home") or ""))
    log("\nTong: %d tai khoan Codex chinh hang" % len(accounts))
    return rows


def write_db(rows):
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        conn.execute("DROP TABLE IF EXISTS codex_account_limits")
        conn.execute(SCHEMA)
        ph = ",".join("?" * len(COLS))
        for r in rows:
            conn.execute("INSERT INTO codex_account_limits(%s) VALUES(%s)" % (",".join(COLS), ph),
                         [r.get(c) for c in COLS])
        conn.execute("DELETE FROM account_capacity_snapshots WHERE source = ?", (SOURCE_TAG,))
        conn.execute("DELETE FROM account_capacity_snapshots WHERE agent_id IN (?, ?)",
                     ("codex-ollama", "codex-t2"))
        by_acc = {}
        for r in rows:
            if r["used_percent"] is not None:
                by_acc.setdefault(r["account_id"], []).append(r)
        for acc_id, rs in by_acc.items():
            live = [r for r in rs if r["resets_at"] > now and now - r["read_at"] <= MAX_READING_AGE]
            pick = min(live, key=lambda r: 100.0 - r["used_percent"]) if live else max(rs, key=lambda r: r["read_at"])
            reset_iso = None
            if pick["resets_at"]:
                reset_iso = datetime.datetime.fromtimestamp(pick["resets_at"], datetime.timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO account_capacity_snapshots"
                "(captured_at, agent_id, model, remaining_percent, reset_at, source) VALUES(?,?,?,?,?,?)",
                (pick["read_at"], acc_id, window_txt(pick["window_minutes"]),
                 100.0 - pick["used_percent"], reset_iso, SOURCE_TAG))
        conn.commit()
    finally:
        conn.close()
    log("Da ghi %d dong cho %d tai khoan vao %s" % (
        len(rows), len({r["account_id"] for r in rows}), os.path.basename(DB_PATH)))


def main():
    real_db = DB_PATH if os.name == "nt" else os.path.realpath(DB_PATH)
    if not DUMP_JSON and not DRY and paths.in_wsl() and real_db.startswith("/mnt/"):
        # SPEC V4: chi tien trinh Windows ghi usage.db (WAL khong dong bo khoa qua /mnt).
        log("TU CHOI ghi %s tu WSL. Chay tu Windows: python bin\\buzz_quota.py "
            "(WSL chi dung --dump-json)" % DB_PATH)
        return 2
    accounts = collect_all()
    if DUMP_JSON:
        sys.stdout.write(json.dumps(dump_accounts(accounts), ensure_ascii=False))
        sys.stdout.write("\n")
        return 0
    rows = rows_from_accounts(accounts)
    if not rows:
        return 1
    if DRY:
        log("--dry-run: khong ghi vao %s" % DB_PATH)
        return 0
    write_db(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
