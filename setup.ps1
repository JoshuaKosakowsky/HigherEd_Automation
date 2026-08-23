[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
$UserSettingsScript = Join-Path $ProjectRoot "shared\user_settings.ps1"
$MinimumPythonVersion = [version]"3.11"
$StepNumber = 0
$StepCount = 6


function Write-SetupStep {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    $script:StepNumber++
    Write-Host ""
    Write-Host "[$script:StepNumber/$StepCount] $Message" -ForegroundColor Cyan
}


function Invoke-CheckedCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Command,

        [string[]]$Arguments = @(),

        [Parameter(Mandatory)]
        [string]$FailureMessage
    )

    & $Command @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE."
    }
}


function Get-PythonLauncher {
    [CmdletBinding()]
    param()

    $candidates = @(
        [pscustomobject]@{
            Command   = "py"
            Arguments = @("-3")
        }
        [pscustomobject]@{
            Command   = "python"
            Arguments = @()
        }
    )

    foreach ($candidate in $candidates) {
        $commandInfo = Get-Command `
            $candidate.Command `
            -CommandType Application `
            -ErrorAction SilentlyContinue

        if ($null -eq $commandInfo) {
            continue
        }

        $versionArguments = @($candidate.Arguments) + @(
            "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        )

        $versionText = & $commandInfo.Source @versionArguments 2>$null

        if ($LASTEXITCODE -ne 0 -or -not $versionText) {
            continue
        }

        try {
            $version = [version]($versionText | Select-Object -Last 1)
        }
        catch {
            continue
        }

        if ($version -lt $MinimumPythonVersion) {
            Write-Host (
                "Found Python {0}, but Python {1} or newer is required." -f `
                    $version,
                    $MinimumPythonVersion
            ) -ForegroundColor Yellow
            continue
        }

        return [pscustomobject]@{
            Command   = $commandInfo.Source
            Arguments = @($candidate.Arguments)
            Version   = $version
        }
    }

    throw @"
Python $MinimumPythonVersion or newer was not found.

Install the current 64-bit version of Python from:
https://www.python.org/downloads/windows/

During installation, select "Add python.exe to PATH". Then close PowerShell,
open it again, return to this folder, and run .\setup.ps1.
"@
}


function Get-InstalledPythonVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PythonExecutable
    )

    $versionText = & $PythonExecutable `
        -c `
        "import sys; print('.'.join(map(str, sys.version_info[:3])))"

    if ($LASTEXITCODE -ne 0 -or -not $versionText) {
        throw "The existing Python environment could not be started: $PythonExecutable"
    }

    return [version]($versionText | Select-Object -Last 1)
}


function Read-YesNoSetupResponse {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Prompt,

        [bool]$DefaultYes = $true
    )

    $defaultLabel = if ($DefaultYes) { "Y/n" } else { "y/N" }

    while ($true) {
        $response = (Read-Host "$Prompt [$defaultLabel]").Trim()

        if ([string]::IsNullOrWhiteSpace($response)) {
            return $DefaultYes
        }

        switch ($response.ToUpperInvariant()) {
            "Y" { return $true }
            "YES" { return $true }
            "N" { return $false }
            "NO" { return $false }
            default {
                Write-Host "Please enter Y for Yes or N for No." -ForegroundColor Yellow
            }
        }
    }
}


function Set-UpAutomationUserDetails {
    [CmdletBinding()]
    param()

    $existingSettings = Read-AutomationUserSettings -AllowMissing

    if ($null -ne $existingSettings) {
        Write-Host "Existing name: $($existingSettings.DisplayName)"
        Write-Host "Existing initials: $($existingSettings.Initials)"

        if (Read-YesNoSetupResponse -Prompt "Keep these user details?") {
            Write-Host "Existing user details were kept."
            return
        }
    }

    while ($true) {
        $displayName = (Read-Host "Enter your full name").Trim()
        $initials = (Read-Host "Enter your initials (2-6 letters)").Trim()

        try {
            Test-AutomationUserSettingsValue `
                -DisplayName $displayName `
                -Initials $initials
        }
        catch {
            Write-Host $_.Exception.Message -ForegroundColor Yellow
            Write-Host "Please try again."
            Write-Host ""
            continue
        }

        $normalizedInitials = $initials.ToUpperInvariant()
        Write-Host ""
        Write-Host "Name: $displayName"
        Write-Host "Default initials: $normalizedInitials"

        if (-not (Read-YesNoSetupResponse -Prompt "Are these details correct?")) {
            Write-Host "Please enter the details again."
            Write-Host ""
            continue
        }

        Save-AutomationUserSettings `
            -DisplayName $displayName `
            -Initials $normalizedInitials |
            Out-Null

        Write-Host "User details saved for this Windows account."
        return
    }
}


$startingLocation = Get-Location

try {
    Write-Host ""
    Write-Host "HigherEd Automation Setup" -ForegroundColor Cyan
    Write-Host "=========================" -ForegroundColor Cyan
    Write-Host "Project folder: $ProjectRoot"
    Write-Host ""
    Write-Host "This may take several minutes. Keep this window open."

    if (-not (Test-Path -LiteralPath $RequirementsFile -PathType Leaf)) {
        throw @"
The repository is incomplete because requirements.txt was not found:
$RequirementsFile

Download or synchronize the complete HigherEd_Automation folder and try again.
"@
    }

    if (-not (Test-Path -LiteralPath $UserSettingsScript -PathType Leaf)) {
        throw "The repository is incomplete because this file was not found: $UserSettingsScript"
    }

    . $UserSettingsScript

    Set-Location $ProjectRoot

    Write-SetupStep "Checking Python and creating the local environment"

    if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
        $installedVersion = Get-InstalledPythonVersion `
            -PythonExecutable $VenvPython

        if ($installedVersion -lt $MinimumPythonVersion) {
            throw @"
The existing .venv uses Python $installedVersion, but Python
$MinimumPythonVersion or newer is required.

Rename or remove this folder and run setup again:
$VenvDir
"@
        }

        Write-Host "Existing environment found. Python $installedVersion"
    }
    elseif (Test-Path -LiteralPath $VenvDir) {
        throw @"
The .venv folder exists, but its Python executable is missing:
$VenvPython

The environment appears incomplete. Rename or remove the .venv folder,
then run .\setup.ps1 again.
"@
    }
    else {
        $pythonLauncher = Get-PythonLauncher
        Write-Host "Using Python $($pythonLauncher.Version): $($pythonLauncher.Command)"

        $createArguments = @($pythonLauncher.Arguments) + @(
            "-m",
            "venv",
            $VenvDir
        )

        Invoke-CheckedCommand `
            -Command $pythonLauncher.Command `
            -Arguments $createArguments `
            -FailureMessage "Python could not create the local environment."

        if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
            throw "The local environment was not created correctly: $VenvPython"
        }

        Write-Host "Local Python environment created."
    }

    Write-SetupStep "Updating Python's installer"
    Invoke-CheckedCommand `
        -Command $VenvPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
        -FailureMessage "pip could not be updated. Check your internet connection."

    Write-SetupStep "Installing required Python packages"
    Invoke-CheckedCommand `
        -Command $VenvPython `
        -Arguments @("-m", "pip", "install", "-r", $RequirementsFile) `
        -FailureMessage (
            "Required packages could not be installed. " +
            "Check your internet connection and try again."
        )

    Write-SetupStep "Verifying the installation"
    $verificationCode = @"
import dotenv
import keyring
import numpy
import openpyxl
import pandas
import requests
from playwright.sync_api import sync_playwright
"@

    Invoke-CheckedCommand `
        -Command $VenvPython `
        -Arguments @("-c", $verificationCode) `
        -FailureMessage "One or more required Python packages could not be imported."

    Write-Host "Required Python packages are available." -ForegroundColor Green

    Write-SetupStep "Installing Playwright browser support"
    Invoke-CheckedCommand `
        -Command $VenvPython `
        -Arguments @("-m", "playwright", "install") `
        -FailureMessage (
            "Playwright browser support could not be installed. " +
            "Check your internet connection and try again."
        )

    Write-SetupStep "Saving your name and initials"
    Set-UpAutomationUserDetails

    Write-Host ""
    Write-Host "SETUP COMPLETE" -ForegroundColor Green
    Write-Host "==============" -ForegroundColor Green
    Write-Host "The automation tools are ready on this computer."
    Write-Host ""
    Write-Host "You do not need to activate Python manually."
    Write-Host ""
    Write-Host "NEXT STEP: install the required PowerShell shortcuts:"
    Write-Host ".\powershell\credentials\setup_profile.ps1"
    Write-Host ""
    Write-Host "Then load them into this PowerShell window:"
    Write-Host ". `$PROFILE"
}
catch {
    Write-Host ""
    Write-Host "SETUP DID NOT COMPLETE" -ForegroundColor Red
    Write-Host "======================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Correct the problem above, then run .\setup.ps1 again."
    exit 1
}
finally {
    Set-Location $startingLocation
}
