param (
    [ValidatePattern('^\d{6}$')]
    [string]$TermCode,

    [switch]$ArchiveOnly,

    # Download and transform, then return before the interactive Banner-upload
    # confirmation. This is used by the desktop GUI.
    [switch]$PrepareOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ArchiveOnly -and $PrepareOnly) {
    throw "ArchiveOnly and PrepareOnly cannot be used together."
}


# ------------------------------------------------------------
# REPOSITORY PATHS
# ------------------------------------------------------------

# Resolve repository files from this launcher's location so the automation
# repository can be installed outside OneDriveCommercial. Mines business data
# is resolved separately from OneDriveCommercial later in this script.
$repositoryRoot = Split-Path -Parent $PSScriptRoot

$termUtilityPath = Join-Path `
    $repositoryRoot `
    "shared\banner\term.ps1"

$winSCPClientPath = Join-Path `
    $repositoryRoot `
    "shared\sftp\winscp_client.ps1"

$configPath = Join-Path `
    $repositoryRoot `
    "config\textbook_brokers.psd1"

$pythonExecutablePath = Join-Path `
    $repositoryRoot `
    ".venv\Scripts\python.exe"


# ------------------------------------------------------------
# VALIDATE AND LOAD CONFIGURATION
# ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Textbook Brokers configuration was not found: $configPath"
}

$config = Import-PowerShellDataFile `
    -Path $configPath


# ------------------------------------------------------------
# CONFIGURE LOGGING
# ------------------------------------------------------------

$logDirectory = Join-Path `
    $repositoryRoot `
    $config.Logging.Directory

if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item `
        -ItemType Directory `
        -Path $logDirectory `
        -Force |
        Out-Null
}

# Every log file has its creation date and time in its filename.
$logTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$logPath = Join-Path `
    $logDirectory `
    "textbook_brokers_$logTimestamp.log"

function Write-Log {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory)]
        [string]$Message,

        [ValidateSet("INFO", "WARNING", "ERROR")]
        [string]$Level = "INFO"
    )

    # Every entry inside the log is also timestamped.
    $entryTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    $logEntry = "[{0}] [{1}] {2}" -f `
        $entryTimestamp,
        $Level,
        $Message

    Write-Host $logEntry

    Add-Content `
        -LiteralPath $logPath `
        -Value $logEntry
}

function Read-YesNoResponse {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory)]
        [string]$Prompt
    )

    while ($true) {
        $response = (Read-Host "$Prompt [Y/N]").Trim()

        switch ($response.ToUpperInvariant()) {
            "Y" {
                return $true
            }

            "YES" {
                return $true
            }

            "N" {
                return $false
            }

            "NO" {
                return $false
            }

            default {
                Write-Host "Please enter Y for Yes or N for No."
            }
        }
    }
}

function Get-TextbookBrokersPendingFiles {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory)]
        [string]$InputDirectory,

        [Parameter(Mandatory)]
        [object[]]$SourceDefinitions
    )

    foreach ($sourceDefinition in $SourceDefinitions) {
        $matchingLocalFiles = @(
            Get-ChildItem `
                -LiteralPath $InputDirectory `
                -File `
                -Filter $sourceDefinition.FilePattern |
                Sort-Object Name
        )

        foreach ($localFile in $matchingLocalFiles) {
            [pscustomobject]@{
                SourceType    = $sourceDefinition.SourceType
                FileName      = $localFile.Name
                LocalPath     = $localFile.FullName
                Length        = $localFile.Length
                LastWriteTime = $localFile.LastWriteTime
                Status        = "Ready"
            }
        }
    }
}

$workflowMode = if ($ArchiveOnly) {
    "archive only"
}
elseif ($PrepareOnly) {
    "download and transform only"
}
else {
    "download and transform"
}

Write-Log "Textbook Brokers workflow started."
Write-Log "Workflow mode: $workflowMode"
Write-Log "Repository root: $repositoryRoot"
Write-Log "Configuration file: $configPath"
Write-Log "Log file: $logPath"


# ------------------------------------------------------------
# LOAD THE SHARED BANNER TERM UTILITY
# ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $termUtilityPath -PathType Leaf)) {
    Write-Log `
        -Level "ERROR" `
        -Message "Banner term utility was not found: $termUtilityPath"

    throw "Banner term utility was not found: $termUtilityPath"
}

. $termUtilityPath

Write-Log "Banner term utility loaded: $termUtilityPath"

if (-not (Test-Path -LiteralPath $winSCPClientPath -PathType Leaf)) {
    Write-Log `
        -Level "ERROR" `
        -Message "WinSCP client was not found: $winSCPClientPath"

    throw "WinSCP client was not found: $winSCPClientPath"
}

. $winSCPClientPath

Write-Log "WinSCP client loaded: $winSCPClientPath"

# ------------------------------------------------------------
# DETERMINE THE BANNER TERM
# ------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($TermCode)) {
    $currentTerm = Get-CurrentBannerTerm

    $TermCode = $currentTerm.Code
    $termName = $currentTerm.Name

    Write-Log "Current Banner term: $termName"
    Write-Log "Banner term code: $TermCode"
    Write-Log (
        "Term dates: {0} through {1}" -f `
            $currentTerm.StartDate.ToString("yyyy-MM-dd"),
            $currentTerm.EndDate.ToString("yyyy-MM-dd")
    )
}
else {
    $suppliedTerm = Get-BannerTermByCode -TermCode $TermCode
    $termName = $suppliedTerm.Name

    Write-Log "Banner term code supplied manually: $TermCode"
    Write-Log "Resolved Banner term name: $termName"
}

# ------------------------------------------------------------
# RESOLVE REMOTE SFTP DIRECTORIES AND SOURCE TYPES
# ------------------------------------------------------------

$remoteSourceDirectory = $config.Remote.SourceDirectory

$finaidCompletedDirectory = `
    $config.Remote.Finaid.CompletedDirectory.
        Replace("{TermCode}", $TermCode).
        Replace("{TermName}", $termName)

$iaCompletedDirectory = `
    $config.Remote.IA.CompletedDirectory.
        Replace("{TermCode}", $TermCode).
        Replace("{TermName}", $termName)

$sourceDefinitions = @(
    [pscustomobject]@{
        SourceType         = "Finaid"
        FilePattern        = $config.Remote.Finaid.FilePattern
        CompletedDirectory = $finaidCompletedDirectory
    }

    [pscustomobject]@{
        SourceType         = "IA"
        FilePattern        = $config.Remote.IA.FilePattern
        CompletedDirectory = $iaCompletedDirectory
    }
)

Write-Log "Remote source directory: $remoteSourceDirectory"
Write-Log "Finaid completed directory: $finaidCompletedDirectory"
Write-Log "IA completed directory: $iaCompletedDirectory"

# ------------------------------------------------------------
# RESOLVE THE BUSINESS ONEDRIVE LOCATION
# ------------------------------------------------------------

$oneDriveRoot = [Environment]::GetEnvironmentVariable(
    $config.Local.RootEnvironmentVariable,
    "Process"
)

if ([string]::IsNullOrWhiteSpace($oneDriveRoot)) {
    $message = @"
The $($config.Local.RootEnvironmentVariable) environment variable is unavailable.

Confirm that OneDrive for Colorado School of Mines is installed,
signed in, and synchronized for this Windows user.
"@

    Write-Log `
        -Level "ERROR" `
        -Message $message

    throw $message
}

$businessRoot = Join-Path `
    $oneDriveRoot `
    $config.Local.BusinessDirectory

$termDirectoryName = $config.Local.TermDirectoryPattern.Replace(
    "{TermCode}",
    $TermCode
)

$termRoot = Join-Path `
    $businessRoot `
    $termDirectoryName


# ------------------------------------------------------------
# RESOLVE TERM-SPECIFIC DIRECTORIES
# ------------------------------------------------------------

# New Finaid and IA files awaiting processing live directly in this folder.
$inputDirectory = $termRoot

$outputDirectory = Join-Path `
    $termRoot `
    $config.Local.OutputDirectory

$completedSourceDirectory = Join-Path `
    $termRoot `
    $config.Local.CompletedSourceDirectory

$uploadedDirectory = Join-Path `
    $termRoot `
    $config.Local.UploadedDirectory

$errorDirectory = Join-Path `
    $termRoot `
    $config.Local.ErrorDirectory


# ------------------------------------------------------------
# CREATE REQUIRED BUSINESS DIRECTORIES
# ------------------------------------------------------------

$requiredDirectories = @(
    $termRoot
    $outputDirectory
    $completedSourceDirectory
    $uploadedDirectory
    $errorDirectory
)

foreach ($directory in $requiredDirectories) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item `
            -ItemType Directory `
            -Path $directory `
            -Force |
            Out-Null

        Write-Log "Created directory: $directory"
    }
    else {
        Write-Log "Directory already exists: $directory"
    }
}


# ------------------------------------------------------------
# RESOLVE FILE PATHS AND PATTERNS
# ------------------------------------------------------------

$outputFilePath = Join-Path `
    $outputDirectory `
    $config.Local.OutputFileName


# ------------------------------------------------------------
# REPORT THE RESOLVED WORKFLOW LOCATIONS
# ------------------------------------------------------------

Write-Log "Textbook Brokers term directory: $termRoot"
Write-Log "Pending source directory: $inputDirectory"
foreach ($sourceDefinition in $sourceDefinitions) {
    $localPattern = Join-Path `
        $inputDirectory `
        $sourceDefinition.FilePattern

    Write-Log (
        "{0} pending source pattern: {1}" -f `
            $sourceDefinition.SourceType,
            $localPattern
    )
}
Write-Log "Banner output directory: $outputDirectory"
Write-Log "Banner output file: $outputFilePath"
Write-Log "Python module: workflows.textbook_brokers.run_textbook_brokers"
Write-Log "Completed source archive: $completedSourceDirectory"
Write-Log "Uploaded Banner archive: $uploadedDirectory"
Write-Log "Error directory: $errorDirectory"


# ------------------------------------------------------------
# DOWNLOAD PENDING TEXTBOOK BROKERS FILES
# ------------------------------------------------------------

if (-not $ArchiveOnly) {
    try {
        $transferResults = @(
            Receive-TextbookBrokersFiles `
                -Connection $config.Connection `
                -OneDriveRoot $oneDriveRoot `
                -RemoteDirectory $remoteSourceDirectory `
                -SourceDefinitions $sourceDefinitions `
                -LocalDirectory $inputDirectory `
                -Log ${function:Write-Log}
        )

        $downloadedCount = @(
            $transferResults |
                Where-Object Status -eq "Downloaded"
        ).Count

        $existingCount = @(
            $transferResults |
                Where-Object Status -eq "AlreadyPresent"
        ).Count

        $conflictCount = @(
            $transferResults |
                Where-Object Status -eq "Conflict"
        ).Count

        $failedCount = @(
            $transferResults |
                Where-Object Status -eq "Failed"
        ).Count

        Write-Log (
            "Transfer summary: $downloadedCount downloaded, " +
            "$existingCount already present, " +
            "$conflictCount conflicts, " +
            "$failedCount failed."
        )

        if ($transferResults.Count -eq 0) {
            Write-Log `
                -Level "WARNING" `
                -Message (
                    "No matching Finaid or IA files were found " +
                    "on the remote server."
                )
        }

        if (($conflictCount + $failedCount) -gt 0) {
            throw (
                "One or more files could not be prepared safely. " +
                "Review the error entries in the workflow log."
            )
        }

        # Inventory every locally pending Finaid and IA file.
        $readySourceFiles = @(
            Get-TextbookBrokersPendingFiles `
                -InputDirectory $inputDirectory `
                -SourceDefinitions $sourceDefinitions
        )

        if ($readySourceFiles.Count -eq 0) {
            Write-Log `
                -Level "WARNING" `
                -Message "No local files are ready for transformation."
        }
        else {
            Write-Log (
                "Local pending summary: " +
                "$($readySourceFiles.Count) file(s) ready for transformation."
            )

            foreach ($readyFile in $readySourceFiles) {
                Write-Log (
                    "Ready for transformation: [{0}] {1}" -f `
                        $readyFile.SourceType,
                        $readyFile.LocalPath
                )
            }
        }

        Write-Log "Textbook Brokers download stage completed successfully."
    }
    catch {
        Write-Log `
            -Level "ERROR" `
            -Message "Textbook Brokers download stage failed: $($_.Exception.Message)"

        throw
    }
}
else {
    Write-Log (
        "Archive-only mode selected. Remote download and Python " +
        "transformation will be skipped."
    )

    $readySourceFiles = @(
        Get-TextbookBrokersPendingFiles `
            -InputDirectory $inputDirectory `
            -SourceDefinitions $sourceDefinitions
    )

    if ($readySourceFiles.Count -eq 0) {
        throw (
            "No pending Finaid or IA source files were found for term " +
            "$TermCode in $inputDirectory"
        )
    }

    foreach ($readyFile in $readySourceFiles) {
        Write-Log (
            "Pending archive source: [{0}] {1}" -f `
                $readyFile.SourceType,
                $readyFile.LocalPath
        )
    }
}


# ------------------------------------------------------------
# TRANSFORM PENDING FILES INTO TSPLOAD.CSV
# ------------------------------------------------------------

if ($ArchiveOnly) {
    if (-not (Test-Path -LiteralPath $outputFilePath -PathType Leaf)) {
        throw (
            "TSPLOAD.csv is not pending for term $TermCode. " +
            "Expected: $outputFilePath"
        )
    }

    $outputFile = Get-Item -LiteralPath $outputFilePath

    if ($outputFile.Length -eq 0) {
        throw "Pending TSPLOAD.csv is empty: $outputFilePath"
    }

    Write-Log "Pending TSPLOAD output verified: $outputFilePath"
    Write-Log "Pending TSPLOAD output size: $($outputFile.Length) bytes"
}
elseif ($readySourceFiles.Count -eq 0) {
    Write-Log `
        -Level "WARNING" `
        -Message "Transformation was skipped because no local source files are pending."

    Write-Log "Textbook Brokers workflow completed with no files to process."
    if ($PrepareOnly) {
        Write-Output "HIGHERED_NO_PENDING_FILES=1"
    }
    return
}
else {
    try {
        if (-not (Test-Path -LiteralPath $pythonExecutablePath -PathType Leaf)) {
            throw "Repository Python executable was not found: $pythonExecutablePath"
        }

        $pythonArguments = @(
            "-m"
            "workflows.textbook_brokers.run_textbook_brokers"
            "--term-code"
            $TermCode
            "--output"
            $outputFilePath
        )

        foreach ($readyFile in $readySourceFiles) {
            $pythonArguments += $readyFile.LocalPath
        }

        Write-Log (
            "Starting Textbook Brokers transformation for {0} source file(s)." -f `
                $readySourceFiles.Count
        )

        Push-Location $repositoryRoot

        try {
            $pythonOutput = @(
                & $pythonExecutablePath @pythonArguments 2>&1
            )

            $pythonExitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }

        foreach ($outputLine in $pythonOutput) {
            Write-Log "Python: $outputLine"
        }

        if ($pythonExitCode -ne 0) {
            throw "Python transformation exited with code $pythonExitCode."
        }

        if (-not (Test-Path -LiteralPath $outputFilePath -PathType Leaf)) {
            throw "Python reported success, but TSPLOAD.csv was not created."
        }

        $outputFile = Get-Item -LiteralPath $outputFilePath

        if ($outputFile.Length -eq 0) {
            throw "TSPLOAD.csv was created but is empty: $outputFilePath"
        }

        Write-Log "TSPLOAD output verified: $outputFilePath"
        Write-Log "TSPLOAD output size: $($outputFile.Length) bytes"
        Write-Log "Textbook Brokers transformation completed successfully."
    }
    catch {
        Write-Log `
            -Level "ERROR" `
            -Message "Textbook Brokers transformation failed: $($_.Exception.Message)"

        throw
    }
}


# ------------------------------------------------------------
# RETURN TO THE GUI BEFORE CONSEQUENTIAL ARCHIVAL
# ------------------------------------------------------------

if ($PrepareOnly) {
    Write-Log (
        "Prepare-only mode completed. TSPLOAD.csv and source files remain " +
        "pending until the Banner upload is confirmed through the archive workflow."
    )

    # Stable machine-readable output for the GUI adapter. Keep this distinct
    # from normal log lines so paths never need to be duplicated in Python.
    Write-Output "HIGHERED_OUTPUT_PATH=$outputFilePath"
    return
}


# ------------------------------------------------------------
# CONFIRM MANUAL BANNER UPLOAD
# ------------------------------------------------------------

$bannerUploadConfirmed = Read-YesNoResponse `
    -Prompt (
        "Have you uploaded TSPLOAD.csv through GJAJFLU and " +
        "confirmed that the transactions were applied successfully?"
    )

if (-not $bannerUploadConfirmed) {
    Write-Log (
        "Banner upload was not confirmed. TSPLOAD.csv, local source " +
        "files, and remote source files were left unchanged."
    )

    Write-Log "Textbook Brokers workflow paused for manual Banner upload."
    Write-Host ""
    Write-Host "After the Banner upload succeeds, run:"
    Write-Host "archive-textbook-brokers"
    return
}

Write-Log "Manual Banner upload and transaction application were confirmed."


# ------------------------------------------------------------
# PREPARE LOCAL ARCHIVE OPERATIONS
# ------------------------------------------------------------

try {
    $archiveTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

    $uploadedFileName = `
        $config.Local.UploadedFileNamePattern.Replace(
            "{DateTime}",
            $archiveTimestamp
        )

    $uploadedFilePath = Join-Path `
        $uploadedDirectory `
        $uploadedFileName

    $localMoveOperations = @()

    foreach ($readyFile in $readySourceFiles) {
        $archivedSourcePath = Join-Path `
            $completedSourceDirectory `
            $readyFile.FileName

        $localMoveOperations += [pscustomobject]@{
            Description     = "$($readyFile.SourceType) source file"
            SourcePath      = $readyFile.LocalPath
            DestinationPath = $archivedSourcePath
        }
    }

    # TSPLOAD is moved last and acts as the completion marker.
    $localMoveOperations += [pscustomobject]@{
        Description     = "TSPLOAD output"
        SourcePath      = $outputFilePath
        DestinationPath = $uploadedFilePath
    }

    # Validate every local move before changing the SFTP server.
    foreach ($operation in $localMoveOperations) {
        if (-not (
            Test-Path `
                -LiteralPath $operation.SourcePath `
                -PathType Leaf
        )) {
            throw (
                "Local archive source was not found: " +
                $operation.SourcePath
            )
        }

        if (Test-Path -LiteralPath $operation.DestinationPath) {
            throw (
                "Local archive destination already exists: " +
                $operation.DestinationPath
            )
        }

        $destinationDirectory = Split-Path `
            -Parent `
            $operation.DestinationPath

        if (-not (
            Test-Path `
                -LiteralPath $destinationDirectory `
                -PathType Container
        )) {
            throw (
                "Local archive directory was not found: " +
                $destinationDirectory
            )
        }
    }


    # ------------------------------------------------------------
    # ARCHIVE FILES ON THE TEXTBOOK BROKERS SFTP SERVER
    # ------------------------------------------------------------

    $remoteArchiveResults = @(
        Move-TextbookBrokersRemoteSourceFiles `
            -Connection $config.Connection `
            -OneDriveRoot $oneDriveRoot `
            -RemoteSourceDirectory $remoteSourceDirectory `
            -SourceFiles $readySourceFiles `
            -SourceDefinitions $sourceDefinitions `
            -Log ${function:Write-Log}
    )

    $remoteMovedCount = @(
        $remoteArchiveResults |
            Where-Object Status -eq "Moved"
    ).Count

    $remoteAlreadyArchivedCount = @(
        $remoteArchiveResults |
            Where-Object Status -eq "AlreadyArchived"
    ).Count

    $remoteNotPresentCount = @(
        $remoteArchiveResults |
            Where-Object Status -eq "NotPresent"
    ).Count

    Write-Log (
        "Remote archive summary: $remoteMovedCount moved, " +
        "$remoteAlreadyArchivedCount already archived, " +
        "$remoteNotPresentCount not present."
    )


    # ------------------------------------------------------------
    # ARCHIVE LOCAL FILES
    # ------------------------------------------------------------

    $completedLocalMoves = @()

    try {
        foreach ($operation in $localMoveOperations) {
            Write-Log (
                "Moving local {0}: {1} -> {2}" -f `
                    $operation.Description,
                    $operation.SourcePath,
                    $operation.DestinationPath
            )

            Move-Item `
                -LiteralPath $operation.SourcePath `
                -Destination $operation.DestinationPath

            $completedLocalMoves += $operation

            if (Test-Path -LiteralPath $operation.SourcePath) {
                throw (
                    "Local source still exists after move: " +
                    $operation.SourcePath
                )
            }

            if (-not (
                Test-Path `
                    -LiteralPath $operation.DestinationPath `
                    -PathType Leaf
            )) {
                throw (
                    "Local destination was not found after move: " +
                    $operation.DestinationPath
                )
            }

            Write-Log (
                "Local move verified: " +
                $operation.DestinationPath
            )
        }
    }
    catch {
        $localMoveError = $_.Exception.Message

        Write-Log `
            -Level "ERROR" `
            -Message (
                "Local archival failed; starting rollback: " +
                $localMoveError
            )

        for (
            $index = $completedLocalMoves.Count - 1;
            $index -ge 0
            $index--
        ) {
            $completedOperation = $completedLocalMoves[$index]

            try {
                if (
                    (Test-Path `
                        -LiteralPath $completedOperation.DestinationPath) -and
                    (-not (
                        Test-Path `
                            -LiteralPath $completedOperation.SourcePath
                    ))
                ) {
                    Move-Item `
                        -LiteralPath $completedOperation.DestinationPath `
                        -Destination $completedOperation.SourcePath

                    Write-Log (
                        "Rollback restored: " +
                        $completedOperation.SourcePath
                    )
                }
            }
            catch {
                Write-Log `
                    -Level "ERROR" `
                    -Message (
                        "Rollback failed for {0}: {1}" -f `
                            $completedOperation.DestinationPath,
                            $_.Exception.Message
                    )
            }
        }

        throw "Local archival failed: $localMoveError"
    }

    Write-Log "Archived TSPLOAD output: $uploadedFilePath"

    Write-Log (
        "Archived {0} local source file(s): {1}" -f `
            $readySourceFiles.Count,
            $completedSourceDirectory
    )

    Write-Log "Textbook Brokers archival completed successfully."
}
catch {
    Write-Log `
        -Level "ERROR" `
        -Message "Textbook Brokers archival failed: $($_.Exception.Message)"

    throw
}

Write-Log "Textbook Brokers workflow completed successfully."
