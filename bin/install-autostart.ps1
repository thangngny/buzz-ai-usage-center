# Keep dashboard up:
#  - BuzzUsageDashboardWatch: loop 30s at logon (no time limit, auto-restart)
#  - BuzzUsageDashboard: every 5 min backup if the loop died
$ErrorActionPreference = "Stop"
$Start = Join-Path $PSScriptRoot "start-dashboard.ps1"
$Watch = Join-Path $PSScriptRoot "watch-dashboard.ps1"
$User = $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

# --- persistent loop ---
$watchAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Watch`""
)
$watchSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
Register-ScheduledTask -TaskName "BuzzUsageDashboardWatch" -Action $watchAction -Trigger $tLogon `
    -Settings $watchSettings -Principal $principal -Force | Out-Null

# --- 5-minute backup ---
$kickAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Start`""
)
$kickSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
$tWatch = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)
Register-ScheduledTask -TaskName "BuzzUsageDashboard" -Action $kickAction -Trigger @($tLogon, $tWatch) `
    -Settings $kickSettings -Principal $principal -Force | Out-Null

Write-Output "tasks: BuzzUsageDashboardWatch (logon loop 30s) + BuzzUsageDashboard (every 5 min)"
Get-ScheduledTask -TaskName "BuzzUsageDashboardWatch", "BuzzUsageDashboard" | Select-Object TaskName, State
