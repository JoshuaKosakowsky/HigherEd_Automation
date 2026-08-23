function Get-AutomationUserSettingsPath {
    [CmdletBinding()]
    param()

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "Windows LOCALAPPDATA is not available for this user."
    }

    Join-Path `
        $env:LOCALAPPDATA `
        "HigherEdAutomation\user-settings.json"
}


function Test-AutomationUserSettingsValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DisplayName,

        [Parameter(Mandatory)]
        [string]$Initials
    )

    if ([string]::IsNullOrWhiteSpace($DisplayName)) {
        throw "Your name cannot be blank."
    }

    if ($DisplayName.Trim().Length -gt 100 -or $DisplayName -match '[\r\n]') {
        throw "Your name must be one line and no more than 100 characters."
    }

    if ($Initials.Trim() -notmatch '^[A-Za-z]{2,6}$') {
        throw "Initials must contain 2 through 6 letters with no spaces."
    }
}


function Save-AutomationUserSettings {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DisplayName,

        [Parameter(Mandatory)]
        [string]$Initials
    )

    Test-AutomationUserSettingsValue `
        -DisplayName $DisplayName `
        -Initials $Initials

    $settingsPath = Get-AutomationUserSettingsPath
    $settingsDirectory = Split-Path -Parent $settingsPath

    if (-not (Test-Path -LiteralPath $settingsDirectory -PathType Container)) {
        New-Item `
            -ItemType Directory `
            -Path $settingsDirectory `
            -Force |
            Out-Null
    }

    $settings = [ordered]@{
        SchemaVersion = 1
        DisplayName   = $DisplayName.Trim()
        Initials      = $Initials.Trim().ToUpperInvariant()
        UpdatedAt     = (Get-Date).ToString("o")
    }

    $temporaryPath = "$settingsPath.tmp"

    $settings |
        ConvertTo-Json |
        Set-Content -LiteralPath $temporaryPath -Encoding UTF8

    Move-Item `
        -LiteralPath $temporaryPath `
        -Destination $settingsPath `
        -Force

    [pscustomobject]$settings
}


function Read-AutomationUserSettings {
    [CmdletBinding()]
    param(
        [switch]$AllowMissing
    )

    $settingsPath = Get-AutomationUserSettingsPath

    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        if ($AllowMissing) {
            return $null
        }

        throw @"
Your automation user details have not been configured.

Run setup again from the HigherEd_Automation folder:
.\setup.ps1
"@
    }

    try {
        $settings = Get-Content `
            -LiteralPath $settingsPath `
            -Raw `
            -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "User settings could not be read: $settingsPath. $($_.Exception.Message)"
    }

    if ($settings.SchemaVersion -ne 1) {
        throw "Unsupported user-settings version in: $settingsPath"
    }

    Test-AutomationUserSettingsValue `
        -DisplayName ([string]$settings.DisplayName) `
        -Initials ([string]$settings.Initials)

    [pscustomobject]@{
        DisplayName  = ([string]$settings.DisplayName).Trim()
        Initials     = ([string]$settings.Initials).Trim().ToUpperInvariant()
        SettingsPath = $settingsPath
    }
}
