from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import unittest
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from data_processing.refunds import REPORT_COLUMNS, RefundParameters, allocate_refunds
from data_processing.refunds.export import WORKBOOK_COLUMNS
from data_processing.refunds.extract import ExtractSettings, render_extract_sql
from data_processing.refunds.pipeline import run_refund_download_pipeline
from tests.python import test_refunds_workflow as python_cases


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFUNDS_QUERY = REPOSITORY_ROOT / "query" / "AR" / "refunds" / "Refunds.sql"


class RefundsQueryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.query = REFUNDS_QUERY.read_text(encoding="utf-8")
        cls.normalized_query = re.sub(r"\s+", " ", cls.query).upper()

    def section(self, start: str, end: str) -> str:
        return self.query[self.query.index(start) : self.query.index(end)].upper()

    def test_query_is_one_read_only_statement(self) -> None:
        body = re.sub(r"/\*.*?\*/|--[^\n]*", "", self.query, flags=re.S)
        body = re.sub(r"'(?:''|[^'])*'", "''", body)
        self.assertEqual(body.count(";"), 1)
        self.assertNotRegex(body.upper(), r"\b(CREATE|INSERT|UPDATE|DELETE|DROP|TRUNCATE|CALL)\b")
        self.assertTrue(body.lstrip().startswith("WITH RECURSIVE"))

    def test_history_is_loaded_once_after_candidate_selection(self) -> None:
        screening = self.section("screening_transactions AS MATERIALIZED", "account_balance_rollup AS")
        self.assertIn("FROM REPORT_SCOPE_PIDMS V", screening)
        self.assertIn("T.TBRACCD_PIDM = V.PIDM", screening)
        self.assertNotIn("TAISMGR.TBRACCD", self.query[self.query.index("account_balance_rollup AS"):].upper())
        self.assertIn("FULL_ACCOUNT_BALANCE <= 0", self.normalized_query)

    def test_recursion_uses_per_account_vectors_without_pair_relation_rescans(self) -> None:
        allocation = self.section("allocation_final AS MATERIALIZED", "allocation_transfer_summary AS")
        self.assertIn("CROSS JOIN LATERAL", allocation)
        self.assertIn("I.PRIORITY_MATCHES", allocation)
        self.assertIn("MIN(K.VALUE::INTEGER)", allocation)
        self.assertIn("TITLE_IV_GIVEN_BY_FY", allocation)
        self.assertIn("TITLE_IV_RECEIVED_BY_FY", allocation)
        self.assertNotIn("JOIN ALLOCATION_PAIRS", allocation)
        self.assertNotIn("JOIN NUMBERED_PAYMENT_SOURCES", allocation)
        self.assertNotIn("PRECURRENT_LOCAL_ALLOCATION", self.normalized_query)

    def test_settlement_requires_known_zero_balances(self) -> None:
        history = self.section("open_term_balances AS", "allocation_ledger AS")
        self.assertIn("RAW_TRANSACTION_BALANCE IS DISTINCT FROM 0", history)
        self.assertIn("CUMULATIVE_BALANCE = 0 AND UNRESOLVED_PREFIX = 0", history)

    def test_schema_inventory_requires_new_metadata(self) -> None:
        schema_query = REFUNDS_QUERY.with_name("validate_refund_schema.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("('TAISMGR', 'TBBDETC', 'PRIORITY')", schema_query)
        self.assertIn("('TAISMGR', 'TBBDETC', 'DCAT_CODE')", schema_query)
        self.assertIn("('TAISMGR', 'TBBDETC', 'TIV_IND')", schema_query)


@dataclass(frozen=True)
class RefundTransaction:
    detail_code: str
    type_ind: str
    priority: str | None
    amount: int | str | None
    balance: int | str | None = 0
    term: str = "209980"
    aid_year: str | None = "9900"
    pidm: int = 1
    effective_date: str | None = "2099-08-01"
    activity_date: str = "2099-08-01"
    category: str = "CSH"
    title_iv: str = "N"
    tran_number: int | None = None


class RefundsPostgresPolicyTests(unittest.TestCase):
    """Execute the complete report against synthetic PostgreSQL tables."""

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
            RefundTransaction("FDPL", "P", "800", 4000, balance=-500,
                              category="FA", title_iv="Y"),
            RefundTransaction("PAYC", "P", "000", 2000, balance=-1500),
        ]

    def run_report(
        self,
        transactions: list[RefundTransaction],
        *,
        authorizations: dict[str, str | list[str]] | None = None,
        refund_hold: bool = False,
        active_ed: bool = True,
        target_term: str = "209980",
        previous_term_override: str | None = None,
        run_date: str = "2099-08-31",
        query: str | None = None,
        context_activity_date: str | None = None,
        explain: bool = False,
    ) -> list[dict]:
        report_query = re.sub(
            r"\b(?:taismgr|saturn|faismgr)\.", "pg_temp.",
            self.query if query is None else query,
        )
        report_query = report_query.replace(
            "CAST(NULL AS varchar(6)) AS target_term_override",
            f"CAST('{target_term}' AS varchar(6)) AS target_term_override",
        )
        if previous_term_override is not None:
            report_query = report_query.replace(
                "CAST(NULL AS varchar(6)) AS previous_term_override",
                f"CAST('{previous_term_override}' AS varchar(6)) AS previous_term_override",
            )
        report_query = report_query.replace(
            "CURRENT_DATE AS run_date", f"DATE '{run_date}' AS run_date"
        )

        schemas = {
            "tbraccd": "pidm int, term_code text, aidy_code text, tran_number int, "
                "detail_code text, amount numeric, balance numeric, "
                "effective_date date, activity_date timestamp",
            "tbbdetc": "detail_code text, desc text, type_ind text, priority text, "
                "dcat_code text, tiv_ind text",
            "spriden": "pidm int, id text, last_name text, first_name text, change_ind text",
            "spbpers": "pidm int, dead_ind text, dead_date date, confid_ind text, activity_date date",
            "tbbacct": "pidm int, deli_code text, refund_ind text, activity_date date",
            "sprhold": "pidm int, hldd_code text, to_date date, activity_date date",
            "rlrpapp": "pidm int, aidy_code text, plus_to_student text, activity_date date",
        }
        sql = ["BEGIN; SET LOCAL statement_timeout = '20s';"]
        for table, columns in schemas.items():
            prefixed = ", ".join(f"{table}_{column}" for column in columns.split(", "))
            sql.append(f"CREATE TEMP TABLE {table} ({prefixed});")

        def insert(table: str, values: tuple[object, ...]) -> None:
            literals = [
                "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"
                for value in values
            ]
            sql.append(f"INSERT INTO {table} VALUES ({', '.join(literals)});")

        details: dict[str, tuple[str, str | None, str, str]] = {}
        used_numbers: dict[int, set[int]] = {}
        next_numbers: dict[int, int] = {}
        for transaction in transactions:
            definition = (
                transaction.type_ind,
                transaction.priority,
                transaction.category,
                transaction.title_iv,
            )
            if transaction.detail_code in details:
                self.assertEqual(details[transaction.detail_code], definition)
            else:
                details[transaction.detail_code] = definition
                insert("tbbdetc", (transaction.detail_code, "Synthetic source", *definition))

            occupied = used_numbers.setdefault(transaction.pidm, set())
            if transaction.tran_number is None:
                number = next_numbers.get(transaction.pidm, 1)
                while number in occupied:
                    number += 1
            else:
                number = transaction.tran_number
            self.assertNotIn(number, occupied)
            occupied.add(number)
            next_numbers[transaction.pidm] = max(next_numbers.get(transaction.pidm, 1), number + 1)
            insert("tbraccd", (
                transaction.pidm, transaction.term, transaction.aid_year, number,
                transaction.detail_code, transaction.amount, transaction.balance,
                transaction.effective_date, transaction.activity_date,
            ))

        authorization_rows = {"9900": "N"} if authorizations is None else authorizations
        control_date = context_activity_date or run_date
        for pidm in sorted({transaction.pidm for transaction in transactions}):
            insert("spriden", (pidm, f"TEST-{pidm}", "Synthetic", "Example", None))
            insert("spbpers", (pidm, "N", None, "N", run_date))
            insert("tbbacct", (pidm, "RH" if refund_hold else None, "N", control_date))
            if active_ed:
                insert("sprhold", (pidm, "ED", "9999-12-31", control_date))
            for aid_year, values in authorization_rows.items():
                for value in values if isinstance(values, list) else [values]:
                    insert("rlrpapp", (pidm, aid_year, value, control_date))

        if explain:
            # Representative lookup indexes belong only to this temporary fixture.
            sql.extend([
                "CREATE INDEX ON tbraccd (tbraccd_pidm);",
                "CREATE INDEX ON tbraccd (tbraccd_term_code);",
                "CREATE INDEX ON tbraccd (tbraccd_detail_code, tbraccd_effective_date);",
                "CREATE UNIQUE INDEX ON tbbdetc (tbbdetc_detail_code);",
                "CREATE INDEX ON spriden (spriden_id);",
                *(f"ANALYZE {table};" for table in schemas),
            ])
            sql.append("EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON) "
                       + report_query.rstrip().removesuffix(";") + "; ROLLBACK;")
        else:
            sql.append(
                "SELECT COALESCE(JSON_AGG(report), '[]'::json) FROM ("
                + report_query.rstrip().removesuffix(";")
                + ") report; ROLLBACK;"
            )
        result = subprocess.run(
            [self.psql, "-X", "-qAt", "--set=ON_ERROR_STOP=1", "--dbname", self.dsn],
            input="\n".join(sql), text=True, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout, parse_float=Decimal)

    def one(self, transactions: list[RefundTransaction], **kwargs: object) -> dict:
        rows = self.run_report(transactions, **kwargs)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def assert_split(self, row: dict, parent: int | str, student: int | str) -> None:
        parent_amount = Decimal(str(parent))
        student_amount = Decimal(str(student))
        self.assertEqual(row["parent_refund_amount"], parent_amount)
        self.assertEqual(row["student_refund_amount"], student_amount)
        self.assertEqual(row["total_refund_amount"], parent_amount + student_amount)
        self.assertEqual(row["total_unused_payment_amount"], row["total_refund_amount"])
        self.assertEqual(row["refund_split_status"], "CALCULATED_SUBJECT_TO_REVIEW")

    def assert_matches_python(self, actual: dict, expected: dict, label: str = "") -> None:
        for column in REPORT_COLUMNS:
            a, e = actual[column], expected[column]
            a = None if pd.isna(a) else a
            e = None if pd.isna(e) else e
            if column == "review_reasons":
                a, e = set((a or "").split("; ")), set((e or "").split("; "))
            elif column.endswith("_date"):
                a = pd.Timestamp(a) if a else None
                e = pd.Timestamp(e) if e else None
            self.assertEqual(a, e, f"{label}: {column}")

    def test_worked_example_uses_priority_allocation(self) -> None:
        row = self.one(self.worked_example())
        self.assert_split(row, 500, 1500)
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertNotIn("PAYA", row["balance_sources"])
        self.assertNotIn("PAYB", row["balance_sources"])
        self.assertIn("FDPL", row["balance_sources"])
        self.assertIn("PAYC", row["balance_sources"])
        self.assertEqual(
            row["fdpl_priority_tie_rule"],
            "EFFECTIVE_PRIORITY_THEN_EARLIEST_TRAN_NUMBER",
        )

    def test_output_columns_follow_requested_order_with_policy_audit(self) -> None:
        expected = """
            cwid last_name first_name full_account_balance total_refund_amount
            proposed_student_delivery student_refund_amount proposed_parent_delivery
            parent_refund_amount balance_sources plus_to_student_status
            parent_plus_target_term refund_split_status third_party_review_required_ind
            third_party_match_source refund_hold_ind raw_delinquency_code active_ed_ind
            raw_refund_account_ind refund_account_selected_ind fdpl_row_count
            target_term_fdpl_amount fdpl_aidy_code fdpl_priority_tie_rule
            unused_fdpl_amount unused_non_fdpl_amount total_unused_payment_amount
            unpaid_charge_amount allocation_review_required_ind
            previous_term_balance_before_current_payments
            prior_terms_balance_before_current_payments
            title_iv_applied_to_older_fiscal_years unrestricted_applied_to_older_terms
            original_payment_row_count original_payment_total original_payment_detail
            deceased_ind deceased_date confidential_ind plus_auth_row_count
            plus_auth_raw_values negative_source_count ambiguous_source_pool_count
            review_status review_reasons last_ar_activity_date
            account_control_activity_date ed_activity_date plus_auth_activity_date
        """.split()
        self.assertEqual(list(self.one(self.worked_example())), expected)

    def test_cross_fy_title_iv_is_capped_and_refund_uses_unused_funds(self) -> None:
        row = self.one([
            RefundTransaction("OLD", "C", "899", 1000, balance=800, term="209955"),
            RefundTransaction("TIVA", "P", "000", 1200, balance=-1000,
                              category="CSH", title_iv="Y"),
        ])
        self.assert_split(row, 0, 1000)
        self.assertEqual(row["full_account_balance"], -200)
        self.assertEqual(row["unpaid_charge_amount"], 800)
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], 200)
        self.assertEqual(row["previous_term_balance_before_current_payments"], 1000)
        self.assertEqual(row["prior_terms_balance_before_current_payments"], 0)
        self.assertEqual(row["allocation_review_required_ind"], "Y")
        self.assertIn("POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT", row["review_reasons"])

    def test_positive_full_account_balances_are_excluded(self) -> None:
        rows = self.run_report([
            RefundTransaction("OLD", "C", "899", 1500, balance=1300, term="209955"),
            RefundTransaction("TIVA", "P", "000", 1200, balance=-1000,
                              category="FA", title_iv="Y"),
        ])
        self.assertEqual(rows, [])

    def test_dormant_historical_fiscal_credit_does_not_enter_recursion(self) -> None:
        rows = self.run_report([
            RefundTransaction("PAY0", "P", "000", 100, balance=-100, pidm=1),
            RefundTransaction("OLDP", "P", "000", 100, term="209780", pidm=2),
            RefundTransaction("OLDC", "C", "700", 200, term="209880", pidm=2),
        ])
        self.assertEqual([row["cwid"] for row in rows], ["TEST-1"])

    def test_cwid_validation_filter_limits_the_report_early(self) -> None:
        filtered_query = self.query.replace(
            "CAST(NULL AS varchar(30)) AS cwid_filter",
            "CAST('TEST-2' AS varchar(30)) AS cwid_filter",
        )
        rows = self.run_report([
            RefundTransaction("PAY0", "P", "000", 100, balance=-100, pidm=1),
            RefundTransaction("PAY0", "P", "000", 200, balance=-200, pidm=2),
        ], query=filtered_query)
        self.assertEqual([row["cwid"] for row in rows], ["TEST-2"])

    def test_targeted_filter_can_inspect_historical_only_credit(self) -> None:
        filtered_query = self.query.replace(
            "CAST(NULL AS varchar(30)) AS cwid_filter",
            "CAST('TEST-2' AS varchar(30)) AS cwid_filter",
        )
        rows = self.run_report([
            RefundTransaction("PAY0", "P", "000", 100, balance=-100, pidm=1),
            RefundTransaction(
                "PAY0", "P", "000", 200, balance=-200,
                term="209880", aid_year="9899", pidm=2,
            ),
        ], query=filtered_query)
        self.assertEqual([row["cwid"] for row in rows], ["TEST-2"])
        self.assertEqual(rows[0]["total_refund_amount"], Decimal("200.00"))

    def test_same_fy_title_iv_has_no_cap(self) -> None:
        row = self.one([
            RefundTransaction("OLD", "C", "899", 1000, term="209980"),
            RefundTransaction("TIVA", "P", "000", 1200, balance=-200,
                              term="210010", category="FA", title_iv="Y"),
        ], target_term="210010", run_date="2100-01-31")
        self.assert_split(row, 0, 200)
        self.assertEqual(row["unpaid_charge_amount"], 0)
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], 0)
        self.assertEqual(row["previous_term_balance_before_current_payments"], 1000)

    def test_non_title_iv_financial_aid_and_cash_are_unrestricted_cross_fy(self) -> None:
        for category in ("FA", "CSH"):
            with self.subTest(category=category):
                row = self.one([
                    RefundTransaction("OLD", "C", "899", 1000, term="209955"),
                    RefundTransaction("FREE", "P", "000", 1200, balance=-200,
                                      category=category, title_iv="N"),
                ])
                self.assert_split(row, 0, 200)
                self.assertEqual(row["unpaid_charge_amount"], 0)
                self.assertEqual(row["unrestricted_applied_to_older_terms"], 1000)

    def test_prior_surplus_can_pay_current_charges_with_title_iv_cap_retained(self) -> None:
        title_iv = self.one([
            RefundTransaction("TIVA", "P", "000", 1200, balance=-1000,
                              term="209955", aid_year="9899", category="FA", title_iv="Y"),
            RefundTransaction("CURR", "C", "700", 1000, balance=800),
        ])
        self.assert_split(title_iv, 0, 1000)
        self.assertEqual(title_iv["full_account_balance"], -200)
        self.assertEqual(title_iv["unpaid_charge_amount"], 800)

        unrestricted = self.one([
            RefundTransaction("FREE", "P", "000", 500, balance=-200,
                              term="209955", aid_year="9899", category="FA", title_iv="N"),
            RefundTransaction("CURR", "C", "700", 300),
        ])
        self.assert_split(unrestricted, 0, 200)
        self.assertEqual(unrestricted["unpaid_charge_amount"], 0)

    def test_precurrent_fiscal_year_respects_payment_eligibility(self) -> None:
        filtered_query = self.query.replace(
            "CAST(NULL AS varchar(30)) AS cwid_filter",
            "CAST('TEST-1' AS varchar(30)) AS cwid_filter",
        )
        row = self.one([
            RefundTransaction("OLD7", "C", "700", 100, term="209955"),
            RefundTransaction("P899", "P", "899", 100, balance=-100,
                              term="209955"),
            RefundTransaction("P000", "P", "000", 100, term="209955"),
        ], query=filtered_query)
        self.assert_split(row, 0, 100)
        self.assertIn("P899", row["balance_sources"])
        self.assertNotIn("P000", row["balance_sources"])

    def test_title_iv_source_give_cap_is_shared_across_older_years(self) -> None:
        row = self.one([
            RefundTransaction("OLD1", "C", "899", 150, term="209780"),
            RefundTransaction("OLD2", "C", "899", 150, term="209880"),
            RefundTransaction("TIVA", "P", "000", 500, balance=-300,
                              category="FA", title_iv="Y"),
        ])
        self.assert_split(row, 0, 300)
        self.assertEqual(row["unpaid_charge_amount"], 100)
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], 200)

    def test_destination_receive_cap_is_shared_across_source_years(self) -> None:
        row = self.one([
            RefundTransaction("OLD", "C", "899", 500, term="209780"),
            RefundTransaction("TIVA", "P", "000", 300, balance=-100,
                              term="209880", aid_year="9899", category="FA", title_iv="Y"),
            RefundTransaction("TIVB", "P", "000", 300, balance=-300,
                              category="FA", title_iv="Y"),
        ])
        self.assert_split(row, 0, 400)
        self.assertEqual(row["unpaid_charge_amount"], 300)

    def test_800a_sources_apply_before_regular_800(self) -> None:
        row = self.one([
            RefundTransaction("CHG8", "C", "899", 100, tran_number=10),
            RefundTransaction("FDPL", "P", "800", 100, balance=-100,
                              category="FA", title_iv="Y", tran_number=2),
            RefundTransaction("TPDT", "P", "800", 100, tran_number=3),
        ])
        self.assert_split(row, 100, 0)
        self.assertIn("FDPL", row["balance_sources"])
        self.assertNotIn("TPDT", row["balance_sources"])

    def test_regular_800_ties_use_earliest_transaction_number(self) -> None:
        early_fdpl = self.one([
            RefundTransaction("CHG8", "C", "899", 100, tran_number=10),
            RefundTransaction("FDPL", "P", "800", 100, category="FA", title_iv="Y",
                              tran_number=1),
            RefundTransaction("OT8", "P", "800", 100, balance=-100, tran_number=2),
        ])
        self.assert_split(early_fdpl, 0, 100)

        late_fdpl = self.one([
            RefundTransaction("CHG8", "C", "899", 100, tran_number=10),
            RefundTransaction("FDPL", "P", "800", 100, balance=-100,
                              category="FA", title_iv="Y", tran_number=2),
            RefundTransaction("OT8", "P", "800", 100, tran_number=1),
        ])
        self.assert_split(late_fdpl, 100, 0)

    def test_000a_applies_first_then_ordinary_000_by_transaction(self) -> None:
        cofp = self.one([
            RefundTransaction("CHG", "C", "700", 100),
            RefundTransaction("PAY0", "P", "000", 100, balance=-100),
            RefundTransaction("COFP", "P", "000", 100),
        ])
        self.assert_split(cofp, 0, 100)
        self.assertIn("PAY0", cofp["balance_sources"])
        self.assertNotIn("COFP", cofp["balance_sources"])

        ach = self.one([
            RefundTransaction("CHG", "C", "700", 100),
            RefundTransaction("ACHK", "P", "000", 100, balance=-100,
                              effective_date="2099-08-01"),
            RefundTransaction("PAY0", "P", "000", 100),
        ])
        self.assert_split(ach, 0, 100)
        self.assertIn("PAY0", ach["balance_sources"])
        self.assertNotIn("ACHK", ach["balance_sources"])
        self.assertEqual(ach["proposed_student_delivery"], "ARFD (System)")

    def test_payment_priority_wildcard_and_charge_descending_order(self) -> None:
        row = self.one([
            RefundTransaction("C897", "C", "897", 100, tran_number=1),
            RefundTransaction("C899", "C", "899", 100, tran_number=2),
            RefundTransaction("P899", "P", "899", 100, tran_number=3),
            RefundTransaction("P890", "P", "890", 100, tran_number=4),
            RefundTransaction("FDPL", "P", "800", 100, balance=-100,
                              category="FA", title_iv="Y", tran_number=5),
        ])
        self.assert_split(row, 100, 0)
        self.assertEqual(row["unpaid_charge_amount"], 0)

    def test_charge_aggregation_preserves_exact_cents(self) -> None:
        row = self.one([
            RefundTransaction("CHG1", "C", "899", "0.10"),
            RefundTransaction("CHG2", "C", "899", "0.20"),
            RefundTransaction("FDPL", "P", "800", "0.35", balance="-0.05",
                              category="FA", title_iv="Y"),
        ])
        self.assert_split(row, "0.05", 0)

    def test_reversals_net_within_detail_term_and_aid_year(self) -> None:
        row = self.one([
            RefundTransaction("ACHK", "P", "000", 1000, balance=-600,
                              effective_date="2099-08-01", tran_number=1),
            RefundTransaction("ACHK", "P", "000", -400,
                              effective_date="2099-08-20", tran_number=2),
        ])
        self.assert_split(row, 0, 600)
        self.assertEqual(row["negative_source_count"], 1)
        self.assertEqual(row["original_payment_total"], 600)
        self.assertEqual(row["proposed_student_delivery"], "AFRD (Transact)")

    def test_charge_credit_offsets_a_different_detail_at_same_priority(self) -> None:
        row = self.one([
            RefundTransaction("HLTH", "C", "879", 1589),
            RefundTransaction("HIWR", "C", "879", -1589),
            RefundTransaction("PAY0", "P", "000", 100, balance=-100),
        ])
        self.assert_split(row, 0, 100)
        self.assertEqual(row["unpaid_charge_amount"], 0)
        self.assertNotIn("NEGATIVE_NET_SOURCE_REQUIRES_REVIEW", row["review_reasons"] or "")

    def test_cross_detail_charge_credits_do_not_create_false_historical_debt(self) -> None:
        row = self.one([
            RefundTransaction("HLTH", "C", "879", "1111", term="209780"),
            RefundTransaction("HIWR", "C", "879", "-1111", term="209780"),
            RefundTransaction("HLTH", "C", "879", "2222", term="209880"),
            RefundTransaction("HIWR", "C", "879", "-2222", term="209880"),
            RefundTransaction("OLD", "C", "899", "4750.25", term="209955"),
            RefundTransaction("HLTH", "C", "879", "3333", term="209955"),
            RefundTransaction("HIWR", "C", "879", "-3333", term="209955"),
            RefundTransaction("TUIN", "C", "899", "9000", tran_number=20),
            RefundTransaction("FEES", "C", "897", "1500", tran_number=21),
            RefundTransaction("HOUS", "C", "889", "2500", tran_number=22),
            RefundTransaction("HLTH", "C", "879", "1600", tran_number=23),
            RefundTransaction("HIWR", "C", "879", "-1600", tran_number=24),
            RefundTransaction("FDPL", "P", "800", "12000", tran_number=25,
                              category="PPL", title_iv="Y"),
            RefundTransaction("FDSL", "P", "800", "1500", tran_number=26,
                              category="FAL", title_iv="Y"),
            RefundTransaction("FDUL", "P", "800", "500", tran_number=27,
                              category="FAL", title_iv="Y"),
            RefundTransaction("PELL", "P", "800", "1500", tran_number=28,
                              category="FAG", title_iv="Y"),
            RefundTransaction("SCHP", "P", "000", "6000", tran_number=29,
                              category="FAS", title_iv="N"),
        ], target_term="209980", run_date="2099-08-31")
        self.assert_split(row, 0, "3749.75")
        self.assertEqual(row["unpaid_charge_amount"], 0)
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], Decimal("200.00"))
        self.assertEqual(row["unrestricted_applied_to_older_terms"], Decimal("4550.25"))
        self.assertNotIn("NEGATIVE_NET_SOURCE_REQUIRES_REVIEW", row["review_reasons"])

    def test_multiple_fdpl_aid_years_use_each_authorization(self) -> None:
        row = self.one([
            RefundTransaction("FDPL", "P", "800", 300, balance=-300,
                              term="209880", aid_year="9899", category="FA", title_iv="Y"),
            RefundTransaction("FDPL", "P", "800", 300, balance=-300,
                              aid_year="9900", category="FA", title_iv="Y"),
        ], authorizations={"9899": "Y", "9900": "N"})
        self.assert_split(row, 300, 300)
        self.assertEqual(row["plus_to_student_status"], "MIXED")
        self.assertEqual(row["proposed_parent_delivery"], "RFDP")

    def test_missing_or_conflicting_plus_authorization_blocks_split(self) -> None:
        transactions = [
            RefundTransaction("FDPL", "P", "800", 100, balance=-100,
                              category="FA", title_iv="Y")
        ]
        missing = self.one(transactions, authorizations={})
        self.assertIsNone(missing["parent_refund_amount"])
        self.assertIn("PLUS_AUTH_RECORD_MISSING", missing["review_reasons"])
        conflict = self.one(transactions, authorizations={"9900": ["Y", "N"]})
        self.assertIsNone(conflict["parent_refund_amount"])
        self.assertIn("PLUS_AUTH_VALUES_CONFLICT", conflict["review_reasons"])
        invalid = self.one(transactions, authorizations={"9900": ""})
        self.assertIsNone(invalid["parent_refund_amount"])
        self.assertIn("PLUS_AUTH_VALUES_CONFLICT", invalid["review_reasons"])

    def test_ach_boundaries_show_exact_date_and_180_day_warning(self) -> None:
        waiting = self.one([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-08-16")
        ])
        self.assertEqual(
            waiting["proposed_student_delivery"], "ACHK Clearing Wait until 09/01/2099"
        )
        self.assertEqual(waiting["review_status"], "WAIT_ACH_CLEARING")

        day_16 = self.one([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-08-15")
        ])
        self.assertEqual(day_16["proposed_student_delivery"], "AFRD (Transact)")

        day_180 = self.one([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-03-04")
        ])
        self.assertEqual(day_180["proposed_student_delivery"], "AFRD (Transact)")

        day_181 = self.one([
            RefundTransaction("ACHK", "P", "000", 50, balance=-50,
                              effective_date="2099-03-03")
        ])
        self.assertEqual(
            day_181["proposed_student_delivery"], "AFRD (Transact) - May Be Too Old"
        )

    def test_crvc_and_standard_student_delivery_codes(self) -> None:
        crvc = self.one([
            RefundTransaction("CRVC", "P", "000", 50, balance=-50)
        ])
        self.assertEqual(crvc["proposed_student_delivery"], "CRVC (Transact)")

        system = self.one([
            RefundTransaction("PAY0", "P", "000", 50, balance=-50)
        ])
        self.assertEqual(system["proposed_student_delivery"], "ARFD (System)")
        check = self.one([
            RefundTransaction("PAY0", "P", "000", 50, balance=-50)
        ], active_ed=False)
        self.assertEqual(check["proposed_student_delivery"], "RFND (CHECK)")
        hold = self.one([
            RefundTransaction("PAY0", "P", "000", 50, balance=-50)
        ], refund_hold=True)
        self.assertEqual(hold["proposed_student_delivery"], "Refund Hold - Student")

    def test_historical_term_60_can_be_selected_as_previous_term(self) -> None:
        row = self.one([
            RefundTransaction("OLD", "C", "899", 100, term="210060"),
            RefundTransaction("PAY0", "P", "000", 200, balance=-100,
                              term="210080"),
        ], target_term="210080", previous_term_override="210060", run_date="2100-08-31")
        self.assertEqual(row["previous_term_balance_before_current_payments"], 100)
        self.assertEqual(row["prior_terms_balance_before_current_payments"], 0)

    def test_stored_balance_is_diagnostic_and_does_not_replace_reconstruction(self) -> None:
        transactions = self.worked_example()
        transactions[-1] = replace(transactions[-1], balance=0)
        row = self.one(transactions)
        self.assert_split(row, 500, 1500)
        self.assertEqual(row["allocation_review_required_ind"], "Y")
        self.assertIn("STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION", row["review_reasons"])

    def test_missing_transaction_amount_blocks_the_split(self) -> None:
        row = self.one(self.worked_example() + [
            RefundTransaction("NULL", "C", "700", None)
        ])
        self.assertIsNone(row["student_refund_amount"])
        self.assertIsNone(row["parent_refund_amount"])
        self.assertIn("MISSING_TRANSACTION_AMOUNT", row["review_reasons"])

    def test_diagnostic_exposes_raw_metadata_without_person_identifiers(self) -> None:
        query = REFUNDS_QUERY.with_name("Refund_allocation_diagnostic.sql").read_text(
            encoding="utf-8"
        )
        transactions = self.worked_example()
        self.assertEqual(self.run_report(transactions, query=query), [])
        query = query.replace(
            "CAST(NULL AS varchar(30)) AS cwid", "CAST('TEST-1' AS varchar(30)) AS cwid"
        )
        rows = self.run_report(transactions, query=query)
        fdpl = next(row for row in rows if row["detail_code"] == "FDPL")
        self.assertEqual(fdpl["category_code"], "FA")
        self.assertEqual(fdpl["title_iv_ind"], "Y")
        self.assertEqual(fdpl["first_tran_number"], fdpl["last_tran_number"])
        self.assertIn("effective", fdpl["transaction_detail"])
        self.assertTrue({"cwid", "pidm", "first_name", "last_name"}.isdisjoint(fdpl))

    def test_manual_and_api_exports_select_same_candidates_with_full_history(self) -> None:
        transactions = [
            # Target activity, net zero, but incompatible priorities leave a refund.
            RefundTransaction("CHG9", "C", "899", 100, pidm=1),
            RefundTransaction("PAY7", "P", "897", 100, balance=-100, pidm=1),
            # Negative stored payment at the two-year boundary; history is not cut.
            RefundTransaction("PAY0", "P", "000", 20, balance=-20, term="209780", pidm=2),
            RefundTransaction("OLD", "C", "899", 10, term="208980", pidm=2),
            RefundTransaction("PAY0", "P", "000", 10, term="208980", pidm=2),
            # Before boundary, no qualifying activity.
            RefundTransaction("PAY0", "P", "000", 20, balance=-20, term="209755", pidm=3),
            # HOMP at day 32, without target activity or a negative stored payment.
            RefundTransaction("HOMP", "C", "889", 10, term="209955", pidm=4, effective_date="2099-07-30"),
            RefundTransaction("PAY0", "P", "000", 20, term="209955", pidm=4),
            RefundTransaction("HOMP", "C", "889", 10, term="209955", pidm=5, effective_date="2099-07-29"),
            RefundTransaction("PAY0", "P", "000", 20, term="209955", pidm=5),
            RefundTransaction("HOMP", "C", "889", 10, term="209955", pidm=6, effective_date="2099-09-01"),
            RefundTransaction("PAY0", "P", "000", 20, term="209955", pidm=6),
            # Positive full-account balance, despite current activity/unused payment.
            RefundTransaction("CHG9", "C", "899", 100, pidm=7),
            RefundTransaction("PAY7", "P", "897", 50, balance=-50, pidm=7),
            # Settled target-term account: SQL candidate, later omitted by Python.
            RefundTransaction("CHG9", "C", "899", 100, pidm=8),
            RefundTransaction("PAY0", "P", "000", 100, pidm=8),
            # Negative charge balance does not qualify as a payment credit.
            RefundTransaction("WAIV", "C", "899", -20, balance=-20, term="209955", pidm=9),
            # Overlap across all three candidate branches must not duplicate rows.
            RefundTransaction("HOMP", "C", "889", 10, pidm=10),
            RefundTransaction("PAY0", "P", "000", 20, balance=-10, pidm=10),
            # Older credits do not erase an all-history debt in the scope filter.
            RefundTransaction("PAY0", "P", "000", 20, balance=-20, pidm=11),
            RefundTransaction("OLD", "C", "899", 30, term="208980", pidm=11),
            # Recent TPPY selects the account even when applied; day 33 does not.
            RefundTransaction("CHG8", "C", "899", 100, term="209955", pidm=12),
            RefundTransaction("TPPY", "P", "800", 100, term="209955", pidm=12,
                              effective_date="2099-07-30"),
            RefundTransaction("FREE", "P", "000", 50, term="209955", pidm=12),
            RefundTransaction("TPPY", "P", "800", 10, term="209955", pidm=13,
                              effective_date="2099-07-29"),
            RefundTransaction("FREE", "P", "000", 50, term="209955", pidm=13),
            # Candidate scope is conservative; Python/SQL review nets reversal.
            RefundTransaction("TPPY", "P", "800", 10, term="209955", pidm=14,
                              effective_date="2099-07-30"),
            RefundTransaction("TPPY", "P", "800", -10, term="209955", pidm=14),
            RefundTransaction("FREE", "P", "000", 50, term="209955", pidm=14),
        ]
        root = REFUNDS_QUERY.parent
        expected = {1, 2, 4, 8, 10, 12, 14}
        downloads = {}
        for name in ("transactions", "context"):
            with self.subTest(export=name):
                manual = self.run_report(transactions, query=(root / f"refund_{name}_manual.sql").read_text())
                downloads[name] = pd.DataFrame(manual)
                self.assertEqual({row["pidm"] for row in manual}, expected)
                self.assertTrue(all(row["extract_row_count"] == len(manual) for row in manual))
                template = (root / f"refund_{name}_extract.sql").read_text()
                settings = ExtractSettings("209980", 2, Path("unused"), run_date=date(2099, 8, 31))
                api = []
                for batch in range(2):
                    api.extend(self.run_report(transactions, query=render_extract_sql(template, settings, batch)))
                def comparable(rows):
                    return sorted(
                        (json.dumps({k: v for k, v in row.items() if k != "extract_row_count"}, sort_keys=True)
                         for row in rows)
                    )
                self.assertEqual(comparable(manual), comparable(api))
                if name == "transactions":
                    self.assertEqual(len(manual), sum(t.pidm in expected for t in transactions))
                    self.assertIn("208980", {row["term_code"] for row in manual if row["pidm"] == 2})
                else:
                    self.assertEqual(len(manual), len(expected))

        # Exercise the actual website-download path through the exported workbook.
        with TemporaryDirectory() as directory:
            work = Path(directory)
            for name, frame in downloads.items():
                frame.to_csv(work / f"{name}.csv", index=False)
            output, report = run_refund_download_pipeline(
                parameters=RefundParameters("209980", date(2099, 8, 31)),
                transaction_file=work / "transactions.csv",
                context_file=work / "context.csv",
                output_file=work / "refunds.xlsx",
            )
            expected_refunds = {
                "TEST-1": 100, "TEST-2": 20, "TEST-4": 10, "TEST-10": 10,
                "TEST-12": 50, "TEST-14": 50,
            }
            self.assertEqual(dict(zip(report.cwid, report.total_refund_amount)), expected_refunds)
            sql_rows = self.run_report(transactions)
            self.assertEqual({row["cwid"] for row in sql_rows}, set(expected_refunds))
            by_cwid = {row["cwid"]: row for row in report.to_dict("records")}
            for row in sql_rows:
                self.assert_matches_python(row, by_cwid[row["cwid"]], row["cwid"])
            for row in report.to_dict("records"):
                self.assertEqual(row["student_refund_amount"], expected_refunds[row["cwid"]])
                self.assertEqual(row["parent_refund_amount"], Decimal("0.00"))
                if row["cwid"] in {"TEST-4", "TEST-10"}:
                    self.assertIn("Mines Park Charge - Review", row["review_reasons"])
                if row["cwid"] == "TEST-12":
                    self.assertIn("Possible Third Party refund", row["review_reasons"])
                if row["cwid"] == "TEST-14":
                    self.assertNotIn("Possible Third Party refund", row["review_reasons"] or "")
            sheets = pd.read_excel(output, sheet_name=None)
            for sheet in sheets.values():
                self.assertEqual(sheet.columns.tolist(), WORKBOOK_COLUMNS)
            workbook = pd.concat([
                sheet[["cwid", "tab_refund_amount"]]
                for sheet in sheets.values() if not sheet.empty
            ], ignore_index=True)
            self.assertEqual(dict(zip(workbook.cwid, workbook.tab_refund_amount)), expected_refunds)
            self.assertEqual(set(sheets["Mines Park Reviews"].cwid), {"TEST-4", "TEST-10"})
            self.assertEqual(set(sheets["Third Party Reviews"].cwid), {"TEST-12"})

    def test_sql_matches_current_python_allocation_scenarios(self) -> None:
        sql_case = self
        filtered = self.query.replace(
            "CAST(NULL AS varchar(30)) AS cwid_filter",
            "CAST('TEST-1' AS varchar(30)) AS cwid_filter",
        )

        class CompareWithSQL(python_cases.RefundAllocationTests):
            def report(self, transactions, **kwargs):
                expected = super().report(transactions, **kwargs)
                converted = [RefundTransaction(
                    detail_code=t.detail_code, type_ind=t.type_ind, priority=t.priority,
                    amount=t.amount, balance=t.stored_balance, term=t.term,
                    aid_year=t.aid_year, effective_date=t.effective_date,
                    activity_date=t.activity_date, category=t.category,
                    title_iv=t.title_iv, tran_number=t.tran_number,
                ) for t in transactions]
                arguments = {key: value for key, value in kwargs.items() if key != "expected_rows"}
                if "run_date" in arguments:
                    arguments["run_date"] = arguments["run_date"].isoformat()
                actual = sql_case.run_report(converted, query=filtered,
                                             context_activity_date="2099-08-31", **arguments)
                sql_case.assertEqual(len(actual), kwargs.get("expected_rows", 1))
                if actual:
                    sql_case.assert_matches_python(actual[0], expected, self._testMethodName)
                return expected

        for method in unittest.defaultTestLoader.getTestCaseNames(CompareWithSQL):
            with self.subTest(scenario=method):
                CompareWithSQL(method).debug()

    def test_sql_matches_python_for_seeded_open_history_population(self) -> None:
        rng = random.Random(90210)
        terms = ("209580", "209610", "209655", "209880", "209910", "209955", "209980")
        priorities = ("899", "897", "869", "890", "800", "700", "000")
        transactions = []
        for pidm in range(1, 81):
            for number in range(1, 31):
                kind = "P" if rng.random() < 0.55 else "C"
                priority = rng.choice(priorities)
                tiv = "Y" if kind == "P" and rng.random() < 0.5 else "N"
                code = "FDPL" if kind == "P" and priority == "800" and tiv == "Y" else kind + priority + tiv
                amount = Decimal(rng.randrange(1, 60000)) / 100
                if rng.random() < 0.1:
                    amount = -amount
                transactions.append(RefundTransaction(
                    code, kind, priority, amount, balance=-amount if kind == "P" else amount,
                    term=rng.choice(terms), aid_year="9900", pidm=pidm,
                    category="FA" if tiv == "Y" else "CSH", title_iv=tiv, tran_number=number,
                ))
            # Establish current activity, retaining both credit and positive-net cases.
            transactions.append(RefundTransaction("BASE", "P", "000", 100, balance=-100,
                                                  pidm=pidm, tran_number=31))
        actual = self.run_report(transactions)
        downloads = {}
        for name in ("transactions", "context"):
            downloads[name] = pd.DataFrame(self.run_report(
                transactions, query=REFUNDS_QUERY.with_name(f"refund_{name}_manual.sql").read_text(),
            ))
        expected = allocate_refunds(downloads["transactions"], downloads["context"],
                                    RefundParameters("209980", date(2099, 8, 31)))
        self.assertGreater(len(expected), 20)
        self.assertEqual({row["cwid"] for row in actual}, set(expected.cwid))
        by_cwid = {row["cwid"]: row for row in expected.to_dict("records")}
        for row in actual:
            with self.subTest(cwid=row["cwid"]):
                self.assert_matches_python(row, by_cwid[row["cwid"]], row["cwid"])

    def test_export_two_year_term_boundaries_and_validation_filter(self) -> None:
        root = REFUNDS_QUERY.parent
        template = (root / "refund_transactions_extract.sql").read_text()
        for run_date, target, first, excluded in (
            ("2024-02-29", "202410", "202210", "202180"),
            ("2026-05-16", "202655", "202455", "202410"),
            ("2026-07-16", "202680", "202480", "202455"),
        ):
            transactions = [
                RefundTransaction("PAY0", "P", "000", 10, balance=-10, term=first, pidm=1),
                RefundTransaction("PAY0", "P", "000", 10, balance=-10, term=excluded, pidm=2),
            ]
            with self.subTest(run_date=run_date):
                rows = self.run_report(transactions, query=(root / "refund_transactions_manual.sql").read_text(),
                                       target_term=target, run_date=run_date)
                self.assertEqual({row["pidm"] for row in rows}, {1})
                settings = ExtractSettings(target, 1, Path("unused"), cwid="TEST-2", run_date=date.fromisoformat(run_date))
                targeted = self.run_report(transactions, query=render_extract_sql(template, settings, 0))
                self.assertEqual({row["pidm"] for row in targeted}, {2})


if __name__ == "__main__":
    unittest.main()
