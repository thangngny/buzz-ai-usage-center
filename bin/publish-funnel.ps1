# Expose the local dashboard (127.0.0.1:8787) on Tailscale Funnel port 8443.
# 443 is already used by /, /dim0, /fairies. 10000 is already used.
# Public URL: https://admin-pc-1.tailc0eb7b.ts.net:8443
# This replaces any previous serve/funnel mapping on 8443.
$ErrorActionPreference = "Stop"
tailscale funnel --bg --https=8443 --yes 8787
tailscale funnel status
