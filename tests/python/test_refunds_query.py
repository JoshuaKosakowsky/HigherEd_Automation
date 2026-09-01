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

    def test_ach_delivery_uses_effective_date_and_nets_window_activity(self) -> None:
        delivery_sources = self.query[
            self.query.index("original_payment_source_amounts AS") :
            self.query.index("joined AS")
        ].upper()
        self.assertIn("S.EFFECTIVE_DATE", delivery_sources)
        self.assertIn("> 16", delivery_sources)
        self.assertIn("< 90", delivery_sources)
        self.assertIn("SUM(X.RAW_AMOUNT)", delivery_sources)
        self.assertIn("ACHK_WINDOW_NET", delivery_sources)

    def test_allocation_inputs_are_scoped_to_the_target_term(self) -> None:
        transactions = self.query[
            self.query.index("candidate_transactions AS") :
            self.query.index("balance_input_checks AS")
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

    def test_stored_balances_replace_priority_replay(self) -> None:
        self.assertIn("D.TBBDETC_PRIORITY", self.normalized_query)
        self.assertNotIn("LATER_PAYMENT_SUMMARY", self.normalized_query)
        self.assertNotIn("CREDITS_AFTER_TARGET_TERM_FDPL", self.normalized_query)
        self.assertNotIn("PRIORITY_ALLOCATION AS", self.normalized_query)
        self.assertNotIn("PAYMENT_POOLS AS", self.normalized_query)
        sources = self.query[
            self.query.index("selected_balance_sources AS") :
            self.query.index("balance_source_summary AS")
        ].upper()
        self.assertIn("X.RAW_TRANSACTION_BALANCE < 0", sources)
        self.assertIn("J.UNUSED_FDPL_AMOUNT", self.normalized_query)

    def test_priority_tie_assumption_is_retired(self) -> None:
        self.assertNotIn("FDPL_LAST_AT_SAME_PRIORITY", self.normalized_query)
        self.assertIn("AS FDPL_PRIORITY_TIE_RULE", self.normalized_query)
        self.assertIn("NOT_APPLICABLE_BALANCE_BASED_SOURCE", self.normalized_query)

    def test_schema_inventory_requires_priority(self) -> None:
        schema_query = REFUNDS_QUERY.with_name("validate_refund_schema.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("('TAISMGR', 'TBBDETC', 'PRIORITY')", schema_query)
        self.assertIn("('TAISMGR', 'TBRACCD', 'BALANCE')", schema_query)

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
    balance: int | str | None = 0
    term: str = "209980"
    aid_year: str = "9900"
    pidm: int = 1
    effective_date: str | None = "2099-08-01"
    activity_date: str = "2099-08-01"


class RefundsPostgresBalanceTests(unittest.TestCase):
    """Execute the report against synthetic PostgreSQL temporary tables."""

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
            RefundTransaction("FDPL", "P", "800", 4000, balance=-500),
            RefundTransaction("PAYC", "P", "000", 2000, balance=-1500),
        ]

    def run_report(
        self,
        transactions: list[RefundTransaction],
        *,
        authorization: str | None = "N",
        refund_hold: bool = False,
        active_ed: bool = True,
        query: str | None = None,
    ) -> list[dict]:
        query = re.sub(
            r"\b(?:taismgr|saturn|faismgr)\.", "pg_temp.",
            self.query if query is None else query,
        )
        query = query.replace(
            "CAST(NULL AS varchar(6)) AS target_term_override",
            "CAST('209980' AS varchar(6)) AS target_term_override",
        )
        query = query.replace(
            "CURRENT_DATE AS run_date", "DATE '2099-08-31' AS run_date"
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
                transaction.detail_code, transaction.amount, transaction.balance,
                transaction.effective_date, transaction.activity_date,
            ))
        for pidm in sorted({transaction.pidm for transaction in transactions}):
            insert("spriden", (pidm, f"TEST-{pidm}", "Synthetic", "Example", None))
            insert("spbpers", (pidm, "N", None, "N", "2099-08-01"))
            insert("tbbacct", (pidm, "RH" if refund_hold else None, "N", "2099-08-01"))
            if active_ed:
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

    def test_worked_example_and_transaction_order_independence(self) -> None:
        transactions = self.worked_example()
        for ordered in (transactions, list(reversed(transactions)), transactions[5:] + transactions[:5]):
            with self.subTest(order=[t.detail_code for t in ordered]):
                row = self.run_report(ordered)[0]
                self.assert_split(row, 500, 1500)
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                self.assertNotIn("PAYA", row["balance_sources"])
                self.assertNotIn("PAYB", row["balance_sources"])
                self.assertEqual(row["fdpl_priority_tie_rule"], "NOT_APPLICABLE_BALANCE_BASED_SOURCE")

    def test_output_columns_follow_requested_order(self) -> None:
        expected_columns = """
            cwid last_name first_name full_account_balance total_refund_amount
            proposed_student_delivery student_refund_amount proposed_parent_delivery
            parent_refund_amount balance_sources
            plus_to_student_status parent_plus_target_term refund_split_status
            third_party_review_required_ind third_party_match_source refund_hold_ind
            raw_delinquency_code active_ed_ind raw_refund_account_ind
            refund_account_selected_ind fdpl_row_count target_term_fdpl_amount
            fdpl_aidy_code fdpl_priority_tie_rule unused_fdpl_amount unused_non_fdpl_amount
            total_unused_payment_amount unpaid_charge_amount allocation_review_required_ind
            original_payment_row_count original_payment_total original_payment_detail
            deceased_ind deceased_date confidential_ind plus_auth_row_count
            plus_auth_raw_values negative_source_count
            ambiguous_source_pool_count review_status review_reasons last_ar_activity_date
            account_control_activity_date ed_activity_date plus_auth_activity_date
        """.split()
        self.assertEqual(list(self.run_report(self.worked_example())[0]), expected_columns)

    def test_standard_and_parent_delivery_codes(self) -> None:
        row = self.run_report(self.worked_example())[0]
        self.assertEqual(row["proposed_student_delivery"], "ARFD (System)")
        self.assertEqual(row["proposed_parent_delivery"], "RFDP")

        no_ed = self.run_report(self.worked_example(), active_ed=False)[0]
        self.assertEqual(no_ed["proposed_student_delivery"], "RFND (CHECK)")

        hold = self.run_report(self.worked_example(), refund_hold=True)[0]
        self.assertEqual(hold["proposed_student_delivery"], "Refund Hold - Student")

    def test_achk_clearing_boundaries_and_crvc_delivery(self) -> None:
        eligible = self.run_report([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-08-14")
        ])[0]
        self.assertEqual(eligible["proposed_student_delivery"], "AFRD (Transact)")
        self.assertEqual(eligible["review_status"], "TRANSACT_REVIEW")

        day_16 = self.run_report([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-08-15")
        ])[0]
        self.assertEqual(day_16["proposed_student_delivery"], "ACHK Clearing Wait")
        self.assertEqual(day_16["review_status"], "WAIT_ACH_CLEARING")

        day_90 = self.run_report([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-06-02")
        ])[0]
        self.assertEqual(day_90["proposed_student_delivery"], "ARFD (System)")

        crvc = self.run_report([
            RefundTransaction("CRVC", "P", "000", 50, balance=-50,
                              effective_date="2099-08-31")
        ])[0]
        self.assertEqual(crvc["proposed_student_delivery"], "CRVC (Transact)")

    def test_achk_window_net_limits_transact_amount_after_return(self) -> None:
        row = self.run_report([
            RefundTransaction("ACHK", "P", "000", 1000, balance=-800),
            RefundTransaction("ACHK", "P", "000", -400),
            RefundTransaction("PAYC", "P", "000", 400, balance=-200),
        ])[0]
        self.assertEqual(row["student_refund_amount"], 1000)
        self.assertEqual(
            row["proposed_student_delivery"],
            "AFRD (Transact) 600.00; ACHK Return/Net Review 200.00; "
            "ARFD (System) 200.00",
        )
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")
        self.assertIn(
            "ACHK_ELIGIBLE_NET_LESS_THAN_REMAINING_BALANCE", row["review_reasons"]
        )

    def test_completed_team_example_parent_plus_and_ach_are_separate_sources(self) -> None:
        transactions = [
            RefundTransaction("TUIN", "C", "899", 1660),
            RefundTransaction("SCHL", "P", "890", 50),
            RefundTransaction("LOAN", "P", "800", 272),
            RefundTransaction("FDPL", "P", "800", 958, balance=-194),
            RefundTransaction("ACHK", "P", "000", 50, balance=-50),
            RefundTransaction("GRNT", "P", "000", 574),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 194, 50)
        self.assertEqual(row["original_payment_total"], 50)
        self.assertIn("FDPL", row["balance_sources"])
        self.assertIn("ACHK", row["balance_sources"])

    def test_completed_team_example_parent_plus_and_other_student_source(self) -> None:
        transactions = [
            RefundTransaction("TUIN", "C", "899", 1393),
            RefundTransaction("SCHL", "P", "890", 300),
            RefundTransaction("LOAN", "P", "800", 322),
            RefundTransaction("FDPL", "P", "800", 1644, balance=-1057),
            RefundTransaction("ACHK", "P", "000", 100),
            RefundTransaction("COFP", "P", "000", 184, balance=-100),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 1057, 100)
        self.assertEqual(row["original_payment_row_count"], 0)
        self.assertIn("COFP", row["balance_sources"])
        self.assertNotIn("ACHK", row["balance_sources"])

    def test_priority_does_not_override_applied_balance(self) -> None:
        transactions = self.worked_example()
        transactions[5] = replace(transactions[5], priority="000")
        transactions[6] = replace(transactions[6], priority="899")
        self.assert_split(self.run_report(transactions)[0], 500, 1500)

    def test_invalid_remaining_source_priority_flags_review_but_keeps_split(self) -> None:
        transactions = self.worked_example()
        transactions[5] = replace(transactions[5], priority=None)
        row = self.run_report(transactions)[0]
        self.assert_split(row, 500, 1500, review_required=True)
        self.assertIn("MISSING_OR_INVALID_DETAIL_PRIORITY", row["review_reasons"])

    def test_missing_transaction_balance_blocks_split(self) -> None:
        transactions = self.worked_example()
        transactions[6] = replace(transactions[6], balance=None)
        self.assert_unresolved(self.run_report(transactions)[0], "MISSING_TRANSACTION_BALANCE")

    def test_unexpected_balance_sign_blocks_split(self) -> None:
        transactions = self.worked_example()
        transactions[3] = replace(transactions[3], balance=1)
        self.assert_unresolved(
            self.run_report(transactions)[0], "UNEXPECTED_TRANSACTION_BALANCE_SIGN"
        )

    def test_unpaid_charge_balance_blocks_split(self) -> None:
        transactions = self.worked_example()
        transactions[0] = replace(transactions[0], balance=100)
        row = self.run_report(transactions)[0]
        self.assertEqual(row["unpaid_charge_amount"], 100)
        self.assert_unresolved(row, "UNPAID_CHARGES_IN_STORED_BALANCES")

    def test_target_term_balances_must_reconcile_to_full_account_refund(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("OLDCH", "C", "899", 100, term="209910")
        ]
        self.assert_unresolved(
            self.run_report(transactions)[0],
            "TARGET_TERM_STORED_BALANCES_DIFFER_FROM_FULL_ACCOUNT_REFUND",
        )

    def test_settled_other_terms_do_not_change_current_split(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("OLDCH", "C", "899", 100, term="209910"),
            RefundTransaction("OLDPY", "P", "000", 100, term="209910"),
        ]
        self.assert_split(self.run_report(transactions)[0], 500, 1500)

    def test_amount_reversals_do_not_override_reconciled_balances(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("ADJ", "C", "879", -100),
            RefundTransaction("PAYA", "P", "899", -100),
        ]
        row = self.run_report(transactions)[0]
        self.assert_split(row, 500, 1500)
        self.assertGreater(row["negative_source_count"], 0)

    def test_card_review_uses_exact_remaining_transaction_balance(self) -> None:
        transactions = self.worked_example()
        transactions[6] = replace(transactions[6], detail_code="CRED", balance=-1500)
        row = self.run_report(transactions)[0]
        self.assert_split(row, 500, 1500)
        self.assertEqual(row["original_payment_total"], 1500)
        self.assertEqual(row["review_status"], "TRANSACT_REVIEW")

    def test_plus_to_student_authorization_and_hold_controls_remain(self) -> None:
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
            RefundTransaction("FDPL", "P", "800", "0.35", balance="-0.05"),
        ]
        self.assert_split(self.run_report(transactions)[0], "0.05", 0)

    def test_no_charges_returns_stored_fdpl_balance(self) -> None:
        row = self.run_report([
            RefundTransaction("FDPL", "P", "800", 500, balance=-500)
        ])[0]
        self.assert_split(row, 500, 0)

    def test_accounts_are_isolated_and_noncredit_accounts_are_excluded(self) -> None:
        transactions = self.worked_example() + [
            RefundTransaction("PAYC", "P", "000", 30, balance=-30, pidm=2),
            RefundTransaction("TUIN", "C", "899", 100, pidm=3),
        ]
        rows = {row["cwid"]: row for row in self.run_report(transactions)}
        self.assertEqual(set(rows), {"TEST-1", "TEST-2"})
        self.assert_split(rows["TEST-1"], 500, 1500)
        self.assert_split(rows["TEST-2"], 0, 30)

    def test_varied_accounts_follow_stored_source_balances(self) -> None:
        rng = random.Random(84721)
        transactions: list[RefundTransaction] = []
        expected: dict[str, tuple[int, int]] = {}
        for pidm in range(1, 101):
            parent = rng.randint(0, 500)
            student = rng.randint(0, 500)
            transactions.extend([
                RefundTransaction("CHRG", "C", "899", 1000, pidm=pidm),
                RefundTransaction("FDPL", "P", "800", 400 + parent,
                                  balance=-parent, pidm=pidm),
                RefundTransaction("PAYA", "P", "000", 600 + student,
                                  balance=-student, pidm=pidm),
            ])
            expected[f"TEST-{pidm}"] = (parent, student)
        rng.shuffle(transactions)
        rows = self.run_report(transactions)
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            with self.subTest(cwid=row["cwid"]):
                self.assert_split(row, *expected[row["cwid"]])

    def test_diagnostic_preserves_raw_amount_and_balance_groups(self) -> None:
        query = REFUNDS_QUERY.with_name("Refund_allocation_diagnostic.sql").read_text(
            encoding="utf-8"
        )
        transactions = self.worked_example() + [
            RefundTransaction("PAYB", "P", "890", -500),
            RefundTransaction("TUIN", "C", "899", 200, term="209910"),
            RefundTransaction("PAYC", "P", "000", 100, balance=-100, pidm=2),
        ]
        self.assertEqual(self.run_report(transactions, query=query), [])
        query = query.replace(
            "CAST(NULL AS varchar(30)) AS cwid", "CAST('TEST-1' AS varchar(30)) AS cwid"
        )
        rows = self.run_report(transactions, query=query)
        groups = {(row["term_code"], row["detail_code"]): row for row in rows}
        self.assertEqual(groups[("209910", "TUIN")]["net_amount_raw"], 200)
        self.assertEqual(groups[("209980", "PAYB")]["net_amount_raw"], 1000)
        self.assertEqual(groups[("209980", "PAYC")]["net_balance_raw"], -1500)
        self.assertTrue({"cwid", "pidm", "first_name", "last_name"}.isdisjoint(rows[0]))


if __name__ == "__main__":
    unittest.main()
