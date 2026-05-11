param(
    [string]$Mode
)

$ErrorActionPreference = "Stop"

function Get-RunMode {
    while ($true) {

        Write-Host ""
        Write-Host "Select SOAHOLD Run Mode:" -ForegroundColor Cyan
        Write-Host "  [T] Test  - No Banner saves"
        Write-Host "  [D] Debug - Saves enabled with verbose logging"
        Write-Host "  [P] Prod  - LIVE Banner saves" -ForegroundColor Yellow
        Write-Host ""

        $choice = Read-Host "Enter choice"

        switch ($choice.ToUpper()) {

            "T" {
                return "test"
            }

            "D" {
                return "debug"
            }

            "P" {

                Write-Host ""
                Write-Host "WARNING: PROD mode will perform LIVE Banner saves." -ForegroundColor Red

                $confirm = Read-Host "Type YES to continue"

                if ($confirm -eq "YES") {
                    return "prod"
                }

                Write-Host "Production mode cancelled." -ForegroundColor Yellow
            }

            default {
                Write-Host "Invalid choice. Please enter T, D, or P." -ForegroundColor Red
            }
        }
    }
}

if (-not $Mode) {
    $Mode = Get-RunMode
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot

Import-Module (
    Join-Path $ProjectRoot "powershell\modules\common.psm1"
) -Force

$env:PYTHONPATH = $ProjectRoot

$WorkflowName = "SOAHOLD"
$TargetName   = "Banner"
$MutexName    = "SOAHOLD_MUTEX"

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyScript  = Join-Path $ProjectRoot "workflows\soahold\run_soahold.py"
$LogDir    = Join-Path $ProjectRoot "logs\banner\soahold"

$LogFile = New-LogFile `
    -LogDir $LogDir `
    -WorkflowName $WorkflowName

Write-Log -Message "Run started" -LogFile $LogFile
Write-Log -Message "Mode: $Mode" -LogFile $LogFile

$mutex = New-Object System.Threading.Mutex($false, $MutexName)

try {

    if (-not $mutex.WaitOne(0)) {

        Write-Log `
            -Message "Another $WorkflowName run is already in progress. Exiting." `
            -LogFile $LogFile

        exit 0
    }

    Set-SystemCredentialEnvironment `
        -TargetName $TargetName `
        -UserEnvName "BANNER_USER" `
        -PasswordEnvName "BANNER_PASS" `
        -LogFile $LogFile

    $env:SOAHOLD_RUN_MODE = $Mode

    $code = Invoke-PythonScript `
        -PythonExe $PythonExe `
        -ScriptPath $PyScript `
        -LogFile $LogFile `
        -WorkingDirectory $ProjectRoot

    if ($code -ne 0) {

        Write-Log `
            -Message "Run failed with exit code $code" `
            -LogFile $LogFile

        exit $code
    }

    Write-Log `
        -Message "Run finished successfully" `
        -LogFile $LogFile

    exit 0
}
catch {

    Write-Log `
        -Message ("ERROR: {0}" -f $_.Exception.Message) `
        -LogFile $LogFile

    exit 1
}
finally {

    if ($mutex) {
        $mutex.ReleaseMutex() | Out-Null
        $mutex.Dispose()
    }
}