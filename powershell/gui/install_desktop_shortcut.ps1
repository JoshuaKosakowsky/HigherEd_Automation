[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$windowedPython = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $windowedPython -PathType Leaf)) {
    throw "Windowed Python was not found: $windowedPython"
}

$desktopDirectory = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktopDirectory)) {
    throw "The Windows desktop folder could not be located."
}

$shortcutPath = Join-Path $desktopDirectory "Mines Bursar Automation.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $windowedPython
$shortcut.Arguments = "-m app.gui.runtime_check --launch"
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = "Open Mines Bursar Automation"
$shortcut.Save()

Write-Host "Desktop shortcut installed: $shortcutPath"
