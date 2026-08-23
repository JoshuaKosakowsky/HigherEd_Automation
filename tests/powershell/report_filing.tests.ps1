$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$modulePath = Join-Path `
    $repositoryRoot `
    "workflows\report_filing\report_filing.psm1"
$configurationPath = Join-Path `
    $repositoryRoot `
    "config\report_filing.psd1"
$userSettingsScript = Join-Path $repositoryRoot "shared\user_settings.ps1"

Import-Module $modulePath -Force
. $userSettingsScript


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


$configuration = Get-ReportFilingConfiguration -Path $configurationPath
$testRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    "HigherEdAutomationReportFilingTests_$([guid]::NewGuid().ToString('N'))"
$originalOneDriveCommercial = $env:OneDriveCommercial
$originalLocalAppData = $env:LOCALAPPDATA

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $env:OneDriveCommercial = $testRoot
    $env:LOCALAPPDATA = Join-Path $testRoot "LocalAppData"

    $report = @($configuration.Reports)[0]
    $proposal = Get-ReportDestinationProposal `
        -ReportDate ([datetime]"2026-07-31") `
        -Initials "abc" `
        -Report $report `
        -DestinationConfiguration $configuration.Destination

    Assert-Equal -Expected 2027 -Actual $proposal.FiscalYear -Case "RDC fiscal year"
    Assert-Equal -Expected "P01" -Actual $proposal.Period -Case "RDC period"
    Assert-Equal `
        -Expected "P01 - July 2026" `
        -Actual $proposal.PeriodDirectoryName `
        -Case "RDC period directory"
    Assert-Equal `
        -Expected "07-31-2026 ABC RDC.pdf" `
        -Actual $proposal.FileName `
        -Case "RDC filename"

    $expectedEnding = Join-Path `
        "FY27\P01 - July 2026" `
        "07-31-2026 ABC RDC.pdf"

    if (-not $proposal.FullPath.EndsWith($expectedEnding)) {
        throw "FAILED: RDC destination did not end with: $expectedEnding"
    }

    Save-AutomationUserSettings `
        -DisplayName "Synthetic Cashier" `
        -Initials "sc" |
        Out-Null
    $userSettings = Read-AutomationUserSettings

    Assert-Equal `
        -Expected "Synthetic Cashier" `
        -Actual $userSettings.DisplayName `
        -Case "Saved display name"
    Assert-Equal `
        -Expected "SC" `
        -Actual $userSettings.Initials `
        -Case "Normalized initials"

    $invalidInitialsRejected = $false

    try {
        Test-AutomationUserSettingsValue `
            -DisplayName "Synthetic Cashier" `
            -Initials "S C"
    }
    catch {
        $invalidInitialsRejected = $true
    }

    Assert-Equal `
        -Expected $true `
        -Actual $invalidInitialsRejected `
        -Case "Initials containing spaces are rejected"
}
finally {
    if ($null -eq $originalOneDriveCommercial) {
        Remove-Item Env:OneDriveCommercial -ErrorAction SilentlyContinue
    }
    else {
        $env:OneDriveCommercial = $originalOneDriveCommercial
    }

    if ($null -eq $originalLocalAppData) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    }
    else {
        $env:LOCALAPPDATA = $originalLocalAppData
    }

    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

Write-Host "Report-filing tests passed." -ForegroundColor Green
