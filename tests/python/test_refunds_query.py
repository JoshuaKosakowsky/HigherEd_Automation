from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFUNDS_QUERY = (
    REPOSITORY_ROOT
    / "query"
    / "AR"
    / "refunds"
    / "Refunds.sql"
)


class RefundsQueryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.query = REFUNDS_QUERY.read_text(encoding="utf-8")
        cls.normalized_query = re.sub(r"\s+", " ", cls.query).upper()

    def test_population_does_not_depend_on_a_popsel(self) -> None:
        self.assertNotIn("GLBEXTR", self.normalized_query)
        self.assertNotIn("POPSEL", self.normalized_query)
        self.assertIn("FROM TAISMGR.TBRACCD T", self.normalized_query)

    def test_population_uses_full_account_credit_balances(self) -> None:
        self.assertRegex(
            self.normalized_query,
            (
                r"FROM ACCOUNT_BALANCE_ROLLUP R WHERE "
                r"R\.UNCLASSIFIED_DETAIL_TYPE_COUNT = 0 AND "
                r"R\.FULL_ACCOUNT_BALANCE < 0"
            ),
        )
        account_population = self.query[
            self.query.index("account_balance_rollup AS") :
            self.query.index("current_identity AS")
        ].upper()
        self.assertNotIn("TBRACCD_TERM_CODE", account_population)

    def test_card_review_uses_selected_balance_sources_across_terms(self) -> None:
        original_payment_section = self.query[
            self.query.index("original_payment_summary AS") :
            self.query.index("joined AS")
        ].upper()
        self.assertIn("FROM SELECTED_BALANCE_SOURCES", original_payment_section)
        self.assertNotIn("TERM_CODE IN", original_payment_section)

    def test_parent_plus_remains_scoped_to_target_term(self) -> None:
        parent_plus_section = self.query[
            self.query.index("fdpl_summary AS") :
            self.query.index("later_payment_summary AS")
        ].upper()
        self.assertIn("X.TERM_CODE = P.TARGET_TERM", parent_plus_section)
        self.assertIn("X.DETAIL_CODE", parent_plus_section)
        self.assertIn("'FDPL'", parent_plus_section)

    def test_parent_plus_split_no_longer_requires_policy_approval(self) -> None:
        self.assertNotIn("POLICY_APPROVAL_REQUIRED", self.normalized_query)
        self.assertNotIn("PROVISIONAL_FDPL_CREATED_CREDIT", self.normalized_query)
        self.assertIn("AS CALCULATED_FDPL_CREATED_CREDIT", self.normalized_query)
        self.assertIn(
            "C.TOTAL_REFUND_AMOUNT - C.CALCULATED_FDPL_CREATED_CREDIT",
            self.normalized_query,
        )

    def test_target_term_is_derived_from_mines_date_boundaries(self) -> None:
        term_section = self.query[
            self.query.index("term_context AS") :
            self.query.index("account_balance_rollup AS")
        ].upper()
        normalized_term_section = re.sub(r"\s+", " ", term_section)
        self.assertIn("CURRENT_DATE AS RUN_DATE", term_section)
        self.assertIn("TARGET_TERM_OVERRIDE", term_section)
        self.assertIn("COALESCE", term_section)
        self.assertRegex(normalized_term_section, r"MAKE_DATE\(.+?, 5, 15\s*\)")
        self.assertRegex(normalized_term_section, r"MAKE_DATE\(.+?, 7, 15\s*\)")
        self.assertIn("THEN '10'", term_section)
        self.assertIn("THEN '55'", term_section)
        self.assertIn("ELSE '80'", term_section)

    def test_parent_plus_labels_are_not_tied_to_one_term(self) -> None:
        self.assertNotIn("202680", self.query)
        self.assertIn("P.TARGET_TERM AS PARENT_PLUS_TARGET_TERM", self.normalized_query)
        self.assertIn("AS TARGET_TERM_FDPL_AMOUNT", self.normalized_query)
        self.assertIn("MULTIPLE_TARGET_TERM_FDPL_ROWS_", self.normalized_query)
        self.assertIn(
            "TARGET_TERM_FDPL_NOT_A_NEGATIVE_CREDIT",
            self.normalized_query,
        )

    def test_third_party_accounts_always_require_manual_review(self) -> None:
        self.assertIn("LEGACY_THIRD_PARTY_CWIDS AS", self.normalized_query)
        self.assertIn("LIKE 'TPS%'", self.normalized_query)
        self.assertIn("LEGACY_TPS.CWID IS NOT NULL", self.normalized_query)
        self.assertIn(
            "AS THIRD_PARTY_REVIEW_REQUIRED_IND",
            self.normalized_query,
        )
        self.assertIn("AS THIRD_PARTY_MATCH_SOURCE", self.normalized_query)
        self.assertIn(
            "THIRD_PARTY_ACCOUNT_REVIEW_REQUIRED",
            self.normalized_query,
        )
        self.assertRegex(
            self.normalized_query,
            (
                r"WHEN S\.THIRD_PARTY_REVIEW_REQUIRED_IND = 'Y' "
                r"THEN 'THIRD_PARTY_REVIEW'"
            ),
        )
        self.assertRegex(
            self.normalized_query,
            (
                r"WHEN F\.THIRD_PARTY_REVIEW_REQUIRED_IND = 'Y' "
                r"THEN 'MANUAL_REVIEW'"
            ),
        )


if __name__ == "__main__":
    unittest.main()
