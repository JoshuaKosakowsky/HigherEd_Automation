[CmdletBinding()]
param([switch]$CheckScans)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ($CheckScans) {
    $pythonWindowless = Join-Path $repositoryRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) {
        throw "Run setup.ps1 to install the check scan dependencies first."
    }
    $taskName = "HigherEd Automation - PaperCut Check Scans - $env:USERNAME"
    $action = New-ScheduledTaskAction -Execute $pythonWindowless `
        -Argument "-m workflows.check_scanning.watch" -WorkingDirectory $repositoryRoot
    $description = "Prepares PaperCut check scans for the current user's review. Shared filing requires cashier approval."
}
else {
    $launcherPath = Join-Path `
        $repositoryRoot `
        "launcher\run_report_filing_watcher.ps1"
    $configurationPath = Join-Path `
        $repositoryRoot `
        "config\report_filing.psd1"
    $modulePath = Join-Path `
        $repositoryRoot `
        "workflows\report_filing\report_filing.psm1"
    $jpmlbRunnerPath = Join-Path `
        $repositoryRoot `
        "workflows\jpmlb\run_jpmlb.py"
    $pythonExecutablePath = Join-Path `
        $repositoryRoot `
        ".venv\Scripts\python.exe"
    $userSettingsScript = Join-Path `
        $repositoryRoot `
        "shared\user_settings.ps1"
    $taskName = "HigherEd Automation - Cashier Report Filing Watcher"

    foreach ($requiredPath in @(
        $launcherPath,
        $configurationPath,
        $modulePath,
        $jpmlbRunnerPath,
        $pythonExecutablePath,
        $userSettingsScript
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Required watcher file was not found: $requiredPath"
        }
    }

    Write-Output 'HIGHERED_PROGRESS={"stage":"Loading report watcher configuration"}'
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

    $actionArguments = (
        '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f `
            $launcherPath
    )
    $action = New-ScheduledTaskAction -Execute $powerShellExecutable -Argument $actionArguments
    $description = "Watches the signed-in user's Downloads folder for configured Cashier reports and requests confirmation before processing them."
}

$windowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if ([string]::IsNullOrWhiteSpace($windowsIdentity)) {
    throw "The current Windows account could not be identified."
}

Write-Output 'HIGHERED_PROGRESS={"stage":"Configuring the current-user watcher task"}'
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
    -Description $description

$existingTask = Get-ScheduledTask `
    -TaskName $taskName `
    -ErrorAction SilentlyContinue

if ($null -ne $existingTask) {
    Stop-ScheduledTask `
        -TaskName $taskName `
        -ErrorAction SilentlyContinue
}

Write-Output 'HIGHERED_PROGRESS={"stage":"Registering the report watcher task"}'
Register-ScheduledTask `
    -TaskName $taskName `
    -InputObject $task `
    -Force |
    Out-Null

Write-Output 'HIGHERED_PROGRESS={"stage":"Starting the report watcher"}'
Start-ScheduledTask -TaskName $taskName

if ($CheckScans) {
    Write-Host "PaperCut check scan watcher installed for $windowsIdentity."
    return
}

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
