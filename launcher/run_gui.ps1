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
