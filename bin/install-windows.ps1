# ==============================================================================
# 🚀 BUZZ DESKTOP ECOSYSTEM & UI ENHANCER — WINDOWS NATIVE INSTALLER
# ==============================================================================
# PowerShell 5.1 / 7+ compatible automated installer for Windows Native
# ==============================================================================
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $PSScriptRoot
$AppData = "$env:APPDATA\xyz.block.buzz.app"
$LocalData = "$env:LOCALAPPDATA\xyz.block.buzz.app"
$ConfigDir = "$env:USERPROFILE\.config\buzz"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   ⚡ BUZZ DESKTOP ENHANCER & ECOSYSTEM SUITE — WINDOWS INSTALLER     " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Check Python
$PyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PyCmd) {
    Write-Error "Python 3 is required on Windows. Please install Python from https://python.org or Microsoft Store."
    exit 1
}
Write-Host "✓ Python detected: $(& python --version)" -ForegroundColor Green

# 2. Setup directories
New-Item -ItemType Directory -Path "$AppData\sounds" -Force | Out-Null
New-Item -ItemType Directory -Path "$AppData\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "$ConfigDir" -Force | Out-Null
Write-Host "✓ Created directories in $AppData" -ForegroundColor Green

# 3. Copy assets & notifier
Copy-Item -Path "$ScriptDir\desktop-enhancer\buzz_ui_enhancer.js" -Destination "$AppData\buzz_ui_enhancer.js" -Force
Copy-Item -Path "$ScriptDir\desktop-enhancer\buzz_sound_notifier.py" -Destination "$AppData\buzz_sound_notifier.py" -Force
if (Test-Path "$ScriptDir\desktop-enhancer\sounds") {
    Copy-Item -Path "$ScriptDir\desktop-enhancer\sounds\*" -Destination "$AppData\sounds\" -Recurse -Force
}
if (Test-Path "$ScriptDir\desktop-enhancer\chime_default.wav") {
    Copy-Item -Path "$ScriptDir\desktop-enhancer\chime_default.wav" -Destination "$AppData\chime_default.wav" -Force
}
Write-Host "✓ Deployed UI Enhancer and Sound Assets" -ForegroundColor Green

# 4. Sound configuration
$CfgFile = "$ConfigDir\sound-notifier.json"
if (-not (Test-Path $CfgFile)) {
    @{
        enabled = $true
        sound_message = "$AppData\sounds\elevenlabs_thang.wav"
        sound_mention = "$AppData\sounds\mention.wav"
        show_desktop_notification = $true
    } | ConvertTo-Json -Depth 3 | Set-Content -Path $CfgFile -Encoding UTF8
    Write-Host "✓ Initialized sound configuration in $CfgFile" -ForegroundColor Green
}

# 5. Register Windows Scheduled Tasks for Autostart
$AutostartScript = Join-Path $PSScriptRoot "install-autostart.ps1"
if (Test-Path $AutostartScript) {
    Write-Host "🔨 Registering Windows Scheduled Tasks..." -ForegroundColor Blue
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$AutostartScript"
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "   🎉 BUZZ ECOSYSTEM INSTALLED SUCCESSFULLY ON WINDOWS!               " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "• Local Dashboard: http://127.0.0.1:8787" -ForegroundColor Yellow
Write-Host "• Run diagnostic : python bin\agent-doctor.py --verify" -ForegroundColor Yellow
Write-Host ""
