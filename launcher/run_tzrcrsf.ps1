$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

Import-Module (
    Join-Path $ProjectRoot "powershell\modules\common.psm1"
) -Force

$env:PYTHONPATH = $ProjectRoot

$WorkflowName = "TZRCRSF"
$TargetName   = "Banner"
$MutexName    = "TZRCRSF_MUTEX"

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyScript  = Join-Path $ProjectRoot "workflows\tzrcrsf\run_tzrcrsf.py"
$LogDir    = Join-Path $ProjectRoot "logs\banner\tzrcrsf"

$LogFile = New-LogFile `
    -LogDir $LogDir `
    -WorkflowName $WorkflowName

Write-Log -Message "Run started" -LogFile $LogFile

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
    Write-Log -Message ("ERROR: {0}" -f $_.Exception.Message) -LogFile $LogFile
    exit 1
}
finally {
    if ($mutex) {
        $mutex.ReleaseMutex() | Out-Null
        $mutex.Dispose()
    }
}