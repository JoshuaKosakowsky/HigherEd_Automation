# Automation Repository Shortcuts

$AUTOMATION_ROOT = "{{PROJECT_ROOT}}"

function open-auto {
    Set-Location $AUTOMATION_ROOT
}

function start-setup {
    & (Join-Path $AUTOMATION_ROOT "setup.ps1")
}

function test-automation {
    & (Join-Path $AUTOMATION_ROOT "tests\run_tests.ps1")
}

function start-population-testing {
    & (Join-Path $AUTOMATION_ROOT "launcher\run_population_testing.ps1")
}

function start-refunds {
    & (Join-Path $AUTOMATION_ROOT "launcher\run_refunds.ps1") @args
}

function start-trends {
    & (Join-Path $AUTOMATION_ROOT "launcher\run_trends.ps1")
}

function start-textbook-brokers {
    & (Join-Path $AUTOMATION_ROOT "launcher\run_textbook_brokers.ps1")
}

function archive-textbook-brokers {
    & (Join-Path $AUTOMATION_ROOT "launcher\archive_textbook_brokers.ps1")
}

function setup-report-watcher {
    & (Join-Path $AUTOMATION_ROOT "setup\setup_report_filing_watcher.ps1")
}

# End Automation Repository Shortcuts
