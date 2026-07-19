$Folders = @(
    "P01 - Jul '26"
    "P02 - Aug '26"
    "P03 - Sep '26"
    "P04 - Oct '26"
    "P05 - Nov '26"
    "P06 - Dec '26"
    "P07 - Jan '27"
    "P08 - Feb '27"
    "P09 - Mar '27"
    "P10 - Apr '27"
    "P11 - May '27"
    "P12 - Jun '27"
)

foreach ($Folder in $Folders) {
    if (Test-Path -LiteralPath $Folder) {
        Write-Host "Already exists: $Folder"
    }
    else {
        New-Item -ItemType Directory -Name $Folder | Out-Null
        Write-Host "Created: $Folder"
    }
}

Write-Host "`nNew FY folders completed."