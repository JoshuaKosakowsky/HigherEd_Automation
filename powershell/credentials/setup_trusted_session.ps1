param(
    [Parameter(Mandatory)]
    [string]$System,

    [ValidateSet("edge", "chrome")]
    [string]$Browser = "chrome"
)

# Supported systems are defined in
# browser_profiles\setup_trusted_session.py under TRUSTED_SESSION_SYSTEMS.
# Add future websites there; this wrapper delegates validation to Python.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SetupScript = Join-Path $ProjectRoot "browser_profiles\setup_trusted_session.py"

if (-not (Test-Path $PythonExe)) {
    throw "Python virtual environment not found. Run .\setup.ps1 first."
}

if (-not (Test-Path $SetupScript)) {
    throw "Trusted session setup script not found at: $SetupScript"
}

$env:PYTHONPATH = $ProjectRoot

Write-Host ""
Write-Host "Starting trusted browser session setup..."
Write-Host "System:  $System"
Write-Host "Browser: $Browser"
Write-Host ""

& $PythonExe $SetupScript --system $System --browser $Browser

$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    throw "Trusted session setup failed with exit code $ExitCode."
}

Write-Host ""
Write-Host "Trusted session setup complete."
