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

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $probe = 'import json, sys; from pathlib import Path; print(json.dumps({"Path": str(Path(sys._base_executable).with_name("pythonw.exe"))}))'
    $interpreter = & $venvPython -c $probe
    if ($LASTEXITCODE -eq 0 -and $interpreter) {
        $baseWindowedPython = ($interpreter | Select-Object -Last 1 | ConvertFrom-Json).Path
        if ($baseWindowedPython -ne $windowedPython -and
            (Test-Path -LiteralPath $baseWindowedPython -PathType Leaf)) {
            $shortcut.TargetPath = $baseWindowedPython
            $shortcut.Arguments = "-m app.gui.runtime_check --bootstrap"
        }
    }
}
$shortcut.Save()

Write-Host "Desktop shortcut installed: $shortcutPath"
