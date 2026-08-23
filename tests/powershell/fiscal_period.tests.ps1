$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fiscalPeriodScript = Join-Path $repositoryRoot "shared\fiscal_period.ps1"

. $fiscalPeriodScript


function Assert-Equal {
    param(
        [Parameter(Mandatory)]
        [object]$Expected,

        [Parameter(Mandatory)]
        [object]$Actual,

        [Parameter(Mandatory)]
        [string]$Case
    )

    if ($Expected -ne $Actual) {
        throw (
            "FAILED: {0}. Expected {1}; received {2}." -f `
                $Case,
                $Expected,
                $Actual
        )
    }
}


$boundaryCases = @(
    @{
        Date = [datetime]"2026-06-30"
        FiscalYear = 2026
        Period = "P12"
        Directory = "P12 - June 2026"
    }
    @{
        Date = [datetime]"2026-07-01"
        FiscalYear = 2027
        Period = "P01"
        Directory = "P01 - July 2026"
    }
    @{
        Date = [datetime]"2026-08-01"
        FiscalYear = 2027
        Period = "P02"
        Directory = "P02 - August 2026"
    }
    @{
        Date = [datetime]"2027-06-30"
        FiscalYear = 2027
        Period = "P12"
        Directory = "P12 - June 2027"
    }
)

foreach ($case in $boundaryCases) {
    $result = Get-MinesFiscalPeriod -Date $case.Date

    Assert-Equal `
        -Expected $case.FiscalYear `
        -Actual $result.FiscalYear `
        -Case "Fiscal year for $($case.Date.ToString('yyyy-MM-dd'))"
    Assert-Equal `
        -Expected $case.Period `
        -Actual $result.PeriodCode `
        -Case "Period for $($case.Date.ToString('yyyy-MM-dd'))"
    Assert-Equal `
        -Expected $case.Directory `
        -Actual $result.PeriodDirectoryName `
        -Case "Folder for $($case.Date.ToString('yyyy-MM-dd'))"
}

$fy27Folders = @(Get-MinesFiscalPeriodFolders -FiscalYear 2027)

Assert-Equal -Expected 12 -Actual $fy27Folders.Count -Case "FY27 folder count"
Assert-Equal `
    -Expected "P01 - July 2026" `
    -Actual $fy27Folders[0].PeriodDirectoryName `
    -Case "FY27 first folder"
Assert-Equal `
    -Expected "P12 - June 2027" `
    -Actual $fy27Folders[-1].PeriodDirectoryName `
    -Case "FY27 final folder"

Write-Host "Fiscal-period tests passed." -ForegroundColor Green
