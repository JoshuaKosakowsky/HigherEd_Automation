$ErrorActionPreference = "Stop"

# Resolve repository root from this file's location:
# powershell/credentials/setup_profile.ps1 -> repo root
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$ShortcutPath = Join-Path $ProjectRoot "powershell\shortcuts\profile_shortcuts.ps1"

if (-not (Test-Path $ShortcutPath)) {
    throw "Shortcut file not found at: $ShortcutPath"
}

# Create the user's PowerShell profile if it does not already exist.
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
}

$StartMarker = "# Automation Repository Shortcuts"
$EndMarker = "# End Automation Repository Shortcuts"

# Read shortcuts from the shortcut file.
$ShortcutContent = Get-Content -Path $ShortcutPath -Raw

# Replace the placeholder with this user's actual repository location.
$ProfileBlock = $ShortcutContent.Replace("{{PROJECT_ROOT}}", $ProjectRoot)
$ProfileContent = Get-Content -Path $PROFILE -Raw

if ($null -eq $ProfileContent) {
    $ProfileContent = ""
}

$ExistingStart = $ProfileContent.IndexOf($StartMarker)

if ($ExistingStart -ge 0) {
    $ExistingEnd = $ProfileContent.IndexOf(
        $EndMarker,
        $ExistingStart
    )

    if ($ExistingEnd -ge 0) {
        $afterBlock = $ExistingEnd + $EndMarker.Length
        $updatedContent = (
            $ProfileContent.Substring(0, $ExistingStart) +
            $ProfileBlock.TrimEnd() +
            $ProfileContent.Substring($afterBlock)
        )
    }
    else {
        # Older shortcut installations did not have an end marker and were
        # always appended to the end of the profile. Replace that legacy block.
        $updatedContent = (
            $ProfileContent.Substring(0, $ExistingStart).TrimEnd() +
            [Environment]::NewLine +
            [Environment]::NewLine +
            $ProfileBlock.TrimEnd() +
            [Environment]::NewLine
        )
    }

    if ($updatedContent -ceq $ProfileContent) {
        Write-Host "Automation shortcuts are already current."
    }
    else {
        $backupPath = "$PROFILE.highered-backup-$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Copy-Item -LiteralPath $PROFILE -Destination $backupPath
        Set-Content -LiteralPath $PROFILE -Value $updatedContent
        Write-Host "Existing automation shortcuts were updated."
        Write-Host "PowerShell profile backup: $backupPath"
    }
}
else {
    Add-Content -LiteralPath $PROFILE -Value "`n$($ProfileBlock.TrimEnd())`n"
    Write-Host "Automation shortcuts were installed."
}

Write-Host ""
Write-Host "Shortcut setup completed successfully."
Write-Host ""
Write-Host "The shortcuts load automatically in each new PowerShell window."
Write-Host "Available shortcuts:"
Write-Host "open-auto"
Write-Host "start-setup"
Write-Host "test-automation"
Write-Host "start-population-testing"
Write-Host "start-refunds"
Write-Host "start-trends"
Write-Host "start-textbook-brokers"
Write-Host "archive-textbook-brokers"
Write-Host "setup-report-watcher"
