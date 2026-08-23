$ErrorActionPreference = "Stop"

$workflowLauncher = Join-Path `
    $PSScriptRoot `
    "run_textbook_brokers.ps1"

if (-not (Test-Path -LiteralPath $workflowLauncher -PathType Leaf)) {
    throw "Textbook Brokers workflow launcher was not found: $workflowLauncher"
}

& $workflowLauncher -ArchiveOnly
