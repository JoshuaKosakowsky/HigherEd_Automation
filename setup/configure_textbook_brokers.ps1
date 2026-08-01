$configurationName = "Textbook Brokers SFTP"

Write-Host "Configuring $configurationName"

$userName = "mines"
$oneDriveRoot = $env:OneDriveCommercial

if ([string]::IsNullOrWhiteSpace($oneDriveRoot)) {
    throw @"
The OneDriveCommercial environment variable is unavailable.

Confirm that OneDrive is installed,
signed in, and synchronized for this Windows user.
"@
}

$privateKeyPath = Join-Path `
    $oneDriveRoot `
    "privatekeys\id_rsa.ppk"

if ([string]::IsNullOrWhiteSpace($userName)) {
    throw "A Textbook Brokers username is required."
}

if (-not (Test-Path -LiteralPath $privateKeyPath -PathType Leaf)) {
    throw "The private-key file was not found: $privateKeyPath"
}

if ([System.IO.Path]::GetExtension($privateKeyPath) -ne ".ppk") {
    throw "The selected private-key file must be a .ppk file."
}

[Environment]::SetEnvironmentVariable(
    "HIGHERED_TEXTBOOK_BROKERS_USERNAME",
    $userName,
    "User"
)

[Environment]::SetEnvironmentVariable(
    "HIGHERED_TEXTBOOK_BROKERS_PPK_PATH",
    $privateKeyPath,
    "User"
)

Write-Host ""
Write-Host "$configurationName was configured successfully."
Write-Host "Private key: $privateKeyPath"
Write-Host "Open a new PowerShell session before running the workflow."