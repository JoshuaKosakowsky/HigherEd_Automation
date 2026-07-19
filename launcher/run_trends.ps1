param(
    [string]$InputDir,
    [string]$OutputFile,
    [string]$DetailCodesFile,
    [string]$FilePattern,
    [switch]$AllowUnmappedDetailCodes
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

$PythonExe = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

$PyScript = Join-Path `
    $ProjectRoot `
    "workflows\trends\run_trends.py"

if (-not (Test-Path $PythonExe)) {
    throw @"
Python environment not found.

Run .\setup.ps1 from the repository root.
"@
}

$env:PYTHONPATH = $ProjectRoot

$Arguments = @(
    $PyScript
)

if ($InputDir) {
    $Arguments += @(
        "--input-dir",
        $InputDir
    )
}

if ($OutputFile) {
    $Arguments += @(
        "--output-file",
        $OutputFile
    )
}

if ($DetailCodesFile) {
    $Arguments += @(
        "--detail-codes-file",
        $DetailCodesFile
    )
}

if ($FilePattern) {
    $Arguments += @(
        "--file-pattern",
        $FilePattern
    )
}

if ($AllowUnmappedDetailCodes) {
    $Arguments += "--allow-unmapped-detail-codes"
}

Push-Location $ProjectRoot

try {
    & $PythonExe @Arguments

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}