function Get-WinSCPAssemblyPath {
    [CmdletBinding()]
    param ()

    $programFiles = [Environment]::GetEnvironmentVariable(
        "ProgramFiles",
        "Process"
    )

    $programFilesX86 = [Environment]::GetEnvironmentVariable(
        "ProgramFiles(x86)",
        "Process"
    )

    $candidatePaths = @(
        (Join-Path $programFiles "WinSCP\WinSCPnet.dll")
        (Join-Path $programFilesX86 "WinSCP\WinSCPnet.dll")
    ) | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    }

    foreach ($candidatePath in $candidatePaths) {
        if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
            return $candidatePath
        }
    }

    throw @"
WinSCPnet.dll was not found.

Expected one of these locations:
$($candidatePaths -join [Environment]::NewLine)

Confirm that WinSCP was installed using the standard installer
and that the .NET assembly component is available.
"@
}


function Receive-TextbookBrokersFiles {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory)]
        [hashtable]$Connection,

        [Parameter(Mandatory)]
        [string]$OneDriveRoot,

        [Parameter(Mandatory)]
        [string]$RemoteDirectory,

        [Parameter(Mandatory)]
        [object[]]$SourceDefinitions,

        [Parameter(Mandatory)]
        [string]$LocalDirectory,

        [Parameter(Mandatory)]
        [scriptblock]$Log
    )

    $winSCPAssemblyPath = Get-WinSCPAssemblyPath

    & $Log "Loading WinSCP assembly: $winSCPAssemblyPath"

    if (-not ("WinSCP.Session" -as [type])) {
        Add-Type -Path $winSCPAssemblyPath
    }

    $privateKeyDirectory = Join-Path `
        $OneDriveRoot `
        $Connection.PrivateKeyDirectory

    $privateKeyPath = Join-Path `
        $privateKeyDirectory `
        $Connection.PrivateKeyFileName

    if (-not (Test-Path -LiteralPath $privateKeyPath -PathType Leaf)) {
        throw "WinSCP private key was not found: $privateKeyPath"
    }

    if (-not (Test-Path -LiteralPath $LocalDirectory -PathType Container)) {
        throw "Local download directory was not found: $LocalDirectory"
    }

    $sessionOptions = New-Object WinSCP.SessionOptions -Property @{
        Protocol               = [WinSCP.Protocol]::Sftp
        HostName              = $Connection.HostName
        PortNumber            = $Connection.PortNumber
        UserName              = $Connection.UserName
        SshPrivateKeyPath     = $privateKeyPath
        SshHostKeyFingerprint = $Connection.HostKeyFingerprint
    }

    $transferOptions = New-Object WinSCP.TransferOptions
    $transferOptions.TransferMode = [WinSCP.TransferMode]::Binary

    $results = [System.Collections.Generic.List[object]]::new()
    $session = New-Object WinSCP.Session

    try {
        & $Log (
            "Connecting to {0}@{1}:{2}" -f `
                $Connection.UserName,
                $Connection.HostName,
                $Connection.PortNumber
        )

        $session.Open($sessionOptions)

        & $Log "WinSCP connection opened successfully."
        & $Log "Reading remote directory: $RemoteDirectory"

        $remoteListing = $session.ListDirectory($RemoteDirectory)

        foreach ($sourceDefinition in $SourceDefinitions) {
            $sourceType = [string]$sourceDefinition.SourceType
            $filePattern = [string]$sourceDefinition.FilePattern

            & $Log "Searching for $sourceType files matching $filePattern"

            $matchingFiles = @(
                $remoteListing.Files |
                    Where-Object {
                        -not $_.IsDirectory -and
                        $_.Name -like $filePattern
                    } |
                    Sort-Object Name
            )

            if ($matchingFiles.Count -eq 0) {
                & $Log `
                    -Level "WARNING" `
                    -Message (
                        "No $sourceType files matching $filePattern were found."
                    )

                continue
            }

            & $Log (
                "Found {0} {1} file(s)." -f `
                    $matchingFiles.Count,
                    $sourceType
            )

            foreach ($remoteFile in $matchingFiles) {
                $localFilePath = Join-Path `
                    $LocalDirectory `
                    $remoteFile.Name

                $escapedFileName = [WinSCP.RemotePath]::EscapeFileMask(
                    $remoteFile.Name
                )

                $remoteFilePath = [WinSCP.RemotePath]::Combine(
                    $RemoteDirectory,
                    $escapedFileName
                )

                if (Test-Path -LiteralPath $localFilePath -PathType Leaf) {
                    $existingFile = Get-Item -LiteralPath $localFilePath

                    if ($existingFile.Length -eq $remoteFile.Length) {
                        & $Log `
                            -Level "WARNING" `
                            -Message (
                                "Already downloaded; using existing file: " +
                                $localFilePath
                            )

                        $results.Add(
                            [pscustomobject]@{
                                SourceType    = $sourceType
                                FileName      = $remoteFile.Name
                                RemotePath    = $remoteFilePath
                                LocalPath     = $localFilePath
                                Length        = $existingFile.Length
                                LastWriteTime = $remoteFile.LastWriteTime
                                Status        = "AlreadyPresent"
                                ErrorMessage  = $null
                            }
                        )

                        continue
                    }

                    $message = (
                        "Local file conflicts with the remote file. " +
                        "Remote size: {0}; local size: {1}; path: {2}" -f `
                            $remoteFile.Length,
                            $existingFile.Length,
                            $localFilePath
                    )

                    & $Log -Level "ERROR" -Message $message

                    $results.Add(
                        [pscustomobject]@{
                            SourceType    = $sourceType
                            FileName      = $remoteFile.Name
                            RemotePath    = $remoteFilePath
                            LocalPath     = $localFilePath
                            Length        = $remoteFile.Length
                            LastWriteTime = $remoteFile.LastWriteTime
                            Status        = "Conflict"
                            ErrorMessage  = $message
                        }
                    )

                    continue
                }

                $temporaryFilePath = (
                    "{0}.partial.{1}" -f `
                        $localFilePath,
                        [guid]::NewGuid().ToString("N")
                )

                try {
                    & $Log (
                        "Downloading {0} file: {1}" -f `
                            $sourceType,
                            $remoteFile.Name
                    )

                    & $Log "Remote file size: $($remoteFile.Length) bytes"
                    & $Log "Local destination: $localFilePath"

                    $transferResult = $session.GetFiles(
                        $remoteFilePath,
                        $temporaryFilePath,
                        $false,
                        $transferOptions
                    )

                    $transferResult.Check()

                    if (-not (
                        Test-Path `
                            -LiteralPath $temporaryFilePath `
                            -PathType Leaf
                    )) {
                        throw (
                            "WinSCP reported success, but the temporary " +
                            "download was not found."
                        )
                    }

                    $temporaryFile = Get-Item `
                        -LiteralPath $temporaryFilePath

                    if ($temporaryFile.Length -ne $remoteFile.Length) {
                        throw (
                            "Downloaded size does not match. " +
                            "Remote: {0}; local: {1}." -f `
                                $remoteFile.Length,
                                $temporaryFile.Length
                        )
                    }

                    Move-Item `
                        -LiteralPath $temporaryFilePath `
                        -Destination $localFilePath

                    & $Log "Download verified: $localFilePath"

                    $results.Add(
                        [pscustomobject]@{
                            SourceType    = $sourceType
                            FileName      = $remoteFile.Name
                            RemotePath    = $remoteFilePath
                            LocalPath     = $localFilePath
                            Length        = $remoteFile.Length
                            LastWriteTime = $remoteFile.LastWriteTime
                            Status        = "Downloaded"
                            ErrorMessage  = $null
                        }
                    )
                }
                catch {
                    $message = (
                        "Failed to download {0}: {1}" -f `
                            $remoteFile.Name,
                            $_.Exception.Message
                    )

                    & $Log -Level "ERROR" -Message $message

                    $results.Add(
                        [pscustomobject]@{
                            SourceType    = $sourceType
                            FileName      = $remoteFile.Name
                            RemotePath    = $remoteFilePath
                            LocalPath     = $localFilePath
                            Length        = $remoteFile.Length
                            LastWriteTime = $remoteFile.LastWriteTime
                            Status        = "Failed"
                            ErrorMessage  = $message
                        }
                    )
                }
                finally {
                    if (Test-Path -LiteralPath $temporaryFilePath) {
                        Remove-Item -LiteralPath $temporaryFilePath -Force
                    }
                }
            }
        }
    }
    finally {
        $session.Dispose()
    }

    & $Log "Remote source files were left unchanged."

    return $results
}