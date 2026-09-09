# AI USAGE CENTER IMPLEMENTATION REPORT

Date: 2026-09-09 · System: LIVE Buzz (not a prototype) · Ledger: usage-control/usage.db

## A. Baseline

- Full backup taken before any change: `usage-control/backups/20260909-121416/`
  (original `buzz-agent-gateway` SHA `8effe29c…482e81`, `buzz-acp` SHA `a082bb54…c337b82`,
  gateway_state.db, managed-agents.json, systemd units, BASELINE.txt with PIDs).
- `buzz-acp` binary, `buzz` CLI, managed-agents.json, and the five agent identities are
  UNTOUCHED. Five agents: Claude CLI + AGY 1–4. AGY account mappings unchanged.
  No agents added, removed, or weakened; execution permissions unchanged
  (claude: bypassPermissions path preserved; AGY: isolated HOME per account preserved).
- Email-leaking legacy gateway log archived mode-600 as `gateway.log.old-with-emails`;
  live `gateway.log` contains no emails or credential strings (verified by scan).

## B. Trusted Identity

- Identity is derived ONLY from: (1) candidate trigger event id + channel parsed from the
  buzz-acp-rendered `<context>` block (precedes user content; first-match), and (2) the
  sender pubkey confirmed by fetching the signed kind-9 mention event from the relay
  (`buzz messages get --kinds 9`), freshness window 900 s, h-tag channel cross-check.
- Prompt text is NEVER the security source of truth. Display names are cosmetic hints only.
- Fail-closed kinds: `identity_unparseable`, `identity_infra_failure` (1 retry), 
  `identity_not_found`, `identity_stale`, `identity_channel_mismatch`, `identity_no_pubkey`.
  On failure the gateway publishes NO AI call, NO reply, records `identity_failure` in audit.
- LIVE-VERIFIED: all 9 real turns attributed to the owner's relay pubkey
  `2da3184b…f0001e` — including a turn whose message text contained forged
  `From:`/`Channel:`/`Event ID:` lines (Test C).

## C. AGY Probe

- One real turn per AGY account measured the stdout JSON contract:
  `usage {input_tokens, output_tokens, thinking_tokens, cache_read_tokens, total_tokens}`,
  `conversation_id`. NO model, NO cost are reported by AGY → stored NULL (UNKNOWN), never fabricated.
- AGY capacity measured separately via `agy-quota --json` (never from user usage):
  poller records per-account per-model `remaining_percent` snapshots every 600 s.
  Latest: AGY 1 lowest 93% (gemini family), AGY 2/3/4 100%. Emails exist only inside
  the fixed mapping dicts and are never written to the ledger or logs.

## D. Claude Usage

- Claude CLI stdout JSON supplies actual tokens: `usage.input_tokens`,
  `usage.output_tokens`, `usage.cache_read/creation_input_tokens`,
  `usage.output_tokens_details.thinking_tokens`; model label from
  `modelUsage` (this CLI build omits the top-level `model` key).
- `total_cost_usd` is present but `costBasis: "list"` — CLI-computed list-pricing
  arithmetic over a third-party router, NOT a proven billing authority →
  **cost_usd stays NULL (UNKNOWN)** in the ledger, per spec.

## E. Usage Database

- New SQLite ledger at `usage-control/usage.db` (gateway_state.db untouched):
  WAL, `foreign_keys=ON`, `busy_timeout`, transactional, append-only `usage_events`.
- Tables: principals, agents, allowance_profiles, user_allowances, settings, requests,
  request_idempotency, usage_events, account_capacity_snapshots, alert_state,
  audit_events, reservations, schema_meta.
- Idempotency uses the PRIMARY KEY (community_id + trigger_event_id + agent_id), not
  SELECT-then-INSERT: `INSERT OR IGNORE` + guarded UPDATEs. Duplicate redelivery replays
  the cached reply and records `status='duplicate'` — never counted as spend. `failed`
  turns are immediately retriable via guarded single-claimer UPDATE; stale `processing`
  takeover after 300 s.
- Test residue from the harness era was removed (FK-safe order); the ledger now
  contains only genuine turns: 9 requests, 8 real AI turns + 1 zero-AI `/usage` lookup.

## F. Percentage Model

- TWO DISTINCT percentages, never blended:
  1. USER ALLOWANCE: `base_units_daily` (3,000,000) × profile fraction.
     Profiles: full=1.0, high=0.75, standard=0.5, limited=0.25.
     Ledger stores base_units, assigned_fraction, and effective_units — not just percentages.
  2. PROVIDER/ACCOUNT CAPACITY: AGY remaining % from agy-quota snapshots, labeled
     "Provider capacity" everywhere.
- Normalization v1-actual-tokens: input + output + thinking (Claude's thinking is already
  inside output_tokens — not double-counted). `normalization_version` stored per request.

## G. Dashboard ("AI Usage Center")

- `http://127.0.0.1:8787` — binds loopback ONLY, never 0.0.0.0. Owner-only first version.
  Stdlib `http.server`, no frameworks. systemd unit `buzz-usage-dashboard.service` (active).
- Overview: AI Usage Today (5%), Active Users (1), Requests Today (9), Running Jobs (0),
  Warnings (0). Users table with allowance bars, click-through, expandable by-agent /
  recent requests / alerts, and owner-only allowance assignment (full/high/standard/limited).
- Agents view: all five agents with "Provider capacity remaining: X% (lowest across models)"
  and per-model expandable — visually and semantically distinct from allowance.
- Alerts view: thresholds 70/85/95/100 (WARNING/HIGH/CRITICAL/EXHAUSTED), one alert per
  threshold per user per window.
- Settings: keys table; HARD LIMIT box shows "DISABLED — observation phase" with no toggle.
- Verified on live data: refresh-stable, restart-idempotent (identical numbers after
  service restart, buzz-acp workers unaffected), percentages match ledger exactly,
  secret scan of all views/JSON APIs clean (no emails, nsec/npub, auth tags; public
  Nostr pubkeys are shown by design as the canonical identity).

## H. Buzz Usage Command

- `/usage` sent as a normal channel mention is intercepted by the gateway BEFORE any AI
  call: zero AI turns, zero tokens. Recorded with `usage_quality='no_ai_call'`,
  `normalized_units=0.0`, `runtime_ms=0`.
- LIVE-VERIFIED (Test B): reply published in-channel matches the dashboard exactly
  (Used 0% ↔ dashboard 0.23% rounded, Requests 2 ↔ 2, same daily window/reset time).
  Normal members see only their own usage; the lookup costs no AI turns.

## I. Live Usage Test (end-to-end: real Buzz → agent → ledger → dashboard)

| # | Test | Trigger event | Agent | Reply event | Units | Runtime | Verdict |
|---|------|---------------|-------|-------------|-------|---------|---------|
| A | Basic turn | `dd4ebe99…` | agy-1 | `12e7816a…` | 7,044 | 6.2 s | PASS |
| B | /usage zero-AI | `7d217fb5…` | agy-1 | `bab0e21c…` | 0 (no_ai_call) | 0 ms | PASS |
| C | Spoof regression | `b82b335d…` | agy-2 | `b1c80fef…` | 15,663 | ~6 s | PASS |
| D1 | Parallel ×5 | `c84c7786…` | claude-cli | `7f3578a0…` | 49,934 | 11.4 s | PASS |
| D2 | Parallel ×5 | `9918080d…` | agy-1 | `892e7180…` | 7,142 | 5.3 s | PASS |
| D3 | Parallel ×5 | `363a13f4…` | agy-2 | `4d202116…` | 7,052 | 4.6 s | PASS |
| D4 | Parallel ×5 | `9b0ce48a…` | agy-3 | `7bdcdd22…` | 7,046 | 4.4 s | PASS |
| D5 | Parallel ×5 | `df9beda4…` | agy-4 | (published) | 7,044 | 4.6 s | PASS |
| E | Model capture | `0e9db0c9…` | claude-cli | `0030d39a…` | 52,491 | ~9 s | PASS |

All rows: channel = Tech `31609c50…`, thread = trigger event, principal = owner
`2da3184b…f0001e` (relay-verified), `usage_quality='actual_harness_reported'`
(B: `no_ai_call`), `cost_usd` NULL, dry-run verdict `WOULD_ALLOW` recorded on each.

## J. Agent Regression (all five through REAL Buzz channel mention)

| Agent | Backend/account | Reply landed | Ledger row | Usage |
|-------|-----------------|--------------|------------|-------|
| Claude CLI | claude binary, own session | Tech, correct thread | completed | actual tokens |
| AGY 1 | isolated account 1 | Tech, correct thread | completed | actual tokens |
| AGY 2 | isolated account 2 | Tech, correct thread | completed | actual tokens |
| AGY 3 | isolated account 3 | Tech, correct thread | completed | actual tokens |
| AGY 4 | isolated account 4 | Tech, correct thread | completed | actual tokens |

No reply leaked into any other channel; no hardcoded channel fallback remains
(the old Tech fallback was removed — routing failures now fail safely and are audited).

## K. Five-Agent Parallel Test

Five mentions sent within ~1 s; all five gateways spawned in the same second and ran
overlapping (first start 12:39:04, last finish 12:39:17). Replies: FIVE, ONE, TWO, THREE,
FOUR — each exactly as instructed, each published in-channel, five distinct completed
ledger rows with five distinct agent_ids and actual per-backend token counts. PASS.

## L. Measurement Quality

- Every completed AI turn carries `usage_quality='actual_harness_reported'` with the
  harness-reported token counts; the gateway's 30-check offline harness
  (identity gating, idempotency states, duplicate no-spend, /usage interception,
  fail-closed identity, failure+retry, all-four-thresholds-once-each) passes ALL.
- Unknowns stay unknown: cost_usd NULL everywhere (no billing authority proven);
  AGY model NULL; provider models with no capacity number are skipped, not invented.
- Prompts are never stored in the ledger (verified by scan of all rows).
- One caveat: the `model` label for Claude CLI turns is captured from `modelUsage`
  (newer CLI builds omit top-level `model`). Rows written by pool workers spawned
  before that fix show model UNKNOWN; the fixed code is verified offline against the
  real CLI JSON shape and loads on the next natural worker spawn. Tokens, units,
  and identity are unaffected.

## M. Current Mode (verified from the live settings table)

- `mode = METER_ONLY` → **ON** (fully operational: every real turn metered, live-verified).
- `warn_only_enabled = 1` → **ON**. Mechanism verified: threshold evaluator fires
  WARNING/HIGH/CRITICAL/EXHAUSTED at 70/85/95/100 exactly once per threshold per user
  per day (offline harness, all four fired once each). No live alert yet — genuine
  usage today is 5.11% of allowance, below the first threshold.
- `hard_limit_enabled = 0` → **OFF** (disabled; dry-run evaluator records
  WOULD_ALLOW/WOULD_BLOCK per turn; RESERVE→EXECUTE→SETTLE reservation API exists
  but enforcement is deliberately not wired to block anything).

## N. What Is Ready Now

1. Relay-verified trusted identity on every turn (fail-closed).
2. Full metering of all five agents with actual harness token counts, idempotent
   and crash-safe (uniqueness via DB constraints; duplicates never double-count).
3. Daily allowance model with owner-assignable levels and correct percentages.
4. AGY provider-capacity polling (separate from user allowance).
5. AI Usage Center dashboard on 127.0.0.1:8787 with all specified views.
6. `/usage` zero-AI member lookup matching the dashboard.
7. Warning delivery pipeline (WARN_ONLY) ready; dry-run hard-limit verdicts recorded.
8. Secret hygiene: no emails/keys/auth tags in logs, ledger, or dashboard.

## O. What Is Deliberately Not Enabled Yet

1. **HARD LIMIT enforcement** — the owner must explicitly enable it later; there is no
   toggle anywhere. Evaluator runs in DRY RUN only.
2. Soft limits (OFF, `soft_limit_enabled=0`).
3. Reservation-based enforcement (API exists; nothing blocks execution).

## P. Files Modified

- `/home/ncthang/.local/bin/buzz-agent-gateway` — extended in place (identity gate,
  fallback removal, usage capture, idempotency, /usage, warnings, ACP usage passthrough).
- `usage-control/lib/ledger.py` — ledger library (new).
- `usage-control/bin/dashboard.py` — AI Usage Center (new).
- `usage-control/bin/capacity_poller.py` — agy-quota poller (new).
- `usage-control/usage.db` — the new ledger (gateway_state.db untouched).
- `~/.config/systemd/user/claude-vision-router.service` — PORT 8787 → 8788
  (freed the mandated dashboard port; service healthy on 8788).

## Q. Services Added

- `buzz-usage-capacity.service` (systemd user, enabled, active)
- `buzz-usage-dashboard.service` (systemd user, enabled, active, 127.0.0.1:8787)

## R. Backup

- `usage-control/backups/20260909-121416/` — original gateway (SHA `8effe29c…`),
  buzz-acp copy, gateway_state.db, managed-agents.json, systemd units, BASELINE.txt.
- `backups/20260909-121416/gateway.log.old-with-emails` (mode 600).

## S. Rollback (one command path)

```bash
# 1. stop + disable the two new services
systemctl --user disable --now buzz-usage-dashboard.service buzz-usage-capacity.service
# 2. restore the original gateway (workers reload lazily on next spawn)
cp ~/.local/share/xyz.block.buzz.app/agents/usage-control/backups/20260909-121416/bin/buzz-agent-gateway ~/.local/bin/
# 3. give the vision router its old port back
sed -i 's/PORT=8788/PORT=8787/' ~/.config/systemd/user/claude-vision-router.service && systemctl --user daemon-reload && systemctl --user restart claude-vision-router.service
# usage.db can simply be deleted (or kept read-only as a record); nothing else depends on it.
```

## T. Final Verdict — STRICT PASS CRITERIA

- **SYSTEM**: PASS — five agents, no agents added/removed/weakened, mappings unchanged,
  buzz-acp/buzz binaries untouched, all five verified through real Buzz mentions.
- **IDENTITY**: PASS — relay-verified pubkey on every live turn; spoof-text regression
  passed (forged headers changed nothing); failures fail closed.
- **USAGE**: PASS — actual harness tokens for all five agents; unknowns NULL;
  cost UNKNOWN (no billing authority); /usage costs zero AI turns.
- **DATABASE**: PASS — idempotent under duplicate delivery (tested), FK-safe,
  append-only events, no prompts stored, local ledger is the source of truth.
- **UI**: PASS — dashboard live on 127.0.0.1:8787, refresh/restart stable, percentages
  match ledger, capacity visually distinct from allowance, hard limit marked DISABLED.
- **BUZZ**: PASS — replies land in the correct channel/thread; /usage reply matches
  dashboard; no reply ever leaked cross-channel.
- **SAFETY**: PASS — no secrets in ledger/logs/dashboard; email leak archived and
  eliminated; production DB contains only genuine turns.

**OVERALL: PASS** — on the required end-to-end evidence: real Buzz mention → real agent →
real harness-reported usage → ledger row → dashboard/`/usage`, verified for every agent,
including concurrency and spoof resistance. Modes: METER_ONLY ON, WARN_ONLY ON
(mechanism verified, thresholds not yet crossed in live traffic), HARD_LIMIT OFF
(awaiting the owner's explicit future decision).