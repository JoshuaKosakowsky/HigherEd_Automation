from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SetupPowerShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.setup = (PROJECT_ROOT / "setup.ps1").read_text(encoding="utf-8")
        cls.profile_setup = (
            PROJECT_ROOT / "powershell" / "credentials" / "setup_profile.ps1"
        ).read_text(encoding="utf-8")

    def test_package_verification_avoids_quoted_python_output(self) -> None:
        self.assertNotIn(
            'print("Required Python packages are available.")',
            self.setup,
        )
        self.assertIn(
            'Write-Host "Required Python packages are available."',
            self.setup,
        )

    def test_setup_installs_shortcuts_before_reporting_completion(self) -> None:
        shortcut_step = self.setup.index(
            'Write-SetupStep "Installing PowerShell shortcuts"'
        )
        shortcut_install = self.setup.index("& $ProfileSetupScript")
        setup_complete = self.setup.index('Write-Host "SETUP COMPLETE"')

        self.assertLess(shortcut_step, shortcut_install)
        self.assertLess(shortcut_install, setup_complete)
        self.assertIn('$StepCount = 7', self.setup)

    def test_shortcuts_load_on_the_next_powershell_session(self) -> None:
        self.assertNotIn('Write-Host ". `$PROFILE"', self.profile_setup)
        self.assertIn(
            "The shortcuts load automatically in each new PowerShell window.",
            self.profile_setup,
        )

    def test_refund_workflow_shortcut_is_installed(self) -> None:
        shortcuts = (
            PROJECT_ROOT / "powershell" / "shortcuts" / "profile_shortcuts.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("function start-refunds", shortcuts)
        self.assertIn("launcher\\run_refunds.ps1", shortcuts)
        self.assertIn('Write-Host "start-refunds"', self.profile_setup)

    def test_current_shortcuts_do_not_create_another_backup(self) -> None:
        current_message = self.profile_setup.index(
            'Write-Host "Automation shortcuts are already current."'
        )
        backup_creation = self.profile_setup.index(
            'Copy-Item -LiteralPath $PROFILE -Destination $backupPath'
        )

        self.assertLess(current_message, backup_creation)


if __name__ == "__main__":
    unittest.main()
