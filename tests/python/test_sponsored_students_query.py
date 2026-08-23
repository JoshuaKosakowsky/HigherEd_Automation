from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPONSOR_QUERY = (
    REPOSITORY_ROOT
    / "query"
    / "AR"
    / "sponsors"
    / "sponsored_student_summary.sql"
)
SCHEMA_QUERY = (
    REPOSITORY_ROOT
    / "query"
    / "AR"
    / "sponsors"
    / "validate_sponsor_schema.sql"
)


class SponsoredStudentsQueryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.query = SPONSOR_QUERY.read_text(encoding="utf-8")
        cls.normalized_query = re.sub(r"\s+", " ", cls.query).upper()

    def test_tbbcstu_defines_both_sides_of_the_relationship(self) -> None:
        self.assertIn("FROM RELEVANT_TERMS R", self.normalized_query)
        self.assertIn("INNER JOIN TAISMGR.TBBCSTU CS", self.normalized_query)
        self.assertIn("TBBCSTU_STU_PIDM AS STUDENT_PIDM", self.normalized_query)
        self.assertIn(
            "TBBCSTU_CONTRACT_PIDM AS SPONSOR_PIDM",
            self.normalized_query,
        )

    def test_contract_setup_join_uses_full_business_key(self) -> None:
        self.assertIn("LEFT JOIN TAISMGR.TBBCONT CONTRACT", self.normalized_query)
        self.assertIn(
            "CONTRACT.TBBCONT_PIDM = R.SPONSOR_PIDM",
            self.normalized_query,
        )
        self.assertIn(
            "CONTRACT.TBBCONT_CONTRACT_NUMBER = R.CONTRACT_NUMBER",
            self.normalized_query,
        )
        self.assertIn(
            "CONTRACT.TBBCONT_TERM_CODE = R.TERM_CODE",
            self.normalized_query,
        )

    def test_amounts_are_classified_by_detail_type(self) -> None:
        self.assertIn("LEFT JOIN TAISMGR.TBBDETC D", self.normalized_query)
        self.assertIn("TBBDETC_TYPE_IND", self.normalized_query)
        self.assertIn("= 'C'", self.normalized_query)
        self.assertIn("= 'P'", self.normalized_query)
        self.assertNotIn("SUM(T.TBRACCD_BALANCE", self.normalized_query)

    def test_current_and_previous_terms_follow_mines_boundaries(self) -> None:
        term_section = self.query[
            self.query.index("term_context AS") :
            self.query.index("sponsor_roster AS")
        ].upper()
        normalized_term_section = re.sub(r"\s+", " ", term_section)

        self.assertIn("CURRENT_DATE AS RUN_DATE", term_section)
        self.assertIn("CURRENT_TERM_OVERRIDE", term_section)
        self.assertRegex(normalized_term_section, r"MAKE_DATE\(.+?, 5, 15\s*\)")
        self.assertRegex(normalized_term_section, r"MAKE_DATE\(.+?, 7, 15\s*\)")
        self.assertIn("WHEN '10'", term_section)
        self.assertIn("WHEN '55'", term_section)
        self.assertIn("WHEN '80'", term_section)
        self.assertIn("'CURRENT' AS TERM_CONTEXT", term_section)
        self.assertIn("'PREVIOUS' AS TERM_CONTEXT", term_section)

    def test_cross_reference_rollups_match_both_directions(self) -> None:
        self.assertIn(
            "T.TBRACCD_CROSSREF_PIDM = REL.SPONSOR_PIDM",
            self.normalized_query,
        )
        self.assertIn(
            "T.TBRACCD_CROSSREF_PIDM = REL.STUDENT_PIDM",
            self.normalized_query,
        )
        self.assertIn("LINKED_STUDENT_CREDITS", self.normalized_query)
        self.assertIn("LINKED_SPONSOR_CHARGES", self.normalized_query)

    def test_unclassified_detail_types_are_visible(self) -> None:
        self.assertIn("NOT IN ('C', 'P')", self.normalized_query)
        self.assertIn(
            '"STUDENT TERM UNCLASSIFIED DETAIL COUNT"',
            self.normalized_query,
        )
        self.assertIn(
            '"SPONSOR FULL ACCOUNT UNCLASSIFIED DETAIL COUNT"',
            self.normalized_query,
        )

    def test_identity_joins_use_current_spriden_rows(self) -> None:
        self.assertIn("FROM SATURN.SPRIDEN S", self.normalized_query)
        self.assertIn("S.SPRIDEN_CHANGE_IND IS NULL", self.normalized_query)

    def test_schema_inventory_covers_every_required_table(self) -> None:
        schema_query = SCHEMA_QUERY.read_text(encoding="utf-8").upper()

        for table_name in (
            "TBBCSTU",
            "TBBCONT",
            "TBRACCD",
            "TBBDETC",
            "SPRIDEN",
            "STVTERM",
        ):
            with self.subTest(table_name=table_name):
                self.assertIn(f"'{table_name}'", schema_query)


if __name__ == "__main__":
    unittest.main()
