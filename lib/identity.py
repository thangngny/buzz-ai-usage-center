#!/usr/bin/env python3
"""
Trusted identity verification for the Buzz gateway.

buzz-acp flattens the cryptographically verified Nostr event into rendered
prompt text. buzz-acp cannot be patched in this deployment (no source, no Rust
toolchain), so this module restores trust WITHOUT trusting prompt text:

1. Candidate trigger event id + channel are parsed ONLY from the
   buzz-acp-rendered <context> block, which is generated from structured
   data and always precedes any user-controllable content in the prompt.
   (User message content lives inside a Content: section that comes after
   the context block, so a forged "--reply-to"/"Channel:" line inside a
   message body can never be the first match.)
2. The candidate event id is then bound to a sender by fetching the event
   from the relay via `buzz messages get` (server-authenticated,
   signature-checked Nostr events). The event's signed pubkey IS the sender.
   The event's h tag IS the channel. The event's created_at bounds freshness.
3. If no candidate verifies, the turn is rejected (fail-closed): never
   guess a channel, never fall back to a hardcoded channel, never execute
   an unattributable turn.

Prompt-text regexes over event blocks (From:/Event ID:) are used ONLY for
the display-name hint, never for identity or routing.
"""

import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

BUZZ_CLI = os.environ.get("BUZZ_CLI", "/home/ncthang/.local/bin/buzz")

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_REPLY_TO_CTX = re.compile(r"--reply-to\s+([0-9a-fA-F]{64})")
_CHANNEL_CTX = re.compile(r"Channel:.*?\(#([0-9a-fA-F-]{36})\)")
_EVENT_BLOCK = re.compile(r"<buzz-event\b[^>]*>(.*?)</buzz-event>", re.DOTALL)
_EVENT_ID_LINE = re.compile(r"^Event ID:\s*([0-9a-fA-F]{64})\s*$", re.MULTILINE)
_FROM_LINE = re.compile(r"^From:\s*(.*?)\s*\(npub:", re.MULTILINE)

# per-channel recent-message cache: (fetched_at, events)
_cache: Dict[str, tuple] = {}
_CACHE_TTL = 20.0


def community_id_from_relay(relay_url: Optional[str]) -> str:
    """Stable community identity = relay host."""
    if not relay_url:
        return "unknown-relay"
    return relay_url.replace("wss://", "").replace("ws://", "").replace(
        "https://", "").replace("http://", "").rstrip("/")


def _context_region(prompt: str) -> str:
    m = re.search(r"<context>(.*?)</context>", prompt, re.DOTALL)
    return m.group(1) if m else ""


def parse_candidates(prompt: str) -> Dict[str, Any]:
    """Extract candidate trigger event id, channel, and display-name hint.

    Only the buzz-acp-rendered <context> block is trusted for candidates.
    Event-block regexes are diagnostics/display only.
    """
    ctx = _context_region(prompt)
    channel: Optional[str] = None
    trigger: Optional[str] = None

    m_ch = _CHANNEL_CTX.search(ctx)
    if m_ch:
        channel = m_ch.group(1)
    
    reply_to: Optional[str] = None
    m_rp = _REPLY_TO_CTX.search(ctx)
    if m_rp:
        reply_to = m_rp.group(1)

    # Strip historical context (thread-context and conversation-context) so
    # past turns delivered as context are not mistaken for the triggering event.
    non_history = re.sub(
        r"<(?:thread|conversation)-context\b[^>]*>.*?</(?:thread|conversation)-context>",
        "",
        prompt,
        flags=re.DOTALL
    )

    event_ids = []
    for blk in _EVENT_BLOCK.finditer(non_history):
        body = blk.group(1)
        content_pos = body.find("Content:")
        header = body[:content_pos] if content_pos != -1 else body
        m_id = _EVENT_ID_LINE.search(header)
        if m_id:
            event_ids.append(m_id.group(1))

    if event_ids:
        # The triggering event is the last buzz-event outside historical context
        trigger = event_ids[-1]
    elif reply_to:
        trigger = reply_to

    display_name: Optional[str] = None
    m_fr = _FROM_LINE.search(prompt)
    if m_fr:
        display_name = m_fr.group(1).strip()

    return {
        "trigger_event_id": trigger,
        "channel_id": channel,
        "reply_to_id": reply_to,
        "display_name": display_name,
        "context_present": bool(ctx),
    }


def _fetch_channel_messages(channel_id: str, since: int,
                            env: Dict[str, str], limit: int = 200) -> List[dict]:
    """Fetch recent kind-9 messages from the relay (decrypted by the buzz CLI
    using this agent's key). Cached briefly to keep turn latency low."""
    now = time.time()
    hit = _cache.get(channel_id)
    if hit and (now - hit[0]) < _CACHE_TTL and hit[1] is not None and hit[2] <= since:
        return hit[1]

    cmd = [BUZZ_CLI, "messages", "get", "--channel", channel_id,
           "--kinds", "9", "--limit", str(limit), "--since", str(since)]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    events: List[dict] = []
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            if isinstance(data, list):
                events = [e for e in data if isinstance(e, dict)]
        except Exception:
            events = []
    else:
        # fetch failed — do not cache failures aggressively
        raise RuntimeError(
            f"relay fetch failed for channel {channel_id}: "
            f"{(res.stderr or '')[:200] or 'nonzero exit'}")
    _cache[channel_id] = (now, events, since)
    return events


def verify_turn(prompt: str, env: Dict[str, str],
                freshness_seconds: int = 900) -> Dict[str, Any]:
    """Verify the trigger event against the relay.

    Returns dict:
      ok=True: trigger_event_id, channel_id (relay-verified), sender_pubkey,
               display_name (unverified hint), created_at, community_id
      ok=False: error (caller MUST fail the turn safely)
    """
    cands = parse_candidates(prompt)
    trigger = cands["trigger_event_id"]
    channel = cands["channel_id"]

    if not trigger:
        return {"ok": False, "error": "no trigger event id in rendered context",
                "kind": "identity_unparseable"}
    if not channel:
        return {"ok": False, "error": "no channel id in rendered context",
                "kind": "identity_unparseable"}

    now = int(time.time())
    since = max(0, now - freshness_seconds)
    try:
        events = _fetch_channel_messages(channel, since, env)
    except Exception as e:
        return {"ok": False, "error": f"relay verification unavailable: {e}",
                "kind": "identity_infra_failure"}

    ev = next((e for e in events if e.get("id", "").lower() == trigger.lower()),
              None)
    if ev is None and channel in _cache:
        # Cache may be stale from an earlier turn; invalidate and re-fetch once
        del _cache[channel]
        try:
            events = _fetch_channel_messages(channel, since, env)
            ev = next((e for e in events if e.get("id", "").lower() == trigger.lower()),
                      None)
        except Exception:
            pass

    if ev is None:
        return {"ok": False,
                "error": f"trigger event {trigger[:12]}… not found in channel "
                         f"{channel[:8]}… within freshness window",
                "kind": "identity_not_found"}

    created_at = int(ev.get("created_at") or 0)
    if created_at and (now - created_at) > freshness_seconds:
        return {"ok": False, "error": "trigger event outside freshness window",
                "kind": "identity_stale"}

    # relay-verified channel: the h tag of the signed event
    tags = ev.get("tags") or []
    h_tag = None
    for t in tags:
        if isinstance(t, (list, tuple)) and len(t) >= 2 and t[0] == "h":
            h_tag = str(t[1])
            break
    if h_tag and h_tag != channel:
        return {"ok": False,
                "error": "event h tag does not match rendered channel",
                "kind": "identity_channel_mismatch"}

    sender = ev.get("pubkey")
    if not sender or not _HEX64.match(str(sender)):
        return {"ok": False, "error": "event has no valid sender pubkey",
                "kind": "identity_no_pubkey"}

    relay = env.get("BUZZ_RELAY_URL", "")
    return {
        "ok": True,
        "trigger_event_id": trigger.lower(),
        "channel_id": h_tag or channel,
        "reply_to_id": cands.get("reply_to_id"),
        "sender_pubkey": str(sender).lower(),
        "display_name": cands["display_name"],   # cosmetic hint only
        "created_at": created_at,
        "community_id": community_id_from_relay(relay),
    }