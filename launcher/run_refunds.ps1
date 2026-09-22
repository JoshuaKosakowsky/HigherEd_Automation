[CmdletBinding()]
param(
    [ValidatePattern('^\d{6}$')]
    [string]$TargetTerm,
    [ValidatePattern('^\d{6}$')]
    [string]$PreviousTerm,
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$RunDate,
    [ValidateRange(1, 1000)]
    [int]$BatchCount = 20,
    [string]$Cwid,
    [string]$ExtractDir,
    [string]$OutputFile,
    [string]$TransactionsFile,
    [string]$ContextFile,
    [switch]$Resume,
    [switch]$Offline,
    [ValidateSet("edge", "chrome")]
    [string]$Browser = "chrome",
    [switch]$FreshLogin
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Python environment not found. Run .\setup.ps1 from the repository root."
}

$arguments = @("-m", "workflows.refunds.run_refunds", "--batch-count", $BatchCount)
foreach ($option in @(
    @{ Bound = "TargetTerm"; Name = "--target-term"; Value = $TargetTerm },
    @{ Bound = "PreviousTerm"; Name = "--previous-term"; Value = $PreviousTerm },
    @{ Bound = "RunDate"; Name = "--run-date"; Value = $RunDate },
    @{ Bound = "Cwid"; Name = "--cwid"; Value = $Cwid },
    @{ Bound = "ExtractDir"; Name = "--extract-dir"; Value = $ExtractDir },
    @{ Bound = "OutputFile"; Name = "--output-file"; Value = $OutputFile },
    @{ Bound = "TransactionsFile"; Name = "--transactions-file"; Value = $TransactionsFile },
    @{ Bound = "ContextFile"; Name = "--context-file"; Value = $ContextFile }
)) {
    if ($PSBoundParameters.ContainsKey($option.Bound)) {
        $arguments += @($option.Name, $option.Value)
    }
}
$arguments += @("--browser", $Browser)
if ($Resume) { $arguments += "--resume" }
if ($Offline) { $arguments += "--offline" }
if ($FreshLogin) { $arguments += "--fresh-login" }

Push-Location $projectRoot
try {
    & $pythonExecutable @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
