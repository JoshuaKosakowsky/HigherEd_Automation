param(
    [Parameter(Mandatory)]
    [string]$Target
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Credential setup"
Write-Host "Target: $Target"
Write-Host ""

if (-not (Get-Module -ListAvailable -Name CredentialManager)) {
    Write-Host "Installing CredentialManager PowerShell module..."
    Install-Module CredentialManager -Scope CurrentUser -Force
}

Import-Module CredentialManager -ErrorAction Stop

$Username = Read-Host "Enter username for $Target"
$Password = Read-Host "Enter password for $Target" -AsSecureString

$Credential = New-Object System.Management.Automation.PSCredential ($Username, $Password)

$ExistingCredential = Get-StoredCredential -Target $Target

if ($ExistingCredential) {
    $Overwrite = Read-Host "Credential target '$Target' already exists. Overwrite it? Y/N"

    if ($Overwrite -notin @("Y", "y", "Yes", "yes")) {
        Write-Host "Credential setup cancelled."
        exit 0
    }

    Remove-StoredCredential -Target $Target | Out-Null
}

New-StoredCredential `
    -Target $Target `
    -UserName $Credential.UserName `
    -Password $Credential.GetNetworkCredential().Password `
    -Persist LocalMachine | Out-Null

Write-Host ""
Write-Host "Credential saved successfully."
Write-Host "Target: $Target"
Write-Host "Username: $Username"