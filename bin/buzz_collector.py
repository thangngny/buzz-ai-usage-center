#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bo thu thap usage THAT cho he Buzz cua openclawboss.

Vi sao can file nay: dashboard goc do he cua tac gia (Claude CLI + 4 cong Google
AGY). He nay khong dung nguon nao trong so do. Ba harness that dang chay:

    codex-acp-openai  -> gpt-5.6-sol    -> ~/.codex/sessions/**/*.jsonl
    codex-acp         -> gpt-oss:120b   -> ~/.codex-ollama/sessions/**/*.jsonl
    claude-code-acp   -> kimi-k2.7-code -> ~/.claude/projects/**/*.jsonl

Log cua buzz-acp KHONG ghi token, nen token phai lay tu file phien cua chinh
harness. Codex ghi su kien `token_count`; Claude Code ghi `message.usage`.

Gan luot ve dung agent: file phien khong biet no chay cho agent nao. Ta dung
hai tang:
  1. Loc theo harness — phien trong ~/.codex chi co the thuoc agent dat
     runtime=codex-openai, v.v.
  2. Trong nhom do, chon agent co cua so luot (doc tu log buzz-acp) trum len
     thoi diem phien bat dau. Khong khop thi don vao agent gia lap cua harness
     (agent_id = "<harness>:unattributed") de TONG SO van dung, chi mat chi tiet.

Chay:  python3 bin/buzz_collector.py [--dry-run]
"""
import json, os, re, shlex, sqlite3, sys, glob, uuid, datetime

HOME = os.path.expanduser("~")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import paths

# Collector phai chay trong WSL (log + phien nam o /home/openclawboss), nhung
# WSL KHONG DUOC ghi usage.db: WAL khong dong bo khoa giua WSL (/mnt/d) va
# dashboard Windows, ghi cheo lam hong CSDL (SPEC V4). Tu Windows, run_via_wsl()
# chup ban sao tam, de WSL ghi vao ban sao, roi Windows tu ghi ket qua vao usage.db.
DB_PATH = os.environ.get("BUZZ_USAGE_DB", os.path.join(ROOT, "usage.db"))
# Dat boi run_via_wsl: DB_PATH la ban sao tam, khong ai khac mo.
SCRATCH = os.environ.get("BUZZ_COLLECT_SCRATCH") == "1"

MANAGED = HOME + "/.local/share/xyz.block.buzz.app.dev/agents/managed-agents.json"
AGENT_LOGS = HOME + "/.local/share/xyz.block.buzz.app.dev/agents/logs"

CUSTOM_HARNESSES = HOME + "/.local/share/xyz.block.buzz.app.dev/custom_harnesses"
# Hai harness nay tu dat CODEX_HOME ben trong wrapper, khong ghi vao env cua file
# dang ky, nen phai biet truoc.
WRAPPER_CODEX_HOME = {
    "codex-ollama": HOME + "/.codex-ollama",
    "codex-t2": HOME + "/.codex-t2",
}


def _codex_home_model(home):
    """Model khai trong config.toml cua mot CODEX_HOME (khong khai thi ghi mac dinh)."""
    try:
        for line in open(os.path.join(home, "config.toml"), encoding="utf-8"):
            t = line.strip()
            if "=" in t and t.split("=", 1)[0].strip() == "model":
                return t.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
    except OSError:
        pass
    return "codex-mac-dinh"


def load_harnesses():
    """runtime -> (thu muc phien, dinh dang, model), DOC TU custom_harnesses.

    Ban truoc ghi cung 4 harness. Ngay 10-11/09 agent duoc chuyen sang harness moi
    (codex-sales: 37 agent, gom ca Lead/Dev/BA/Reviewer/Ops; codex-creative;
    codex-creative-lead). Collector khong biet cac id do nen loai gan het agent —
    luot chua gan tang tu 278 len 3.061 — va bo qua han phien trong ~/.codex-sales,
    ~/.codex-creative. Doc tu file dang ky thi harness moi tu duoc nhan.
    """
    out = {}
    for f in sorted(glob.glob(CUSTOM_HARNESSES + "/*.json")):
        try:
            h = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        hid = h.get("id")
        env = h.get("env") or {}
        if not hid:
            continue
        home = env.get("CODEX_HOME") or WRAPPER_CODEX_HOME.get(hid)
        if home:
            out[hid] = (home + "/sessions", "codex", _codex_home_model(home))
        elif env.get("ANTHROPIC_MODEL"):
            out[hid] = (HOME + "/.claude/projects", "claude", env["ANTHROPIC_MODEL"])
        elif env.get("HERMES_HOME"):
            hh = env["HERMES_HOME"]
            out[hid] = (os.path.join(hh, "logs"), "hermes", _hermes_model(hh))
    return out


def _hermes_model(home):
    try:
        for line in open(os.path.join(home, "config.yaml"), encoding="utf-8"):
            t = line.strip()
            if t.startswith("default:"):
                return t.split(":", 1)[1].strip().strip("'").strip('"')
    except OSError:
        pass
    return "hermes-mac-dinh"


HARNESS = load_harnesses()


DRY = "--dry-run" in sys.argv
NO_BACKUP = "--no-backup" in sys.argv


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- agents ----
def load_agents():
    """Doc agent that tu Buzz. Tra ve list dict + community_id pho bien nhat."""
    if not os.path.exists(MANAGED):
        log("KHONG THAY %s" % MANAGED)
        return [], "", set()
    out = []
    all_pk = set()
    for a in json.load(open(MANAGED, encoding="utf-8")):
        pk = (a.get("pubkey") or "").lower()
        rt = a.get("runtime")
        if pk:
            all_pk.add(pk)          # ke ca agent dung san (Fizz/Honey/Pollen)
        # Giu MOI agent co pubkey, ke ca runtime la. Can cho gan luot qua @mention
        # va dau van tay prompt; loc theo harness o day tung lam mat gan het agent.
        if not pk:
            continue
        out.append({
            "pubkey": pk,
            "name": a.get("display_name") or a.get("name") or pk[:8],
            "runtime": rt or "-",
            "model": HARNESS[rt][2] if rt in HARNESS else "-",
            "active": bool(a.get("is_active")),
            "fingerprint": prompt_fingerprint(a.get("system_prompt") or ""),
        })
    return out, detect_community(), all_pk


def prompt_fingerprint(sp):
    """Lay manh dac trung tu system_prompt de nhan dang agent trong file phien.

    Buzz nhet nguyen system_prompt cua agent vao phien harness duoi dang mot user
    message, nen tim thay manh nay la biet phien thuoc agent nao — chinh xac,
    khong phai suy doan theo thoi gian.

    Hai cai bay da gap khi chon manh nay:
      1. Prompt CO THE bi sua (07-08/09 da bo ten model khoi prompt Lead/Ops/
         Reviewer). Lay manh qua dai se khong khop nhung phien CU. Nen chi lay
         phan dau — phan neu vai tro — vi phan do gan nhu khong bao gio doi.
      2. Nhom [DK] 9 agent dung chung khung prompt: dong dai dau tien giong het
         nhau ("Muc tieu la giam cong viec lap lai..."). Phai uu tien tieu de
         markdown "# [DK] <Ten>" vi do moi la cho khac nhau.
    """
    lines = [l.strip() for l in (sp or "").splitlines() if l.strip()]
    # Uu tien tieu de markdown: "# [DK] People Ops", "# TroLy — dieu huong ..."
    for l in lines[:3]:
        if l.startswith("#"):
            t = l.lstrip("# ").strip()
            if len(t) >= 6:
                return t[:40]
    # Neu khong co tieu de: lay dau dong dai dau tien, NGAN thoi de chiu duoc
    # viec prompt bi sua ve sau.
    for l in lines:
        if len(l) > 25:
            return l[:55]
    return ""


def detect_community():
    """Community lay tu log buzz-acp moi nhat — KHONG hardcode, vi no da doi
    3 lan (dukickk -> platogroup -> ncthang04) trong vong 2 ngay."""
    files = sorted(glob.glob(AGENT_LOGS + "/*.log"), key=os.path.getmtime, reverse=True)
    for f in files[:12]:
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        m = re.findall(r"relay=wss://([^\s]+)", txt)
        if m:
            return m[-1]
    return "unknown.communities.buzz.xyz"


def agent_turn_windows(pubkey):
    """Cua so luot cua mot agent, doc tu log buzz-acp.
    Tra ve [(bat_dau_epoch, ket_thuc_epoch)]. Dung de gan phien ve agent."""
    wins = []
    for f in glob.glob("%s/%s__*.log" % (AGENT_LOGS, pubkey)):
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        txt = re.sub(r"\x1b\[[0-9;]*m", "", txt)
        # moi dong co dau thoi gian ISO; luot ket thuc o agent_returned
        for m in re.finditer(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)[.\d]*Z.*?agent_returned", txt, re.M):
            end = iso_to_epoch(m.group(1))
            if end:
                wins.append((end - 7200, end))  # luot toi da 2h (max_turn=7200s)
    return wins


def iso_to_epoch(s):
    try:
        return int(datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
                   .replace(tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        return None


# -------------------------------------------------------------- sessions ----
def parse_codex_session(path):
    """Doc mot rollout JSONL cua Codex -> list luot {ts, tokens...}."""
    turns, started, model, cur_event = [], None, None, None
    try:
        fh = open(path, encoding="utf-8", errors="ignore")
    except OSError:
        return [], None, None
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = iso_ms_to_epoch(d.get("timestamp"))
            if started is None and ts:
                started = ts
            p = d.get("payload") or {}
            if d.get("type") == "turn_context" and p.get("model"):
                model = p["model"]

            # Ghi nho khoi <buzz-event> gan nhat: moi luot tinh phi thuoc ve
            # nguoi da goi trong khoi do.
            if d.get("type") == "response_item" and p.get("role") == "user":
                for t in user_texts(p):
                    mm = BUZZ_EVENT_RE.search(t)
                    if mm:
                        ev = parse_buzz_event(mm.group(1))
                        if ev:
                            cur_event = ev
                continue

            if d.get("type") != "event_msg" or p.get("type") != "token_count":
                continue
            u = ((p.get("info") or {}).get("last_token_usage")) or {}
            if not u:
                continue
            turns.append({
                "ts": ts or started or 0,
                "input": u.get("input_tokens") or 0,
                "output": u.get("output_tokens") or 0,
                "total": u.get("total_tokens") or 0,
                "cache_read": u.get("cached_input_tokens") or 0,
                "cache_write": u.get("cache_write_input_tokens") or 0,
                "thinking": u.get("reasoning_output_tokens") or 0,
                "event": cur_event,
            })
    return turns, started, model


def parse_claude_session(path):
    """Doc JSONL cua Claude Code -> list luot tu message.usage."""
    turns, started, model, cur_event = [], None, None, None
    try:
        fh = open(path, encoding="utf-8", errors="ignore")
    except OSError:
        return [], None, None
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = iso_ms_to_epoch(d.get("timestamp"))
            if started is None and ts:
                started = ts
            msg = d.get("message") or {}
            model = msg.get("model") or model
            if msg.get("role") == "user":
                for t in user_texts(msg):
                    mm = BUZZ_EVENT_RE.search(t)
                    if mm:
                        ev = parse_buzz_event(mm.group(1))
                        if ev:
                            cur_event = ev
            u = msg.get("usage") or d.get("usage")
            if not u:
                continue
            inp = u.get("input_tokens") or 0
            out = u.get("output_tokens") or 0
            cr = u.get("cache_read_input_tokens") or 0
            cw = u.get("cache_creation_input_tokens") or 0
            th = ((u.get("output_tokens_details") or {}).get("thinking_tokens")) or 0
            turns.append({
                "ts": ts or started or 0, "input": inp, "output": out,
                "total": inp + out, "cache_read": cr, "cache_write": cw,
                "thinking": th, "event": cur_event,
            })
    return turns, started, model


BUZZ_EVENT_RE = re.compile(
    r"<buzz-event[^>]*>(.*?)</buzz-event>", re.S)


def parse_buzz_event(text):
    """Boc thong tin tu khoi <buzz-event> ma Buzz nhet vao phien harness.

    Khoi nay la nguon CHINH XAC NHAT: no ghi ro ai gui, kenh nao, goi agent nao,
    luc may gio. Nho no moi bocs duoc quota theo TUNG NGUOI — dieu ma dau van tay
    prompt (chi biet agent) khong lam duoc.

    Vi du khoi:
        Event ID: 18e0bfd9...
        Channel: Tech (#31609c50-d3c9-44e7-af2f-6b3d38ae6545)
        From: NcThang (npub: npub1..., hex: 2da3184b...)
        Content: @Lead dieu phoi agent danh gia code cho toi
        Parsed: mentions=[Lead (6cdab9d6...)]
    """
    out = {}
    m = re.search(r"^Event ID:\s*([0-9a-f]{16,})", text, re.M)
    if m:
        out["event_id"] = m.group(1)
    m = re.search(r"^Channel:\s*(.*?)\s*\(#([0-9a-f-]{36})\)", text, re.M)
    if m:
        out["channel_name"], out["channel_id"] = m.group(1), m.group(2)
    m = re.search(r"^From:\s*(.*?)\s*\(.*?hex:\s*([0-9a-f]{64})", text, re.M)
    if m:
        out["from_name"], out["from_pubkey"] = m.group(1), m.group(2).lower()
    m = re.search(r"^Time:\s*(\S+)", text, re.M)
    if m:
        out["time"] = m.group(1)
    # agent duoc goi — lay tu dong Parsed: mentions=[Ten (pubkey)]
    m = re.search(r"mentions=\[(.*?)\]", text, re.S)
    if m:
        pks = re.findall(r"\(([0-9a-f]{64})\)", m.group(1))
        if pks:
            out["mentioned"] = [p.lower() for p in pks]
    return out


def user_texts(payload):
    """Tra ve list text cua mot user message (Codex va Claude khac cau truc)."""
    c = payload.get("content")
    if isinstance(c, str):
        return [c]
    out = []
    for ct in (c or []):
        if isinstance(ct, dict):
            t = ct.get("text")
            if t:
                out.append(t)
        elif isinstance(ct, str):
            out.append(ct)
    return out


def parse_hermes_log(path):
    """Hermes khong ghi jsonl token. Moi lan goi model trong agent.log = 1 luot
    (usage_quality=unknown, token NULL). Van dem duoc CLI da chay."""
    turns, started, model = [], None, None
    rx = re.compile(
        r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).*OpenAI client created.*model=(\S+)"
    )
    try:
        fh = open(path, encoding="utf-8", errors="ignore")
    except OSError:
        return [], None, None
    ict = datetime.timezone(datetime.timedelta(hours=7))
    with fh:
        for line in fh:
            m = rx.search(line)
            if not m:
                continue
            try:
                ts = int(datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                         .replace(tzinfo=ict).timestamp())
            except ValueError:
                continue
            if started is None:
                started = ts
            model = m.group(2).rstrip(",;")
            turns.append({
                "ts": ts, "input": None, "output": None, "total": None,
                "cache_read": None, "cache_write": None, "thinking": None,
                "event": None, "quality": "unknown",
            })
    return turns, started, model


def iso_ms_to_epoch(s):
    if not s:
        return None
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


# ------------------------------------------------------------------- ghi ----
COMMUNITIES = [
    "dukick.communities.buzz.xyz",
    "dukickk.communities.buzz.xyz",
    "platogroup.communities.buzz.xyz",
    "ncthang04.communities.buzz.xyz",
    "nguyenphiylan.communities.buzz.xyz",
]
BUZZ_BIN = HOME + "/buzz/target/debug/buzz"
CHAN_MAP_CACHE = os.path.join(ROOT, ".channel-map.json")


def load_channel_map(refresh=False):
    """Ban do channel_id -> community, doc TU LOG AGENT, khong can keyring.

    Can ban do nay vi file phien harness chi ghi channel_id, khong ghi community.
    Ma he nay co 5 community va da doi 3 lan trong 2 ngay, nen khong the doan.

    Vi sao doc log thay vi goi `buzz channels list`:
      Goi CLI thi phai lay khoa tu GNOME keyring, ma kho do chi mo khi Buzz dang
      chay va mo khoa thanh cong. Thuc te no hay ket o trang thai khoa (daemon
      `--start` khong unlock gianh mat Secret Service), lam bo do lieu phu thuoc
      vao mot thu no khong nen phu thuoc. Cong cu DO khong duoc doi he thong
      phai dang song moi chay duoc.

    Log agent da co san ca hai manh, trong cung mot file:
        buzz-acp starting: relay=wss://<community> ...
        subscribed to channel <uuid>
    Doc tuan tu: moi dong `subscribed` thuoc ve `relay=` gan nhat phia truoc.

    Han che: chi thay kenh ma agent tung nghe. Du cho viec quy usage, vi usage
    chi phat sinh o kenh co agent.
    """
    out = {}
    rx_relay = re.compile(r"relay=wss://(\S+)")
    rx_chan = re.compile(r"subscribed to channel ([0-9a-f-]{36})")
    for f in glob.glob(AGENT_LOGS + "/*.log"):
        cur = None
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                m = rx_relay.search(line)
                if m:
                    cur = m.group(1)
                    continue
                m = rx_chan.search(line)
                if m and cur:
                    out[m.group(1)] = cur
    if out:
        n_comm = len(set(out.values()))
        log("  Ban do kenh (tu log): %d kenh tren %d community" % (len(out), n_comm))
        for comm in sorted(set(out.values())):
            log("     %-38s %d kenh"
                % (comm, sum(1 for v in out.values() if v == comm)))
    else:
        log("  ! Khong dung duoc ban do kenh tu log — quy het ve community dang do.")
    try:
        json.dump(out, open(CHAN_MAP_CACHE, "w", encoding="utf-8"), indent=1)
    except OSError:
        pass
    return out


def purge_agent_principals(conn, all_agent_pk):
    """Xoa agent khoi bang principals.

    Agent tag lan nhau nen truong `From:` trong <buzz-event> co the la MOT AGENT.
    Neu khong don, trang "Nguoi dung" se hien ca bot lan nguoi that va con so
    quota theo nguoi sai hoan toan (Lead/Reviewer/Ops/Dev/BA/Fizz tung bi dem
    nham thanh nguoi).
    """
    if not all_agent_pk:
        return 0
    rows = [r[0] for r in conn.execute("SELECT principal_pubkey FROM principals")]
    bad = [pk for pk in rows if pk in all_agent_pk]
    for pk in bad:
        conn.execute("DELETE FROM principals WHERE principal_pubkey=?", (pk,))
    return len(bad)


def upsert_principals(conn, people):
    """Ghi NGUOI DUNG that (khong phai agent) vao bang principals.

    Nguon: truong `From:` trong khoi <buzz-event>. Day la cach duy nhat biet
    ai da goi agent — tu do moi tinh duoc quota theo tung nguoi.
    """
    now = int(datetime.datetime.now().timestamp())
    for pk, name in people.items():
        row = conn.execute(
            "SELECT community_id, first_seen_at FROM principals WHERE principal_pubkey=?",
            (pk,)).fetchone()
        comm = conn.execute(
            "SELECT community_id FROM requests WHERE principal_pubkey=? "
            "ORDER BY started_at DESC LIMIT 1", (pk,)).fetchone()
        comm = (comm or [None])[0] or (row or ["", 0])[0] or "unknown"
        first = conn.execute(
            "SELECT MIN(started_at) FROM requests WHERE principal_pubkey=?", (pk,)).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(started_at) FROM requests WHERE principal_pubkey=?", (pk,)).fetchone()[0]
        conn.execute(
            "INSERT INTO principals(principal_pubkey, community_id, display_name,"
            " first_seen_at, last_seen_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(principal_pubkey) DO UPDATE SET community_id=excluded.community_id,"
            " display_name=COALESCE(NULLIF(excluded.display_name,''), principals.display_name),"
            " first_seen_at=MIN(principals.first_seen_at, excluded.first_seen_at),"
            " last_seen_at=MAX(principals.last_seen_at, excluded.last_seen_at)",
            (pk, comm, name or "", first or now, last or now))


def upsert_agents(conn, agents):
    """Dang ky agent that vao bang `agents`, kem agent gia lap moi harness
    de hung nhung luot khong gan duoc ve ai."""
    rows = 0
    for a in agents:
        conn.execute(
            "INSERT INTO agents(agent_id, agent_pubkey, display_name, backend_kind) "
            "VALUES(?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET "
            "agent_pubkey=excluded.agent_pubkey, display_name=excluded.display_name, "
            "backend_kind=excluded.backend_kind",
            (a["pubkey"][:16], a["pubkey"], a["name"], a["runtime"]))
        rows += 1
    for rt in HARNESS:
        conn.execute(
            "INSERT INTO agents(agent_id, agent_pubkey, display_name, backend_kind) "
            "VALUES(?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET "
            "display_name=excluded.display_name",
            ("%s:unattributed" % rt, None, "%s (chua gan)" % rt, rt))
        rows += 1
    return rows


def backfill_acp_windows(conn, agents, windows, community, chan_to_comm):
    """Agent da chay (log buzz-acp agent_returned) nhung khong co file phien
    Codex/Claude/Hermes — van ghi 1 luot unknown de dashboard nhan CLI."""
    have = {r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM requests")}
    n = 0
    for a in agents:
        aid = a["pubkey"][:16]
        if aid in have:
            continue
        wins = windows.get(a["pubkey"] or "", ())
        if not wins:
            continue
        rt = a["runtime"] or "unknown"
        for i, (_lo, hi) in enumerate(wins):
            sid = "acp-log:%s" % aid
            rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "%s#%d" % (sid, i)))
            conn.execute(
                "INSERT INTO requests(request_id, community_id, channel_id,"
                " thread_id, trigger_event_id, principal_pubkey, agent_id, started_at,"
                " completed_at, status, runtime_ms, model, session_id, usage_quality,"
                " normalized_units, normalization_version, dry_run_verdict, detail)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, community, "", sid, "%s#%d" % (sid, i), None, aid,
                 hi, hi, "completed", None, "-", sid, "unknown", None,
                 "v1-actual-tokens", "WOULD_ALLOW", "backfill tu log buzz-acp"))
            conn.execute(
                "INSERT INTO usage_events(request_id, occurred_at, usage_quality, source,"
                " input_tokens, output_tokens, total_tokens, cache_read_tokens,"
                " cache_write_tokens, thinking_tokens, cost_usd, model)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, hi, "unknown", "buzz-acp-log", None, None, None, None, None, None,
                 None, None))
            n += 1
    return n


def pick_agent(turn_ts, candidates, windows):
    """Chon agent co cua so luot trum len thoi diem nay. Nhieu ung vien thi lay
    cai co diem ket thuc gan nhat — luot vua xong thuong la thu pham."""
    best, best_gap = None, None
    for a in candidates:
        for lo, hi in windows.get(a["pubkey"], ()):
            if lo <= turn_ts <= hi:
                gap = hi - turn_ts
                if best_gap is None or gap < best_gap:
                    best, best_gap = a, gap
    return best


def collect(conn, agents, community, all_agent_pk):
    # Dung lai TU DAU moi lan chay. Ly do: neu dung INSERT OR IGNORE thi ban ghi
    # cu khong duoc cap nhat (agent_id gan sai o lan truoc se ket lai), con
    # usage_events thi bi nhan doi. Xoa sach roi ghi lai la cach duy nhat bao dam
    # chay bao nhieu lan cung ra dung mot ket qua.
    conn.execute("DELETE FROM usage_events")
    conn.execute("DELETE FROM requests")

    by_rt = {}
    for a in agents:
        by_rt.setdefault(a["runtime"], []).append(a)
    windows = {a["pubkey"]: agent_turn_windows(a["pubkey"]) for a in agents}

    n_req = n_usage = n_skip = n_people_hits = 0
    stats = {}
    people = {}                      # pubkey -> ten hien thi (nguoi that)
    agent_by_pk = {a["pubkey"]: a for a in agents}
    chan_to_comm = load_channel_map()
    # Gom runtime theo thu muc phien. codex-creative va codex-creative-lead cung
    # ghi vao ~/.codex-creative; quet theo tung runtime se dem MOI PHIEN HAI LAN.
    groups = {}
    for rt_, (sd_, fm_, dm_) in HARNESS.items():
        g = groups.setdefault(sd_, {"fmt": fm_, "model": dm_, "rts": []})
        g["rts"].append(rt_)

    for sess_dir, g in sorted(groups.items()):
        fmt, default_model = g["fmt"], g["model"]
        rt = sorted(g["rts"])[0]          # nhan dai dien cho ca nhom
        if not os.path.isdir(sess_dir):
            continue
        if fmt == "hermes":
            files = glob.glob(os.path.join(sess_dir, "*.log"))
        else:
            files = glob.glob(sess_dir + "/**/*.jsonl", recursive=True)
        cands = [a for r_ in g["rts"] for a in by_rt.get(r_, [])]
        for path in files:
            if fmt == "codex":
                turns, started, model = parse_codex_session(path)
            elif fmt == "claude":
                turns, started, model = parse_claude_session(path)
            else:
                turns, started, model = parse_hermes_log(path)
            if not turns:
                continue
            sid = os.path.splitext(os.path.basename(path))[0]
            sid_key = os.path.abspath(path)

            # Gan CHINH XAC bang dau van tay prompt: Buzz nhet system_prompt cua
            # agent vao trong phien harness, nen tim thay manh nao la biet ngay
            # phien thuoc ai. Chinh xac hon han doan theo thoi gian.
            session_owner = None
            try:
                raw = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                raw = ""
            if raw:
                # Khop voi TOAN BO agent, khong chi nhung con dang dat harness nay.
                # Ly do: runtime thay doi theo thoi gian (vd Lead/Ops/Reviewer da
                # chuyen codex-ollama -> codex-openai ngay 08/09). Phien cu van
                # thuoc ve chinh agent do. Dau van tay prompt khong phu thuoc harness.
                matched = [a for a in agents if a["fingerprint"] and a["fingerprint"] in raw]
                if len(matched) == 1:
                    session_owner = matched[0]
                elif len(matched) > 1:
                    # Nhieu agent trung prompt (vd Lead/LeadTech, BA/BATech dung
                    # chung persona). Go bang cua so luot; khong go duoc thi lay
                    # con dau cho on dinh.
                    tie = pick_agent(turns[0]["ts"], matched, windows)
                    session_owner = tie or matched[0]
            for i, t in enumerate(turns):
                quality = t.get("quality") or "actual_harness_reported"
                if not t["total"] and quality != "unknown":
                    continue
                ev = t.get("event") or {}

                # Uu tien agent duoc @mention trong buzz-event — chac chan hon
                # dau van tay prompt, vi no la pubkey that cua agent bi goi.
                owner = None
                for pk in (ev.get("mentioned") or []):
                    owner = agent_by_pk.get(pk)
                    if owner:
                        break
                owner = owner or session_owner or pick_agent(t["ts"], cands, windows)
                agent_id = owner["pubkey"][:16] if owner else "%s:unattributed" % rt
                if not owner:
                    n_skip += 1

                principal = ev.get("from_pubkey")
                if principal:
                    n_people_hits += 1
                    # Agent tag lan nhau, nen truong From: co the la MOT AGENT chu
                    # khong phai nguoi. Van luu principal_pubkey de biet ai kich
                    # hoat, nhung KHONG dua agent vao bang principals — neu khong
                    # trang "Nguoi dung" se lan lon nguoi that voi bot.
                    if principal not in all_agent_pk:
                        people[principal] = (ev.get("from_name")
                                             or people.get(principal) or "")
                chan = ev.get("channel_id") or ""
                comm = chan_to_comm.get(chan, community)

                rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "%s#%d" % (sid_key, i)))
                conn.execute(
                    "INSERT INTO requests(request_id, community_id, channel_id,"
                    " thread_id, trigger_event_id, principal_pubkey, agent_id, started_at,"
                    " completed_at, status, runtime_ms, model, session_id, usage_quality,"
                    " normalized_units, normalization_version, dry_run_verdict, detail)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, comm, chan, sid,
                     ev.get("event_id") or "%s#%d" % (sid, i), principal, agent_id,
                     t["ts"], t["ts"], "completed", None, model or default_model, sid,
                     quality, (None if t["total"] is None else float(t["total"])),
                     "v1-actual-tokens",
                     "WOULD_ALLOW", ev.get("channel_name") or "thu tu file phien"))
                n_req += 1
                src = "hermes-agent-log" if fmt == "hermes" else "%s-session-jsonl" % fmt
                conn.execute(
                    "INSERT INTO usage_events(request_id, occurred_at, usage_quality, source,"
                    " input_tokens, output_tokens, total_tokens, cache_read_tokens,"
                    " cache_write_tokens, thinking_tokens, cost_usd, model)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, t["ts"], quality, src,
                     t["input"], t["output"], t["total"], t["cache_read"],
                     t["cache_write"], t["thinking"], None, model or default_model))
                n_usage += 1
                s = stats.setdefault(rt, {"turns": 0, "tokens": 0})
                s["turns"] += 1
                s["tokens"] += int(t["total"] or 0)
    n_bf = backfill_acp_windows(conn, agents, windows, community, chan_to_comm)
    if n_bf:
        log("  backfill tu log buzz-acp (CLI khong co file phien): %d luot" % n_bf)
        n_req += n_bf
    purge_agent_principals(conn, all_agent_pk)
    upsert_principals(conn, people)
    return n_req, n_usage, n_skip, stats, people, n_people_hits


def rebuild_aggregates(conn, community):
    """Dung lai usage_aggregates tu requests + usage_events. Moc ngay theo ICT
    (UTC+7) dung nhu dashboard mong doi."""
    conn.execute("DELETE FROM usage_aggregates")
    ICT = 7 * 3600
    for period, span in (("daily", 86400), ("weekly", 7 * 86400), ("monthly", 30 * 86400)):
        conn.execute(
            "INSERT INTO usage_aggregates(period, period_start, community_id, agent_id,"
            " principal_pubkey, requests, completed, failed, units_actual, units_unknown,"
            " actual_events, unknown_events) "
            "SELECT ?, ((r.started_at + ?) / ?) * ? - ?, r.community_id, r.agent_id,"
            " COALESCE(r.principal_pubkey,''), COUNT(*),"
            " SUM(CASE WHEN r.status='completed' THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN r.status!='completed' THEN 1 ELSE 0 END),"
            " COALESCE(SUM(r.normalized_units),0), 0, COUNT(*), 0 "
            "FROM requests r GROUP BY 2,3,4,5",
            (period, ICT, span, span, ICT))


# Bang collector dung lai tu dau moi lan chay.
REBUILT_TABLES = ("usage_events", "requests", "usage_aggregates")
# Agent cua he khac ma collector go bo (xem main()).
FOREIGN_BACKEND_KINDS = ("claude-cli", "agy")
# Lan chay WSL. Dashboard cho COLLECT_TIMEOUT (> WSL_TIMEOUT + 2 lan cho khoa 60 s):
# neu dashboard giet truoc, `finally` khong chay va file tam bi bo lai.
WSL_TIMEOUT = 480


def _remove_db_files(path):
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
        except OSError as e:
            _emit(sys.stderr, "collector: khong xoa duoc %s: %s\n" % (path + suffix, e))


def _emit(stream, text):
    """Ghi log ma khong bao gio vo vi ma hoa: dashboard chay collector qua pipe,
    tren Windows khong co PYTHONIOENCODING thi stdout la cp1252 strict va ten
    tieng Viet lam UnicodeEncodeError (truoc day xay ra TRUOC buoc merge)."""
    if not text:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(text.encode("utf-8", "replace"))
        buffer.flush()
    else:
        enc = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(enc, "replace").decode(enc, "replace"))


def _table_columns(conn, schema, table):
    return [r[1] for r in conn.execute("PRAGMA %s.table_info(%s)" % (schema, table))]


def snapshot_db(db_path, dest):
    """Ban sao nhat quan cua usage.db (backup API, an toan khi dashboard dang mo
    WAL). Ban sao dung rollback journal de WSL khong bao gio dung WAL qua /mnt."""
    _remove_db_files(dest)
    src = sqlite3.connect(db_path, timeout=60.0)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def merge_scratch(db_path, scratch):
    """Ghi ket qua collector tu ban sao vao usage.db — chi tu tien trinh Windows,
    trong mot transaction. Chi dong vao bang cua collector; settings, quota,
    allowance... giu nguyen."""
    check = sqlite3.connect(scratch)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as e:
        result = str(e)
    finally:
        check.close()
    if result != "ok":
        raise RuntimeError("ban sao tam hong (%s) — giu nguyen %s" % (result, db_path))

    conn = sqlite3.connect(db_path, timeout=60.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ATTACH DATABASE ? AS s", (scratch,))

        def copy_sql(table, verb):
            # Cot tuong minh theo thu tu cua usage.db: ban sao lech luoc do thi
            # dung han thay vi ghi cot nay vao cot kia.
            cols = _table_columns(conn, "main", table)
            if set(cols) != set(_table_columns(conn, "s", table)):
                raise RuntimeError("luoc do bang %s lech giua usage.db va ban sao" % table)
            names = ",".join('"%s"' % c for c in cols)
            return "%s INTO main.%s (%s) SELECT %s FROM s.%s" % (verb, table, names, names, table)

        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                kinds = ",".join("?" * len(FOREIGN_BACKEND_KINDS))
                conn.execute(
                    "DELETE FROM main.account_capacity_snapshots WHERE agent_id IN "
                    "(SELECT agent_id FROM main.agents WHERE backend_kind IN (%s))" % kinds,
                    FOREIGN_BACKEND_KINDS)
                conn.execute("DELETE FROM main.agents WHERE backend_kind IN (%s)" % kinds,
                             FOREIGN_BACKEND_KINDS)
                conn.execute(copy_sql("agents", "INSERT OR REPLACE"))
                conn.execute(
                    "DELETE FROM main.principals WHERE principal_pubkey IN "
                    "(SELECT agent_pubkey FROM s.agents WHERE agent_pubkey IS NOT NULL)")
                conn.execute(copy_sql("principals", "INSERT OR REPLACE"))
                for table in REBUILT_TABLES:
                    conn.execute("DELETE FROM main.%s" % table)
                    conn.execute(copy_sql(table, "INSERT"))
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise
        finally:
            try:
                conn.execute("DETACH DATABASE s")
            except sqlite3.Error:
                pass
    finally:
        conn.close()


def run_via_wsl(args, db_path=None):
    """Chay collector trong WSL tu Windows ma WSL khong cham usage.db."""
    db_path = db_path or DB_PATH
    dry = "--dry-run" in args
    scratch = "%s.collect-%d.db" % (os.path.splitext(db_path)[0], os.getpid())
    try:
        if not dry:
            if not os.path.exists(db_path):
                _emit(sys.stderr, "KHONG THAY DB: %s\n" % db_path)
                return 1
            if "--no-backup" not in args:
                bak = db_path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                snapshot_db(db_path, bak)
                _emit(sys.stdout, "Sao luu   : %s\n" % bak)
            snapshot_db(db_path, scratch)
        script = "BUZZ_COLLECT_SCRATCH=1 BUZZ_USAGE_DB=%s python3 %s %s" % (
            shlex.quote(paths.win_to_wsl(scratch)),
            shlex.quote(paths.win_to_wsl(os.path.abspath(__file__))),
            " ".join(shlex.quote(a) for a in args))
        r = paths.wsl_bash(script, timeout=WSL_TIMEOUT)
        if r.returncode == 0 and not dry:
            # Gop TRUOC khi in: log khong duoc phep lam hong lan cap nhat.
            merge_scratch(db_path, scratch)
        _emit(sys.stderr, r.stderr or "")
        _emit(sys.stdout, r.stdout or "")
        if r.returncode != 0 or dry:
            return r.returncode
        _emit(sys.stdout, "Ghi usage.db: tu Windows (ban sao tam da gop)\n")
        return 0
    except Exception as e:
        _emit(sys.stderr, "collector: %s\n" % e)
        return 1
    finally:
        _remove_db_files(scratch)


def main():
    global HARNESS
    real_db = DB_PATH if os.name == "nt" else os.path.realpath(DB_PATH)
    if not DRY and not SCRATCH and paths.in_wsl() and real_db.startswith("/mnt/"):
        log("TU CHOI ghi %s tu WSL: WAL khong dong bo khoa voi dashboard Windows, "
            "usage.db se hong. Chay tu Windows: python bin\\buzz_collector.py" % DB_PATH)
        return 2
    HARNESS = load_harnesses()
    agents, community, all_agent_pk = load_agents()
    log("Community  : %s" % community)
    log("Agent that : %d (moi agent co pubkey)  |  harness theo doi: %d" % (len(agents), len(HARNESS)))
    if not agents:
        log("Khong co agent nao — dung.")
        return 1
    by_rt = {}
    for a in agents:
        by_rt.setdefault(a["runtime"], []).append(a["name"])
    for rt, names in sorted(by_rt.items()):
        log("   %-20s %-18s %d agent" % (rt, HARNESS[rt][2] if rt in HARNESS else "(khong theo doi)", len(names)))

    if DRY:
        log("\n--dry-run: khong ghi gi vao %s" % DB_PATH)
        return 0

    if not os.path.exists(DB_PATH):
        log("KHONG THAY DB: %s" % DB_PATH)
        return 1
    if SCRATCH:
        log("\nSao luu   : phia Windows lo (ban sao tam)")
    elif not NO_BACKUP:
        bak = DB_PATH + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        import shutil
        shutil.copy2(DB_PATH, bak)
        log("\nSao luu   : %s" % bak)
    else:
        log("\nSao luu   : bo qua (--no-backup)")

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=%s" % ("DELETE" if SCRATCH else "WAL"))
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # Xoa du lieu cua he KHAC (claude-cli + agy-* cua tac gia) — ta chi giu
        # so lieu cua he nay. Ban goc da duoc sao luu o tren.
        old = [r[0] for r in conn.execute(
            "SELECT agent_id FROM agents WHERE backend_kind IN ('claude-cli','agy')")]
        if old:
            q = ",".join("?" * len(old))
            conn.execute("DELETE FROM usage_events WHERE request_id IN "
                         "(SELECT request_id FROM requests WHERE agent_id IN (%s))" % q, old)
            conn.execute("DELETE FROM requests WHERE agent_id IN (%s)" % q, old)
            conn.execute("DELETE FROM account_capacity_snapshots WHERE agent_id IN (%s)" % q, old)
            conn.execute("DELETE FROM agents WHERE agent_id IN (%s)" % q, old)
            log("Da go %d agent cua he khac: %s" % (len(old), ", ".join(old)))

        n_ag = upsert_agents(conn, agents)
        log("Dang ky   : %d agent" % n_ag)

        n_req, n_usage, n_skip, stats, people, n_ph = collect(conn, agents, community, all_agent_pk)
        rebuild_aggregates(conn, community)
        conn.commit()
    finally:
        conn.close()

    log("\n=== Ket qua ===")
    log("requests moi   : %d" % n_req)
    log("usage_events   : %d" % n_usage)
    log("chua gan duoc  : %d luot (don vao <harness>:unattributed)" % n_skip)
    log("gan duoc nguoi   : %d luot co <buzz-event> (biet ai goi)" % n_ph)
    log("")
    log("%-14s %8s %14s" % ("harness", "luot", "tong token"))
    log("-" * 40)
    for rt, st in sorted(stats.items()):
        log("%-14s %8d %14s" % (rt, st["turns"], "{:,}".format(st["tokens"])))
    if people:
        log("")
        log("NGUOI DUNG tim thay: %d" % len(people))
        for pk, nm in sorted(people.items(), key=lambda kv: (kv[1] or kv[0])):
            log("   %-18s %s..." % (nm or "(chua ro ten)", pk[:16]))
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        sys.exit(run_via_wsl(sys.argv[1:]))
    sys.exit(main())
