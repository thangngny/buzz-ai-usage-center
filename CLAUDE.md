# Claude Code Directives — Buzz Ecosystem Suite

See comprehensive operational manual in [AGENTS.md](AGENTS.md).

## Quickstart Commands
- **Diagnostic:** `python3 bin/agent-doctor.py --json`
- **Auto-install:** `python3 bin/agent-doctor.py --install`
- **Verify:** `python3 bin/agent-doctor.py --verify`

## Core Invariants
1. Non-invasive `LD_PRELOAD` architecture on Linux/WSL; WebView2 on Windows.
2. Dynamic `$HOME` and `%USERPROFILE%` paths everywhere (never hardcode usernames).
3. Port 8787 must have `allow_reuse_address = True`.
4. Never commit `.env`, `usage.db`, or Nostr private keys.
