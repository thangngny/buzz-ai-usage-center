# Start Cloudflare Tunnel for AI Usage Center Dashboard
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Cloudflared = "C:\Users\Admin\.buzz\tools\cloudflared.exe"

if (-not (Test-Path $Cloudflared)) {
    Write-Error "cloudflared.exe not found at $Cloudflared"
    exit 1
}

# Check if dashboard is up
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 3
} catch {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\start-dashboard.ps1"
}

# Start tunnel process
Start-Process -FilePath $Cloudflared -ArgumentList "tunnel --url http://127.0.0.1:8787" -WorkingDirectory $Root
