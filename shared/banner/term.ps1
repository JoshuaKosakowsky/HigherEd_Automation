$script:BannerTermConfigPath = Join-Path `
    (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) `
    "config\institutions\mines\banner_terms.json"


function Get-BannerTermDefinitions {
    [CmdletBinding()]
    param()

    if (-not (
        Test-Path `
            -LiteralPath $script:BannerTermConfigPath `
            -PathType Leaf
    )) {
        throw "Banner term configuration was not found: $script:BannerTermConfigPath"
    }

    try {
        $configuration = Get-Content `
            -LiteralPath $script:BannerTermConfigPath `
            -Raw `
            -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw (
            "Banner term configuration is not valid JSON: {0}. {1}" -f `
                $script:BannerTermConfigPath,
                $_.Exception.Message
        )
    }

    if ($configuration.schemaVersion -ne 1) {
        throw (
            "Unsupported Banner term configuration schema version: {0}" -f `
                $configuration.schemaVersion
        )
    }

    if ($configuration.termCodeYear -ne "calendarYear") {
        throw (
            "Unsupported Banner term-code year rule: {0}" -f `
                $configuration.termCodeYear
        )
    }

    $configuredTerms = @($configuration.terms)

    if ($configuredTerms.Count -eq 0) {
        throw "Banner term configuration does not contain any terms."
    }

    $validationYear = 2000
    $definitions = @()
    $seenNames = @()
    $seenSuffixes = @()

    for ($index = 0; $index -lt $configuredTerms.Count; $index++) {
        $configuredTerm = $configuredTerms[$index]
        $name = [string]$configuredTerm.name
        $codeSuffix = [string]$configuredTerm.codeSuffix
        $startMonthDay = [string]$configuredTerm.startMonthDay
        $endMonthDay = [string]$configuredTerm.endMonthDay

        if ([string]::IsNullOrWhiteSpace($name)) {
            throw "Banner term at sequence index $index has no name."
        }

        if ($codeSuffix -notmatch '^\d{2}$') {
            throw "Banner term '$name' must have a two-digit code suffix."
        }

        if ($seenNames -contains $name) {
            throw "Banner term name is duplicated: $name"
        }

        if ($seenSuffixes -contains $codeSuffix) {
            throw "Banner term code suffix is duplicated: $codeSuffix"
        }

        try {
            $startDate = [datetime]::ParseExact(
                "$validationYear-$startMonthDay",
                "yyyy-MM-dd",
                [Globalization.CultureInfo]::InvariantCulture
            )
            $endDate = [datetime]::ParseExact(
                "$validationYear-$endMonthDay",
                "yyyy-MM-dd",
                [Globalization.CultureInfo]::InvariantCulture
            )
        }
        catch {
            throw (
                "Banner term '$name' has an invalid month-day boundary. " +
                "Expected MM-dd values."
            )
        }

        if ($startDate -gt $endDate) {
            throw "Banner term '$name' starts after it ends."
        }

        $definitions += [pscustomobject]@{
            Name          = $name
            CodeSuffix    = $codeSuffix
            StartMonthDay = $startMonthDay
            EndMonthDay   = $endMonthDay
            StartDate     = $startDate
            EndDate       = $endDate
            SequenceIndex = $index
        }

        $seenNames += $name
        $seenSuffixes += $codeSuffix
    }

    if ($definitions[0].StartMonthDay -ne "01-01") {
        throw "The first Banner term must start on January 1."
    }

    if ($definitions[-1].EndMonthDay -ne "12-31") {
        throw "The final Banner term must end on December 31."
    }

    for ($index = 1; $index -lt $definitions.Count; $index++) {
        $expectedStart = $definitions[$index - 1].EndDate.AddDays(1)

        if ($definitions[$index].StartDate -ne $expectedStart) {
            throw (
                "Banner terms must be ordered with no gaps or overlaps. " +
                "The boundary before '$($definitions[$index].Name)' is invalid."
            )
        }
    }

    return $definitions
}


function New-BannerTermResult {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$Definition,

        [Parameter(Mandatory)]
        [int]$CalendarYear
    )

    $startDate = [datetime]::ParseExact(
        "$CalendarYear-$($Definition.StartMonthDay)",
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $endDate = [datetime]::ParseExact(
        "$CalendarYear-$($Definition.EndMonthDay)",
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture
    )

    [pscustomobject]@{
        Code          = "$CalendarYear$($Definition.CodeSuffix)"
        Name          = "$($Definition.Name) $CalendarYear"
        TermName      = $Definition.Name
        CodeSuffix    = $Definition.CodeSuffix
        CalendarYear  = $CalendarYear
        StartDate     = $startDate
        EndDate       = $endDate
        SequenceIndex = $Definition.SequenceIndex
    }
}


function Get-BannerTerm {
    [CmdletBinding()]
    param(
        [datetime]$Date = (Get-Date)
    )

    $definitions = @(Get-BannerTermDefinitions)
    $calendarYear = $Date.Year

    foreach ($definition in $definitions) {
        $term = New-BannerTermResult `
            -Definition $definition `
            -CalendarYear $calendarYear

        if (
            $Date.Date -ge $term.StartDate.Date -and
            $Date.Date -le $term.EndDate.Date
        ) {
            return $term
        }
    }

    throw "No Banner term could be determined for $($Date.ToString('yyyy-MM-dd'))."
}


function Get-BannerTermByCode {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidatePattern('^\d{6}$')]
        [string]$TermCode
    )

    $calendarYear = [int]$TermCode.Substring(0, 4)
    $codeSuffix = $TermCode.Substring(4, 2)
    $definitions = @(Get-BannerTermDefinitions)
    $definition = $definitions |
        Where-Object CodeSuffix -eq $codeSuffix |
        Select-Object -First 1

    if ($null -eq $definition) {
        throw "Unsupported Banner term-code suffix: $codeSuffix"
    }

    New-BannerTermResult `
        -Definition $definition `
        -CalendarYear $calendarYear
}


function Get-RelativeBannerTerm {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$Term,

        [Parameter(Mandatory)]
        [int]$Offset
    )

    $definitions = @(Get-BannerTermDefinitions)
    $targetIndex = $Term.SequenceIndex + $Offset
    $targetYear = $Term.CalendarYear

    while ($targetIndex -lt 0) {
        $targetIndex += $definitions.Count
        $targetYear--
    }

    while ($targetIndex -ge $definitions.Count) {
        $targetIndex -= $definitions.Count
        $targetYear++
    }

    New-BannerTermResult `
        -Definition $definitions[$targetIndex] `
        -CalendarYear $targetYear
}


function Get-NextBannerTerm {
    [CmdletBinding(DefaultParameterSetName = "ByDate")]
    param(
        [Parameter(ParameterSetName = "ByDate")]
        [datetime]$Date = (Get-Date),

        [Parameter(Mandatory, ParameterSetName = "ByCode")]
        [ValidatePattern('^\d{6}$')]
        [string]$TermCode
    )

    $term = if ($PSCmdlet.ParameterSetName -eq "ByCode") {
        Get-BannerTermByCode -TermCode $TermCode
    }
    else {
        Get-BannerTerm -Date $Date
    }

    Get-RelativeBannerTerm -Term $term -Offset 1
}


function Get-PreviousBannerTerm {
    [CmdletBinding(DefaultParameterSetName = "ByDate")]
    param(
        [Parameter(ParameterSetName = "ByDate")]
        [datetime]$Date = (Get-Date),

        [Parameter(Mandatory, ParameterSetName = "ByCode")]
        [ValidatePattern('^\d{6}$')]
        [string]$TermCode
    )

    $term = if ($PSCmdlet.ParameterSetName -eq "ByCode") {
        Get-BannerTermByCode -TermCode $TermCode
    }
    else {
        Get-BannerTerm -Date $Date
    }

    Get-RelativeBannerTerm -Term $term -Offset -1
}


function Get-CurrentBannerTerm {
    [CmdletBinding()]
    param()

    Get-BannerTerm -Date (Get-Date)
}


function Get-CurrentBannerTermCode {
    [CmdletBinding()]
    param()

    (Get-CurrentBannerTerm).Code
}
