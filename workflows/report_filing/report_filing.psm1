$script:RepositoryRoot = Split-Path -Parent (
    Split-Path -Parent $PSScriptRoot
)

$fiscalPeriodScript = Join-Path $script:RepositoryRoot "shared\fiscal_period.ps1"
$userSettingsScript = Join-Path $script:RepositoryRoot "shared\user_settings.ps1"

if (-not (Test-Path -LiteralPath $fiscalPeriodScript -PathType Leaf)) {
    throw "Fiscal-period utility was not found: $fiscalPeriodScript"
}

if (-not (Test-Path -LiteralPath $userSettingsScript -PathType Leaf)) {
    throw "User-settings utility was not found: $userSettingsScript"
}

. $fiscalPeriodScript
. $userSettingsScript


function Get-ReportFilingLocalDirectory {
    [CmdletBinding()]
    param()

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "Windows LOCALAPPDATA is not available for this user."
    }

    $directory = Join-Path $env:LOCALAPPDATA "HigherEdAutomation\report-filing"

    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $directory
}


function Write-ReportFilingLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message,

        [ValidateSet("INFO", "WARNING", "ERROR")]
        [string]$Level = "INFO"
    )

    $logPath = Join-Path (Get-ReportFilingLocalDirectory) "report-filing.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content `
        -LiteralPath $logPath `
        -Value "[$timestamp] [$Level] $Message" `
        -Encoding UTF8
}


function Get-ReportFilingConfiguration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Report-filing configuration was not found: $Path"
    }

    $configuration = Import-PowerShellDataFile -Path $Path

    if ($configuration.SchemaVersion -ne 1) {
        throw "Unsupported report-filing configuration version: $($configuration.SchemaVersion)"
    }

    if ($null -eq $configuration.Watcher) {
        throw "Report-filing configuration is missing Watcher settings."
    }

    if ($null -eq $configuration.Destination) {
        throw "Report-filing configuration is missing Destination settings."
    }

    $reports = @($configuration.Reports)

    if ($reports.Count -eq 0) {
        throw "Report-filing configuration does not define any reports."
    }

    foreach ($report in $reports) {
        foreach ($requiredField in @(
            "Id",
            "DisplayName",
            "SourceFilePattern",
            "SourceTimestampFormat",
            "RequiredExtension",
            "DestinationSuffix"
        )) {
            if ([string]::IsNullOrWhiteSpace([string]$report[$requiredField])) {
                throw "A report definition is missing $requiredField."
            }
        }

        if ([string]$report.RequiredExtension -ne ".pdf") {
            throw "The first report-filing version supports PDF reports only."
        }
    }

    $configuration
}


function Get-WindowsDownloadsDirectory {
    [CmdletBinding()]
    param()

    $downloadsKnownFolderId = "{374DE290-123F-4565-9164-39C4925E467B}"
    $userShellFoldersPath = (
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\" +
        "User Shell Folders"
    )

    try {
        $properties = Get-ItemProperty `
            -LiteralPath $userShellFoldersPath `
            -ErrorAction Stop
        $downloadsValue = $properties.PSObject.Properties[
            $downloadsKnownFolderId
        ].Value

        if (-not [string]::IsNullOrWhiteSpace([string]$downloadsValue)) {
            $expandedPath = [Environment]::ExpandEnvironmentVariables(
                [string]$downloadsValue
            )

            if (Test-Path -LiteralPath $expandedPath -PathType Container) {
                return $expandedPath
            }
        }
    }
    catch {
        Write-ReportFilingLog `
            -Level "WARNING" `
            -Message "Could not resolve the Windows Downloads known folder."
    }

    if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        throw "Windows USERPROFILE is not available for this user."
    }

    $fallbackPath = Join-Path $env:USERPROFILE "Downloads"

    if (-not (Test-Path -LiteralPath $fallbackPath -PathType Container)) {
        throw "Downloads folder was not found: $fallbackPath"
    }

    $fallbackPath
}


function Resolve-ReportFilingBusinessRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$DestinationConfiguration
    )

    $environmentVariableName = [string](
        $DestinationConfiguration.RootEnvironmentVariable
    )
    $rootPath = [Environment]::GetEnvironmentVariable(
        $environmentVariableName
    )

    if ([string]::IsNullOrWhiteSpace($rootPath)) {
        if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            throw "Windows USERPROFILE is not available for this user."
        }

        $rootPath = Join-Path `
            $env:USERPROFILE `
            ([string]$DestinationConfiguration.RootFallbackDirectory)
    }

    if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) {
        throw @"
The Colorado School of Mines OneDrive folder was not found:
$rootPath

Confirm OneDrive is signed in and fully synchronized.
"@
    }

    Join-Path $rootPath ([string]$DestinationConfiguration.BusinessDirectory)
}


function Get-ReportSourceDate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$FileName,

        [Parameter(Mandatory)]
        [hashtable]$Report
    )

    $timestamp = [datetime]::MinValue
    if ([datetime]::TryParseExact(
        $FileName,
        [string]$Report.SourceTimestampFormat,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$timestamp
    )) {
        return $timestamp.Date
    }

    return $null
}


function Get-ReportDestinationProposal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [datetime]$ReportDate,

        [Parameter(Mandatory)]
        [string]$Initials,

        [Parameter(Mandatory)]
        [hashtable]$Report,

        [Parameter(Mandatory)]
        [hashtable]$DestinationConfiguration,

        [switch]$Bank2723
    )

    $fiscalPeriod = Get-MinesFiscalPeriod -Date $ReportDate
    $businessRoot = Resolve-ReportFilingBusinessRoot `
        -DestinationConfiguration $DestinationConfiguration
    $fiscalYearDirectoryName = (
        [string]$DestinationConfiguration.FiscalYearDirectoryPattern
    ).Replace(
        "{FiscalYear}",
        [string]$fiscalPeriod.FiscalYear
    ).Replace(
        "{FiscalYearTwoDigit}",
        [string]$fiscalPeriod.FiscalYearTwoDigit
    )
    $fiscalYearDirectory = Join-Path $businessRoot $fiscalYearDirectoryName
    $periodDirectory = Join-Path `
        $fiscalYearDirectory `
        $fiscalPeriod.PeriodDirectoryName
    $normalizedInitials = $Initials.Trim().ToUpperInvariant()
    $bankSuffix = if ($Bank2723) { " 2723" } else { "" }
    $fileName = "{0}_{1} {2}{3}.pdf" -f `
        $ReportDate.ToString("MM-dd-yyyy"),
        $normalizedInitials,
        ([string]$Report.DestinationSuffix),
        $bankSuffix

    [pscustomobject]@{
        ReportDate             = $ReportDate.Date
        FiscalYear             = $fiscalPeriod.FiscalYear
        FiscalYearDirectory    = $fiscalYearDirectory
        Period                 = $fiscalPeriod.PeriodCode
        PeriodDirectory        = $periodDirectory
        PeriodDirectoryName    = $fiscalPeriod.PeriodDirectoryName
        FileName               = $fileName
        FullPath               = Join-Path $periodDirectory $fileName
    }
}


function Wait-ReportFileReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [hashtable]$WatcherConfiguration
    )

    $deadline = (Get-Date).AddSeconds(
        [int]$WatcherConfiguration.StableTimeoutSeconds
    )
    $requiredChecks = [int]$WatcherConfiguration.RequiredStableChecks
    $stableChecks = 0
    $previousLength = -1L

    while ((Get-Date) -lt $deadline) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            return $null
        }

        try {
            $file = Get-Item -LiteralPath $Path -ErrorAction Stop
            $stream = [System.IO.File]::Open(
                $file.FullName,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::None
            )
            $stream.Close()
            $stream.Dispose()

            if ($file.Length -gt 0 -and $file.Length -eq $previousLength) {
                $stableChecks++
            }
            else {
                $stableChecks = 0
            }

            $previousLength = $file.Length

            if ($stableChecks -ge $requiredChecks) {
                return Get-Item -LiteralPath $Path
            }
        }
        catch {
            $stableChecks = 0
        }

        Start-Sleep -Seconds (
            [int]$WatcherConfiguration.StableCheckIntervalSeconds
        )
    }

    return $null
}


function Test-PdfFileSignature {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $stream = $null

    try {
        $stream = [System.IO.File]::OpenRead($Path)
        $buffer = New-Object byte[] 5
        $bytesRead = $stream.Read($buffer, 0, $buffer.Length)

        if ($bytesRead -ne 5) {
            return $false
        }

        [Text.Encoding]::ASCII.GetString($buffer) -eq "%PDF-"
    }
    finally {
        if ($null -ne $stream) {
            $stream.Close()
            $stream.Dispose()
        }
    }
}


function Get-ReportFileFingerprint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.IO.FileInfo]$File
    )

    [pscustomobject]@{
        Path             = $File.FullName
        Length           = $File.Length
        LastWriteTimeUtc = $File.LastWriteTimeUtc.ToString("o")
        Sha256           = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
    }
}


function Get-ReportFilingStatePath {
    [CmdletBinding()]
    param()

    Join-Path (Get-ReportFilingLocalDirectory) "state.json"
}


function Read-ReportFilingState {
    [CmdletBinding()]
    param()

    $statePath = Get-ReportFilingStatePath

    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]@{ Ignored = @() }
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw |
            ConvertFrom-Json -ErrorAction Stop
        return [pscustomobject]@{ Ignored = @($state.Ignored) }
    }
    catch {
        Write-ReportFilingLog `
            -Level "WARNING" `
            -Message "Ignored-file state was invalid and will be rebuilt."
        return [pscustomobject]@{ Ignored = @() }
    }
}


function Test-ReportFingerprintIgnored {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$Fingerprint
    )

    $state = Read-ReportFilingState

    foreach ($ignored in @($state.Ignored)) {
        if (
            [string]$ignored.Path -eq $Fingerprint.Path -and
            [long]$ignored.Length -eq $Fingerprint.Length -and
            [string]$ignored.LastWriteTimeUtc -eq $Fingerprint.LastWriteTimeUtc -and
            [string]$ignored.Sha256 -eq $Fingerprint.Sha256
        ) {
            return $true
        }
    }

    return $false
}


function Add-IgnoredReportFingerprint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$Fingerprint
    )

    $state = Read-ReportFilingState
    $retained = @(
        $state.Ignored |
            Where-Object {
                -not (
                    [string]$_.Path -eq $Fingerprint.Path -and
                    [string]$_.Sha256 -eq $Fingerprint.Sha256
                )
            } |
            Select-Object -Last 199
    )
    $retained += [pscustomobject]@{
        Path             = $Fingerprint.Path
        Length           = $Fingerprint.Length
        LastWriteTimeUtc = $Fingerprint.LastWriteTimeUtc
        Sha256           = $Fingerprint.Sha256
        IgnoredAt        = (Get-Date).ToString("o")
    }

    $statePath = Get-ReportFilingStatePath
    $temporaryPath = "$statePath.tmp"

    [ordered]@{
        SchemaVersion = 1
        Ignored       = $retained
    } |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $temporaryPath -Encoding UTF8

    Move-Item `
        -LiteralPath $temporaryPath `
        -Destination $statePath `
        -Force
}


function Show-ReportFilingMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message,

        [string]$Title = "HigherEd Automation",

        [ValidateSet("Information", "Warning", "Error")]
        [string]$Icon = "Information"
    )

    Add-Type -AssemblyName System.Windows.Forms

    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        ([System.Windows.Forms.MessageBoxIcon]$Icon)
    ) | Out-Null
}


function Show-ReportFilingConfirmation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.IO.FileInfo]$File,

        [Parameter(Mandatory)]
        [hashtable]$Report,

        [Parameter(Mandatory)]
        [hashtable]$DestinationConfiguration,

        [Parameter(Mandatory)]
        [psobject]$UserSettings,

        [Parameter(Mandatory)]
        [datetime]$ReportDate
    )

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Confirm Cashier Report Filing"
    $form.StartPosition = "CenterScreen"
    $form.Size = New-Object System.Drawing.Size(940, 680)
    $form.MinimumSize = New-Object System.Drawing.Size(940, 680)
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

    $heading = New-Object System.Windows.Forms.Label
    $heading.Text = "Please verify every detail before this file is moved."
    $heading.Font = New-Object System.Drawing.Font("Segoe UI", 15, [Drawing.FontStyle]::Bold)
    $heading.AutoSize = $true
    $heading.Location = New-Object System.Drawing.Point(25, 20)
    $form.Controls.Add($heading)

    $taskLabel = New-Object System.Windows.Forms.Label
    $taskLabel.Text = "Task: $($Report.DisplayName)"
    $taskLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [Drawing.FontStyle]::Bold)
    $taskLabel.AutoSize = $true
    $taskLabel.Location = New-Object System.Drawing.Point(27, 60)
    $form.Controls.Add($taskLabel)

    $sourceLabel = New-Object System.Windows.Forms.Label
    $sourceLabel.Text = "Downloaded file"
    $sourceLabel.AutoSize = $true
    $sourceLabel.Location = New-Object System.Drawing.Point(27, 98)
    $form.Controls.Add($sourceLabel)

    $sourceBox = New-Object System.Windows.Forms.TextBox
    $sourceBox.Text = $File.FullName
    $sourceBox.ReadOnly = $true
    $sourceBox.Location = New-Object System.Drawing.Point(30, 122)
    $sourceBox.Size = New-Object System.Drawing.Size(860, 30)
    $sourceBox.BackColor = [Drawing.Color]::White
    $form.Controls.Add($sourceBox)

    $dateLabel = New-Object System.Windows.Forms.Label
    $dateLabel.Text = "Report/deposit date"
    $dateLabel.AutoSize = $true
    $dateLabel.Location = New-Object System.Drawing.Point(27, 172)
    $form.Controls.Add($dateLabel)

    $datePicker = New-Object System.Windows.Forms.DateTimePicker
    $datePicker.Format = [System.Windows.Forms.DateTimePickerFormat]::Long
    $datePicker.Value = $ReportDate.Date
    $datePicker.Location = New-Object System.Drawing.Point(30, 198)
    $datePicker.Size = New-Object System.Drawing.Size(380, 30)
    $form.Controls.Add($datePicker)

    $initialsLabel = New-Object System.Windows.Forms.Label
    $initialsLabel.Text = "Cashier initials"
    $initialsLabel.AutoSize = $true
    $initialsLabel.Location = New-Object System.Drawing.Point(457, 172)
    $form.Controls.Add($initialsLabel)

    $initialsBox = New-Object System.Windows.Forms.TextBox
    $initialsBox.Text = $UserSettings.Initials
    $initialsBox.CharacterCasing = "Upper"
    $initialsBox.MaxLength = 6
    $initialsBox.Location = New-Object System.Drawing.Point(460, 198)
    $initialsBox.Size = New-Object System.Drawing.Size(150, 30)
    $form.Controls.Add($initialsBox)

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Default set by: $($UserSettings.DisplayName)"
    $nameLabel.AutoSize = $true
    $nameLabel.ForeColor = [Drawing.Color]::DimGray
    $nameLabel.Location = New-Object System.Drawing.Point(625, 202)
    $form.Controls.Add($nameLabel)

    $bankBox = New-Object System.Windows.Forms.CheckBox
    $bankBox.Text = "Bank 2723 (append to filename)"
    $bankBox.AutoSize = $true
    $bankBox.Location = New-Object System.Drawing.Point(460, 245)
    $form.Controls.Add($bankBox)

    $newNameLabel = New-Object System.Windows.Forms.Label
    $newNameLabel.Text = "New filename"
    $newNameLabel.AutoSize = $true
    $newNameLabel.Location = New-Object System.Drawing.Point(27, 252)
    $form.Controls.Add($newNameLabel)

    $newNameBox = New-Object System.Windows.Forms.TextBox
    $newNameBox.ReadOnly = $true
    $newNameBox.Location = New-Object System.Drawing.Point(30, 276)
    $newNameBox.Size = New-Object System.Drawing.Size(860, 30)
    $newNameBox.BackColor = [Drawing.Color]::LightYellow
    $newNameBox.Font = New-Object System.Drawing.Font("Segoe UI", 11, [Drawing.FontStyle]::Bold)
    $form.Controls.Add($newNameBox)

    $destinationLabel = New-Object System.Windows.Forms.Label
    $destinationLabel.Text = "Complete destination"
    $destinationLabel.AutoSize = $true
    $destinationLabel.Location = New-Object System.Drawing.Point(27, 330)
    $form.Controls.Add($destinationLabel)

    $destinationBox = New-Object System.Windows.Forms.TextBox
    $destinationBox.ReadOnly = $true
    $destinationBox.Multiline = $true
    $destinationBox.WordWrap = $true
    $destinationBox.ScrollBars = "Vertical"
    $destinationBox.Location = New-Object System.Drawing.Point(30, 354)
    $destinationBox.Size = New-Object System.Drawing.Size(860, 95)
    $destinationBox.BackColor = [Drawing.Color]::LightYellow
    $destinationBox.Font = New-Object System.Drawing.Font("Segoe UI", 10, [Drawing.FontStyle]::Bold)
    $form.Controls.Add($destinationBox)

    $instructionLabel = New-Object System.Windows.Forms.Label
    $instructionLabel.Text = (
        "Is the name correct? Change the initials when filing for someone else. " +
        "Select Bank 2723 only when needed. " +
        "Changing the date updates the fiscal year, period, and filename."
    )
    $instructionLabel.AutoSize = $false
    $instructionLabel.Size = New-Object System.Drawing.Size(860, 50)
    $instructionLabel.Location = New-Object System.Drawing.Point(30, 470)
    $instructionLabel.ForeColor = [Drawing.Color]::DarkBlue
    $form.Controls.Add($instructionLabel)

    $selection = [ordered]@{
        Action   = "Cancel"
        Proposal = $null
        Initials = $null
    }

    $updatePreview = {
        try {
            $previewInitials = $initialsBox.Text.Trim().ToUpperInvariant()

            if ([string]::IsNullOrWhiteSpace($previewInitials)) {
                $previewInitials = "INITIALS"
            }

            $proposal = Get-ReportDestinationProposal `
                -ReportDate $datePicker.Value.Date `
                -Initials $previewInitials `
                -Bank2723:$bankBox.Checked `
                -Report $Report `
                -DestinationConfiguration $DestinationConfiguration
            $newNameBox.Text = $proposal.FileName
            $destinationBox.Text = $proposal.FullPath
        }
        catch {
            $newNameBox.Text = "Configuration error"
            $destinationBox.Text = $_.Exception.Message
        }
    }

    $datePicker.Add_ValueChanged($updatePreview)
    $initialsBox.Add_TextChanged($updatePreview)
    $bankBox.Add_CheckedChanged($updatePreview)
    & $updatePreview

    $confirmButton = New-Object System.Windows.Forms.Button
    $confirmButton.Text = "Confirm and Move"
    $confirmButton.Size = New-Object System.Drawing.Size(210, 52)
    $confirmButton.Location = New-Object System.Drawing.Point(440, 545)
    $confirmButton.BackColor = [Drawing.Color]::PaleGreen
    $confirmButton.Font = New-Object System.Drawing.Font("Segoe UI", 11, [Drawing.FontStyle]::Bold)
    $form.Controls.Add($confirmButton)

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel - Leave File"
    $cancelButton.Size = New-Object System.Drawing.Size(210, 52)
    $cancelButton.Location = New-Object System.Drawing.Point(680, 545)
    $form.Controls.Add($cancelButton)

    $confirmButton.Add_Click({
        $normalizedInitials = $initialsBox.Text.Trim().ToUpperInvariant()

        if ($normalizedInitials -notmatch '^[A-Z]{2,6}$') {
            Show-ReportFilingMessage `
                -Title "Check Cashier Initials" `
                -Icon "Warning" `
                -Message "Enter 2 through 6 letters for the cashier initials."
            return
        }

        try {
            $proposal = Get-ReportDestinationProposal `
                -ReportDate $datePicker.Value.Date `
                -Initials $normalizedInitials `
                -Bank2723:$bankBox.Checked `
                -Report $Report `
                -DestinationConfiguration $DestinationConfiguration
        }
        catch {
            Show-ReportFilingMessage `
                -Title "Destination Could Not Be Calculated" `
                -Icon "Error" `
                -Message $_.Exception.Message
            return
        }

        if (-not (
            Test-Path `
                -LiteralPath $proposal.PeriodDirectory `
                -PathType Container
        )) {
            Show-ReportFilingMessage `
                -Title "Destination Folder Is Missing" `
                -Icon "Error" `
                -Message @"
The file was not moved because this folder does not exist:

$($proposal.PeriodDirectory)

Choose the correct report date or ask your supervisor to create the folder.
"@
            return
        }

        if (Test-Path -LiteralPath $proposal.FullPath) {
            Show-ReportFilingMessage `
                -Title "File Already Exists" `
                -Icon "Error" `
                -Message @"
The file was not moved because this destination already exists:

$($proposal.FullPath)

No file was overwritten. Ask your supervisor to review both files.
"@
            return
        }

        $selection.Action = "Confirm"
        $selection.Proposal = $proposal
        $selection.Initials = $normalizedInitials
        $form.Close()
    })

    $cancelButton.Add_Click({
        $selection.Action = "Cancel"
        $form.Close()
    })

    $form.Add_FormClosing({
        if ($selection.Action -ne "Confirm") {
            $selection.Action = "Cancel"
        }
    })

    $form.AcceptButton = $confirmButton
    $form.CancelButton = $cancelButton
    $form.ShowDialog() | Out-Null
    $form.Dispose()

    [pscustomobject]$selection
}


function Move-ReportFileSafely {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.IO.FileInfo]$SourceFile,

        [Parameter(Mandatory)]
        [string]$DestinationPath
    )

    if (Test-Path -LiteralPath $DestinationPath) {
        throw "Destination already exists; no file was overwritten: $DestinationPath"
    }

    $destinationDirectory = Split-Path -Parent $DestinationPath

    if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
        throw "Destination folder does not exist: $destinationDirectory"
    }

    $temporaryName = ".{0}.{1}.partial" -f `
        ([System.IO.Path]::GetFileName($DestinationPath)),
        ([guid]::NewGuid().ToString("N"))
    $temporaryPath = Join-Path $destinationDirectory $temporaryName

    try {
        Copy-Item `
            -LiteralPath $SourceFile.FullName `
            -Destination $temporaryPath `
            -ErrorAction Stop

        $sourceHash = (Get-FileHash `
            -LiteralPath $SourceFile.FullName `
            -Algorithm SHA256).Hash
        $copiedHash = (Get-FileHash `
            -LiteralPath $temporaryPath `
            -Algorithm SHA256).Hash

        if ($sourceHash -ne $copiedHash) {
            throw "Copied-file verification failed. The Downloads file was preserved."
        }

        Move-Item `
            -LiteralPath $temporaryPath `
            -Destination $DestinationPath `
            -ErrorAction Stop
    }
    catch {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }

        throw
    }

    $sourceRemoved = $true

    try {
        Remove-Item `
            -LiteralPath $SourceFile.FullName `
            -Force `
            -ErrorAction Stop
    }
    catch {
        $sourceRemoved = $false
    }

    [pscustomobject]@{
        DestinationPath = $DestinationPath
        SourceRemoved   = $sourceRemoved
    }
}


function Invoke-ReportFilingCandidate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [hashtable]$Configuration,

        [Parameter(Mandatory)]
        [psobject]$UserSettings
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }

    $candidateName = [System.IO.Path]::GetFileName($Path)
    $matchingReports = @(
        $Configuration.Reports |
            Where-Object {
                $candidateName -like ([string]$_.SourceFilePattern) -and
                $null -ne (Get-ReportSourceDate -FileName $candidateName -Report $_)
            }
    )

    if ($matchingReports.Count -eq 0) {
        return
    }

    if ($matchingReports.Count -gt 1) {
        Write-ReportFilingLog `
            -Level "ERROR" `
            -Message "File matched multiple report definitions and was left in place: $Path"
        return
    }

    $report = $matchingReports[0]
    $extension = [System.IO.Path]::GetExtension($Path)

    if ($extension -ine ([string]$report.RequiredExtension)) {
        return
    }

    $readyFile = Wait-ReportFileReady `
        -Path $Path `
        -WatcherConfiguration $Configuration.Watcher

    if ($null -eq $readyFile) {
        Write-ReportFilingLog `
            -Level "WARNING" `
            -Message "Matching file did not become ready and was left in place: $Path"
        return
    }

    if (-not (Test-PdfFileSignature -Path $readyFile.FullName)) {
        Write-ReportFilingLog `
            -Level "ERROR" `
            -Message "Matching file did not contain a PDF signature: $Path"
        Show-ReportFilingMessage `
            -Title "Downloaded File Is Not a Valid PDF" `
            -Icon "Error" `
            -Message @"
This filename matched $($report.DisplayName), but the file is not a valid PDF:

$($readyFile.FullName)

The file was left in Downloads. Download the report again or ask your supervisor.
"@
        return
    }

    $fingerprint = Get-ReportFileFingerprint -File $readyFile

    if (Test-ReportFingerprintIgnored -Fingerprint $fingerprint) {
        return
    }

    $selection = Show-ReportFilingConfirmation `
        -File $readyFile `
        -Report $report `
        -DestinationConfiguration $Configuration.Destination `
        -UserSettings $UserSettings `
        -ReportDate (Get-ReportSourceDate -FileName $candidateName -Report $report)

    if ($selection.Action -ne "Confirm") {
        Add-IgnoredReportFingerprint -Fingerprint $fingerprint
        Write-ReportFilingLog "User cancelled; unchanged file will not prompt again: $Path"
        return
    }

    $currentFile = Get-Item -LiteralPath $readyFile.FullName -ErrorAction Stop
    $currentFingerprint = Get-ReportFileFingerprint -File $currentFile

    if (
        $currentFingerprint.Length -ne $fingerprint.Length -or
        $currentFingerprint.LastWriteTimeUtc -ne $fingerprint.LastWriteTimeUtc -or
        $currentFingerprint.Sha256 -ne $fingerprint.Sha256
    ) {
        Show-ReportFilingMessage `
            -Title "File Changed Before It Could Be Moved" `
            -Icon "Warning" `
            -Message "The Downloads file changed after confirmation. It was left in place."
        return
    }

    try {
        $moveResult = Move-ReportFileSafely `
            -SourceFile $currentFile `
            -DestinationPath $selection.Proposal.FullPath
    }
    catch {
        Write-ReportFilingLog `
            -Level "ERROR" `
            -Message "Verified transfer failed: $($_.Exception.Message)"
        Show-ReportFilingMessage `
            -Title "File Was Not Moved" `
            -Icon "Error" `
            -Message $_.Exception.Message
        return
    }

    Write-ReportFilingLog "Report filed successfully: $($moveResult.DestinationPath)"

    if ($moveResult.SourceRemoved) {
        Show-ReportFilingMessage `
            -Title "Report Filed Successfully" `
            -Message @"
The report was verified and moved to:

$($moveResult.DestinationPath)
"@
    }
    else {
        Show-ReportFilingMessage `
            -Title "Report Copied - Downloads Copy Remains" `
            -Icon "Warning" `
            -Message @"
The verified report is here:

$($moveResult.DestinationPath)

Windows could not remove the original Downloads copy. Ask your supervisor to review it.
"@
    }
}


function Invoke-ExistingReportFilingCandidates {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DownloadsDirectory,

        [Parameter(Mandatory)]
        [hashtable]$Configuration,

        [Parameter(Mandatory)]
        [psobject]$UserSettings
    )

    $minimumWriteTime = (Get-Date).AddDays(
        -[int]$Configuration.Watcher.ExistingFileLookbackDays
    )
    $seenPaths = @{}

    foreach ($report in @($Configuration.Reports)) {
        $files = Get-ChildItem `
            -LiteralPath $DownloadsDirectory `
            -File `
            -Filter ([string]$report.SourceFilePattern) `
            -ErrorAction SilentlyContinue

        foreach ($file in @($files)) {
            if ($file.LastWriteTime -lt $minimumWriteTime) {
                continue
            }

            if ($seenPaths.ContainsKey($file.FullName)) {
                continue
            }

            $seenPaths[$file.FullName] = $true
            Invoke-ReportFilingCandidate `
                -Path $file.FullName `
                -Configuration $Configuration `
                -UserSettings $UserSettings
        }
    }
}


function Start-ReportFilingWatcher {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ConfigurationPath,

        [string]$DownloadsDirectory
    )

    $mutexName = "Local\HigherEdAutomation.ReportFilingWatcher.$env:USERNAME"
    $mutex = New-Object System.Threading.Mutex($false, $mutexName)
    $ownsMutex = $false
    $watcher = $null
    $subscriptions = $null

    try {
        $ownsMutex = $mutex.WaitOne(0)

        if (-not $ownsMutex) {
            return
        }

        $configuration = Get-ReportFilingConfiguration -Path $ConfigurationPath
        $userSettings = Read-AutomationUserSettings

        if ([string]::IsNullOrWhiteSpace($DownloadsDirectory)) {
            $DownloadsDirectory = Get-WindowsDownloadsDirectory
        }

        if (-not (
            Test-Path `
                -LiteralPath $DownloadsDirectory `
                -PathType Container
        )) {
            throw "Downloads folder was not found: $DownloadsDirectory"
        }

        Write-ReportFilingLog "Watcher started for: $DownloadsDirectory"

        $watcher = New-Object System.IO.FileSystemWatcher
        $watcher.Path = $DownloadsDirectory
        $watcher.Filter = "*"
        $watcher.IncludeSubdirectories = $false
        $watcher.NotifyFilter = (
            [System.IO.NotifyFilters]::FileName -bor
            [System.IO.NotifyFilters]::LastWrite -bor
            [System.IO.NotifyFilters]::Size
        )

        $eventPrefix = "HigherEdReportFiling.$PID"
        $subscriptions = @(
            Register-ObjectEvent `
                -InputObject $watcher `
                -EventName Created `
                -SourceIdentifier "$eventPrefix.Created"
            Register-ObjectEvent `
                -InputObject $watcher `
                -EventName Renamed `
                -SourceIdentifier "$eventPrefix.Renamed"
            Register-ObjectEvent `
                -InputObject $watcher `
                -EventName Error `
                -SourceIdentifier "$eventPrefix.Error"
        )

        $watcher.EnableRaisingEvents = $true

        Invoke-ExistingReportFilingCandidates `
            -DownloadsDirectory $DownloadsDirectory `
            -Configuration $configuration `
            -UserSettings $userSettings

        while ($true) {
            $event = Wait-Event -Timeout 5

            if ($null -eq $event) {
                continue
            }

            if (-not $event.SourceIdentifier.StartsWith($eventPrefix)) {
                continue
            }

            try {
                if ($event.SourceIdentifier -eq "$eventPrefix.Error") {
                    Write-ReportFilingLog `
                        -Level "WARNING" `
                        -Message "Watcher reported an error; running a catch-up scan."
                    Invoke-ExistingReportFilingCandidates `
                        -DownloadsDirectory $DownloadsDirectory `
                        -Configuration $configuration `
                        -UserSettings $userSettings
                }
                else {
                    Invoke-ReportFilingCandidate `
                        -Path ([string]$event.SourceEventArgs.FullPath) `
                        -Configuration $configuration `
                        -UserSettings $userSettings
                }
            }
            catch {
                Write-ReportFilingLog `
                    -Level "ERROR" `
                    -Message "Candidate processing failed: $($_.Exception.Message)"
            }
            finally {
                Remove-Event -EventIdentifier $event.EventIdentifier -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        if ($null -ne $subscriptions) {
            foreach ($subscription in @($subscriptions)) {
                Unregister-Event `
                    -SubscriptionId $subscription.SubscriptionId `
                    -ErrorAction SilentlyContinue
            }
        }

        if ($null -ne $watcher) {
            $watcher.EnableRaisingEvents = $false
            $watcher.Dispose()
        }

        if ($ownsMutex) {
            $mutex.ReleaseMutex()
        }

        $mutex.Dispose()
    }
}


Export-ModuleMember -Function @(
    "Get-ReportFilingConfiguration",
    "Get-ReportDestinationProposal",
    "Get-ReportSourceDate",
    "Get-WindowsDownloadsDirectory",
    "Invoke-ReportFilingCandidate",
    "Start-ReportFilingWatcher"
)
