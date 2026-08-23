[CmdletBinding()]
param(
    [string]$DownloadsDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$modulePath = Join-Path `
    $repositoryRoot `
    "workflows\report_filing\report_filing.psm1"
$configurationPath = Join-Path `
    $repositoryRoot `
    "config\report_filing.psd1"

if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
    throw "Report-filing module was not found: $modulePath"
}

Import-Module $modulePath -Force

try {
    Start-ReportFilingWatcher `
        -ConfigurationPath $configurationPath `
        -DownloadsDirectory $DownloadsDirectory
}
catch {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            "Report Filing Watcher Could Not Start",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    catch {
        Write-Error $_.Exception.Message
    }

    exit 1
}
