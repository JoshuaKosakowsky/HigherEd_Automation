from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AR_QUERY_ROOT = REPOSITORY_ROOT / "query" / "AR"


class AccountsReceivableQueryDocumentationTests(unittest.TestCase):
    def test_every_report_family_has_documentation_and_schema_validation(self) -> None:
        families = {
            "aging": "validate_aging_schema.sql",
            "activity": "validate_activity_schema.sql",
            "refunds": "validate_refund_schema.sql",
            "contact_information": "validate_contact_schema.sql",
            "sponsors": "validate_sponsor_schema.sql",
            "loans": "validate_loan_schema.sql",
        }

        self.assertTrue((AR_QUERY_ROOT / "README.md").is_file())

        for family, validation_query in families.items():
            with self.subTest(family=family):
                family_path = AR_QUERY_ROOT / family
                self.assertTrue((family_path / "README.md").is_file())
                self.assertTrue((family_path / validation_query).is_file())

    def test_aging_buckets_are_complete_and_non_overlapping(self) -> None:
        expected_boundaries = {
            "0-30Days.sql": (0, 30),
            "31-60Days.sql": (31, 60),
            "61-90Days.sql": (61, 90),
        }

        for filename, (minimum, maximum) in expected_boundaries.items():
            with self.subTest(filename=filename):
                query = (AR_QUERY_ROOT / "aging" / filename).read_text(
                    encoding="utf-8"
                )
                normalized_query = re.sub(r"\s+", "", query).lower()
                self.assertIn(f")>={minimum}", normalized_query)
                self.assertIn(f")<={maximum}", normalized_query)

        oldest_query = (
            AR_QUERY_ROOT / "aging" / "91+Days.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(")>=91", re.sub(r"\s+", "", oldest_query).lower())

    def test_activity_documentation_discloses_preserved_limitations(self) -> None:
        readme = (
            AR_QUERY_ROOT / "activity" / "README.md"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("hard-coded detail-code list", readme)
        self.assertIn("does not currently return current-month rows", readme)
        self.assertIn("placeholder empty detail codes", readme)
        self.assertRegex(readme, r"groups by the raw\s+amount")

    def test_contact_query_is_not_presented_as_an_outstanding_check_report(self) -> None:
        query = (
            AR_QUERY_ROOT / "contact_information" / "OS_Checks.sql"
        ).read_text(encoding="utf-8").lower()
        readme = (
            AR_QUERY_ROOT / "contact_information" / "README.md"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("does not identify outstanding checks", query)
        self.assertIn("does **not** query a check", readme)
        self.assertRegex(readme, r"contact\s+(information\s+)?lookup")

    def test_schema_validators_report_missing_columns(self) -> None:
        validators = AR_QUERY_ROOT.glob("*/validate_*_schema.sql")

        for path in validators:
            with self.subTest(path=path.name):
                query = path.read_text(encoding="utf-8").upper()
                self.assertIn("INFORMATION_SCHEMA.COLUMNS", query)

                if path.parent.name != "sponsors":
                    self.assertIn("'MISSING'", query)
                    self.assertIn("'FOUND'", query)


if __name__ == "__main__":
    unittest.main()
