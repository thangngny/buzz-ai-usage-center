#!/usr/bin/env python3
"""
AGY account capacity poller for the usage-control ledger.

Runs `agy-quota --json` periodically and appends per-account per-model
remaining_percent snapshots into usage.db (account_capacity_snapshots).

Security notes:
- AGY account emails are matched INTERNALLY against the fixed gateway
  mapping and are NEVER written to the ledger, logs, or stdout.
- The ledger stores only gateway agent labels (agy-1..agy-4).
- This measures PROVIDER/ACCOUNT CAPACITY — a completely separate quantity
  from user allowance percentages. The two are never mixed.

Provider capacity is distinct from user allowance: capacity answers "how
much does this AGY account have left", allowance answers "how much of a
user's allocated share is consumed".
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import analytics  # noqa: E402
import ledger  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGY_QUOTA = os.environ.get("AGY_QUOTA_BIN", "/home/ncthang/.local/bin/agy-quota")

# Fixed gateway account mapping (must mirror buzz-agent-gateway; emails never logged).
# Real addresses live outside version control: set AGY_ACCOUNT_MAP to inline JSON,
# or keep them in agy-accounts.json next to the repo root (git-ignored).
# See agy-accounts.example.json for the expected shape.
ACCOUNT_MAP_FILE = os.environ.get(
    "AGY_ACCOUNT_MAP_FILE", os.path.join(REPO_ROOT, "agy-accounts.json"))


def _load_email_to_agent() -> dict:
    raw = os.environ.get("AGY_ACCOUNT_MAP")
    if not raw:
        try:
            with open(ACCOUNT_MAP_FILE, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items() if k and v}


EMAIL_TO_AGENT = _load_email_to_agent()

POLL_FAILURE_LOG = os.path.join(REPO_ROOT, "capacity_poller.log")


def plog(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(POLL_FAILURE_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def poll_once() -> int:
    res = subprocess.run([AGY_QUOTA, "--json"], capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        plog(f"agy-quota failed (code {res.returncode})")
        return 0
    try:
        data = json.loads(res.stdout)
    except Exception as e:
        plog(f"agy-quota output not JSON: {e}")
        return 0

    total = 0
    for acct in data.get("accounts", []):
        email = acct.get("email") or ""
        agent_id = EMAIL_TO_AGENT.get(email.lower())
        if not agent_id:
            # Unknown account: record nothing, leak nothing
            plog("skipping account not in fixed gateway mapping")
            continue
        rows = []
        for m in acct.get("models", []):
            if m.get("remaining_percent") is None:
                continue  # unknown stays unknown — never invent a number
            rows.append({
                "model": m.get("name"),
                "remaining_percent": m.get("remaining_percent"),
                "reset_at": m.get("reset_at"),
            })
        if rows:
            total += ledger.record_capacity_snapshots(agent_id, rows)
    # owner Alert Center: low capacity / sharp drops (deduplicated per day)
    try:
        analytics.record_capacity_alerts()
    except Exception as e:
        plog(f"capacity alert scan error (continuing): {e}")
    return total


def main():
    ledger.init_db()
    interval = int(ledger.get_setting("capacity_poll_interval_seconds", "600"))
    once = "--once" in sys.argv
    plog(f"capacity poller start (interval={interval}s, once={once})")
    if not EMAIL_TO_AGENT:
        plog("no gateway account mapping configured "
             f"(set AGY_ACCOUNT_MAP or create {ACCOUNT_MAP_FILE}); "
             "every account will be skipped")
    while True:
        try:
            n = poll_once()
            if n:
                plog(f"recorded {n} capacity snapshots")
        except Exception as e:
            plog(f"poll error (continuing): {e}")
        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()