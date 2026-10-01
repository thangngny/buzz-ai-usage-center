# Persistent watchdog: keep dashboard + Funnel 8443 up.
# Run at Windows logon (task BuzzUsageDashboardWatch). Loops until logoff.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Start = Join-Path $PSScriptRoot "start-dashboard.ps1"
$Log = Join-Path $Root "dashboard-watch.log"

function Wlog($m) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    try { Add-Content -Path $Log -Value $line -Encoding UTF8 } catch {}
}

Wlog "watchdog start"
while ($true) {
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Start | Out-Null
    } catch {
        Wlog ("start-dashboard error: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds 30
}
