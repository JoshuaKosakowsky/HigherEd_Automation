param (
    [ValidatePattern('^\d{6}$')]
    [string]$TermCode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"


# ------------------------------------------------------------
# REPOSITORY PATHS
# ------------------------------------------------------------

$repositoryRoot = Join-Path `
    $env:OneDriveCommercial `
    "HigherEd_Automation"

$termUtilityPath = Join-Path `
    $repositoryRoot `
    "shared\banner\term.ps1"

$winSCPClientPath = Join-Path `
    $repositoryRoot `
    "shared\sftp\winscp_client.ps1"

$configPath = Join-Path `
    $repositoryRoot `
    "config\textbook_brokers.psd1"


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

Write-Log "Textbook Brokers workflow started."
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
    $termYear = $TermCode.Substring(0, 4)
    $termSuffix = $TermCode.Substring(4, 2)

    $termSeason = switch ($termSuffix) {
        "10" { "Spring" }
        "55" { "Summer" }
        "80" { "Fall" }
        default {
            throw "Unsupported Banner term-code suffix: $termSuffix"
        }
    }

    $termName = "$termSeason $termYear"

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
Write-Log "Completed source archive: $completedSourceDirectory"
Write-Log "Uploaded Banner archive: $uploadedDirectory"
Write-Log "Error directory: $errorDirectory"


# ------------------------------------------------------------
# DOWNLOAD PENDING TEXTBOOK BROKERS FILES
# ------------------------------------------------------------

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
        "Transfer summary: {0} downloaded, {1} already present, " +
        "{2} conflicts, {3} failed." -f `
            $downloadedCount,
            $existingCount,
            $conflictCount,
            $failedCount
    )

    if ($transferResults.Count -eq 0) {
        Write-Log `
            -Level "WARNING" `
            -Message "No pending Finaid or IA files were found."
    }

    if (($conflictCount + $failedCount) -gt 0) {
        throw (
            "One or more files could not be prepared safely. " +
            "Review the error entries in the workflow log."
        )
    }

    $readySourceFiles = @(
        $transferResults |
            Where-Object {
                $_.Status -in @(
                    "Downloaded",
                    "AlreadyPresent"
                )
            }
    )

    foreach ($readyFile in $readySourceFiles) {
        Write-Log (
            "Ready for transformation: [{0}] {1}" -f `
                $readyFile.SourceType,
                $readyFile.LocalPath
        )
    }

    Write-Log "Textbook Brokers download stage completed successfully."
}
catch {
    Write-Log `
        -Level "ERROR" `
        -Message "Textbook Brokers download stage failed: $($_.Exception.Message)"

    throw
}


# ------------------------------------------------------------
# FUTURE WORKFLOW EXECUTION
# ------------------------------------------------------------

# The Python transformation, source-file archival, remote-file
# archival, and future Banner upload will be called below this point.