$ErrorActionPreference = "Stop"

# Resolve repository root from this file's location:
# powershell/setup/setup_profile.ps1 -> repo root
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$ShortcutPath = Join-Path $ProjectRoot "powershell\shortcuts\profile_shortcuts.ps1"

if (-not (Test-Path $ShortcutPath)) {
    throw "Shortcut file not found at: $ShortcutPath"
}

# Create the user's PowerShell profile if it does not already exist
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
}

$Marker = "# Automation Repository Shortcuts"

# Prevent duplicate shortcut blocks
if (Select-String -Path $PROFILE -Pattern $Marker -SimpleMatch -Quiet) {
    Write-Host "Shortcuts are already installed."
    Write-Host "Reload shortcuts with:"
    Write-Host ". `$PROFILE"
    exit 0
}

# Read shortcuts from the shortcut file
$ShortcutContent = Get-Content -Path $ShortcutPath -Raw

# Replace placeholder with this user's actual repo location
$ProfileBlock = $ShortcutContent.Replace("{{PROJECT_ROOT}}", $ProjectRoot)

# Append shortcuts to the user's PowerShell profile
Add-Content -Path $PROFILE -Value "`n$ProfileBlock"

Write-Host ""
Write-Host "Shortcuts installed successfully."
Write-Host ""
Write-Host "Next, run:"
Write-Host ". `$PROFILE"
Write-Host ""
Write-Host "Then you can use:"
Write-Host "open-auto"
Write-Host "start-setup"
Write-Host "banner.fgiglac"