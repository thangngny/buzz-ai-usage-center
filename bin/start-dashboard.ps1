# Start dashboard on 127.0.0.1:8787 if down, then attach Tailscale Funnel :8443.
# Idempotent: safe to run every 30s from watch-dashboard.ps1.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
# python.exe (not pythonw): pythonw hid crashes and the start script thought 8787 was dead.
$Py = "C:\Python314\python.exe"
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

function PublicUrl {
    try {
        $j = tailscale status --json | ConvertFrom-Json
        $dns = [string]$j.Self.DNSName
        if ($dns) { return ("https://{0}:8443" -f $dns.TrimEnd(".")) }
    } catch {}
    return "https://trungthu.tailc0eb7b.ts.net:8443"
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

& tailscale funnel --bg --https=8443 --yes 8787 | Out-Null
$pub = PublicUrl
Write-Output "local  http://127.0.0.1:8787"
Write-Output "public $pub"
