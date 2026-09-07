[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path `
    $repositoryRoot `
    ".venv\Scripts\python.exe"
$pythonTestDirectory = Join-Path `
    $PSScriptRoot `
    "python"
$bannerTermTests = Join-Path `
    $PSScriptRoot `
    "powershell\banner_term.tests.ps1"
$fiscalPeriodTests = Join-Path `
    $PSScriptRoot `
    "powershell\fiscal_period.tests.ps1"
$reportFilingTests = Join-Path `
    $PSScriptRoot `
    "powershell\report_filing.tests.ps1"
$tkRuntimeTests = Join-Path `
    $PSScriptRoot `
    "powershell\tk_runtime.tests.ps1"

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw @"
Python environment not found:
$pythonExecutable

Run .\setup.ps1 from the repository root, then try again.
"@
}

if (-not (Test-Path -LiteralPath $pythonTestDirectory -PathType Container)) {
    throw "Python test directory not found: $pythonTestDirectory"
}

if (-not (Test-Path -LiteralPath $bannerTermTests -PathType Leaf)) {
    throw "Banner term test script not found: $bannerTermTests"
}

if (-not (Test-Path -LiteralPath $fiscalPeriodTests -PathType Leaf)) {
    throw "Fiscal-period test script not found: $fiscalPeriodTests"
}

if (-not (Test-Path -LiteralPath $reportFilingTests -PathType Leaf)) {
    throw "Report-filing test script not found: $reportFilingTests"
}

if (-not (Test-Path -LiteralPath $tkRuntimeTests -PathType Leaf)) {
    throw "Tk runtime test script not found: $tkRuntimeTests"
}

Write-Host ""
Write-Host "HigherEd Automation Tests" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan

Push-Location $repositoryRoot

try {
    Write-Host ""
    Write-Host "[1/5] Running Python tests" -ForegroundColor Cyan

    & $pythonExecutable `
        -m unittest discover `
        -s $pythonTestDirectory `
        -v

    if ($LASTEXITCODE -ne 0) {
        throw "Python tests failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "[2/5] Running Banner term tests" -ForegroundColor Cyan

    & $bannerTermTests

    Write-Host ""
    Write-Host "[3/5] Running fiscal-period tests" -ForegroundColor Cyan

    & $fiscalPeriodTests

    Write-Host ""
    Write-Host "[4/5] Running report-filing tests" -ForegroundColor Cyan

    & $reportFilingTests

    Write-Host ""
    Write-Host "[5/5] Running Tk runtime tests" -ForegroundColor Cyan

    & $tkRuntimeTests
}
catch {
    Write-Host ""
    Write-Host "TESTS FAILED" -ForegroundColor Red
    Write-Host "============" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "ALL TESTS PASSED" -ForegroundColor Green
Write-Host "================" -ForegroundColor Green
