# Automation Repository Shortcuts

$AUTOMATION_ROOT = "{{PROJECT_ROOT}}"

function open-auto {
    Set-Location $AUTOMATION_ROOT
}

function start-setup{
    & (Join-Path $AUTOMATION_ROOT "setup.ps1")
}

function banner.fgiglac {
    & (Join-Path $AUTOMATION_ROOT "launcher\run_fgiglac.ps1")
}