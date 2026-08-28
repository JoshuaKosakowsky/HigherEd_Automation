from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import unittest
from dataclasses import dataclass, replace
from decimal import Decimal
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

    def test_card_review_uses_selected_target_term_balance_sources(self) -> None:
        original_payment_section = self.query[
            self.query.index("original_payment_summary AS") :
            self.query.index("joined AS")
        ].upper()
        self.assertIn("FROM SELECTED_BALANCE_SOURCES", original_payment_section)
        self.assertNotIn("TERM_CODE IN", original_payment_section)

    def test_allocation_inputs_are_scoped_to_the_target_term(self) -> None:
        transactions = self.query[
            self.query.index("candidate_transactions AS") :
            self.query.index("allocation_sources AS")
        ].upper()
        self.assertIn("CROSS JOIN PARAMS P", transactions)
        self.assertIn("WHERE T.TBRACCD_TERM_CODE = P.TARGET_TERM", transactions)

    def test_parent_plus_remains_scoped_to_target_term(self) -> None:
        parent_plus_section = self.query[
            self.query.index("fdpl_summary AS") :
            self.query.index("plus_authorization AS")
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

    def test_priority_allocation_replaces_posting_order(self) -> None:
        self.assertIn("D.TBBDETC_PRIORITY", self.normalized_query)
        self.assertNotIn("LATER_PAYMENT_SUMMARY", self.normalized_query)
        self.assertNotIn("CREDITS_AFTER_TARGET_TERM_FDPL", self.normalized_query)
        allocation = self.query[
            self.query.index("allocation_pairs AS") :
            self.query.index("allocation_final AS")
        ].upper()
        self.assertNotIn("TRAN_NUMBER", allocation)
        self.assertIn("J.UNUSED_FDPL_AMOUNT", self.normalized_query)

    def test_temporary_fdpl_tie_assumption_is_explicit_and_configurable(self) -> None:
        self.assertIn("TEMPORARY BUSINESS ASSUMPTION", self.normalized_query)
        self.assertIn("TRUE AS FDPL_LAST_AT_SAME_PRIORITY", self.normalized_query)
        self.assertIn("AS FDPL_PRIORITY_TIE_RULE", self.normalized_query)
        self.assertNotRegex(self.normalized_query, r"PRIORITY(?:_CODE)?\s*=\s*'?800")

    def test_schema_inventory_requires_priority(self) -> None:
        schema_query = REFUNDS_QUERY.with_name("validate_refund_schema.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("('TAISMGR', 'TBBDETC', 'PRIORITY')", schema_query)

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


@dataclass(frozen=True)
class RefundTransaction:
    detail_code: str
    type_ind: str
    priority: str | None
    amount: int | str
    term: str = "209980"
    aid_year: str = "9900"
    pidm: int = 1


class RefundsPostgresAllocationTests(unittest.TestCase):
    """Execute the actual report using only temporary tables and synthetic data.

    Opt in with REFUNDS_TEST_DSN pointing to an isolated PostgreSQL test database.
    REFUNDS_TEST_PSQL may supply a psql executable outside PATH. No Python database
    dependency is needed. Every invocation rolls back all fixture data.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = os.environ.get("REFUNDS_TEST_DSN")
        cls.psql = os.environ.get("REFUNDS_TEST_PSQL") or shutil.which("psql")
        if not cls.dsn:
            raise unittest.SkipTest("Set REFUNDS_TEST_DSN for synthetic PostgreSQL tests")
        if not cls.psql:
            raise RuntimeError("REFUNDS_TEST_DSN is set but psql is unavailable")
        cls.query = REFUNDS_QUERY.read_text(encoding="utf-8")

    @staticmethod
    def worked_example() -> list[RefundTransaction]:
        return [
            RefundTransaction("TUIN", "C", "899", 6000),
            RefundTransaction("FEES", "C", "897", 1000),
            RefundTransaction("OTHR", "C", "700", 500),
            RefundTransaction("PAYA", "P", "899", 2000),
            RefundTransaction("PAYB", "P", "890", 1500),
            RefundTransaction("FDPL", "P", "800", 4000),
            RefundTransaction("PAYC", "P", "000", 2000),
        ]

    def run_report(
        self,
        transactions: list[RefundTransaction],
        *,
        fdpl_last: bool = True,
        authorization: str | None = "N",
        refund_hold: bool = False,
        query: str | None = None,
    ) -> list[dict]:
        # Schema qualifications alone are redirected; allocation SQL is unmodified.
        query = re.sub(
            r"\b(?:taismgr|saturn|faismgr)\.", "pg_temp.",
            self.query if query is None else query,
        )
        query = query.replace(
            "CAST(NULL AS varchar(6)) AS target_term_override",
            "CAST('209980' AS varchar(6)) AS target_term_override",
        )
        if not fdpl_last:
            query = query.replace(
                "TRUE AS fdpl_last_at_same_priority",
                "FALSE AS fdpl_last_at_same_priority",
            )

        schemas = {
            "tbraccd": "pidm int, term_code text, aidy_code text, tran_number int, "
                "detail_code text, amount numeric, balance numeric, "
                "effective_date date, activity_date date",
            "tbbdetc": "detail_code text, desc text, type_ind text, priority text",
            "spriden": "pidm int, id text, last_name text, first_name text, change_ind text",
            "spbpers": "pidm int, dead_ind text, dead_date date, confid_ind text, activity_date date",
            "tbbacct": "pidm int, deli_code text, refund_ind text, activity_date date",
            "sprhold": "pidm int, hldd_code text, to_date date, activity_date date",
            "rlrpapp": "pidm int, aidy_code text, plus_to_student text, activity_date date",
        }
        sql = ["BEGIN; SET LOCAL statement_timeout = '15s';"]
        for table, columns in schemas.items():
            prefixed = ", ".join(f"{table}_{column}" for column in columns.split(", "))
            sql.append(f"CREATE TEMP TABLE {table} ({prefixed});")

        def insert(table: str, values: tuple) -> None:
            literals = [
                "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"
                for value in values
            ]
            sql.append(f"INSERT INTO {table} VALUES ({', '.join(literals)});")

        details: dict[str, tuple] = {}
        for number, transaction in enumerate(transactions, start=1):
            definition = (transaction.type_ind, transaction.priority)
            if transaction.detail_code in details:
                self.assertEqual(details[transaction.detail_code], definition)
            else:
                details[transaction.detail_code] = definition
                insert("tbbdetc", (transaction.detail_code, "Synthetic source", *definition))
            insert("tbraccd", (
                transaction.pidm, transaction.term, transaction.aid_year, number,
                transaction.detail_code, transaction.amount, 0, "2099-08-01", "2099-08-01",
            ))
        for pidm in sorted({transaction.pidm for transaction in transactions}):
            insert("spriden", (pidm, f"TEST-{pidm}", "Synthetic", "Example", None))
            insert("spbpers", (pidm, "N", None, "N", "2099-08-01"))
            insert("tbbacct", (pidm, "RH" if refund_hold else None, "N", "2099-08-01"))
            insert("sprhold", (pidm, "ED", "9999-12-31", "2099-08-01"))
            if authorization is not None:
                insert("rlrpapp", (pidm, "9900", authorization, "2099-08-01"))
        sql.append(
            "SELECT COALESCE(JSON_AGG(report), '[]'::json) FROM ("
            + query.rstrip().removesuffix(";") + ") report; ROLLBACK;"
        )
        result = subprocess.run(
            [self.psql, "-X", "-qAt", "--set=ON_ERROR_STOP=1", "--dbname", self.dsn],
            input="\n".join(sql), text=True, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout, parse_float=Decimal)

    def assert_split(
        self, row: dict, parent: int | str, student: int | str, *, review_required: bool = False
    ) -> None:
        parent_amount, student_amount = Decimal(str(parent)), Decimal(str(student))
        self.assertEqual(row["parent_refund_amount"], parent_amount)
        self.assertEqual(row["student_refund_amount"], student_amount)
        self.assertEqual(row["total_refund_amount"], parent_amount + student_amount)
        self.assertEqual(row["total_unused_payment_amount"], row["total_refund_amount"])
        self.assertEqual(row["unpaid_charge_amount"], 0)
        self.assertEqual(row["allocation_review_required_ind"], "Y" if review_required else "N")
        self.assertEqual(row["refund_split_status"], "CALCULATED_SUBJECT_TO_REVIEW")

    def assert_unresolved(self, row: dict, reason: str) -> None:
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")
        self.assertIn(reason, row["review_reasons"])
        self.assertIsNone(row["parent_refund_amount"])
        self.assertIsNone(row["student_refund_amount"])
        self.assertEqual(row["refund_split_status"], "UNDETERMINED_SEE_REVIEW_REASONS")

    def test_worked_example_and_posting_order_independence(self) -> None:
        transactions = self.worked_example()
        for ordered in (transactions, list(reversed(transactions)), transactions[5:] + transactions[:5]):
            with self.subTest(order=[t.detail_code for t in ordered]):
                row = self.run_report(ordered)[0]
                self.assert_split(row, 500, 1500)
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                self.assertNotIn("PAYA", row["balance_sources"])
                self.assertNotIn("PAYB", row["balance_sources"])

    def test_output_columns_follow_requested_order(self) -> None:
        expected_columns = """
            cwid last_name first_name full_account_balance total_refund_amount
            student_refund_amount parent_refund_amount balance_sources
            plus_to_student_status parent_plus_target_term refund_split_status
            third_party_review_required_ind third_party_match_source refund_hold_ind
            raw_delinquency_code active_ed_ind raw_refund_account_ind
            refund_account_selected_ind fdpl_row_count target_term_fdpl_amount
            fdpl_aidy_code fdpl_priority_tie_rule unused_fdpl_amount unused_non_fdpl_amount
            total_unused_payment_amount unpaid_charge_amount allocation_review_required_ind
            original_payment_row_count original_payment_total original_payment_detail
            proposed_student_delivery proposed_parent_delivery deceased_ind deceased_date
            confidential_ind plus_auth_row_count plus_auth_raw_values negative_source_count
            ambiguous_source_pool_count review_status review_reasons last_ar_activity_date
            account_control_activity_date ed_activity_date plus_auth_activity_date
        """.split()
        row = self.run_report(self.worked_example())[0]
        self.assertEqual(list(row), expected_columns)

    def test_allocation_diagnostic_is_scoped_and_preserves_raw_source_groups(self) -> None:
        query = REFUNDS_QUERY.with_name("Refund_allocation_diagnostic.sql").read_text(
            encoding="utf-8"
        )
        transactions = self.worked_example() + [
            RefundTransaction("PAYB", "P", "890", -500),
            RefundTransaction("TUIN", "C", "899", 200, term="209910"),
            RefundTransaction("PAYC", "P", "000", 100, pidm=2),
        ]
        self.assertEqual(self.run_report(transactions, query=query), [])
        query = query.replace(
            "CAST(NULL AS varchar(30)) AS cwid", "CAST('TEST-1' AS varchar(30)) AS cwid"
        )
        rows = self.run_report(transactions, query=query)
        self.assertEqual(len(rows), 8)
        groups = {(row["term_code"], row["detail_code"]): row for row in rows}
        self.assertEqual(groups[("209910", "TUIN")]["net_amount_raw"], 200)
        payment = groups[("209980", "PAYB")]
        self.assertEqual(payment["priority_raw"], "890")
        self.assertEqual(payment["type_ind"], "P")
        self.assertEqual(payment["net_amount_raw"], 1000)
        self.assertEqual(payment["transaction_count"], 2)
        self.assertEqual(payment["negative_amount_row_count"], 1)
        self.assertEqual(groups[("209980", "PAYC")]["net_amount_raw"], 2000)
        self.assertTrue({"cwid", "pidm", "first_name", "last_name"}.isdisjoint(rows[0]))

    def test_fdpl_last_tie_rule_is_configurable_and_not_hard_coded_to_800(self) -> None:
        for charge_priority, payment_priority in (("899", "800"), ("479", "470")):
            transactions = [
                RefundTransaction("CHRG", "C", charge_priority, 1000),
                RefundTransaction("FDPL", "P", payment_priority, 800),
                RefundTransaction("PAYA", "P", payment_priority, 600),
            ]
            with self.subTest(priority=payment_priority):
                last = self.run_report(transactions)[0]
                self.assert_split(last, 400, 0)
                self.assertIn("ASSUMPTION_FDPL_LAST", last["fdpl_priority_tie_rule"])
                first = self.run_report(transactions, fdpl_last=False)[0]
                self.assert_split(first, 0, 400)
                self.assertIn("ASSUMPTION_FDPL_FIRST", first["fdpl_priority_tie_rule"])

    def test_each_zero_is_a_positional_wildcard(self) -> None:
        transactions = [
            RefundTransaction("CHGA", "C", "899", 100),
            RefundTransaction("CHGB", "C", "889", 100),
            RefundTransaction("FDPL", "P", "809", 150),
            RefundTransaction("PAYA", "P", "080", 100),
            RefundTransaction("PAYB", "P", "0", 25),
        ]
        self.assert_split(self.run_report(transactions)[0], 0, 75)

    def test_charges_are_prioritized_before_lower_charge_payments(self) -> None:
        transactions = [
            RefundTransaction("LOWC", "C", "891", 100),
            RefundTransaction("HIGH", "C", "899", 100),
            RefundTransaction("PAYA", "P", "890", 100),
            RefundTransaction("FDPL", "P", "809", 100),
            RefundTransaction("PAYB", "P", "000", 100),
        ]
        # Paying 891 first would incorrectly leave student funds instead of FDPL.
        self.assert_split(self.run_report(transactions)[0], 100, 0)

    def test_unmatched_restricted_credit_does_not_hide_unpaid_charges(self) -> None:
        transactions = [
            RefundTransaction("CHRG", "C", "700", 500),
            RefundTransaction("FDPL", "P", "800", 1000),
        ]
        row = self.run_report(transactions)[0]
        self.assertEqual(row["unpaid_charge_amount"], 500)
        self.assert_unresolved(row, "UNPAID_CHARGES_AFTER_PRIORITY_ALLOCATION")

    def test_no_charges_returns_unspent_payments(self) -> None:
        row = self.run_report([RefundTransaction("FDPL", "P", "800", 500)])[0]
        self.assert_split(row, 500, 0)

    def test_missing_or_malformed_charge_and_payment_priorities_require_review(self) -> None:
        for index in (0, 5):
            for priority in (None, "", "ABC", "8000", "-1"):
                with self.subTest(index=index, priority=priority):
                    transactions = self.worked_example()
                    transactions[index] = replace(transactions[index], priority=priority)
                    self.assert_unresolved(
                        self.run_report(transactions)[0], "MISSING_OR_INVALID_DETAIL_PRIORITY"
                    )

    def test_charge_and_payment_reversals_net_within_their_source(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("TUIN", "C", "899", -1000),
            RefundTransaction("PAYB", "P", "890", -500),
        ]
        self.assert_split(self.run_report(transactions)[0], 1000, 1500)

    def test_unmatched_net_reversal_is_not_invented_as_a_new_payment(self) -> None:
        transactions = self.worked_example() + [RefundTransaction("REVX", "C", "899", -100)]
        self.assert_unresolved(
            self.run_report(transactions)[0], "NEGATIVE_NET_SOURCE_REQUIRES_REVIEW"
        )

    def test_partial_non_fdpl_tie_keeps_possible_card_sources_visible(self) -> None:
        transactions = [
            RefundTransaction("CHRG", "C", "899", 100),
            RefundTransaction("PAYA", "P", "800", 100),
            RefundTransaction("CRED", "P", "800", 100),
            RefundTransaction("FDPL", "P", "800", 100),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 100, 100, review_required=True)
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")
        self.assertIn("SAME_PRIORITY_SOURCE_SPLIT_UNRESOLVED", row["review_reasons"])
        self.assertIn("CRED", row["balance_sources"])
        self.assertIn("REVIEW_ACH_CC_IN_TRANSACT", row["review_reasons"])
        self.assertIsNone(row["original_payment_total"])

    def test_student_source_review_does_not_hide_authorized_student_refund(self) -> None:
        transactions = [
            RefundTransaction("CHRG", "C", "899", 100),
            RefundTransaction("PAYA", "P", "800", 100),
            RefundTransaction("PAYB", "P", "800", 100),
            RefundTransaction("FDPL", "P", "800", 100),
        ]
        row = self.run_report(transactions, authorization="Y")[0]
        self.assert_split(row, 0, 200, review_required=True)
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")

    def test_student_only_source_review_does_not_hide_the_split(self) -> None:
        transactions = [
            RefundTransaction("CHRG", "C", "899", 100),
            RefundTransaction("PAYA", "P", "800", 100),
            RefundTransaction("PAYB", "P", "800", 100),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 0, 100, review_required=True)
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")

    def test_fully_unused_tied_sources_have_known_amounts(self) -> None:
        transactions = [
            RefundTransaction("PAYA", "P", "800", 100),
            RefundTransaction("CRED", "P", "800", 200),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 0, 300)
        self.assertEqual(row["original_payment_total"], 200)
        self.assertEqual(row["review_status"], "TRANSACT_REVIEW")

    def test_card_review_uses_unused_amount_not_original_payment(self) -> None:
        transactions = self.worked_example()
        transactions[-1] = replace(transactions[-1], detail_code="CRED")
        row = self.run_report(transactions)[0]
        self.assert_split(row, 500, 1500)
        self.assertEqual(row["original_payment_total"], 1500)
        self.assertEqual(row["review_status"], "TRANSACT_REVIEW")
        transactions[-1] = replace(transactions[-1], detail_code="PAYC")
        transactions[3] = replace(transactions[3], detail_code="CRED")
        row = self.run_report(transactions)[0]
        self.assertEqual(row["original_payment_row_count"], 0)
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")

    def test_other_term_charges_are_not_reapplied_but_still_limit_the_refund(self) -> None:
        transactions = self.worked_example()
        transactions[0] = replace(transactions[0], term="209910")
        row = self.run_report(transactions)[0]
        self.assertEqual(row["total_refund_amount"], 2000)
        self.assertEqual(row["total_unused_payment_amount"], 8000)
        self.assertEqual(row["unused_fdpl_amount"], 4000)
        self.assert_unresolved(row, "TARGET_TERM_ALLOCATION_DIFFERS_FROM_FULL_ACCOUNT_REFUND")

    def test_other_term_payments_are_not_used_for_target_term_charges(self) -> None:
        transactions = self.worked_example()
        transactions[4] = replace(transactions[4], term="209910")
        row = self.run_report(transactions)[0]
        self.assertEqual(row["total_refund_amount"], 2000)
        self.assertEqual(row["total_unused_payment_amount"], 500)
        self.assertEqual(row["unused_fdpl_amount"], 0)
        self.assert_unresolved(row, "TARGET_TERM_ALLOCATION_DIFFERS_FROM_FULL_ACCOUNT_REFUND")

    def test_settled_other_term_refunds_do_not_change_current_split_or_sources(self) -> None:
        for term in ("209910", "210010"):
            with self.subTest(term=term):
                transactions = self.worked_example() + [
                    RefundTransaction("TUIN", "C", "899", 6000, term=term),
                    RefundTransaction("RFDP", "C", "800", 1000, term=term),
                    RefundTransaction("FDPL", "P", "800", 5000, term=term),
                    RefundTransaction("CRED", "P", "000", 2000, term=term),
                ]
                row = self.run_report(transactions)[0]
                self.assert_split(row, 500, 1500)
                self.assertEqual(row["fdpl_row_count"], 1)
                self.assertEqual(row["original_payment_row_count"], 0)
                self.assertNotIn("CRED", row["balance_sources"])
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")

    def test_other_term_priority_validation_does_not_block_current_allocation(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("OLDC", "C", None, 100, term="209910"),
            RefundTransaction("OLDP", "P", None, 100, term="209910"),
        ]
        self.assert_split(self.run_report(transactions)[0], 500, 1500)

    def test_unused_other_term_fdpl_is_not_assigned_to_student(self) -> None:
        transactions = [RefundTransaction("FDPL", "P", "800", 500, term="209910")]
        self.assert_unresolved(
            self.run_report(transactions)[0], "TARGET_TERM_ALLOCATION_DIFFERS_FROM_FULL_ACCOUNT_REFUND"
        )

    def test_existing_authorization_and_hold_controls_remain(self) -> None:
        transactions = self.worked_example()
        self.assert_split(self.run_report(transactions, authorization="Y")[0], 0, 2000)
        self.assertEqual(self.run_report(transactions, refund_hold=True)[0]["review_status"], "HOLD")
        missing = self.run_report(transactions, authorization=None)[0]
        self.assertEqual(missing["review_status"], "MANUAL_REVIEW")
        self.assertIn("PLUS_AUTH_RECORD_MISSING", missing["review_reasons"])

    def test_multiple_fdpl_rows_remain_manual_review(self) -> None:
        transactions = self.worked_example() + [RefundTransaction("FDPL", "P", "800", 100)]
        self.assert_unresolved(self.run_report(transactions)[0], "MULTIPLE_TARGET_TERM_FDPL_ROWS_2")

    def test_exact_cents_are_preserved(self) -> None:
        transactions = [
            RefundTransaction("CHRG", "C", "899", "0.30"),
            RefundTransaction("PAYA", "P", "899", "0.10"),
            RefundTransaction("FDPL", "P", "800", "0.25"),
        ]
        self.assert_split(self.run_report(transactions)[0], "0.05", 0)

    def test_accounts_are_isolated_and_noncredit_accounts_are_excluded(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("PAYC", "P", "000", 30, pidm=2),
            RefundTransaction("TUIN", "C", "899", 100, pidm=3),
        ]
        rows = {row["cwid"]: row for row in self.run_report(transactions)}
        self.assertEqual(set(rows), {"TEST-1", "TEST-2"})
        self.assert_split(rows["TEST-1"], 500, 1500)
        self.assert_split(rows["TEST-2"], 0, 30)

    def test_varied_accounts_match_independent_charge_by_charge_allocation(self) -> None:
        rng = random.Random(84721)
        transactions = []
        expected = {}
        for pidm in range(1, 101):
            charges = {
                priority: rng.randint(1, 1000)
                for priority in rng.sample(["899", "891", "897", "889", "700", "001"], 3)
            }
            payments = {
                (priority, False): rng.randint(1, 1000)
                for priority in rng.sample(["899", "890", "809", "080", "800", "700"], 3)
            }
            payments[("800", True)] = rng.randint(1, 1000)
            payments[("000", False)] = sum(charges.values())
            for priority, amount in charges.items():
                transactions.append(RefundTransaction(f"C{priority}", "C", priority, amount, pidm=pidm))
            for (priority, is_fdpl), amount in payments.items():
                transactions.append(RefundTransaction(
                    "FDPL" if is_fdpl else f"P{priority}", "P", priority, amount, pidm=pidm
                ))

            remaining = payments.copy()
            for charge_priority in sorted(charges, reverse=True):
                owed = charges[charge_priority]
                for key in sorted(payments, key=lambda key: (-int(key[0]), key[1])):
                    priority, _ = key
                    if all(p == "0" or p == c for p, c in zip(priority, charge_priority)):
                        applied = min(owed, remaining[key])
                        remaining[key] -= applied
                        owed -= applied
                self.assertEqual(owed, 0)
            expected[f"TEST-{pidm}"] = (
                remaining[("800", True)],
                sum(amount for (_, is_fdpl), amount in remaining.items() if not is_fdpl),
            )
        rng.shuffle(transactions)
        rows = self.run_report(transactions)
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            with self.subTest(cwid=row["cwid"]):
                self.assert_split(row, *expected[row["cwid"]])


if __name__ == "__main__":
    unittest.main()
