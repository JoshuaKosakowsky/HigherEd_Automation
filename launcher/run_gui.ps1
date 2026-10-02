[CmdletBinding()]
param(
    [switch]$Console
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$windowedPython = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"


function Show-GuiLaunchError {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    if ($Console) {
        Write-Host $Message -ForegroundColor Red
        return
    }

    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        $Message,
        "Mines Bursar Automation",
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
}


try {
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw @"
The automation environment has not been set up.

Open PowerShell in this repository and run:
    .\setup.ps1
"@
    }

    Push-Location $projectRoot
    try {
        $diagnosticsDirectory = Join-Path $env:LOCALAPPDATA "HigherEdAutomation"
        New-Item -ItemType Directory -Path $diagnosticsDirectory -Force | Out-Null
        $diagnosticsPath = Join-Path $diagnosticsDirectory "gui-runtime-check.log"
        # Validate native plugin initialization before starting pythonw, whose
        # startup errors would otherwise be invisible to the employee.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            # Windows PowerShell 5.1 treats redirected native stderr as error
            # records. Qt's useful debug messages are not themselves failures.
            $ErrorActionPreference = "Continue"
            & $pythonExecutable -m app.gui.runtime_check *> $diagnosticsPath
            $runtimeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($runtimeExitCode -ne 0) {
            throw @"
The desktop runtime could not start. Close automation programs, open PowerShell in this repository, and run:
    .\setup.ps1 -RepairGui

Diagnostic log for IT: $diagnosticsPath
"@
        }

        if ($Console) {
            & $pythonExecutable -m app.gui.main
            if ($LASTEXITCODE -ne 0) {
                throw "The application exited with code $LASTEXITCODE."
            }
        }
        else {
            if (-not (Test-Path -LiteralPath $windowedPython -PathType Leaf)) {
                throw "Windowed Python was not found: $windowedPython"
            }

            Start-Process `
                -FilePath $windowedPython `
                -ArgumentList @("-m", "app.gui.main") `
                -WorkingDirectory $projectRoot
        }
    }
    finally {
        Pop-Location
    }
}
catch {
    Show-GuiLaunchError -Message $_.Exception.Message
    exit 1
}
