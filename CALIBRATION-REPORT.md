# AI USAGE CENTER — CALIBRATION PHASE REPORT

Date: 2026-09-09 · System: LIVE Buzz · Phase: 2 — Observation, Calibration, and Owner Visibility
Stack unchanged: Buzz → buzz-acp → buzz-agent-gateway → Claude CLI / AGY 1–4 → usage ledger → AI Usage Center

## 1. Executive Summary

The live Usage Center was extended into an owner CALIBRATION CENTER without touching the
agent architecture, account mappings, or enforcement posture. Everything in this phase is
OBSERVATION + RECOMMENDATION only: no hard limits, no soft limits, no automatic profile
changes, no rebuilt systems. The honest headline is that **the dataset is too small for
quota decisions** — and the system now says so explicitly rather than inventing numbers.

**OVERALL STATUS: PASS** (every implemented deliverable live-verified; the calibration
verdicts themselves are honestly INSUFFICIENT_DATA — that is a correct result, not a failure).

## 2. Operating Mode (unchanged — verified from live settings after all work)

| Mode | State |
|------|-------|
| METER_ONLY | **ON** (every real turn metered, live-verified again this phase) |
| WARN_ONLY | **ON** (warning thresholds 70/85/95/100; mechanism verified in harness) |
| SOFT_LIMIT | **OFF** |
| HARD_LIMIT | **OFF** (no toggle exists anywhere; readiness verdict: NOT READY) |

## 3. Observation Dataset

- Timezone for ALL calibration windows: **Asia/Ho_Chi_Minh (ICT, UTC+7)** — Today / 24h /
  3d / 7d / 30d / custom (YYYY-MM-DD), boundaries at ICT midnight.
- Observation period so far: **0.1 days** (started 2026-09-09 ~13:00 ICT).
- Requests: **16 today** — 13 real AI turns + 3 zero-AI `/usage` lookups (incl. `/usage system`).
- Completed AI turns with actual harness-reported tokens: **13**, from **1 active user**
  (the owner), across **all five agents**.
- Raw ledger preserved in full (append-only `usage_events`; daily/weekly/monthly
  `usage_aggregates` are regenerated rollups — rebuild verified: aggregates reproduce
  today's totals exactly, 250,539 units).
- **DATA CONFIDENCE: INSUFFICIENT** (needs ≥ 3–7 days / ≥ 20+ requests / ≥ 2 users for LOW+).

## 4. Measurement Quality

- **100.0% actual coverage** — every completed AI turn carries real harness token counts
  (`actual_harness_reported`); 0 unknown. Estimated/actual are never blended; unknowns
  would stay unknown.
- New gateway code is now **live-confirmed**: the Claude CLI `model` label is captured from
  `modelUsage` (this build omits the top-level `model` key) — the live regression turn
  recorded `glm-5.3:cloud` (previous rows had model UNKNOWN; Phase-1 caveat closed).
- `cost_usd` remains NULL everywhere (no billing authority proven). AGY model stays NULL
  (not reported by the backend). Prompts are never stored (verified by scan).
- Per-agent coverage table lives on the Calibration page; a coverage drop below 95% raises
  a DATA_QUALITY_DEGRADED alert.

## 5. Request Distribution (boundaries DERIVED from data, not hardcoded)

13 completed requests (30d window): median **7K** · P75 24K · P90 51K · P95 **52K** ·
largest **53K** units. Bucket boundaries = this window's P25/median/P75/P95:
Very Light 25% · Light 25% · Medium 25% · Heavy 12.5% · Very Heavy 12.5%.
Sample is small; these boundaries will move as real usage accumulates — by design.

## 6. User Analytics (window: today/30d — same day here)

| User | Profile | Used % | Requests | Fail | Median | P90 | Largest | Runtime | Peak concurrent | Most used |
|------|---------|--------|----------|------|--------|-----|---------|---------|-----------------|-----------|
| NcThang (owner) | full | **8.4%** | 16 (13 AI) | 0 | 7K | 51K | 53K | ~75s | 13 | claude-cli by units / agy-1 by count |

Percentages and requests are primary; raw units only in the Details foldout. Sortable by
units/requests/runtime/failures. Runtime avg/median/P75/P90/P95/largest computed per
request; per-user day-over-day, peak concurrency via interval sweep.

## 7. Agent Analytics (share of usage, 30d)

| Agent | Share | Requests | Users | Failures | Retries | Running | Median |
|-------|-------|----------|-------|----------|---------|---------|--------|
| Claude CLI | 61.8% | 3 | 1 | 0 | 0 | 0 | 52K |
| AGY 2 | 11.9% | 3 | 1 | 0 | 0 | 0 | 14K |
| AGY 1 | 11.7% | 3 | 1 | 0 | 0 | 0 | 7K |
| AGY 3 | 8.9% | 2 | 1 | 0 | 0 | 0 | 15K |
| AGY 4 | 5.7% | 2 | 1 | 0 | 0 | 0 | 7K |

## 8. AGY Provider Capacity (separate quantity — NEVER mixed with user allowance)

Latest `agy-quota` snapshots (poller active, 600s cadence):
**AGY 1: 93% remaining (lowest model: gemini-2.5-flash)** · AGY 2/3/4: 100%.
Displayed under its own "Provider capacity" heading everywhere. Detection rules added:
remaining ≤ 20% (Critical at ≤10%) or a ≥10-point drop in 24h raise
ACCOUNT_CAPACITY_LOW / AGENT_CAPACITY_WARNING alerts. None triggered (levels healthy).

## 9. Base Allowance Calibration (3,000,000 units/day — UNCHANGED)

- Median user-day usage: 250K · P90: 250K (1 sample) → **Assessment: INSUFFICIENT_DATA**.
- **Recommendation: WAIT_FOR_MORE_DATA** · Confidence: LOW.
- Reason shown to the owner verbatim: "only 13 completed AI requests over 0.1 days — too
  little history for a statistically meaningful assessment." Current usage (8.4% of base
  on the heaviest day so far) is suggestive but NOT a basis for changing the base.
- Nothing was changed automatically; the base stays exactly as configured.

## 10. Suggested Allowance Profiles (recommendation engine)

**INSUFFICIENT_DATA** — no profile suggestions are produced until ≥ 3 days / ≥ 100 real
requests are observed. When the sample is sufficient the engine will derive
Limited/Standard/High/Full suggestions from the P25/median/P75/P95 of observed user-days,
with % of base, historical exceedance %, users-fitting count, confidence, and sample size —
displayed as RECOMMENDATIONS only (assignment stays an explicit owner action).

## 11. Alert Center (deduplicated; no AI used for alert text)

Kinds supported: USER_USAGE_WARNING, AGENT_CAPACITY_WARNING, USAGE_SPIKE,
HIGH_FAILURE_RATE, DATA_QUALITY_DEGRADED, ACCOUNT_CAPACITY_LOW, FUTURE_LIMIT_WOULD_BLOCK.
Dedup: one row per kind+subject+day; repeat occurrences bump the counter (no spam).
Currently open (both are genuine observations of the deliberate test bursts — left for
the owner to acknowledge):
1. USAGE_SPIKE (system, Unusual): "8 AI requests ran concurrently at one point."
2. USAGE_SPIKE (NcThang, Unusual): "More than 10 requests in a single hour."
Anomaly rules are simple and explainable (≥3× own 7-day average, >3× all-time P95 single
request, >10 req/hour, ≥30% failure over last 20, ≥3 retries per trigger, ≥5 concurrent,
AGY capacity rules). **Anomalies are never auto-blocked.** Acknowledge button verified
(HTTP POST → status `acknowledged`, `acknowledged_by` recorded).

## 12. Hard Limit Readiness — verdict: **NOT READY**

| Checklist item | Status | Evidence |
|---|---|---|
| Trusted user identity | PASS | 13/13 requests carry relay-verified sender pubkey |
| Trusted channel identity | PASS | channel cross-checked against signed trigger event |
| Duplicate-safe accounting | PASS | PK uniqueness; duplicates replay cache, never spend |
| Sufficient observation history | **NOT MET** | 0.1 days, 13 requests → confidence INSUFFICIENT |
| Sufficient measurement quality | PASS | 100% actual coverage, 0 unknown |
| Concurrent reservation mechanism | TESTED OFFLINE | reserve/settle/release/expiry verified; 0 production uses |
| Restart safety | PARTIAL | dashboard+poller verified live; full gateway cycle unexercised |
| Warning thresholds | TESTED OFFLINE | all four fire once-each in harness; no live crossing yet |
| Owner override mechanism | **NOT DESIGNED** | required before any enforcement |
| Provider capacity behavior | PARTIAL | snapshots flow; multi-week depletion unobserved |

Verdict can only be READY FOR CONTROLLED TESTING when every item is empirically PASS —
and enforcement stays OFF regardless until the owner explicitly decides.

## 13. Concurrency Dry-Run (hypothetical replay — production was never blocked)

Replay of all 13 real completed requests against a hypothetical hard limit at each
user's effective allowance: **13 WOULD_ALLOW · 0 WOULD_WARN · 0 WOULD_BLOCK.**
A non-zero WOULD_BLOCK count would raise a FUTURE_LIMIT_WOULD_BLOCK alert (as guidance
for the owner, not enforcement).

## 14. Regression Tests (all LIVE, real Buzz → agent → ledger → dashboard)

| Test | Result |
|------|--------|
| Five concurrent mentions (claude-cli + AGY 1–4) | PASS — 5 rows, 5 distinct agents, all completed 13:36:59→13:37:11 overlapping, actual harness tokens, thread = trigger event, channel = Tech, principal = relay-verified owner |
| Duplicate accounting | PASS — 0 triggers with >1 non-duplicate row; 0 orphan idempotency rows |
| Cross-account routing | PASS — each reply/row attributed to its own agent_id; no leakage |
| Cross-channel leakage | PASS — all replies in Tech channel, correct threads |
| `/usage` (member view) | PASS — reply: "Used: 8% / Remaining: 92% / Requests: 16 / Reset: 00:00 ICT / Most used agent: Claude CLI"; zero AI turns (no_ai_call, 0 units) |
| `/usage system` (owner view) | PASS — "Active users today: 1 / Overall usage today: 8% / Warnings: 1 / Highest user: NcThang (8%) / Lowest AGY capacity: AGY 1 — 93% (gemini-2.5-flash) / Dashboard: http://127.0.0.1:8787"; zero AI turns |
| Non-owner gating | PASS (harness) — non-owner `/usage system` gets own usage + "owner only" note; never aggregate data |
| Percentile math never on hot path | PASS — all P-quantiles computed at dashboard/query time; gateway meters only SUM |
| Offline harness (gateway) | ALL 40 CHECKS PASS (incl. 14 new calibration checks) |
| Secret hygiene | PASS — scan of all 8 live views + alerts + calibration: no nsec/npub/email/auth-tag/key material |

## 15. Restart Tests (ONLY the services this phase modified)

- **Dashboard restart** → history preserved (units 250,539 / requests 16 identical
  before/after), calibration page serving immediately, and **buzz-acp PID set identical**
  (md5-verified) — agents completely unaffected.
- **Capacity poller restart** → resumed polling; latest snapshot 18 s old after restart.
- No agent processes were restarted at any point in this phase.

## 16. Dashboard Verdicts (http://127.0.0.1:8787 — loopback-only)

- **NEW Calibration page** (`/calibration`): window selector (Today/24h/3d/7d/30d/custom,
  ICT), Data Confidence, Measurement Quality, Request Distribution, Usage Share
  (by agent & user), Users table (sortable, percentage-first), Agents table, separate
  Provider Capacity block (never blended with allowance), Base Allowance Calibration,
  Suggested Profiles, Anomalies, Hard-Limit Readiness checklist, Concurrency Dry-Run.
  Verified: all windows + custom render, friendly custom-date error, sort works.
- **Upgraded Alerts page**: Alert Center (owner_alerts with kind/severity/first/last
  seen/occurrences/status + acknowledge) above the threshold-alerts table.
- All Phase-1 views (Overview/Users/Agents/Settings) unchanged and re-verified;
  `/usage` reply and dashboard agree (8% both).

## 17. Files Modified

| File | Change |
|------|--------|
| `usage-control/lib/analytics.py` | **NEW** — calibration engine: ICT windows, percentiles, data-derived distribution, user/agent stats, usage share, confidence, measurement quality, base-allowance calibration, profile recommendation engine, explainable anomaly rules, readiness checklist, concurrency dry-run, alert-center scan. ruff+pyright clean. |
| `usage-control/lib/ledger.py` | Extended: `owner_alerts` + `usage_aggregates` tables, `owner_pubkeys` setting, `record_owner_alert` (dedup upsert w/ severity-max + occurrences), `acknowledge_owner_alert`, `owner_alerts_recent`, `is_owner` (pubkey-based), ICT helpers, `rebuild_aggregates` (reproducible rollups). Existing API untouched. |
| `usage-control/bin/dashboard.py` | Extended: Calibration view, Alert Center with acknowledge route, nav item, query parsing. |
| `usage-control/bin/capacity_poller.py` | Extended: records capacity alerts after each poll (deduplicated, failures non-fatal). |
| `~/.local/bin/buzz-agent-gateway` | Extended `/usage`: "Most used agent" line, "Reset: 00:00 ICT", `detail` shows share % (no raw units), NEW owner-gated `/usage system` zero-AI overview; non-owners never see aggregate data. |
| `usage-control/usage.db` | New tables (owner_alerts, usage_aggregates) + today's genuine traffic. |

## 18. Backup & Rollback

- Phase-0 backup: `usage-control/backups/20260909-131801-calibration-phase/`
  (gateway, dashboard, poller, ledger SHAs; systemd units; copy of usage.db;
  BASELINE-calibration.txt with PIDs/health/row counts/modes).
- Rollback: restore those files, `systemctl --user restart buzz-usage-dashboard.service
  buzz-usage-capacity.service` — the two new DB tables can be dropped or ignored
  (nothing in the enforcement path depends on them); agents were never touched.
- Note: gateway change is backward-compatible; old workers (if any pooled instance
  survived) simply lack the new `/usage` lines until respawn.

## 19. Recommended Observation Period & Next Phase

**Observation period: keep observing for 3–7 days** (minimum) of real multi-user traffic
before any quota decision. Confidence gates in the system: INSUFFICIENT → LOW (≥1 day,
≥20 requests, ≥90% actual) → MEDIUM (≥3 days, ≥100 requests) → HIGH (≥7 days, ≥300).

**Exactly ONE recommended next phase (NOT implemented):**

> **Phase 3 — Controlled Enforcement Preparation.** After the observation window, if
> Data Confidence reaches MEDIUM+, revisit: (1) base allowance decision from the then-current
> calibration assessment, (2) profile assignments from the recommendation table,
> (3) design of the owner override mechanism (the one readiness item with no design),
> (4) a controlled hard-limit test against a disposable test user. Do not begin this
> phase while confidence is INSUFFICIENT/LOW — that is the entire point of this phase.

**Do not enable hard limits now.** Hard Limit Readiness is NOT READY, and the system is
deliberately reporting INSUFFICIENT_DATA rather than inventing thresholds.