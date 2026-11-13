# Start dashboard on 127.0.0.1:8787 if down.
# Idempotent: safe to run every 30s from watch-dashboard.ps1.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Py = "C:\Users\Admin\marketing-ai-system\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Py = $cmd.Source }
}

function Test-Dash {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (-not (Test-Dash)) {
    Start-Process -FilePath $Py -ArgumentList "bin\dashboard.py" -WorkingDirectory $Root -WindowStyle Hidden
    $ok = $false
    foreach ($i in 1..25) {
        Start-Sleep -Seconds 1
        if (Test-Dash) { $ok = $true; break }
    }
    if (-not $ok) {
        Write-Error "dashboard did not come up on 8787"
        exit 1
    }
}

# Check Cloudflare tunnel
$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    & $Py "$Root\bin\run_public_tunnel.py" | Out-Null
}

Write-Output "local  http://127.0.0.1:8787"

