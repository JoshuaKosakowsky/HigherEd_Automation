param (
    [ValidatePattern('^\d{6}$')]
    [string]$TermCode
)

$ErrorActionPreference = "Stop"

$workflowLauncher = Join-Path `
    $PSScriptRoot `
    "run_textbook_brokers.ps1"

if (-not (Test-Path -LiteralPath $workflowLauncher -PathType Leaf)) {
    throw "Textbook Brokers workflow launcher was not found: $workflowLauncher"
}

$workflowParameters = @{
    ArchiveOnly = $true
}

if (-not [string]::IsNullOrWhiteSpace($TermCode)) {
    $workflowParameters.TermCode = $TermCode
}

& $workflowLauncher @workflowParameters
