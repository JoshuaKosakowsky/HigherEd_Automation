[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$launcherPath = Join-Path $ProjectRoot "launcher\run_gui.ps1"
if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "The GUI launcher was not found: $launcherPath"
}

$powerShell = Get-Command powershell.exe -CommandType Application
$desktopDirectory = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktopDirectory)) {
    throw "The Windows desktop folder could not be located."
}

$shortcutPath = Join-Path $desktopDirectory "Mines Bursar Automation.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powerShell.Source
$shortcut.Arguments = (
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f `
        $launcherPath
)
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = "Open Mines Bursar Automation"
$shortcut.Save()

Write-Host "Desktop shortcut installed: $shortcutPath"
