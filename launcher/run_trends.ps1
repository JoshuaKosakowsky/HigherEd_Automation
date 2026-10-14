param(
    [string]$InputDir,
    [string]$OutputFile,
    [string]$DetailCodesFile,
    [string]$FilePattern,
    [switch]$AllowUnmappedDetailCodes,
    [ValidateSet("files", "sql")][string]$Source = "files",
    [int]$FirstFiscalYear,
    [int]$LastFiscalYear,
    [string]$ExtractDir,
    [int]$PageSize = 1000,
    [switch]$ConfirmProd
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

$PythonExe = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw @"
Python environment not found.

Run .\setup.ps1 from the repository root.
"@
}

$Arguments = @(
    "-m"
    "workflows.trends.run_trends"
)

$Arguments += @("--source", $Source, "--page-size", "$PageSize")
if ($FirstFiscalYear) { $Arguments += @("--first-fiscal-year", "$FirstFiscalYear") }
if ($LastFiscalYear) { $Arguments += @("--last-fiscal-year", "$LastFiscalYear") }
if ($ExtractDir) { $Arguments += @("--extract-dir", $ExtractDir) }
if ($ConfirmProd) { $Arguments += "--confirm-prod" }

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
