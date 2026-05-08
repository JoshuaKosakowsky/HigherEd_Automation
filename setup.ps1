$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"

Write-Host "Project root: $ProjectRoot"
Set-Location $ProjectRoot

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..."

    python -m venv $VenvDir

    if (-not (Test-Path $VenvPython)) {
        throw "Virtual environment was not created correctly. Python not found at: $VenvPython"
    }
}
else {
    Write-Host "Virtual environment already exists."
}

Write-Host "Using Python:"
& $VenvPython --version

Write-Host "Upgrading pip..."
& $VenvPython -m pip install --upgrade pip

if (-not (Test-Path $RequirementsFile)) {
    throw "requirements.txt not found at: $RequirementsFile"
}

Write-Host "Installing Python packages from requirements.txt..."
& $VenvPython -m pip install -r $RequirementsFile

if ($LASTEXITCODE -ne 0) {
    throw "Package installation failed from requirements.txt"
}

Write-Host "Verifying Playwright import..."
& $VenvPython -c "from playwright.sync_api import sync_playwright; print('Playwright import OK')"

if ($LASTEXITCODE -ne 0) {
    throw "Playwright was not installed correctly in the virtual environment."
}

Write-Host "Installing Playwright browsers..."
& $VenvPython -m playwright install

if ($LASTEXITCODE -ne 0) {
    throw "Playwright browser installation failed."
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "To activate manually, run:"
Write-Host ".\.venv\Scripts\Activate.ps1"