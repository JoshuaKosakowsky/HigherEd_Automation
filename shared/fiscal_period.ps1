function Get-MinesFiscalPeriod {
    [CmdletBinding()]
    param(
        [datetime]$Date = (Get-Date)
    )

    $calendarDate = $Date.Date
    $fiscalYear = if ($calendarDate.Month -ge 7) {
        $calendarDate.Year + 1
    }
    else {
        $calendarDate.Year
    }

    $periodNumber = if ($calendarDate.Month -ge 7) {
        $calendarDate.Month - 6
    }
    else {
        $calendarDate.Month + 6
    }

    $periodCode = "P{0:D2}" -f $periodNumber
    $monthName = $calendarDate.ToString(
        "MMMM",
        [Globalization.CultureInfo]::InvariantCulture
    )

    [pscustomobject]@{
        Date                = $calendarDate
        FiscalYear          = $fiscalYear
        FiscalYearTwoDigit  = "{0:D2}" -f ($fiscalYear % 100)
        PeriodNumber        = $periodNumber
        PeriodCode          = $periodCode
        MonthName           = $monthName
        CalendarYear        = $calendarDate.Year
        PeriodDirectoryName = (
            "{0} - {1} {2}" -f `
                $periodCode,
                $monthName,
                $calendarDate.Year
        )
    }
}


function Get-MinesFiscalPeriodFolders {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateRange(2000, 2200)]
        [int]$FiscalYear
    )

    $firstCalendarYear = $FiscalYear - 1

    for ($periodNumber = 1; $periodNumber -le 12; $periodNumber++) {
        $monthOffset = $periodNumber - 1
        $periodDate = ([datetime]::new($firstCalendarYear, 7, 1)).AddMonths(
            $monthOffset
        )

        Get-MinesFiscalPeriod -Date $periodDate
    }
}
