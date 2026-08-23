[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path `
    $repositoryRoot `
    "launcher\run_report_filing_watcher.ps1"
$configurationPath = Join-Path `
    $repositoryRoot `
    "config\report_filing.psd1"
$modulePath = Join-Path `
    $repositoryRoot `
    "workflows\report_filing\report_filing.psm1"
$userSettingsScript = Join-Path `
    $repositoryRoot `
    "shared\user_settings.ps1"
$taskName = "HigherEd Automation - Cashier Report Filing Watcher"

foreach ($requiredPath in @(
    $launcherPath,
    $configurationPath,
    $modulePath,
    $userSettingsScript
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required watcher file was not found: $requiredPath"
    }
}

. $userSettingsScript
$userSettings = Read-AutomationUserSettings
Import-Module $modulePath -Force
$configuration = Get-ReportFilingConfiguration -Path $configurationPath

$powerShellExecutableName = if ($PSVersionTable.PSEdition -eq "Core") {
    "pwsh.exe"
}
else {
    "powershell.exe"
}
$powerShellExecutable = Join-Path $PSHOME $powerShellExecutableName

if (-not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)) {
    throw "The current PowerShell executable could not be identified."
}

$windowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if ([string]::IsNullOrWhiteSpace($windowsIdentity)) {
    throw "The current Windows account could not be identified."
}

$actionArguments = (
    '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f `
        $launcherPath
)
$action = New-ScheduledTaskAction `
    -Execute $powerShellExecutable `
    -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $windowsIdentity
$principal = New-ScheduledTaskPrincipal `
    -UserId $windowsIdentity `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([timespan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description (
        "Watches the signed-in user's Downloads folder for configured " +
        "Cashier reports and requests confirmation before filing them."
    )

$existingTask = Get-ScheduledTask `
    -TaskName $taskName `
    -ErrorAction SilentlyContinue

if ($null -ne $existingTask) {
    Stop-ScheduledTask `
        -TaskName $taskName `
        -ErrorAction SilentlyContinue
}

Register-ScheduledTask `
    -TaskName $taskName `
    -InputObject $task `
    -Force |
    Out-Null

Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "REPORT FILING WATCHER INSTALLED" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host "Windows account: $windowsIdentity"
Write-Host "Default name: $($userSettings.DisplayName)"
Write-Host "Default initials: $($userSettings.Initials)"
Write-Host "Scheduled task: $taskName"
Write-Host ""
Write-Host "The watcher is now running in the background."
Write-Host "Unrelated downloads are ignored without a notification."
Write-Host ""

$placeholderReports = @(
    $configuration.Reports |
        Where-Object {
            [string]$_.SourceFilePattern -like "PLACEHOLDER_*"
        }
)

if ($placeholderReports.Count -gt 0) {
    Write-Host "IMPORTANT: The report filename is still a placeholder." -ForegroundColor Yellow
    Write-Host "The watcher will remain quiet until this setting is updated:"
    Write-Host $configurationPath
    Write-Host ""
    Write-Host "Current placeholder: $($placeholderReports[0].SourceFilePattern)"
}
