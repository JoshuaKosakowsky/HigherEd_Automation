$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TaskName = "HigherEd Automation - Expire Insights Session"
$Description = (
    "Revokes and removes the current user's cached Ellucian " +
    "Insights session each day."
)

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python virtual environment not found. Run .\setup.ps1 first."
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m workflows.insights_api_test.run_insights_test --logout" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At "12:00 AM"
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentIdentity `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description $Description `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Force | Out-Null

Write-Host "Insights session cleanup task installed." -ForegroundColor Green
Write-Host "Task: $TaskName"
Write-Host "Schedule: Daily at midnight (or next available sign-in if missed)"
