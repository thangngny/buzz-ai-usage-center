#!/usr/bin/env python3
"""
usage-control ledger — accounting source of truth for AI usage on the local
Buzz gateway.

Design constraints (per implementation spec):
- Dedicated new DB; gateway_state.db is NOT the usage ledger.
- SQLite, WAL mode, foreign_keys=ON, busy_timeout, short IMMEDIATE transactions.
- Append-only usage_events (never updated after insert).
- Idempotency keyed on (community_id, trigger_event_id, agent_id) via
  database constraints, not SELECT-then-INSERT races.
- Unknown measurements stay NULL, never zero. cost_usd stays NULL while no
  billing authority is proven.
- All writes are best-effort from the gateway's point of view: a ledger
  failure must degrade accounting, never break an agent turn (the caller
  wraps calls in try/except where required).
"""

import os
import sqlite3
import time
import uuid
from typing import Any, Optional

DB_PATH = os.environ.get(
    "BUZZ_USAGE_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "usage.db"),
)

SCHEMA_VERSION = "1"
NORMALIZATION_VERSION_DEFAULT = "v1-actual-tokens"

REQUEST_STATUSES = (
    "running", "completed", "failed", "cancelled", "timeout",
    "rejected_identity", "duplicate", "stale_reclaimed",
)

ALLOWANCE_PROFILES = {
    # profile_id: assigned_fraction of the base allowance
    "full": 1.0,
    "high": 0.75,
    "standard": 0.5,
    "limited": 0.25,
}

DEFAULT_SETTINGS = {
    # policy baseline: normalized token units per principal per window (day).
    # 100% of allowance == base_units_daily * assigned_fraction.
    "base_units_daily": "3000000",
    # operation modes: METER_ONLY, WARN_ONLY (SOFT_LIMIT/HARD_LIMIT exist as
    # future states and are deliberately not implemented as blockers).
    "mode": "METER_ONLY",
    "warn_only_enabled": "1",
    "hard_limit_enabled": "0",          # MUST stay 0; owner flips later
    "soft_limit_enabled": "0",
    "threshold_warning": "70",
    "threshold_high": "85",
    "threshold_critical": "95",
    "threshold_exhausted": "100",
    "identity_freshness_seconds": "900",
    "default_allowance_profile": "full",
    "capacity_poll_interval_seconds": "600",
    "normalization_version": NORMALIZATION_VERSION_DEFAULT,
    "usage_command": "/usage",
    # Owner pubkeys (comma-separated) authorized for owner-only zero-AI
    # overviews (/usage system). Identity is pubkey-based, never display-name.
    "owner_pubkeys": "2da3184b999140883867865a09b97d61397a5265e209fe9c58b93c59f3f0001e",
}

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS principals (
    principal_pubkey TEXT PRIMARY KEY,
    community_id TEXT NOT NULL,
    display_name TEXT,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,          -- claude-cli, agy-1..agy-4
    agent_pubkey TEXT,
    display_name TEXT,
    backend_kind TEXT NOT NULL          -- claude-cli | agy
);

CREATE TABLE IF NOT EXISTS allowance_profiles (
    profile_id TEXT PRIMARY KEY,
    assigned_fraction REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_allowances (
    community_id TEXT NOT NULL,
    principal_pubkey TEXT NOT NULL REFERENCES principals(principal_pubkey),
    profile_id TEXT NOT NULL REFERENCES allowance_profiles(profile_id),
    effective_fraction REAL NOT NULL,
    assigned_by TEXT,
    assigned_at INTEGER NOT NULL,
    PRIMARY KEY (community_id, principal_pubkey)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    thread_id TEXT,
    trigger_event_id TEXT NOT NULL,
    principal_pubkey TEXT,
    agent_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    status TEXT NOT NULL,
    runtime_ms INTEGER,
    model TEXT,
    session_id TEXT,
    usage_quality TEXT,                 -- actual_harness_reported | unknown
    normalized_units REAL,
    normalization_version TEXT,
    dry_run_verdict TEXT,               -- WOULD_ALLOW | WOULD_BLOCK
    dry_run_reason TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_principal_time
    ON requests(principal_pubkey, started_at);
CREATE INDEX IF NOT EXISTS idx_requests_agent_time
    ON requests(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_requests_event
    ON requests(trigger_event_id, agent_id);

CREATE TABLE IF NOT EXISTS request_idempotency (
    community_id TEXT NOT NULL,
    trigger_event_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES requests(request_id),
    status TEXT NOT NULL,               -- processing | completed | failed
    published_response TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (community_id, trigger_event_id, agent_id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    usage_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL REFERENCES requests(request_id),
    occurred_at INTEGER NOT NULL,
    usage_quality TEXT NOT NULL,        -- actual_harness_reported | unknown
    source TEXT NOT NULL,               -- claude-stdout-json | agy-stdout-json | none
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    thinking_tokens INTEGER,
    cost_usd REAL,                      -- stays NULL: no proven billing authority
    model TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_events_request ON usage_events(request_id);

CREATE TABLE IF NOT EXISTS account_capacity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at INTEGER NOT NULL,
    agent_id TEXT NOT NULL,             -- agy-1..agy-4 (gateway account label)
    model TEXT NOT NULL,
    remaining_percent REAL,
    reset_at TEXT,
    source TEXT NOT NULL,
    UNIQUE (captured_at, agent_id, model)
);

CREATE TABLE IF NOT EXISTS alert_state (
    community_id TEXT NOT NULL,
    principal_pubkey TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    threshold TEXT NOT NULL,            -- warning | high | critical | exhausted
    triggered_at INTEGER NOT NULL,
    request_id TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (community_id, principal_pubkey, window_start, threshold)
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL,
    principal_pubkey TEXT NOT NULL,
    request_id TEXT,
    units REAL NOT NULL,
    status TEXT NOT NULL,               -- reserved | settled | released | expired
    created_at INTEGER NOT NULL,
    settled_at INTEGER
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);

-- Calibration-phase owner alerts (deduplicated, acknowledgeable).
-- dedup_key makes one logical condition one alert row; last_seen/occurrences
-- update instead of spawning a new row per request (no alert spam).
CREATE TABLE IF NOT EXISTS owner_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,      -- kind|subject|window-day
    kind TEXT NOT NULL,                 -- USER_USAGE_WARNING | AGENT_CAPACITY_WARNING | USAGE_SPIKE |
                                        -- HIGH_FAILURE_RATE | DATA_QUALITY_DEGRADED |
                                        -- ACCOUNT_CAPACITY_LOW | FUTURE_LIMIT_WOULD_BLOCK
    subject_type TEXT NOT NULL,         -- user | agent | system
    subject_id TEXT,                    -- pubkey / agent_id / NULL
    subject_label TEXT,
    severity TEXT NOT NULL,             -- Unusual | High Usage | Critical
    reason TEXT NOT NULL,               -- always explainable, plain language
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',-- open | acknowledged
    acknowledged_by TEXT,
    acknowledged_at INTEGER
);

-- Derived aggregates for dashboard speed. Raw usage ledger data is retained
-- untouched; these rollups are regenerable from raw at any time
-- (rebuild_aggregates) so historical percentages stay reproducible.
CREATE TABLE IF NOT EXISTS usage_aggregates (
    period TEXT NOT NULL,               -- daily | weekly | monthly
    period_start INTEGER NOT NULL,      -- ICT boundary of the bucket start
    community_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    principal_pubkey TEXT NOT NULL,     -- '' when unknown
    requests INTEGER NOT NULL,
    completed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    units_actual REAL NOT NULL,
    units_unknown REAL NOT NULL,
    actual_events INTEGER NOT NULL,
    unknown_events INTEGER NOT NULL,
    PRIMARY KEY (period, period_start, community_id, agent_id, principal_pubkey)
);
"""


def now() -> int:
    return int(time.time())


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,))
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        for pid, frac in ALLOWANCE_PROFILES.items():
            conn.execute(
                "INSERT OR IGNORE INTO allowance_profiles (profile_id, assigned_fraction) "
                "VALUES (?, ?)", (pid, frac))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: Any = None) -> Any:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: Any, by: str = "system") -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))
            audit(conn, "config_change", f"{key}={value} by={by}")
    finally:
        conn.close()


def audit(conn: sqlite3.Connection, kind: str, detail: str) -> None:
    """Record an audit event on an open connection (inside caller's txn)."""
    conn.execute(
        "INSERT INTO audit_events (at, kind, detail) VALUES (?, ?, ?)",
        (now(), kind, detail[:2000]))


def audit_standalone(kind: str, detail: str) -> None:
    try:
        conn = connect()
        try:
            with conn:
                audit(conn, kind, detail)
        finally:
            conn.close()
    except Exception:
        pass


# --------------------------------------------------------------------------
# principals / agents / allowances
# --------------------------------------------------------------------------

def upsert_principal(community_id: str, pubkey: str, display_name: Optional[str] = None) -> None:
    if not pubkey:
        return
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO principals (principal_pubkey, community_id, display_name,"
                " first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(principal_pubkey) DO UPDATE SET "
                "  last_seen_at = excluded.last_seen_at,"
                "  community_id = COALESCE(principals.community_id, excluded.community_id),"
                "  display_name = COALESCE(excluded.display_name, principals.display_name)",
                (pubkey, community_id, display_name, now(), now()))
    finally:
        conn.close()


def upsert_agent(agent_id: str, display_name: str, backend_kind: str,
                 agent_pubkey: Optional[str] = None) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO agents (agent_id, display_name, backend_kind, agent_pubkey) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(agent_id) DO UPDATE SET display_name = excluded.display_name",
                (agent_id, display_name, backend_kind, agent_pubkey))
    finally:
        conn.close()


CANONICAL_AGENTS = [
    ("claude-cli", "Claude CLI", "claude-cli"),
    ("agy-1", "AGY 1", "agy"),
    ("agy-2", "AGY 2", "agy"),
    ("agy-3", "AGY 3", "agy"),
    ("agy-4", "AGY 4", "agy"),
]


def ensure_canonical_agents() -> None:
    """Idempotently register the five production agents so the Agents view
    shows them before the first gateway worker starts."""
    for agent_id, display_name, kind in CANONICAL_AGENTS:
        upsert_agent(agent_id, display_name, kind)


def get_allowance(community_id: str, pubkey: str) -> dict:
    """Effective allowance for a principal: base * fraction, plus raw fields."""
    base = float(get_setting("base_units_daily", DEFAULT_SETTINGS["base_units_daily"]))
    conn = connect()
    try:
        row = conn.execute(
            "SELECT profile_id, effective_fraction FROM user_allowances "
            "WHERE community_id = ? AND principal_pubkey = ?",
            (community_id, pubkey)).fetchone()
        if row:
            frac = float(row["effective_fraction"])
            profile = row["profile_id"]
        else:
            profile = str(get_setting("default_allowance_profile",
                                       DEFAULT_SETTINGS["default_allowance_profile"]))
            frac = ALLOWANCE_PROFILES.get(profile, 1.0)
    finally:
        conn.close()
    return {
        "base_units": base,
        "profile_id": profile,
        "assigned_fraction": frac,
        "effective_units": base * frac,
    }


def set_user_allowance(community_id: str, pubkey: str, profile_id: str, by: str) -> None:
    if profile_id not in ALLOWANCE_PROFILES:
        raise ValueError(f"unknown allowance profile: {profile_id}")
    upsert_principal(community_id, pubkey)
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO user_allowances (community_id, principal_pubkey, profile_id,"
                " effective_fraction, assigned_by, assigned_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(community_id, principal_pubkey) DO UPDATE SET "
                "  profile_id = excluded.profile_id,"
                "  effective_fraction = excluded.effective_fraction,"
                "  assigned_by = excluded.assigned_by,"
                "  assigned_at = excluded.assigned_at",
                (community_id, pubkey, profile_id, ALLOWANCE_PROFILES[profile_id],
                 by, now()))
            audit(conn, "allowance_assigned",
                  f"principal={pubkey[:12]}… profile={profile_id} by={by}")
    finally:
        conn.close()


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------

def new_request_id() -> str:
    return str(uuid.uuid4())


def record_request_start(req: Any) -> None:
    """req keys: request_id, community_id, channel_id, thread_id,
    trigger_event_id, principal_pubkey, agent_id, dry_run_verdict,
    dry_run_reason, started_at (optional)."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO requests (request_id, community_id, channel_id, thread_id,"
                " trigger_event_id, principal_pubkey, agent_id, started_at, status,"
                " dry_run_verdict, dry_run_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                (req["request_id"], req["community_id"], req["channel_id"],
                 req.get("thread_id"), req["trigger_event_id"],
                 req.get("principal_pubkey"), req["agent_id"],
                 req.get("started_at") or now(),
                 req.get("dry_run_verdict"), req.get("dry_run_reason")))
    finally:
        conn.close()


def finish_request(request_id: str, status: str, runtime_ms: Optional[int] = None,
                   model: Optional[str] = None, session_id: Optional[str] = None,
                   usage_quality: Optional[str] = None, normalized_units: Optional[float] = None,
                   detail: Optional[str] = None) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "UPDATE requests SET completed_at = ?, status = ?, runtime_ms = ?,"
                " model = ?, session_id = ?, usage_quality = ?, normalized_units = ?,"
                " normalization_version = ?, detail = ? WHERE request_id = ?",
                (now(), status, runtime_ms, model, session_id, usage_quality,
                 normalized_units, NORMALIZATION_VERSION_DEFAULT, detail, request_id))
    finally:
        conn.close()


def record_usage_event(request_id: str, usage: dict) -> None:
    """Append one usage measurement for a completed turn. NULLs stay NULL."""
    if not usage:
        return
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage_events (request_id, occurred_at, usage_quality,"
                " source, input_tokens, output_tokens, total_tokens, cache_read_tokens,"
                " cache_write_tokens, thinking_tokens, cost_usd, model)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (request_id, now(), usage.get("usage_quality", "unknown"),
                 usage.get("source", "none"),
                 usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("total_tokens"), usage.get("cache_read_tokens"),
                 usage.get("cache_write_tokens"), usage.get("thinking_tokens"),
                 usage.get("cost_usd"),          # expected None for now
                 usage.get("model")))
    finally:
        conn.close()


# --------------------------------------------------------------------------
# idempotency (race-safe)
# --------------------------------------------------------------------------

def acquire_idempotency(community_id: str, trigger_event_id: str, agent_id: str,
                        request_id: str, stale_seconds: int = 300):
    """Atomically claim the (community, event, agent) turn.

    Returns a tuple:
      ("acquired", None)                    proceed with the turn
      ("completed", published_response)     already done — reply with cached text
      ("in_progress", None)                 another worker is on it — skip
    """
    t = now()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT OR IGNORE INTO request_idempotency (community_id, trigger_event_id,"
            " agent_id, request_id, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'processing', ?, ?)",
            (community_id, trigger_event_id, agent_id, request_id, t, t))
        if cur.rowcount == 1:
            conn.commit()
            return "acquired", None

        row = conn.execute(
            "SELECT status, published_response, request_id, updated_at"
            " FROM request_idempotency WHERE community_id = ? AND trigger_event_id = ?"
            " AND agent_id = ?",
            (community_id, trigger_event_id, agent_id)).fetchone()
        if row is None:  # should not happen
            conn.commit()
            return "acquired", None

        if row["status"] == "completed":
            conn.commit()
            return "completed", row["published_response"]

        if row["status"] == "failed":
            # A failed turn is retriable immediately, but only one worker may
            # claim the retry (guarded UPDATE = race-safe).
            upd = conn.execute(
                "UPDATE request_idempotency SET request_id = ?, status = 'processing',"
                " published_response = NULL, updated_at = ?"
                " WHERE community_id = ? AND trigger_event_id = ? AND agent_id = ?"
                " AND status = 'failed'",
                (request_id, t, community_id, trigger_event_id, agent_id))
            if upd.rowcount == 1:
                audit(conn, "idempotency_retry",
                      f"event={trigger_event_id[:12]}… agent={agent_id}")
                conn.commit()
                return "acquired", None
            conn.commit()
            return "in_progress", None

        # processing. Take over only if stale, guarded by updated_at.
        upd = conn.execute(
            "UPDATE request_idempotency SET request_id = ?, status = 'processing',"
            " published_response = NULL, updated_at = ?"
            " WHERE community_id = ? AND trigger_event_id = ? AND agent_id = ?"
            " AND updated_at < ?",
            (request_id, t, community_id, trigger_event_id, agent_id, t - stale_seconds))
        if upd.rowcount == 1:
            # reclaim: the abandoned request row is marked failed so consumption
            # math never counts a turn that never produced usage.
            conn.execute(
                "UPDATE requests SET status = 'stale_reclaimed',"
                " completed_at = ?, detail = COALESCE(detail,'') || 'reclaimed by retry'"
                " WHERE request_id = ? AND status IN ('running')",
                (t, row["request_id"]))
            audit(conn, "idempotency_takeover",
                  f"event={trigger_event_id[:12]}… agent={agent_id}")
            conn.commit()
            return "acquired", None

        conn.commit()
        return "in_progress", None
    finally:
        conn.close()


def mark_idempotency(community_id: str, trigger_event_id: str, agent_id: str,
                     status: str, published_response: Optional[str] = None) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "UPDATE request_idempotency SET status = ?, published_response = ?,"
                " updated_at = ? WHERE community_id = ? AND trigger_event_id = ?"
                " AND agent_id = ?",
                (status, published_response, now(),
                 community_id, trigger_event_id, agent_id))
    finally:
        conn.close()


# --------------------------------------------------------------------------
# consumption, thresholds, alerts, dry-run
# --------------------------------------------------------------------------

def window_start(ts: Optional[int] = None) -> int:
    """Current allowance window start = local calendar day midnight."""
    lt = time.localtime(ts if ts is not None else now())
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0,
                            0, 0, -1)))


def consumed_units(community_id: str, pubkey: str, ws: Optional[int] = None) -> dict:
    """Units consumed in the current window for a principal. Counts only
    completed turns (duplicates/running/failed add requests but no spend)."""
    ws = ws if ws is not None else window_start()
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(normalized_units), 0) AS units, COUNT(*) AS reqs"
            " FROM requests WHERE principal_pubkey = ? AND community_id = ?"
            " AND started_at >= ? AND status = 'completed'",
            (pubkey, community_id, ws)).fetchone()
        running = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE principal_pubkey = ?"
            " AND community_id = ? AND started_at >= ? AND status = 'running'",
            (pubkey, community_id, ws)).fetchone()["n"]
        total_reqs = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE principal_pubkey = ?"
            " AND community_id = ? AND started_at >= ?"
            " AND status IN ('completed','failed','timeout','cancelled','running')",
            (pubkey, community_id, ws)).fetchone()["n"]
    finally:
        conn.close()
    return {"units": float(row["units"]), "requests": total_reqs,
            "running": running}


def evaluate_thresholds(community_id: str, pubkey: str) -> dict:
    """Current used%/remaining% and the highest threshold crossed."""
    allowance = get_allowance(community_id, pubkey)
    cons = consumed_units(community_id, pubkey)
    eff = allowance["effective_units"] or 1.0
    used_pct = round(cons["units"] / eff * 100.0, 2)
    thresholds = {
        "warning": float(get_setting("threshold_warning", "70")),
        "high": float(get_setting("threshold_high", "85")),
        "critical": float(get_setting("threshold_critical", "95")),
        "exhausted": float(get_setting("threshold_exhausted", "100")),
    }
    crossed = None
    for name in ("exhausted", "critical", "high", "warning"):
        if used_pct >= thresholds[name]:
            crossed = name
            break
    return {
        "used_pct": used_pct,
        "remaining_pct": round(max(0.0, 100.0 - used_pct), 2),
        "threshold_crossed": crossed,
        "thresholds": thresholds,
        "consumed": cons,
        "allowance": allowance,
    }


def dry_run_verdict(community_id: str, pubkey: str) -> dict:
    """WOULD_ALLOW / WOULD_BLOCK evaluation. NEVER blocks anything today:
    hard_limit_enabled is 0 and enforcement is deliberately unimplemented."""
    if not pubkey:
        return {"verdict": "WOULD_ALLOW", "reason": "no verified principal"}
    ev = evaluate_thresholds(community_id, pubkey)
    if ev["used_pct"] >= 100.0:
        return {"verdict": "WOULD_BLOCK",
                "reason": f"used {ev['used_pct']}% of allowance (hard limit at 100%)"}
    return {"verdict": "WOULD_ALLOW",
            "reason": f"used {ev['used_pct']}%, remaining {ev['remaining_pct']}%"}


def newly_crossed_alerts(community_id: str, pubkey: str, request_id: str) -> list:
    """Threshold crossings not yet alerted in this window. One alert per
    threshold per window; a jump past several thresholds alerts each of them
    once. Returns list of dicts for the caller to deliver."""
    ev = evaluate_thresholds(community_id, pubkey)
    crossed_names = [name for name, pct in sorted(ev["thresholds"].items(),
                                                  key=lambda kv: kv[1])
                     if ev["used_pct"] >= pct]
    if not crossed_names:
        return []
    ws = window_start()
    out = []
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for name in crossed_names:
            already = conn.execute(
                "SELECT 1 FROM alert_state WHERE community_id = ? AND principal_pubkey = ?"
                " AND window_start = ? AND threshold = ?",
                (community_id, pubkey, ws, name)).fetchone()
            if already:
                continue
            conn.execute(
                "INSERT INTO alert_state (community_id, principal_pubkey, window_start,"
                " threshold, triggered_at, request_id, delivered) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (community_id, pubkey, ws, name, now(), request_id))
            audit(conn, "alert_triggered",
                  f"principal={pubkey[:12]}… threshold={name} used={ev['used_pct']}%")
            out.append({
                "threshold": name,
                "used_pct": ev["used_pct"],
                "remaining_pct": ev["remaining_pct"],
            })
        conn.commit()
    finally:
        conn.close()
    return out


def mark_alert_delivered(community_id: str, pubkey: str, threshold: str) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "UPDATE alert_state SET delivered = 1 WHERE community_id = ?"
                " AND principal_pubkey = ? AND window_start = ? AND threshold = ?",
                (community_id, pubkey, window_start(), threshold))
    finally:
        conn.close()


def normalization(units_input: Optional[int], units_output: Optional[int],
                    units_thinking: Optional[int] = 0) -> Optional[float]:
    """v1-actual-tokens: normalized unit = actual reported input + output tokens
    (thinking included where the harness reports it separately, as AGY does).
    Claude reports thinking inside output_tokens, so it is not double counted.
    Every contribution is harness-reported actuals; nothing estimated."""
    if units_input is None and units_output is None:
        return None
    return float((units_input or 0) + (units_output or 0) + (units_thinking or 0))


# --------------------------------------------------------------------------
# reservations (Phase 13 stub: RESERVE -> EXECUTE -> SETTLE)
# --------------------------------------------------------------------------
# The model is PREPARED but enforcement is deliberately NOT implemented:
# while hard_limit_enabled = 0, reserve_units() always reserves and the
# gateway never blocks a turn. Wiring reservations into the gateway turn
# flow is deferred until the owner explicitly enables hard limits.

def reserve_units(community_id: str, pubkey: str,
                  estimated_units: float, request_id: Optional[str] = None) -> dict:
    """RESERVE step. Returns {'reserved': True, 'reservation_id': ...,
    'would_refuse': bool, 'reason': ...}. While hard_limit_enabled = 0 this
    ALWAYS reserves (metering continues; nothing is blocked). 'would_refuse'
    records the verdict a future enforcement pass would apply."""
    would_refuse = False
    reason = "metering only — hard limit disabled"
    if str(get_setting("hard_limit_enabled", "0")) == "1":
        ev = evaluate_thresholds(community_id, pubkey)
        if ev["used_pct"] >= 100.0:
            would_refuse = True
            reason = f"used {ev['used_pct']}% of allowance"
    reservation_id = str(uuid.uuid4())
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO reservations (reservation_id, community_id,"
                " principal_pubkey, request_id, units, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                (reservation_id, community_id, pubkey, request_id,
                 float(estimated_units or 0), now()))
    finally:
        conn.close()
    return {"reserved": True, "reservation_id": reservation_id,
            "would_refuse": would_refuse, "reason": reason}


def settle_reservation(reservation_id: str, request_id: Optional[str] = None) -> None:
    """SETTLE step: bind the reservation to the request that consumed it."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                "UPDATE reservations SET status = 'settled', settled_at = ?,"
                " request_id = COALESCE(?, request_id)"
                " WHERE reservation_id = ? AND status = 'reserved'",
                (now(), request_id, reservation_id))
    finally:
        conn.close()


def release_reservation(reservation_id: str, reason: str = "released") -> None:
    """RELEASE step: the turn did not consume (failed/cancelled/timeout)."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                "UPDATE reservations SET status = 'released', settled_at = ?"
                " WHERE reservation_id = ? AND status = 'reserved'",
                (now(), reservation_id))
            audit(conn, "reservation_released",
                  f"reservation={reservation_id[:12]}… reason={reason}")
    finally:
        conn.close()


def expire_reservations(max_age_seconds: int = 3600) -> int:
    """Maintenance: reservations never settled or released are expired so
    stale rows cannot pile up. Returns count expired."""
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE reservations SET status = 'expired', settled_at = ?"
                " WHERE status = 'reserved' AND created_at < ?",
                (now(), now() - max_age_seconds))
            return cur.rowcount
    finally:
        conn.close()


# --------------------------------------------------------------------------
# capacity snapshots
# --------------------------------------------------------------------------

def record_capacity_snapshots(agent_id: str, rows: list, source: str = "agm/agy-quota") -> int:
    """rows: [{model, remaining_percent, reset_at}] for one agent account."""
    t = now()
    conn = connect()
    try:
        with conn:
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO account_capacity_snapshots"
                    " (captured_at, agent_id, model, remaining_percent, reset_at, source)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (t, agent_id, r.get("model"), r.get("remaining_percent"),
                     r.get("reset_at"), source))
        return len(rows)
    finally:
        conn.close()


def latest_capacity(agent_id: str) -> list:
    conn = connect()
    try:
        t = conn.execute(
            "SELECT MAX(captured_at) AS m FROM account_capacity_snapshots"
            " WHERE agent_id = ?", (agent_id,)).fetchone()["m"]
        if t is None:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT model, remaining_percent, reset_at, source, captured_at"
            " FROM account_capacity_snapshots WHERE agent_id = ? AND captured_at = ?"
            " ORDER BY model", (agent_id, t))]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# dashboard queries
# --------------------------------------------------------------------------

def overview() -> dict:
    ws = window_start()
    conn = connect()
    try:
        today = conn.execute(
            "SELECT COALESCE(SUM(normalized_units),0) AS units, COUNT(*) AS reqs"
            " FROM requests WHERE started_at >= ? AND status = 'completed'",
            (ws,)).fetchone()
        active_users = conn.execute(
            "SELECT COUNT(DISTINCT principal_pubkey) AS n FROM requests"
            " WHERE started_at >= ? AND principal_pubkey IS NOT NULL", (ws,)).fetchone()["n"]
        running = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE status = 'running'").fetchone()["n"]
        warns = conn.execute(
            "SELECT COUNT(*) AS n FROM alert_state WHERE window_start = ?",
            (ws,)).fetchone()["n"]
        fails = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE started_at >= ?"
            " AND status IN ('failed','timeout')", (ws,)).fetchone()["n"]
    finally:
        conn.close()
    return {
        "window_start": ws,
        "units_today": float(today["units"]),
        "requests_today": today["reqs"],
        "active_users": active_users,
        "running": running,
        "alerts_today": warns,
        "failures_today": fails,
        "base_units_daily": float(get_setting("base_units_daily")),
        "mode": get_setting("mode"),
        "warn_only_enabled": get_setting("warn_only_enabled"),
        "hard_limit_enabled": get_setting("hard_limit_enabled"),
    }


def user_summaries(community_id: Optional[str] = None) -> list:
    """Per-principal usage for the current window as percentages."""
    ws = window_start()
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT principal_pubkey, community_id, display_name FROM principals"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        if community_id and r["community_id"] != community_id:
            continue
        if not r["principal_pubkey"]:
            continue
        ev = evaluate_thresholds(r["community_id"], r["principal_pubkey"])
        cons = ev["consumed"]
        top_agent = top_agent_for(r["community_id"], r["principal_pubkey"], ws)
        out.append({
            "principal_pubkey": r["principal_pubkey"],
            "community_id": r["community_id"],
            "display_name": r["display_name"],
            "profile_id": ev["allowance"]["profile_id"],
            "used_pct": ev["used_pct"],
            "remaining_pct": ev["remaining_pct"],
            "requests": cons["requests"],
            "running": cons["running"],
            "units": cons["units"],
            "effective_units": ev["allowance"]["effective_units"],
            "most_used_agent": top_agent,
            "status": ev["threshold_crossed"] or "normal",
        })
    out.sort(key=lambda u: -u["used_pct"])
    return out


def top_agent_for(community_id: str, pubkey: str, ws: int) -> Optional[str]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT agent_id, SUM(normalized_units) AS u, COUNT(*) AS c FROM requests"
            " WHERE principal_pubkey = ? AND community_id = ? AND started_at >= ?"
            " AND status = 'completed' GROUP BY agent_id"
            " ORDER BY u DESC, c DESC LIMIT 1", (pubkey, community_id, ws)).fetchone()
    finally:
        conn.close()
    return row["agent_id"] if row else None


def user_detail(community_id: str, pubkey: str) -> dict:
    ws = window_start()
    ev = evaluate_thresholds(community_id, pubkey)
    conn = connect()
    try:
        by_agent = [dict(r) for r in conn.execute(
            "SELECT agent_id, COUNT(*) AS requests, COALESCE(SUM(normalized_units),0) AS units"
            " FROM requests WHERE principal_pubkey = ? AND community_id = ?"
            " AND started_at >= ? AND status = 'completed'"
            " GROUP BY agent_id ORDER BY units DESC", (pubkey, community_id, ws))]
        recent = [dict(r) for r in conn.execute(
            "SELECT request_id, agent_id, status, started_at, runtime_ms,"
            " normalized_units, model, usage_quality, dry_run_verdict, detail"
            " FROM requests WHERE principal_pubkey = ? AND community_id = ?"
            " ORDER BY started_at DESC LIMIT 25", (pubkey, community_id))]
        alerts = [dict(r) for r in conn.execute(
            "SELECT threshold, triggered_at, delivered, window_start FROM alert_state"
            " WHERE principal_pubkey = ? AND community_id = ?"
            " ORDER BY triggered_at DESC LIMIT 20", (pubkey, community_id))]
        runtime = conn.execute(
            "SELECT COALESCE(SUM(runtime_ms),0) AS ms FROM requests"
            " WHERE principal_pubkey = ? AND community_id = ? AND started_at >= ?",
            (pubkey, community_id, ws)).fetchone()["ms"]
    finally:
        conn.close()
    return {"window_start": ws, "evaluate": ev, "by_agent": by_agent,
            "recent": recent, "alerts": alerts, "runtime_ms_today": runtime}


def agent_summaries() -> list:
    ws = window_start()
    conn = connect()
    try:
        agents = [dict(r) for r in conn.execute(
            "SELECT agent_id, display_name, backend_kind FROM agents")]
        for a in agents:
            row = conn.execute(
                "SELECT COUNT(*) AS reqs, COALESCE(SUM(normalized_units),0) AS units"
                " FROM requests WHERE agent_id = ? AND started_at >= ?"
                " AND status = 'completed'", (a["agent_id"], ws)).fetchone()
            fails = conn.execute(
                "SELECT COUNT(*) AS n FROM requests WHERE agent_id = ?"
                " AND started_at >= ? AND status IN ('failed','timeout')",
                (a["agent_id"], ws)).fetchone()["n"]
            a.update({"requests": row["reqs"], "units": float(row["units"]),
                      "failures": fails})
    finally:
        conn.close()
    for a in agents:
        a["capacity"] = latest_capacity(a["agent_id"]) if a["backend_kind"] == "agy" else []
    return agents


def alerts_recent(limit: int = 50) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT a.community_id, a.principal_pubkey, a.threshold, a.triggered_at,"
            " a.delivered, p.display_name FROM alert_state a"
            " LEFT JOIN principals p ON p.principal_pubkey = a.principal_pubkey"
            " ORDER BY a.triggered_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def activity_recent(limit: int = 50) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT r.request_id, r.agent_id, r.status, r.started_at, r.runtime_ms,"
            " r.normalized_units, r.usage_quality, r.dry_run_verdict,"
            " p.display_name FROM requests r"
            " LEFT JOIN principals p ON p.principal_pubkey = r.principal_pubkey"
            " ORDER BY r.started_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def audit_recent(limit: int = 100) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT at, kind, detail FROM audit_events ORDER BY at DESC LIMIT ?",
            (limit,))]
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Calibration phase: owner alerts (deduplicated, acknowledgeable)
# ---------------------------------------------------------------------------

def record_owner_alert(kind: str, subject_type: str, subject_id: Optional[str],
                       subject_label: Optional[str], severity: str,
                       reason: str, dedup_key: Optional[str] = None) -> None:
    """Upsert a deduplicated owner alert. Same dedup_key = same logical alert:
    first insert creates the row; later hits bump last_seen and occurrences
    (severity keeps the highest seen). Never one alert per request."""
    ts = now()
    dedup_key = dedup_key or f"{kind}|{subject_id or subject_type}|{ts // 86400}"
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO owner_alerts (dedup_key, kind, subject_type, subject_id,"
                " subject_label, severity, reason, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(dedup_key) DO UPDATE SET"
                " last_seen = excluded.last_seen,"
                " occurrences = occurrences + 1,"
                " severity = CASE WHEN (CASE excluded.severity"
                "   WHEN 'Unusual' THEN 0 WHEN 'High Usage' THEN 1 ELSE 2 END) >"
                "  (CASE owner_alerts.severity WHEN 'Unusual' THEN 0"
                "   WHEN 'High Usage' THEN 1 ELSE 2 END)"
                " THEN excluded.severity ELSE owner_alerts.severity END",
                (dedup_key, kind, subject_type, subject_id, subject_label,
                 severity, reason, ts, ts))
    finally:
        conn.close()


def acknowledge_owner_alert(alert_id: int, by: str = "owner") -> bool:
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE owner_alerts SET status = 'acknowledged',"
                " acknowledged_by = ?, acknowledged_at = ?"
                " WHERE id = ? AND status = 'open'", (by, now(), alert_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def owner_alerts_recent(limit: int = 100) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM owner_alerts ORDER BY last_seen DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def is_owner(pubkey: Optional[str]) -> bool:
    """Owner authorization is pubkey-based ONLY (never display names)."""
    if not pubkey:
        return False
    owners = [p.strip().lower() for p in
              (get_setting("owner_pubkeys", "") or "").split(",") if p.strip()]
    return pubkey.lower() in owners


# ---------------------------------------------------------------------------
# Calibration phase: derived aggregates (regenerable rollups of raw history)
# ---------------------------------------------------------------------------

def _ict():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Asia/Ho_Chi_Minh")


def period_start_daily(ts: int) -> int:
    """Midnight boundary of the ICT calendar day containing ts."""
    import datetime as _dt
    d = _dt.datetime.fromtimestamp(ts, _ict()).date()
    return int(_dt.datetime(d.year, d.month, d.day, tzinfo=_ict()).timestamp())


def rebuild_aggregates() -> int:
    """Regenerate daily/weekly/monthly rollups from the RAW ledger.
    Raw data is never modified; aggregates are fully reproducible.
    Returns the number of aggregate rows written."""
    import datetime as _dt
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT r.started_at, r.community_id, r.agent_id,"
            " COALESCE(r.principal_pubkey, '') AS pk,"
            " CASE r.status WHEN 'completed' THEN 1 ELSE 0 END AS completed,"
            " CASE r.status WHEN 'failed' THEN 1 ELSE 0 END AS failed,"
            " r.normalized_units, r.usage_quality"
            " FROM requests r"
            " WHERE r.usage_quality IN ('actual_harness_reported','unknown')").fetchall()
        buckets = {}          # (period, pstart, comm, agent, pk) -> dict
        for r in rows:
            d = _dt.datetime.fromtimestamp(r["started_at"], _ict()).date()
            day_start = period_start_daily(r["started_at"])
            # ISO week starts Monday 00:00 ICT: walk back from the day
            week_start = day_start - (d.weekday() * 86400)
            month_start = period_start_daily(
                int(_dt.datetime(d.year, d.month, 1, tzinfo=_ict()).timestamp()))
            is_actual = 1 if r["usage_quality"] == "actual_harness_reported" else 0
            for period, pstart in (("daily", day_start), ("weekly", week_start),
                                   ("monthly", month_start)):
                k = (period, pstart, r["community_id"], r["agent_id"], r["pk"])
                b = buckets.setdefault(k, {"requests": 0, "completed": 0,
                                            "failed": 0, "units_actual": 0.0,
                                            "units_unknown": 0.0,
                                            "actual_events": 0, "unknown_events": 0})
                b["requests"] += 1
                b["completed"] += r["completed"]
                b["failed"] += r["failed"]
                if is_actual:
                    b["actual_events"] += 1
                    b["units_actual"] += float(r["normalized_units"] or 0.0)
                else:
                    b["unknown_events"] += 1
                    b["units_unknown"] += float(r["normalized_units"] or 0.0)
        with conn:
            conn.execute("DELETE FROM usage_aggregates")
            for (period, pstart, comm, agent, pk), b in buckets.items():
                conn.execute(
                    "INSERT INTO usage_aggregates (period, period_start, community_id,"
                    " agent_id, principal_pubkey, requests, completed, failed,"
                    " units_actual, units_unknown, actual_events, unknown_events)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (period, pstart, comm, agent, pk, b["requests"], b["completed"],
                     b["failed"], b["units_actual"], b["units_unknown"],
                     b["actual_events"], b["unknown_events"]))
        return len(buckets)
    finally:
        conn.close()
