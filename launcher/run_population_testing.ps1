param(
    [double]$SamplePercent,
    [string[]]$Staff,
    [string]$InputFile,
    [string]$OutputFile
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

$PythonExe = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\python.exe"

$PyScript = Join-Path `
    $ProjectRoot `
    "workflows\population_testing\run_population_testing.py"

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

if (
    $PSBoundParameters.ContainsKey(
        "SamplePercent"
    )
) {
    $Arguments += @(
        "--sample-percent",
        $SamplePercent
    )
}

if ($Staff) {
    $Arguments += "--staff"
    $Arguments += $Staff
}

if ($InputFile) {
    $Arguments += @(
        "--input-file",
        $InputFile
    )
}

if ($OutputFile) {
    $Arguments += @(
        "--output-file",
        $OutputFile
    )
}

Push-Location $ProjectRoot

try {
    & $PythonExe @Arguments

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}