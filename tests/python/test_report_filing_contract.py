from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = REPOSITORY_ROOT / "config" / "report_filing.psd1"
MODULE = (
    REPOSITORY_ROOT
    / "workflows"
    / "report_filing"
    / "report_filing.psm1"
)
SETUP = REPOSITORY_ROOT / "setup.ps1"
SCHEDULER_SETUP = (
    REPOSITORY_ROOT / "setup" / "setup_report_filing_watcher.ps1"
)


class ReportFilingPowerShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = CONFIGURATION.read_text(encoding="utf-8")
        cls.module = MODULE.read_text(encoding="utf-8")
        cls.normalized_module = re.sub(r"\s+", " ", cls.module).upper()
        cls.setup = SETUP.read_text(encoding="utf-8")
        cls.scheduler_setup = SCHEDULER_SETUP.read_text(encoding="utf-8")

    def test_submission_confirmation_is_configured(self) -> None:
        self.assertIn(
            'SourceFilePattern   = "Submission_Confirmation_*.pdf"',
            self.config,
        )
        self.assertIn('RequiredExtension   = ".pdf"', self.config)
        self.assertIn('DestinationSuffix   = "RDC"', self.config)
        self.assertIn("MM_dd_yyyy_HH_mm_ss", self.config)
        self.assertIn("[DATETIME]::TRYPARSEEXACT", self.normalized_module)

    def test_jpmlb_transformation_is_configured(self) -> None:
        self.assertIn(
            'SourceFilePattern     = "Transaction_Results_*.csv"',
            self.config,
        )
        self.assertIn('Operation             = "TransformJpmlb"', self.config)
        self.assertIn('RequiredExtension     = ".csv"', self.config)
        self.assertIn("MM_dd_yyyy_HH_mm_ss", self.config)
        self.assertIn("Y-Brswork\\Cashier\\Payments", self.config)
        self.assertIn("WORKFLOWS.JPMLB.RUN_JPMLB", self.normalized_module)
        self.assertIn(".PARTIAL.XLSX", self.normalized_module)
        self.assertIn("workflows\\jpmlb\\run_jpmlb.py", self.scheduler_setup)
        self.assertIn(".venv\\Scripts\\python.exe", self.scheduler_setup)

    def test_confirmation_uses_source_date_and_per_file_bank_choice(self) -> None:
        self.assertIn("$DATEPICKER.VALUE = $REPORTDATE.DATE", self.normalized_module)
        self.assertIn("$INITIALSBOX.TEXT = $USERSETTINGS.INITIALS", self.normalized_module)
        self.assertIn("$BANKBOX.ADD_CHECKEDCHANGED($UPDATEPREVIEW)", self.normalized_module)
        self.assertEqual(self.normalized_module.count("-BANK2723:$BANKBOX.CHECKED"), 2)

    def test_destination_conventions_are_explicit(self) -> None:
        self.assertIn("GRP-Bursar Office - General", self.config)
        self.assertIn("Y-Brswork\\Cashier\\Daily Closing", self.config)
        self.assertIn(
            'FiscalYearDirectoryPattern = "FY{FiscalYearTwoDigit}"',
            self.config,
        )
        self.assertIn('TOSTRING("MM-DD-YYYY")', self.normalized_module)

    def test_watcher_is_event_driven_and_filters_before_prompting(self) -> None:
        self.assertIn("SYSTEM.IO.FILESYSTEMWATCHER", self.normalized_module)
        self.assertIn("-EVENTNAME CREATED", self.normalized_module)
        self.assertIn("-EVENTNAME RENAMED", self.normalized_module)
        match_position = self.normalized_module.index("$MATCHINGREPORTS.COUNT -EQ 0")
        prompt_position = self.normalized_module.index(
            "$SELECTION = SHOW-REPORTFILINGCONFIRMATION"
        )
        self.assertLess(match_position, prompt_position)

    def test_transfer_is_verified_and_never_overwrites(self) -> None:
        self.assertIn("TEST-PDFFILESIGNATURE", self.normalized_module)
        self.assertIn("GET-FILEHASH", self.normalized_module)
        self.assertIn("$SOURCEHASH -NE $COPIEDHASH", self.normalized_module)
        self.assertIn("DESTINATION ALREADY EXISTS", self.normalized_module)
        self.assertIn(".PARTIAL", self.normalized_module)
        self.assertIn("[SYSTEM.IO.FILE]::MOVE", self.normalized_module)
        self.assertIn("SOURCEFINGERPRINT", self.normalized_module)

    def test_cancel_uses_a_full_file_fingerprint(self) -> None:
        for field in ("PATH", "LENGTH", "LASTWRITETIMEUTC", "SHA256"):
            self.assertIn(field, self.normalized_module)
        self.assertIn("ADD-IGNOREDREPORTFINGERPRINT", self.normalized_module)

    def test_setup_collects_identity_and_scheduler_is_interactive(self) -> None:
        self.assertIn("Saving your name and initials", self.setup)
        self.assertIn("Save-AutomationUserSettings", self.setup)
        self.assertIn("-AtLogOn", self.scheduler_setup)
        self.assertIn("-LogonType Interactive", self.scheduler_setup)
        self.assertIn("-MultipleInstances IgnoreNew", self.scheduler_setup)


if __name__ == "__main__":
    unittest.main()
