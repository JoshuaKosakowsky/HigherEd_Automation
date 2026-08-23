@{
    SchemaVersion = 1

    Watcher = @{
        ExistingFileLookbackDays    = 7
        StableCheckIntervalSeconds  = 1
        RequiredStableChecks        = 3
        StableTimeoutSeconds        = 120
    }

    Destination = @{
        RootEnvironmentVariable  = "OneDriveCommercial"
        RootFallbackDirectory    = "OneDrive - Colorado School of Mines"
        BusinessDirectory        = "GRP-Bursar Office - General\Y-Brswork\Cashier\Daily Closing"

        # Change this one value if the actual fiscal-year folders use another
        # format, such as "FY 2027" or "Fiscal Year 2027".
        FiscalYearDirectoryPattern = "FY{FiscalYearTwoDigit}"
    }

    Reports = @(
        @{
            Id                  = "cashier_daily_closing_rdc"
            DisplayName         = "Cashier Daily Closing RDC"

            # Replace this placeholder after confirming the website's normal
            # downloaded filename. PowerShell wildcards are allowed.
            SourceFilePattern   = "PLACEHOLDER_DAILY_CLOSING*.pdf"
            RequiredExtension   = ".pdf"

            DestinationSuffix   = "RDC"
        }
    )
}
