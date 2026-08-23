from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SetupPowerShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.setup = (PROJECT_ROOT / "setup.ps1").read_text(encoding="utf-8")

    def test_package_verification_avoids_quoted_python_output(self) -> None:
        self.assertNotIn(
            'print("Required Python packages are available.")',
            self.setup,
        )
        self.assertIn(
            'Write-Host "Required Python packages are available."',
            self.setup,
        )


if __name__ == "__main__":
    unittest.main()
