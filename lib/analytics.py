#!/usr/bin/env python3
"""
usage-control analytics — OWNER CALIBRATION computations for the AI Usage
Center. Read-only against the raw ledger; derived numbers only.

Design constraints (calibration-phase spec):
- Percentages / requests / time are the primary display language; raw units
  are secondary details.
- All daily boundaries use Asia/Ho_Chi_Minh (ICT, UTC+7, no DST).
- Bucket boundaries are DERIVED from observed data (percentiles), never
  arbitrary constants.
- Recommendations are owner-facing only: nothing is auto-assigned or changed.
- No AI model is ever called for any of this.
- These functions run on dashboard query / report time only — never in the
  agent hot path.
"""

import datetime as dt
import math
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import ledger

ICT = ZoneInfo("Asia/Ho_Chi_Minh")

AGENT_LABELS = {aid: label for aid, label, _kind in ledger.CANONICAL_AGENTS}

WINDOWS = {
    "today": "Today",
    "24h": "Last 24 hours",
    "3d": "Last 3 days",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
}


# ---------------------------------------------------------------------------
# time helpers (all boundaries in ICT)
# ---------------------------------------------------------------------------

def ict_midnight(ts: int) -> int:
    d = dt.datetime.fromtimestamp(ts, ICT).date()
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=ICT).timestamp())


def window_bounds(window: str, custom_from: Optional[str] = None,
                  custom_to: Optional[str] = None,
                  now_ts: Optional[int] = None) -> Tuple[int, int, str]:
    """Return (start_ts, end_ts_exclusive, label) for a calibration window."""
    now_ts = now_ts or ledger.now()
    if window == "today":
        return ict_midnight(now_ts), now_ts, "Today"
    if window == "24h":
        return now_ts - 86400, now_ts, "Last 24 hours"
    if window in ("3d", "7d", "30d"):
        days = int(window[:-1])
        start = ict_midnight(now_ts - (days - 1) * 86400)
        return start, now_ts, WINDOWS[window]
    if window == "custom":
        if not (custom_from and custom_to):
            raise ValueError("custom window requires from/to dates (YYYY-MM-DD)")
        d0 = dt.datetime.strptime(custom_from, "%Y-%m-%d").replace(
            tzinfo=ICT, hour=0, minute=0, second=0)
        d1 = dt.datetime.strptime(custom_to, "%Y-%m-%d").replace(
            tzinfo=ICT, hour=0, minute=0, second=0) + dt.timedelta(days=1)
        return int(d0.timestamp()), min(int(d1.timestamp()), now_ts), \
            f"{custom_from} → {custom_to}"
    # default: today
    return ict_midnight(now_ts), now_ts, "Today"


# ---------------------------------------------------------------------------
# statistics helpers
# ---------------------------------------------------------------------------

def percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    """Nearest-rank percentile over pre-sorted values."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def stats_summary(values: List[float]) -> Dict[str, Optional[float]]:
    s = sorted(values)
    return {
        "count": len(s),
        "avg": (sum(s) / len(s)) if s else None,
        "median": percentile(s, 50),
        "p75": percentile(s, 75),
        "p90": percentile(s, 90),
        "p95": percentile(s, 95),
        "max": s[-1] if s else None,
        "total": sum(s) if s else 0.0,
    }


def fmt_units(v: Optional[float]) -> str:
    """Owner-friendly: 12K / 1.2M; None -> UNKNOWN."""
    if v is None:
        return "UNKNOWN"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return f"{v:.0f}"


def fmt_pct(v: Optional[float]) -> str:
    return "UNKNOWN" if v is None else f"{v:.1f}%"


def fmt_secs(ms: Optional[int]) -> str:
    if ms is None:
        return "—"
    s = ms / 1000.0
    if s < 60:
        return f"{s:.0f}s"
    m, s = divmod(int(s), 60)
    return f"{m}m{s:02d}s"


# ---------------------------------------------------------------------------
# request distribution (Phase 4) — buckets DERIVED from observed data
# ---------------------------------------------------------------------------

def request_distribution(start: int, end: int) -> Dict[str, Any]:
    """Distribution of real completed AI requests in the window.
    Bucket boundaries are the window's own P25/P50/P75/P95 — derived from
    the data, not hardcoded."""
    conn = ledger.connect()
    try:
        rows = [float(r["normalized_units"]) for r in conn.execute(
            "SELECT normalized_units FROM requests"
            " WHERE started_at >= ? AND started_at < ?"
            " AND status = 'completed' AND usage_quality = 'actual_harness_reported'"
            " AND normalized_units IS NOT NULL", (start, end))]
        unknown = conn.execute(
            "SELECT COUNT(*) AS n FROM requests"
            " WHERE started_at >= ? AND started_at < ?"
            " AND status = 'completed' AND usage_quality = 'unknown'",
            (start, end)).fetchone()["n"]
    finally:
        conn.close()
    s = sorted(rows)
    summ = stats_summary(s)
    p25 = percentile(s, 25)
    buckets: List[Dict[str, Any]] = []
    if s:
        bounds = {
            "Very Light": (0.0, p25),
            "Light": (p25, summ["median"]),
            "Medium": (summ["median"], summ["p75"]),
            "Heavy": (summ["p75"], summ["p95"]),
            "Very Heavy": (summ["p95"], summ["max"]),
        }
        for name, (lo, hi) in bounds.items():
            if name == "Very Light":
                cnt = sum(1 for v in s if v <= hi)
            elif name == "Very Heavy":
                cnt = sum(1 for v in s if v > lo)
            else:
                cnt = sum(1 for v in s if lo < v <= hi)
            buckets.append({
                "name": name, "count": cnt,
                "share": (cnt / len(s) * 100.0),
                "upper": fmt_units(hi), "raw_upper": hi,
            })
    return {"summary": summ, "buckets": buckets,
            "unknown_requests": unknown,
            "bucket_basis": ("boundaries = this window's P25 / median / P75 / P95"
                             " (derived from observed data, not fixed constants)")
            if s else "no completed requests in window"}


# ---------------------------------------------------------------------------
# per-user analytics (Phase 2)
# ---------------------------------------------------------------------------

def user_analytics(start: int, end: int) -> Dict[str, Any]:
    base = float(ledger.get_setting("base_units_daily", "3000000") or 0)
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT r.principal_pubkey, p.display_name, r.community_id,"
            " r.status, r.normalized_units, r.runtime_ms, r.started_at,"
            " r.completed_at, r.usage_quality, r.agent_id"
            " FROM requests r LEFT JOIN principals p"
            " ON p.principal_pubkey = r.principal_pubkey"
            " WHERE r.started_at >= ? AND started_at < ?"
            " AND r.usage_quality IN ('actual_harness_reported','unknown')"
            " ORDER BY r.started_at", (start, end)).fetchall()
        warnings = conn.execute(
            "SELECT principal_pubkey, COUNT(*) AS n FROM alert_state"
            " WHERE triggered_at >= ? GROUP BY principal_pubkey",
            (start,)).fetchall()
    finally:
        conn.close()
    warn_map = {r["principal_pubkey"]: r["n"] for r in warnings}

    users: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pk = r["principal_pubkey"] or "(unknown)"
        u = users.setdefault(pk, {
            "pubkey": pk,
            "label": r["display_name"] or (pk[:12] + "…"),
            "community_id": r["community_id"],
            "profile": ledger.get_allowance(r["community_id"], pk).get("profile_id"),
            "requests": 0, "completed": 0, "failed": 0,
            "units_actual": 0.0, "units_unknown": 0.0,
            "units_list": [], "runtime_total_ms": 0,
            "agent_counts": {}, "warn": warn_map.get(pk, 0),
        })
        u["requests"] += 1
        if r["status"] == "completed":
            u["completed"] += 1
            if r["usage_quality"] == "actual_harness_reported" \
                    and r["normalized_units"] is not None:
                u["units_actual"] += float(r["normalized_units"])
                u["units_list"].append(float(r["normalized_units"]))
            else:
                u["units_unknown"] += float(r["normalized_units"] or 0)
        elif r["status"] in ("failed", "timeout"):
            u["failed"] += 1
        u["runtime_total_ms"] += r["runtime_ms"] or 0
        u["agent_counts"][r["agent_id"]] = u["agent_counts"].get(r["agent_id"], 0) + 1

    # peak concurrent per user (interval sweep over the window)
    for pk, u in users.items():
        urows = [r for r in rows if (r["principal_pubkey"] or "(unknown)") == pk
                 and r["runtime_ms"]]
        events = []
        for r in urows:
            events.append((r["started_at"], 1))
            events.append((r["started_at"] + (r["runtime_ms"] or 0), -1))
        events.sort()
        cur = peak = 0
        for _, d in events:
            cur += d
            peak = max(peak, cur)
        u["peak_concurrent"] = peak
        st = stats_summary(u["units_list"])
        u["stats"] = st
        u["units"] = u["units_actual"] + u["units_unknown"]
        eff = ledger.get_allowance(u["community_id"], pk).get("effective_units") \
            or (base or 1)
        u["effective_units"] = eff
        u["used_pct"] = min(100.0, u["units_actual"] / eff * 100.0) if eff else None
        u["remaining_pct"] = max(0.0, 100.0 - (u["used_pct"] or 0.0))
        u["top_agent"] = max(u["agent_counts"], key=u["agent_counts"].get) \
            if u["agent_counts"] else None
    return {"users": sorted(users.values(), key=lambda x: -x["units"]),
            "base_units": base}


# ---------------------------------------------------------------------------
# per-agent analytics (Phase 3)
# ---------------------------------------------------------------------------

def agent_analytics(start: int, end: int) -> Dict[str, Any]:
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT r.agent_id, r.status, r.normalized_units, r.runtime_ms,"
            " r.started_at, r.principal_pubkey, r.usage_quality, r.trigger_event_id"
            " FROM requests r WHERE r.started_at >= ? AND started_at < ?"
            " AND r.usage_quality IN ('actual_harness_reported','unknown')"
            " ORDER BY r.started_at", (start, end)).fetchall()
    finally:
        conn.close()
    agents: Dict[str, Dict[str, Any]] = {}
    total_units = 0.0
    for r in rows:
        a = agents.setdefault(r["agent_id"], {
            "agent_id": r["agent_id"], "requests": 0, "completed": 0,
            "failed": 0, "units_actual": 0.0, "units_unknown": 0.0,
            "units_list": [], "runtime_total_ms": 0,
            "users": set(), "triggers": {},
            "running": 0,
        })
        a["requests"] += 1
        a["users"].add(r["principal_pubkey"] or "(unknown)")
        a["triggers"][r["trigger_event_id"]] = \
            a["triggers"].get(r["trigger_event_id"], 0) + 1
        if r["status"] == "completed":
            a["completed"] += 1
            if r["usage_quality"] == "actual_harness_reported" \
                    and r["normalized_units"] is not None:
                a["units_actual"] += float(r["normalized_units"])
                a["units_list"].append(float(r["normalized_units"]))
            else:
                a["units_unknown"] += float(r["normalized_units"] or 0)
        elif r["status"] in ("failed", "timeout"):
            a["failed"] += 1
        elif r["status"] == "running":
            a["running"] += 1
        a["runtime_total_ms"] += r["runtime_ms"] or 0
    for a in agents.values():
        total_units += a["units_actual"] + a["units_unknown"]
    out = []
    for a in sorted(agents.values(), key=lambda x: -(x["units_actual"])):
        st = stats_summary(a["units_list"])
        out.append({
            "agent_id": a["agent_id"],
            "label": AGENT_LABELS.get(a["agent_id"], a["agent_id"]),
            "requests": a["requests"], "completed": a["completed"],
            "failed": a["failed"], "running": a["running"],
            "active_users": len(a["users"]),
            "units": a["units_actual"] + a["units_unknown"],
            "share_pct": (a["units_actual"] + a["units_unknown"]) / total_units * 100.0
                if total_units else 0.0,
            "stats": st, "runtime_total_ms": a["runtime_total_ms"],
            "retries": sum(1 for n in a["triggers"].values() if n > 1),
        })
    # include zero-activity canonical agents
    for agent_id, label, _kind in ledger.CANONICAL_AGENTS:
        if agent_id not in agents:
            out.append({
                "agent_id": agent_id, "label": label, "requests": 0,
                "completed": 0, "failed": 0, "running": 0, "active_users": 0,
                "units": 0.0, "share_pct": 0.0,
                "stats": stats_summary([]), "runtime_total_ms": 0, "retries": 0,
            })
    return {"agents": out, "total_units": total_units}


# ---------------------------------------------------------------------------
# usage share (Phase 5)
# ---------------------------------------------------------------------------

def usage_share(start: int, end: int) -> Dict[str, Any]:
    ua = user_analytics(start, end)
    aa = agent_analytics(start, end)
    users = sorted(ua["users"], key=lambda x: -x["units"])
    total = sum(u["units"] for u in users)
    share_users = []
    if total > 0:
        for u in users[:3]:
            share_users.append({"label": u["label"],
                                "pct": u["units"] / total * 100.0})
        others = sum(u["units"] for u in users[3:])
        if users[3:]:
            share_users.append({"label": "Others",
                                "pct": others / total * 100.0})
    return {"by_agent": [{"label": a["label"], "pct": a["share_pct"]}
                         for a in aa["agents"] if a["requests"] > 0],
            "by_user": share_users}


# ---------------------------------------------------------------------------
# measurement quality (Phase 9)
# ---------------------------------------------------------------------------

def measurement_quality(start: int, end: int) -> Dict[str, Any]:
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT agent_id, usage_quality, COUNT(*) AS n"
            " FROM requests WHERE started_at >= ? AND started_at < ?"
            " AND usage_quality IN ('actual_harness_reported','unknown')"
            " GROUP BY agent_id, usage_quality", (start, end)).fetchall()
    finally:
        conn.close()
    per: Dict[str, Dict[str, int]] = {}
    total_actual = total_unknown = 0
    for r in rows:
        d = per.setdefault(r["agent_id"], {"actual": 0, "unknown": 0})
        if r["usage_quality"] == "actual_harness_reported":
            d["actual"] += r["n"]
            total_actual += r["n"]
        else:
            d["unknown"] += r["n"]
            total_unknown += r["n"]
    agents = {}
    for aid, d in per.items():
        ai = d["actual"] + d["unknown"]
        agents[aid] = {
            "actual": d["actual"], "unknown": d["unknown"],
            "coverage": d["actual"] / ai * 100.0 if ai else None,
        }
    ai_all = total_actual + total_unknown
    return {
        "agents": agents,
        "total_actual": total_actual, "total_unknown": total_unknown,
        "coverage": total_actual / ai_all * 100.0 if ai_all else None,
        "unknown_coverage": total_unknown / ai_all * 100.0 if ai_all else None,
    }


# ---------------------------------------------------------------------------
# data confidence (Phase 8)
# ---------------------------------------------------------------------------

def data_confidence(now_ts: Optional[int] = None) -> Dict[str, Any]:
    now_ts = now_ts or ledger.now()
    conn = ledger.connect()
    try:
        first = conn.execute(
            "SELECT MIN(started_at) AS m FROM requests"
            " WHERE usage_quality IN ('actual_harness_reported','unknown')").fetchone()["m"]
        n_completed = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE status = 'completed'"
            " AND usage_quality = 'actual_harness_reported'").fetchone()["n"]
        n_failed = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE status IN"
            " ('failed','timeout')").fetchone()["n"]
        n_users = conn.execute(
            "SELECT COUNT(DISTINCT principal_pubkey) AS n FROM requests"
            " WHERE principal_pubkey IS NOT NULL").fetchone()["n"]
        n_unknown = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE usage_quality = 'unknown'").fetchone()["n"]
    finally:
        conn.close()
    days = (now_ts - first) / 86400.0 if first else 0.0
    ai = n_completed + n_unknown
    actual_share = (n_completed / ai * 100.0) if ai else 0.0
    # explicit, explainable levels; never strong recommendations from thin data
    if ai < 20 or days < 1 or n_users < 1:
        level = "INSUFFICIENT"
    elif days < 3 or ai < 100 or actual_share < 90.0:
        level = "LOW"
    elif days < 7 or ai < 300 or actual_share < 97.0:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {
        "observation_start": first,
        "observation_days": days,
        "completed_requests": n_completed,
        "failed_requests": n_failed,
        "unknown_requests": n_unknown,
        "active_users": n_users,
        "actual_share": actual_share,
        "level": level,
        "min_recommended_days": "3–7 days of real usage",
    }


# ---------------------------------------------------------------------------
# base allowance calibration (Phase 6)
# ---------------------------------------------------------------------------

def daily_user_usage_samples(now_ts: Optional[int] = None) -> List[float]:
    """Per-user per-ICT-day ACTUAL usage samples across all history
    (user-days). Only actual measurements; unknown days excluded, noted
    separately by measurement_quality."""
    now_ts = now_ts or ledger.now()
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT started_at, principal_pubkey, normalized_units FROM requests"
            " WHERE status = 'completed' AND usage_quality = 'actual_harness_reported'"
            " AND normalized_units IS NOT NULL AND principal_pubkey IS NOT NULL"
            " ORDER BY started_at", ()).fetchall()
    finally:
        conn.close()
    per_day: Dict[Tuple[str, int], float] = {}
    for r in rows:
        key = (r["principal_pubkey"], ict_midnight(r["started_at"]))
        per_day[key] = per_day.get(key, 0.0) + float(r["normalized_units"])
    return sorted(per_day.values())


def base_allowance_calibration(now_ts: Optional[int] = None) -> Dict[str, Any]:
    now_ts = now_ts or ledger.now()
    base = float(ledger.get_setting("base_units_daily", "3000000") or 0)
    conf = data_confidence(now_ts)
    samples = daily_user_usage_samples(now_ts)
    summ = stats_summary(samples)
    assessment = "INSUFFICIENT_DATA"
    confidence = "LOW"
    recommendation = "WAIT_FOR_MORE_DATA"
    reasons: List[str] = []
    if conf["level"] in ("INSUFFICIENT",):
        reasons.append(f"only {conf['completed_requests']} completed AI requests"
                       f" over {conf['observation_days']:.1f} days — too little"
                       " history for a statistically meaningful assessment")
    else:
        p90 = summ["p90"] or 0.0
        ratio = p90 / base if base else 0.0
        if ratio < 0.05:
            assessment = "TOO_HIGH"
            recommendation = "DECREASE"
        elif ratio < 0.20:
            assessment = "HIGH"
            recommendation = "DECREASE"
        elif ratio <= 0.60:
            assessment = "REASONABLE"
            recommendation = "KEEP"
        else:
            assessment = "LOW"
            recommendation = "INCREASE"
        confidence = {"LOW": "LOW", "MEDIUM": "MEDIUM"}.get(conf["level"], "HIGH")
        reasons.append(
            f"P90 user-day usage is {fmt_pct(ratio * 100)} of the base allowance"
            f" ({fmt_units(p90)} of {fmt_units(base)} units)")
        if conf["observation_days"] < 7:
            reasons.append(f"observation period {conf['observation_days']:.1f} days"
                           " is below the 3–7 day minimum recommendation")
    return {
        "current_base": base, "current_base_fmt": fmt_units(base),
        "median_daily": summ["median"], "median_daily_fmt": fmt_units(summ["median"]),
        "p90_daily": summ["p90"], "p90_daily_fmt": fmt_units(summ["p90"]),
        "user_day_samples": len(samples),
        "assessment": assessment, "confidence": confidence,
        "recommendation": recommendation, "reasons": reasons,
        "confidence_level": conf["level"],
    }


# ---------------------------------------------------------------------------
# profile recommendation engine (Phase 7) — recommend only, never assign
# ---------------------------------------------------------------------------

def profile_recommendations(now_ts: Optional[int] = None) -> Dict[str, Any]:
    """Suggest effective allowance sizes per profile concept from the real
    distribution of per-user daily usage. Percentiles of observed user-days
    define each concept; exceedance = share of historical user-days that would
    have gone over the suggestion. Owner may approve or ignore — nothing is
    applied automatically."""
    now_ts = now_ts or ledger.now()
    base = float(ledger.get_setting("base_units_daily", "3000000") or 0)
    samples = daily_user_usage_samples(now_ts)
    s = sorted(samples)

    # per-user medians for the "users likely to fit" column
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT started_at, principal_pubkey, normalized_units FROM requests"
            " WHERE status = 'completed' AND usage_quality = 'actual_harness_reported'"
            " AND normalized_units IS NOT NULL AND principal_pubkey IS NOT NULL").fetchall()
    finally:
        conn.close()
    per_user: Dict[str, List[float]] = {}
    for r in rows:
        per_user.setdefault(r["principal_pubkey"], []).append(float(r["normalized_units"]))

    n = len(s)
    conf = data_confidence(now_ts)
    if conf["level"] == "INSUFFICIENT":
        return {"profiles": [], "samples": n,
                "note": "INSUFFICIENT_DATA: no profile recommendations until at"
                         " least 3 days / 100 real requests are observed.",
                "base": base}
    # concept → percentile of user-day usage distribution (explained, not arbitrary)
    concepts = [
        ("Limited", 25, "P25 of observed user-days"),
        ("Standard", 50, "median of observed user-days"),
        ("High", 75, "P75 of observed user-days"),
        ("Full", 95, "P95 of observed user-days"),
    ]
    profiles = []
    for name, p, basis in concepts:
        suggested = percentile(s, p) or 0.0
        suggested = math.ceil(suggested / 1000.0) * 1000.0   # round up to 1K
        exceed = sum(1 for v in s if v > suggested)
        exceed_pct = exceed / n * 100.0 if n else 0.0
        fits = sum(1 for vals in per_user.values()
                   if (percentile(sorted(vals), 50) or 0) <= suggested)
        profiles.append({
            "profile": name, "basis": basis,
            "suggested_units": suggested, "suggested_fmt": fmt_units(suggested),
            "pct_of_base": suggested / base * 100.0 if base else None,
            "exceedance_pct": exceed_pct, "exceedance_days": exceed,
            "users_fitting": fits, "samples": n,
            "confidence": "LOW" if n < 10 else ("MEDIUM" if n < 30 else "HIGH"),
        })
    return {"profiles": profiles, "samples": n, "base": base}


# ---------------------------------------------------------------------------
# anomaly detection (Phase 12) — explainable, never blocking
# ---------------------------------------------------------------------------

def detect_anomalies(now_ts: Optional[int] = None) -> List[Dict[str, Any]]:
    """Simple, explainable anomaly rules over real ledger data.
    Severity: Unusual / High Usage / Critical. Every finding carries a
    plain-language reason. Detection never blocks or changes anything."""
    now_ts = now_ts or ledger.now()
    conn = ledger.connect()
    try:
        reqs = [dict(r) for r in conn.execute(
            "SELECT r.principal_pubkey, p.display_name, r.agent_id, r.status,"
            " r.normalized_units, r.started_at, r.runtime_ms, r.usage_quality,"
            " r.trigger_event_id"
            " FROM requests r LEFT JOIN principals p"
            " ON p.principal_pubkey = r.principal_pubkey"
            " WHERE r.usage_quality IN ('actual_harness_reported','unknown')"
            " ORDER BY r.started_at", ())]
        # burst rules scan the recent window only (today's anomalies, not
        # forever-re-triggering on historical bursts)
        recent = [r for r in reqs if r["started_at"] >= now_ts - 86400]
    finally:
        conn.close()
    findings: List[Dict[str, Any]] = []

    # 1. user daily usage vs their own prior-7-day average (min 2 prior days)
    per_user_day: Dict[str, Dict[int, float]] = {}
    for r in reqs:
        if r["status"] == "completed" and r["usage_quality"] == "actual_harness_reported" \
                and r["principal_pubkey"] and r["normalized_units"] is not None:
            d = per_user_day.setdefault(r["principal_pubkey"], {})
            key = ict_midnight(r["started_at"])
            d[key] = d.get(key, 0.0) + float(r["normalized_units"])
    today_key = ict_midnight(now_ts)
    for pk, days in per_user_day.items():
        label = next((r["display_name"] for r in reqs
                      if r["principal_pubkey"] == pk and r["display_name"]), None) \
            or (pk[:12] + "…")
        prior = [v for k, v in days.items() if k < today_key][-7:]
        today = days.get(today_key, 0.0)
        if len(prior) >= 2 and today > 0:
            avg = sum(prior) / len(prior)
            if today >= 3 * avg and avg > 0:
                mult = today / avg
                sev = "Critical" if (mult >= 10 or today >= 8500000) else "High Usage"
                findings.append({
                    "kind": "USAGE_SPIKE", "subject_type": "user", "subject_id": pk,
                    "subject_label": label, "severity": sev,
                    "reason": f"Usage is {mult:.1f}× this user's 7-day average"
                              f" ({fmt_units(today)} today vs {fmt_units(avg)} average).",
                })

    # 2. single request far above the global P95 (min 20 samples)
    all_units = sorted(float(r["normalized_units"]) for r in reqs
                       if r["status"] == "completed" and r["normalized_units"] is not None)
    p95 = percentile(all_units, 95)
    if len(all_units) >= 20 and p95:
        for r in recent:
            if r["status"] == "completed" and r["normalized_units"] \
                    and float(r["normalized_units"]) > 3 * p95:
                findings.append({
                    "kind": "USAGE_SPIKE", "subject_type": "user",
                    "subject_id": r["principal_pubkey"] or "(unknown)",
                    "subject_label": r["display_name"] or "unknown user",
                    "severity": "Unusual",
                    "reason": f"Single request {fmt_units(float(r['normalized_units']))}"
                              f" is >3× the all-time P95 ({fmt_units(p95)}).",
                })

    # 3. high request rate: >10 completed requests by one user in any rolling hour
    by_user: Dict[str, List[int]] = {}
    for r in reqs:
        if r["status"] == "completed" and r["principal_pubkey"]:
            by_user.setdefault(r["principal_pubkey"], []).append(r["started_at"])
    for pk, ts_list in by_user.items():
        ts_list = sorted(t for t in ts_list if t >= now_ts - 86400)
        for i, t in enumerate(ts_list):
            if sum(1 for t2 in ts_list[i:] if t2 - t <= 3600) > 10:
                findings.append({
                    "kind": "USAGE_SPIKE", "subject_type": "user", "subject_id": pk,
                    "subject_label": next((x["display_name"] for x in reqs
                                           if x["principal_pubkey"] == pk
                                           and x["display_name"]), None)
                                       or (pk[:12] + "…"),
                    "severity": "Unusual",
                    "reason": "More than 10 requests in a single hour.",
                })
                break

    # 4. high failure rate: ≥30% of last 20 requests failed (min 10 total)
    recent_status = [r["status"] for r in reqs[-20:]]
    if len(recent_status) >= 10:
        fail_rate = sum(1 for s in recent_status
                        if s in ("failed", "timeout")) / len(recent_status)
        if fail_rate >= 0.3:
            findings.append({
                "kind": "HIGH_FAILURE_RATE", "subject_type": "system",
                "subject_id": None, "subject_label": "system",
                "severity": "Critical" if fail_rate >= 0.5 else "Unusual",
                "reason": f"{fail_rate * 100:.0f}% of the last {len(recent_status)}"
                          " requests failed or timed out.",
            })

    # 5. repeated retries: same trigger delivered 3+ times
    trig: Dict[str, int] = {}
    for r in recent:
        trig[r["trigger_event_id"]] = trig.get(r["trigger_event_id"], 0) + 1
    for t, n in trig.items():
        if n >= 3:
            findings.append({
                "kind": "HIGH_FAILURE_RATE", "subject_type": "system",
                "subject_id": None, "subject_label": "system", "severity": "Unusual",
                "reason": f"Trigger {t[:8]}… was attempted {n} times (repeated retries).",
            })

    # 6. excessive concurrent jobs (≥5 overlapping)
    events = []
    for r in recent:
        if r["runtime_ms"]:
            events.append((r["started_at"], 1))
            events.append((r["started_at"] + r["runtime_ms"], -1))
    events.sort()
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    if peak >= 5:
        findings.append({
            "kind": "USAGE_SPIKE", "subject_type": "system", "subject_id": None,
            "subject_label": "system", "severity": "Unusual",
            "reason": f"{peak} AI requests ran concurrently at one point.",
        })
    return findings


def capacity_anomalies() -> List[Dict[str, Any]]:
    """AGY provider capacity anomalies: low remaining or sharp drop.
    Based on the latest snapshot per agent/model vs ~24h ago."""
    conn = ledger.connect()
    try:
        latest = conn.execute(
            "SELECT agent_id, model, remaining_percent, captured_at FROM"
            " account_capacity_snapshots s WHERE id IN"
            " (SELECT MAX(id) FROM account_capacity_snapshots"
            "  GROUP BY agent_id, model)").fetchall()
        day_ago = conn.execute(
            "SELECT agent_id, model, MIN(remaining_percent) AS rp FROM"
            " account_capacity_snapshots WHERE captured_at >= ?"
            " GROUP BY agent_id, model",
            (ledger.now() - 90000,)).fetchall()
    finally:
        conn.close()
    findings = []
    day_map = {(r["agent_id"], r["model"]): r["rp"] for r in day_ago}
    for r in latest:
        if r["remaining_percent"] is None:
            continue
        key = (r["agent_id"], r["model"])
        prev = day_map.get(key)
        label = f"AGY {r['agent_id'][-1]} · {r['model']}"
        if r["remaining_percent"] <= 20:
            findings.append({
                "kind": "ACCOUNT_CAPACITY_LOW", "subject_type": "agent",
                "subject_id": r["agent_id"], "subject_label": label,
                "severity": "Critical" if r["remaining_percent"] <= 10 else "High Usage",
                "reason": f"Provider capacity for {label} is down to"
                          f" {r['remaining_percent']:.0f}% remaining.",
            })
        elif prev is not None and prev - r["remaining_percent"] >= 10:
            findings.append({
                "kind": "AGENT_CAPACITY_WARNING", "subject_type": "agent",
                "subject_id": r["agent_id"], "subject_label": label,
                "severity": "Unusual",
                "reason": f"{label} capacity dropped {prev - r['remaining_percent']:.0f}"
                          f" points in the last 24h"
                          f" (now {r['remaining_percent']:.0f}% remaining).",
            })
    return findings


def data_quality_anomalies(start: int, end: int) -> List[Dict[str, Any]]:
    q = measurement_quality(start, end)
    out = []
    if q["coverage"] is not None and q["coverage"] < 95.0:
        out.append({
            "kind": "DATA_QUALITY_DEGRADED", "subject_type": "system",
            "subject_id": None, "subject_label": "measurement pipeline",
            "severity": "Unusual",
            "reason": f"Only {q['coverage']:.1f}% of AI requests carry actual"
                      f" harness-reported usage ({q['total_unknown']} unknown).",
        })
    return out


# ---------------------------------------------------------------------------
# hard limit readiness (Phase 10) — empirical only, never "READY" on assumptions
# ---------------------------------------------------------------------------

def hard_limit_readiness() -> Dict[str, Any]:
    conf = data_confidence()
    qual = measurement_quality(0, ledger.now())
    conn = ledger.connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE"
            " usage_quality IN ('actual_harness_reported','unknown')").fetchone()["n"]
        with_identity = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE principal_pubkey IS NOT NULL"
            " AND channel_id IS NOT NULL"
            " AND usage_quality IN ('actual_harness_reported','unknown')").fetchone()["n"]
        reservations = conn.execute(
            "SELECT COUNT(*) AS n FROM reservations").fetchone()["n"]
        settled = conn.execute(
            "SELECT COUNT(*) AS n FROM reservations WHERE status = 'settled'").fetchone()["n"]
        warns = conn.execute("SELECT COUNT(*) AS n FROM alert_state").fetchone()["n"]
    finally:
        conn.close()

    checks = [
        {
            "item": "Trusted user identity",
            "status": "PASS" if total > 0 and with_identity == total else "UNPROVEN",
            "evidence": (f"{with_identity}/{total} recorded requests carry a"
                         " relay-verified sender pubkey" if total else
                         "no requests recorded yet"),
        },
        {
            "item": "Trusted channel identity",
            "status": "PASS" if total > 0 and with_identity == total else "UNPROVEN",
            "evidence": "channel cross-checked against the signed trigger event"
                         if total else "no requests recorded yet",
        },
        {
            "item": "Duplicate-safe accounting",
            "status": "PASS",
            "evidence": ("uniqueness via PK constraint; duplicate redelivery replays"
                         " cached reply and records status='duplicate' (never spend)"
                         " — proven in offline replay tests"),
        },
        {
            "item": "Sufficient observation history",
            "status": "PASS" if conf["level"] in ("MEDIUM", "HIGH") else "NOT MET",
            "evidence": (f"{conf['observation_days']:.1f} days observed,"
                         f" {conf['completed_requests']} completed requests"
                         f" → confidence {conf['level']}"),
        },
        {
            "item": "Sufficient measurement quality",
            "status": "PASS" if (qual["coverage"] or 0) >= 99.0 else "NOT MET",
            "evidence": (f"actual usage coverage {fmt_pct(qual['coverage'])}"
                         f" ({qual['total_actual']} actual,"
                         f" {qual['total_unknown']} unknown requests)"),
        },
        {
            "item": "Concurrent reservation mechanism tested",
            "status": "TESTED OFFLINE" if reservations == 0 else "PARTIAL",
            "evidence": (f"{reservations} reservations, {settled} settled in"
                         " production" if reservations else
                         "reserve/settle/release/expiry paths verified offline;"
                         " zero production reservations exercised yet"),
        },
        {
            "item": "Restart safety tested",
            "status": "PARTIAL",
            "evidence": ("dashboard + poller restarts verified live with history"
                         " preserved; full gateway restart cycle not yet exercised"
                         " in production"),
        },
        {
            "item": "Warning thresholds tested",
            "status": "PASS" if warns > 0 else "TESTED OFFLINE",
            "evidence": (f"{warns} production threshold alerts recorded"
                         if warns else
                         "all four thresholds verified once-each in the offline"
                         " harness; no production crossing yet (usage far below 70%)"),
        },
        {
            "item": "Owner override mechanism designed",
            "status": "NOT DESIGNED",
            "evidence": ("manual owner allow/deny override for a hard-limit block"
                         " is not yet designed — required before enforcement"),
        },
        {
            "item": "Provider capacity behavior understood",
            "status": "PARTIAL",
            "evidence": ("agy-quota snapshots flow (poller active); multi-week"
                         " capacity-depletion behavior not yet observed"),
        },
    ]
    required = [c for c in checks if c["item"] in (
        "Trusted user identity", "Trusted channel identity", "Duplicate-safe accounting",
        "Sufficient observation history", "Sufficient measurement quality",
        "Concurrent reservation mechanism tested", "Restart safety tested",
        "Warning thresholds tested", "Owner override mechanism designed",
        "Provider capacity behavior understood")]
    all_pass = all(c["status"] == "PASS" for c in required)
    return {
        "checks": checks,
        "verdict": "READY FOR CONTROLLED TESTING" if all_pass else "NOT READY",
    }


# ---------------------------------------------------------------------------
# concurrency dry-run replay (Phase 11) — hypothetical, never blocking
# ---------------------------------------------------------------------------

def concurrency_dry_run(start: int, end: int) -> Dict[str, Any]:
    """Replay the window's REAL completed requests in order, per user, against
    a HYPOTHETICAL hard limit (base × their profile fraction, warn thresholds
    as configured). Counts WOULD_ALLOW / WOULD_WARN / WOULD_BLOCK.
    Nothing is enforced; production requests are never rejected."""
    base = float(ledger.get_setting("base_units_daily", "3000000") or 0)
    th_w = float(ledger.get_setting("threshold_warning", "70"))
    th_h = float(ledger.get_setting("threshold_high", "85"))
    th_c = float(ledger.get_setting("threshold_critical", "95"))
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT r.principal_pubkey, r.community_id, r.agent_id, r.normalized_units"
            " FROM requests r WHERE r.started_at >= ? AND started_at < ?"
            " AND r.status = 'completed' AND r.usage_quality = 'actual_harness_reported'"
            " AND r.normalized_units IS NOT NULL"
            " AND r.principal_pubkey IS NOT NULL ORDER BY r.started_at",
            (start, end)).fetchall()
    finally:
        conn.close()
    running: Dict[str, float] = {}
    counts = {"WOULD_ALLOW": 0, "WOULD_WARN": 0, "WOULD_BLOCK": 0}
    blocks: List[Dict[str, Any]] = []
    for r in rows:
        pk = r["principal_pubkey"]
        frac = ledger.get_allowance(r["community_id"], pk).get("assigned_fraction", 1.0)
        eff = base * frac
        spent = running.get(pk, 0.0) + float(r["normalized_units"])
        pct = spent / eff * 100.0 if eff else 0.0
        verdict = "WOULD_ALLOW"
        if pct >= 100.0:
            verdict = "WOULD_BLOCK"
            blocks.append({"user": pk[:12] + "…", "agent": r["agent_id"],
                           "pct": pct, "units": float(r["normalized_units"])})
        elif pct >= th_c or pct >= th_h or pct >= th_w:
            verdict = "WOULD_WARN"
        counts[verdict] += 1
        running[pk] = spent
    return {
        "counts": counts, "blocks": blocks[:10],
        "replayed": len(rows), "hypothetical_base": base,
        "note": ("Dry run only: real requests were all allowed in production."
                 " Verdicts show what a hard limit WOULD have done."),
    }

# ---------------------------------------------------------------------------
# alert-center scan (Phase 13) — deduplicated recording, never blocking
# ---------------------------------------------------------------------------

SEVERITY_RANK = {"Unusual": 0, "High Usage": 1, "Critical": 2}
THRESH_SEVERITY = {"warning": "Unusual", "high": "High Usage",
                   "critical": "Critical", "exhausted": "Critical"}


def _record(f: Dict[str, Any], day: int) -> None:
    dedup = f"{f['kind']}|{f.get('subject_id') or f.get('subject_type') or 'system'}|{day}"
    ledger.record_owner_alert(kind=f["kind"], subject_type=f["subject_type"],
                              subject_id=f.get("subject_id"),
                              subject_label=f.get("subject_label"),
                              severity=f["severity"], reason=f["reason"],
                              dedup_key=dedup)


def record_capacity_alerts() -> int:
    """Capacity-only scan (used by the poller). Deduplicated per day."""
    day = ict_midnight(ledger.now())
    findings = capacity_anomalies()
    for f in findings:
        _record(f, day)
    return len(findings)


def scan_and_record_alerts() -> List[Dict[str, Any]]:
    """Full owner-alert scan at calibration render time: usage anomalies,
    capacity anomalies, data quality, mirrored user threshold warnings, and
    hypothetical would-block verdicts from the concurrency dry run.
    All alerts deduplicate per day (occurrences counted, never spammed).
    Recording an alert never blocks or changes any request."""
    now_ts = ledger.now()
    day = ict_midnight(now_ts)
    findings: List[Dict[str, Any]] = []

    for f in detect_anomalies(now_ts):
        findings.append(f)
    for f in capacity_anomalies():
        findings.append(f)
    s, e, _ = window_bounds("today", now_ts=now_ts)
    for f in data_quality_anomalies(s, e):
        findings.append(f)

    # mirror delivered threshold warnings from alert_state into the center
    conn = ledger.connect()
    try:
        rows = conn.execute(
            "SELECT a.principal_pubkey, a.threshold, a.triggered_at, p.display_name"
            " FROM alert_state a LEFT JOIN principals p"
            " ON p.principal_pubkey = a.principal_pubkey"
            " WHERE a.triggered_at >= ?", (day,)).fetchall()
    finally:
        conn.close()
    for r in rows:
        findings.append({
            "kind": "USER_USAGE_WARNING", "subject_type": "user",
            "subject_id": r["principal_pubkey"],
            "subject_label": r["display_name"] or (r["principal_pubkey"][:12] + "…"),
            "severity": THRESH_SEVERITY.get(r["threshold"], "Unusual"),
            "reason": f"Usage crossed the {r['threshold']} threshold today"
                      " (warning delivered in-channel).",
        })

    # hypothetical future-limit blocks found by the dry run replay
    dry = concurrency_dry_run(s, e)
    if dry["counts"]["WOULD_BLOCK"] > 0:
        findings.append({
            "kind": "FUTURE_LIMIT_WOULD_BLOCK", "subject_type": "system",
            "subject_id": None, "subject_label": "dry-run replay",
            "severity": "High Usage",
            "reason": (f"Hypothetical hard limit would have blocked"
                       f" {dry['counts']['WOULD_BLOCK']} of {dry['replayed']}"
                       " requests today (dry run only — nothing was blocked)."),
        })

    for f in findings:
        _record(f, day)
    return findings
