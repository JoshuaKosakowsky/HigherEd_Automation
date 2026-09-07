$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtimeScript = Join-Path $repositoryRoot "powershell\gui\tk_runtime.ps1"

. $runtimeScript


function Assert-Equal {
    param(
        [Parameter(Mandatory)]
        [object]$Expected,

        [Parameter(Mandatory)]
        [object]$Actual,

        [Parameter(Mandatory)]
        [string]$Case
    )

    if ($Expected -ne $Actual) {
        throw (
            "FAILED: {0}. Expected {1}; received {2}." -f `
                $Case,
                $Expected,
                $Actual
        )
    }
}


$testRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    "highered-tk-runtime-$([guid]::NewGuid().ToString('N'))"
$pythonBase = Join-Path $testRoot "Python Base"
$tclLibrary = Join-Path $pythonBase "tcl\tcl8.6"
$tkLibrary = Join-Path $pythonBase "tcl\tk8.6"
$fakePython = Join-Path $testRoot "python.cmd"
$originalTclLibrary = $env:TCL_LIBRARY
$originalTkLibrary = $env:TK_LIBRARY

try {
    New-Item -ItemType Directory -Path $tclLibrary -Force | Out-Null
    New-Item -ItemType Directory -Path $tkLibrary -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $tclLibrary "init.tcl") | Out-Null
    New-Item -ItemType File -Path (Join-Path $tkLibrary "tk.tcl") | Out-Null

    $fakePythonContent = @"
@echo off
echo $pythonBase
echo 8.6
echo 8.6
exit /b 0
"@
    Set-Content `
        -LiteralPath $fakePython `
        -Value $fakePythonContent `
        -Encoding ASCII

    $runtime = Set-GuiTkRuntimeEnvironment -PythonExecutable $fakePython

    Assert-Equal `
        -Expected $pythonBase `
        -Actual $runtime.PythonBase `
        -Case "Base Python is read from the virtual-environment interpreter"
    Assert-Equal `
        -Expected $tclLibrary `
        -Actual $env:TCL_LIBRARY `
        -Case "Validated Tcl library is process-scoped"
    Assert-Equal `
        -Expected $tkLibrary `
        -Actual $env:TK_LIBRARY `
        -Case "Validated Tk library is process-scoped"
}
finally {
    $env:TCL_LIBRARY = $originalTclLibrary
    $env:TK_LIBRARY = $originalTkLibrary

    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}

Write-Host "Tk runtime tests passed." -ForegroundColor Green
