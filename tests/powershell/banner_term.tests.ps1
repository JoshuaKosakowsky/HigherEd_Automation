$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$termScript = Join-Path $repositoryRoot "shared\banner\term.ps1"

. $termScript


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
    @{ Date = [datetime]"2026-01-01"; Code = "202610" }
    @{ Date = [datetime]"2026-05-15"; Code = "202610" }
    @{ Date = [datetime]"2026-05-16"; Code = "202655" }
    @{ Date = [datetime]"2026-07-15"; Code = "202655" }
    @{ Date = [datetime]"2026-07-16"; Code = "202680" }
    @{ Date = [datetime]"2026-12-31"; Code = "202680" }
    @{ Date = [datetime]"2020-02-29"; Code = "202010" }
    @{ Date = [datetime]"2035-08-01"; Code = "203580" }
)

foreach ($case in $boundaryCases) {
    $term = Get-BannerTerm -Date $case.Date
    Assert-Equal `
        -Expected $case.Code `
        -Actual $term.Code `
        -Case "Current term for $($case.Date.ToString('yyyy-MM-dd'))"
}

$sequenceCases = @(
    @{ Source = "202610"; Next = "202655"; Previous = "202580" }
    @{ Source = "202655"; Next = "202680"; Previous = "202610" }
    @{ Source = "202680"; Next = "202710"; Previous = "202655" }
)

foreach ($case in $sequenceCases) {
    $nextTerm = Get-NextBannerTerm -TermCode $case.Source
    $previousTerm = Get-PreviousBannerTerm -TermCode $case.Source

    Assert-Equal `
        -Expected $case.Next `
        -Actual $nextTerm.Code `
        -Case "Next term after $($case.Source)"

    Assert-Equal `
        -Expected $case.Previous `
        -Actual $previousTerm.Code `
        -Case "Previous term before $($case.Source)"
}

Assert-Equal `
    -Expected "202710" `
    -Actual (Get-NextBannerTerm -Date ([datetime]"2026-12-31")).Code `
    -Case "Date-based next term crosses the calendar year"

Assert-Equal `
    -Expected "202580" `
    -Actual (Get-PreviousBannerTerm -Date ([datetime]"2026-01-01")).Code `
    -Case "Date-based previous term crosses the calendar year"

$invalidCodeWasRejected = $false

try {
    Get-BannerTermByCode -TermCode "202699" | Out-Null
}
catch {
    $invalidCodeWasRejected = $true
}

Assert-Equal `
    -Expected $true `
    -Actual $invalidCodeWasRejected `
    -Case "Unsupported term-code suffix is rejected"

Write-Host "Banner term tests passed." -ForegroundColor Green
