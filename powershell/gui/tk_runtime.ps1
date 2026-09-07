function Find-GuiTkLibraryDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TclRoot,

        [Parameter(Mandatory)]
        [string]$PreferredDirectoryName,

        [Parameter(Mandatory)]
        [string]$DirectoryPrefix,

        [Parameter(Mandatory)]
        [string]$RequiredFile
    )

    $preferredPath = Join-Path $TclRoot $PreferredDirectoryName
    $preferredFile = Join-Path $preferredPath $RequiredFile

    if (
        (Test-Path -LiteralPath $preferredPath -PathType Container) -and
        (Test-Path -LiteralPath $preferredFile -PathType Leaf)
    ) {
        return (Get-Item -LiteralPath $preferredPath).FullName
    }

    $validatedCandidates = @(
        Get-ChildItem `
            -LiteralPath $TclRoot `
            -Directory `
            -ErrorAction Stop |
            Where-Object {
                $_.Name -like "$DirectoryPrefix*" -and
                (Test-Path `
                    -LiteralPath (Join-Path $_.FullName $RequiredFile) `
                    -PathType Leaf)
            } |
            Sort-Object -Property Name -Descending
    )

    if ($validatedCandidates.Count -eq 0) {
        throw (
            "No valid $DirectoryPrefix library was found under: $TclRoot. " +
            "Repair or reinstall Python with Tcl/Tk support."
        )
    }

    return $validatedCandidates[0].FullName
}


function Set-GuiTkRuntimeEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PythonExecutable
    )

    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        throw "Python executable was not found: $PythonExecutable"
    }

    $runtimeCode = @"
import _tkinter
import sys
print(sys.base_prefix)
print(_tkinter.TCL_VERSION)
print(_tkinter.TK_VERSION)
"@

    $runtimeOutput = @(& $PythonExecutable -c $runtimeCode)

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Python could not report its Tcl/Tk runtime information: " +
            $PythonExecutable
        )
    }

    $runtimeLines = @(
        $runtimeOutput |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )

    if ($runtimeLines.Count -lt 3) {
        throw "Python returned incomplete Tcl/Tk runtime information."
    }

    $pythonBase = $runtimeLines[-3]
    $tclVersion = $runtimeLines[-2]
    $tkVersion = $runtimeLines[-1]

    $tclRoot = Join-Path $pythonBase "tcl"

    if (-not (Test-Path -LiteralPath $tclRoot -PathType Container)) {
        throw @"
Python's Tcl/Tk directory was not found:
$tclRoot

Repair or reinstall the base Python installation with Tcl/Tk support.
"@
    }

    $tclLibrary = Find-GuiTkLibraryDirectory `
        -TclRoot $tclRoot `
        -PreferredDirectoryName "tcl$tclVersion" `
        -DirectoryPrefix "tcl" `
        -RequiredFile "init.tcl"

    $tkLibrary = Find-GuiTkLibraryDirectory `
        -TclRoot $tclRoot `
        -PreferredDirectoryName "tk$tkVersion" `
        -DirectoryPrefix "tk" `
        -RequiredFile "tk.tcl"

    # Process-scoped variables are inherited by the GUI child process and do
    # not modify the staff member's user-level or machine-level environment.
    $env:TCL_LIBRARY = $tclLibrary
    $env:TK_LIBRARY = $tkLibrary

    return [pscustomobject]@{
        PythonBase = $pythonBase
        TclLibrary = $tclLibrary
        TkLibrary  = $tkLibrary
    }
}
