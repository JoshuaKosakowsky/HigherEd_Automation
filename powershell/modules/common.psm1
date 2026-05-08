function New-DirectoryIfMissing {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function New-LogFile {
    param(
        [Parameter(Mandatory)]
        [string]$LogDir,

        [Parameter(Mandatory)]
        [string]$WorkflowName
    )

    New-DirectoryIfMissing -Path $LogDir

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    return Join-Path $LogDir ("{0}_{1}.log" -f $WorkflowName, $timestamp)
}

function Write-Log {
    param(
        [Parameter(Mandatory)]
        [string]$Message,

        [Parameter(Mandatory)]
        [string]$LogFile
    )

    $line = "===== $Message $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
    $line | Tee-Object -FilePath $LogFile -Append | Out-Host
}

function Get-StoredCredOrThrow {
    param(
        [Parameter(Mandatory)]
        [string]$TargetName
    )

    $storedCred = Get-StoredCredential -Target $TargetName

    if (-not $storedCred) {
        throw "No Windows Credential found for Target '$TargetName'."
    }

    return $storedCred
}

function Set-SystemCredentialEnvironment {
    param(
        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$UserEnvName,

        [Parameter(Mandatory)]
        [string]$PasswordEnvName,

        [Parameter(Mandatory)]
        [string]$LogFile
    )

    $storedCred = Get-StoredCredOrThrow -TargetName $TargetName

    Set-Item -Path "Env:$UserEnvName" -Value $storedCred.UserName
    Set-Item -Path "Env:$PasswordEnvName" -Value $storedCred.GetNetworkCredential().Password

    Write-Log `
        -Message ("Loaded credential target '{0}' for user: {1}" -f $TargetName, $storedCred.UserName) `
        -LogFile $LogFile
}

function Invoke-PythonScript {
    param(
        [Parameter(Mandatory)]
        [string]$PythonExe,

        [Parameter(Mandatory)]
        [string]$ScriptPath,

        [Parameter(Mandatory)]
        [string]$LogFile,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory
    )

    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found at: $PythonExe"
    }

    if (-not (Test-Path $ScriptPath)) {
        throw "Python script not found at: $ScriptPath"
    }

    Push-Location $WorkingDirectory

    try {
        & $PythonExe -u $ScriptPath 2>&1 |
            ForEach-Object {

                $line = $_.ToString()

                # Show immediately in terminal
                Write-Host $line

                # Save immediately to log
                Add-Content -Path $LogFile -Value $line
            }

        return $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}


Export-ModuleMember -Function `
    New-DirectoryIfMissing, `
    New-LogFile, `
    Write-Log, `
    Get-StoredCredOrThrow, `
    Set-SystemCredentialEnvironment, `
    Invoke-PythonScript