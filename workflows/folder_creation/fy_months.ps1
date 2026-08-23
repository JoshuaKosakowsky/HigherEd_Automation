param(
    [ValidateRange(2000, 2200)]
    [int]$FiscalYear
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fiscalPeriodScript = Join-Path $repositoryRoot "shared\fiscal_period.ps1"

if (-not (Test-Path -LiteralPath $fiscalPeriodScript -PathType Leaf)) {
    throw "Fiscal-period utility was not found: $fiscalPeriodScript"
}

. $fiscalPeriodScript

if (-not $PSBoundParameters.ContainsKey("FiscalYear")) {
    $FiscalYear = (Get-MinesFiscalPeriod -Date (Get-Date)).FiscalYear
}

$Folders = @(
    Get-MinesFiscalPeriodFolders -FiscalYear $FiscalYear |
        Select-Object -ExpandProperty PeriodDirectoryName
)

foreach ($Folder in $Folders) {
    if (Test-Path -LiteralPath $Folder) {
        Write-Host "Already exists: $Folder"
    }
    else {
        New-Item -ItemType Directory -Name $Folder | Out-Null
        Write-Host "Created: $Folder"
    }
}

Write-Host "`nFY$FiscalYear period folders completed."
