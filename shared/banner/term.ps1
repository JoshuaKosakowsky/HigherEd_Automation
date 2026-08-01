function Get-BannerTerm {
    [CmdletBinding()]
    param (
        [datetime]$Date = (Get-Date)
    )

    $calendarYear = $Date.Year

    $termDefinitions = @(
        @{
            NameSuffix = "Spring"
            CodeSuffix = "10"
            StartDate  = [datetime]::new($calendarYear, 1, 1)
            EndDate    = [datetime]::new($calendarYear, 5, 15)
        }
        @{
            NameSuffix = "Summer"
            CodeSuffix = "55"
            StartDate  = [datetime]::new($calendarYear, 5, 16)
            EndDate    = [datetime]::new($calendarYear, 7, 15)
        }
        @{
            NameSuffix = "Fall"
            CodeSuffix = "80"
            StartDate  = [datetime]::new($calendarYear, 7, 16)
            EndDate    = [datetime]::new($calendarYear, 12, 31)
        }
    )

    $term = $termDefinitions |
        Where-Object {
            $Date.Date -ge $_.StartDate.Date -and
            $Date.Date -le $_.EndDate.Date
        } |
        Select-Object -First 1

    if ($null -eq $term) {
        throw "No Banner term could be determined for $($Date.ToString('yyyy-MM-dd'))."
    }

    [PSCustomObject]@{
        Code      = "$calendarYear$($term.CodeSuffix)"
        Name      = "$($term.NameSuffix) $calendarYear"
        StartDate = $term.StartDate
        EndDate   = $term.EndDate
    }
}


function Get-CurrentBannerTerm {
    [CmdletBinding()]
    param ()

    Get-BannerTerm -Date (Get-Date)
}


function Get-CurrentBannerTermCode {
    [CmdletBinding()]
    param ()

    (Get-CurrentBannerTerm).Code
}