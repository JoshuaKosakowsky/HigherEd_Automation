from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from data_processing.refunds import REPORT_COLUMNS, RefundParameters, allocate_refunds
from data_processing.refunds.export import export_refund_report
from data_processing.refunds.extract import (
    ExtractSettings,
    _validate_complete_result,
    extract_refund_data,
    render_extract_sql,
)
from data_processing.refunds.ingest import read_refund_download
from data_processing.refunds.terms import derive_target_term, fiscal_year_start, previous_term


TRANSACTION_COLUMNS = [
    "pidm", "term_code", "aidy_code", "tran_number", "detail_code", "amount",
    "stored_balance", "effective_date", "activity_date", "detail_desc", "type_ind",
    "priority", "category_code", "title_iv_ind",
]
CONTEXT_COLUMNS = [
    "pidm", "cwid", "last_name", "first_name", "deceased_ind", "deceased_date",
    "confidential_ind", "account_control_row_count", "refund_hold_count",
    "raw_delinquency_code", "raw_refund_account_ind", "account_control_activity_date",
    "active_ed_row_count", "ed_activity_date", "plus_auth_row_ind", "plus_auth_aidy_code",
    "plus_to_student", "plus_auth_activity_date",
]


@dataclass(frozen=True)
class Transaction:
    detail_code: str
    type_ind: str
    priority: str | None
    amount: int | str | None
    stored_balance: int | str | None = 0
    term: str = "209980"
    aid_year: str | None = "9900"
    effective_date: str | None = "2099-08-01"
    activity_date: str | None = "2099-08-01"
    category: str = "CSH"
    title_iv: str = "N"
    tran_number: int | None = None


class RefundAllocationTests(unittest.TestCase):
    def report(
        self,
        transactions: list[Transaction],
        *,
        authorizations: dict[str, str | list[str]] | None = None,
        refund_hold: bool = False,
        active_ed: bool = True,
        target_term: str = "209980",
        previous_term_override: str | None = None,
        run_date: date = date(2099, 8, 31),
        expected_rows: int = 1,
    ) -> dict[str, object]:
        transaction_rows = []
        occupied: set[int] = set()
        next_number = 1
        for transaction in transactions:
            number = transaction.tran_number
            if number is None:
                while next_number in occupied:
                    next_number += 1
                number = next_number
            occupied.add(number)
            next_number = max(next_number, number + 1)
            transaction_rows.append([
                1, transaction.term, transaction.aid_year, number,
                transaction.detail_code, transaction.amount, transaction.stored_balance,
                transaction.effective_date, transaction.activity_date, "Synthetic source",
                transaction.type_ind, transaction.priority, transaction.category,
                transaction.title_iv,
            ])

        authorization_values = {"9900": "N"} if authorizations is None else authorizations
        context_rows = []
        for aid_year, raw_values in authorization_values.items():
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            for value in values:
                context_rows.append([
                    1, "TEST-1", "Synthetic", "Example", "N", None, "N", 1,
                    1 if refund_hold else 0, "RH" if refund_hold else None, "N",
                    "2099-08-31", 1 if active_ed else 0,
                    "2099-08-31" if active_ed else None, 1, aid_year, value, "2099-08-31",
                ])
        if not context_rows:
            context_rows.append([
                1, "TEST-1", "Synthetic", "Example", "N", None, "N", 1,
                1 if refund_hold else 0, "RH" if refund_hold else None, "N",
                "2099-08-31", 1 if active_ed else 0,
                "2099-08-31" if active_ed else None, 0, None, None, None,
            ])
        result = allocate_refunds(
            pd.DataFrame(transaction_rows, columns=TRANSACTION_COLUMNS),
            pd.DataFrame(context_rows, columns=CONTEXT_COLUMNS),
            RefundParameters(target_term, run_date, previous_term_override),
        )
        self.assertEqual(len(result), expected_rows)
        if expected_rows == 0:
            return {}
        return result.iloc[0].to_dict()

    @staticmethod
    def worked_example() -> list[Transaction]:
        return [
            Transaction("TUIN", "C", "899", 6000),
            Transaction("FEES", "C", "897", 1000),
            Transaction("OTHR", "C", "700", 500),
            Transaction("PAYA", "P", "899", 2000),
            Transaction("PAYB", "P", "890", 1500),
            Transaction("FDPL", "P", "800", 4000, -500, category="FA", title_iv="Y"),
            Transaction("PAYC", "P", "000", 2000, -1500),
        ]

    def assert_split(self, row: dict[str, object], parent: str, student: str) -> None:
        self.assertEqual(row["parent_refund_amount"], Decimal(parent))
        self.assertEqual(row["student_refund_amount"], Decimal(student))
        self.assertEqual(row["total_refund_amount"], Decimal(parent) + Decimal(student))

    def test_worked_example_and_output_contract(self) -> None:
        row = self.report(self.worked_example())
        self.assert_split(row, "500.00", "1500.00")
        self.assertEqual(list(row), REPORT_COLUMNS)
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertIn("FDPL", str(row["balance_sources"]))
        self.assertNotIn("PAYA", str(row["balance_sources"]))

    def test_cross_fy_title_iv_uses_200_give_and_receive_cap(self) -> None:
        row = self.report([
            Transaction("OLD1", "C", "899", 150, term="209780"),
            Transaction("OLD2", "C", "899", 150, term="209880"),
            Transaction("TIVA", "P", "000", 500, -300, category="FA", title_iv="Y"),
        ])
        self.assertEqual(row["total_refund_amount"], Decimal("200.00"))
        self.assertEqual(row["total_unused_payment_amount"], Decimal("300.00"))
        self.assertIsNone(row["parent_refund_amount"])
        self.assertIsNone(row["student_refund_amount"])
        self.assertEqual(row["unpaid_charge_amount"], Decimal("100.00"))
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], Decimal("200.00"))
        self.assertEqual(row["review_status"], "REAPPLICATION_REQUIRED")

        destination = self.report([
            Transaction("OLD", "C", "899", 500, term="209780"),
            Transaction("TIVA", "P", "000", 300, -100, term="209880", aid_year="9899", category="FA", title_iv="Y"),
            Transaction("TIVB", "P", "000", 300, -300, category="FA", title_iv="Y"),
        ])
        self.assertEqual(destination["total_refund_amount"], Decimal("100.00"))
        self.assertEqual(destination["total_unused_payment_amount"], Decimal("400.00"))
        self.assertIsNone(destination["student_refund_amount"])
        self.assertEqual(destination["unpaid_charge_amount"], Decimal("300.00"))

    def test_same_fy_title_iv_and_unrestricted_cross_fy_are_not_capped(self) -> None:
        same_fy = self.report([
            Transaction("OLD", "C", "899", 1000, term="209980"),
            Transaction("TIVA", "P", "000", 1200, -200, term="210010", category="FA", title_iv="Y"),
        ], target_term="210010", run_date=date(2100, 1, 31))
        self.assert_split(same_fy, "0.00", "200.00")
        self.assertEqual(same_fy["unpaid_charge_amount"], Decimal("0.00"))

        unrestricted = self.report([
            Transaction("OLD", "C", "899", 1000, term="209955"),
            Transaction("FREE", "P", "000", 1200, -200, category="FA", title_iv="N"),
        ])
        self.assert_split(unrestricted, "0.00", "200.00")
        self.assertEqual(unrestricted["unrestricted_applied_to_older_terms"], Decimal("1000.00"))

    def test_artificial_priority_bands_and_earliest_tie_breaker(self) -> None:
        first_800 = self.report([
            Transaction("CHG8", "C", "899", 100, tran_number=10),
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y", tran_number=2),
            Transaction("TPDT", "P", "800", 100, tran_number=3),
        ])
        self.assert_split(first_800, "100.00", "0.00")

        early_fdpl = self.report([
            Transaction("CHG8", "C", "899", 100, tran_number=10),
            Transaction("FDPL", "P", "800", 100, category="FA", title_iv="Y", tran_number=1),
            Transaction("OT8", "P", "800", 100, -100, tran_number=2),
        ])
        self.assert_split(early_fdpl, "0.00", "100.00")

        last_000 = self.report([
            Transaction("CHG", "C", "700", 100),
            Transaction("ACHK", "P", "000", 100, -100),
            Transaction("PAY0", "P", "000", 100),
        ])
        self.assertIn("000Z", str(last_000["balance_sources"]))
        self.assertEqual(last_000["proposed_student_delivery"], "AFRD (Transact)")

        first_000 = self.report([
            Transaction("CHG", "C", "700", 100),
            Transaction("PAY0", "P", "000", 100, -100),
            Transaction("COFP", "P", "000", 100),
        ])
        self.assertIn("PAY0", str(first_000["balance_sources"]))
        self.assertNotIn("COFP", str(first_000["balance_sources"]))

    def test_positional_wildcards_preserve_descending_charge_order(self) -> None:
        row = self.report([
            Transaction("C897", "C", "897", 100, tran_number=1),
            Transaction("C899", "C", "899", 100, tran_number=2),
            Transaction("P899", "P", "899", 100, tran_number=3),
            Transaction("P890", "P", "890", 100, tran_number=4),
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y", tran_number=5),
        ])
        self.assert_split(row, "100.00", "0.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))

    def test_allocation_preserves_exact_cents(self) -> None:
        row = self.report([
            Transaction("CHG1", "C", "899", "0.10"),
            Transaction("CHG2", "C", "899", "0.20"),
            Transaction("FDPL", "P", "800", "0.35", "-0.05", category="FA", title_iv="Y"),
        ])
        self.assert_split(row, "0.05", "0.00")

    def test_reversals_and_cross_detail_charge_credits_net_correctly(self) -> None:
        reversal = self.report([
            Transaction("ACHK", "P", "000", 1000, -600, tran_number=1),
            Transaction("ACHK", "P", "000", -400, 0, tran_number=2),
        ])
        self.assert_split(reversal, "0.00", "600.00")
        self.assertEqual(reversal["negative_source_count"], 1)

        charges = self.report([
            Transaction("HLTH", "C", "879", 1589),
            Transaction("HIWR", "C", "879", -1589),
            Transaction("PAY0", "P", "000", 100, -100),
        ])
        self.assert_split(charges, "0.00", "100.00")
        self.assertEqual(charges["unpaid_charge_amount"], Decimal("0.00"))

    def test_tricky_cross_term_charge_credits_do_not_create_false_debt(self) -> None:
        row = self.report([
            Transaction("HLTH", "C", "879", "1111", term="209780"),
            Transaction("HIWR", "C", "879", "-1111", term="209780"),
            Transaction("HLTH", "C", "879", "2222", term="209880"),
            Transaction("HIWR", "C", "879", "-2222", term="209880"),
            Transaction("OLD", "C", "899", "4750.25", term="209955"),
            Transaction("HLTH", "C", "879", "3333", term="209955"),
            Transaction("HIWR", "C", "879", "-3333", term="209955"),
            Transaction("TUIN", "C", "899", "9000", tran_number=20),
            Transaction("FEES", "C", "897", "1500", tran_number=21),
            Transaction("HOUS", "C", "889", "2500", tran_number=22),
            Transaction("HLTH", "C", "879", "1600", tran_number=23),
            Transaction("HIWR", "C", "879", "-1600", tran_number=24),
            Transaction("FDPL", "P", "800", "12000", tran_number=25, category="PPL", title_iv="Y"),
            Transaction("FDSL", "P", "800", "1500", tran_number=26, category="FAL", title_iv="Y"),
            Transaction("FDUL", "P", "800", "500", tran_number=27, category="FAL", title_iv="Y"),
            Transaction("PELL", "P", "800", "1500", tran_number=28, category="FAG", title_iv="Y"),
            Transaction("SCHP", "P", "000", "6000", tran_number=29, category="FAS"),
        ])
        self.assert_split(row, "0.00", "3749.75")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], Decimal("200.00"))
        self.assertEqual(row["unrestricted_applied_to_older_terms"], Decimal("4550.25"))

    def test_historical_credit_reconstruction_uses_priority_eligibility(self) -> None:
        row = self.report([
            Transaction("OLD7", "C", "700", 100, term="209955"),
            Transaction("P899", "P", "899", 100, -100, term="209955"),
            Transaction("P000", "P", "000", 100, term="209955"),
        ])
        self.assert_split(row, "0.00", "100.00")
        self.assertIn("P899", str(row["balance_sources"]))
        self.assertNotIn("P000", str(row["balance_sources"]))

    def test_policy_unused_funds_do_not_become_an_actionable_refund(self) -> None:
        row = self.report([
            Transaction("OLD", "C", "899", 1500, 1300, term="209955"),
            Transaction("TIVA", "P", "000", 1200, -1000, category="FA", title_iv="Y"),
        ])
        self.assertEqual(row["full_account_balance"], Decimal("300.00"))
        self.assertEqual(row["total_refund_amount"], Decimal("0.00"))
        self.assertEqual(row["total_unused_payment_amount"], Decimal("1000.00"))
        self.assertIsNone(row["parent_refund_amount"])
        self.assertIsNone(row["student_refund_amount"])
        self.assertEqual(row["unpaid_charge_amount"], Decimal("1300.00"))
        self.assertEqual(row["allocation_review_required_ind"], "Y")
        self.assertEqual(row["review_status"], "REAPPLICATION_REQUIRED")

    def test_zero_balance_unused_parent_plus_is_blocked_for_reapplication(self) -> None:
        row = self.report([
            Transaction("OLD7", "C", "700", "4375.00", term="209880"),
            Transaction(
                "FDPL", "P", "800", "4375.00", "-4375.00",
                category="FA", title_iv="Y",
            ),
        ])
        self.assertEqual(row["full_account_balance"], Decimal("0.00"))
        self.assertEqual(row["total_refund_amount"], Decimal("0.00"))
        self.assertEqual(row["unused_fdpl_amount"], Decimal("4375.00"))
        self.assertEqual(row["unpaid_charge_amount"], Decimal("4375.00"))
        self.assertIsNone(row["parent_refund_amount"])
        self.assertIsNone(row["student_refund_amount"])
        self.assertEqual(row["proposed_parent_delivery"], "REAPPLICATION REQUIRED")
        self.assertEqual(row["refund_split_status"], "REAPPLICATION_REQUIRED")
        self.assertEqual(row["review_status"], "REAPPLICATION_REQUIRED")
        self.assertIn(
            "POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT",
            str(row["review_reasons"]),
        )

    def test_settled_old_term_is_not_reopened_by_current_priorities(self) -> None:
        row = self.report([
            Transaction("OLD7", "C", "700", 100, term="209880", tran_number=1),
            Transaction("P899", "P", "899", 100, term="209880", tran_number=2),
            Transaction("P000", "P", "000", 100, tran_number=3),
        ])
        self.assert_split(row, "0.00", "100.00")
        self.assertIn("P000", str(row["balance_sources"]))
        self.assertNotIn("P899", str(row["balance_sources"]))

    def test_closed_cross_fy_history_and_posted_current_refund_are_omitted(self) -> None:
        self.report([
            Transaction(
                "FDPL", "P", "800", 600, 0, term="209810",
                aid_year="9798", category="FA", title_iv="Y",
            ),
            Transaction("LATE", "C", "700", 1320, 0, term="209855"),
            Transaction("PAY0", "P", "000", 720, 0, term="209880"),
            Transaction("FDSL", "P", "800", 100, 0, category="FA", title_iv="Y"),
            Transaction("ARFD", "C", "800", 100, 0),
        ], expected_rows=0)

    def test_bad_inputs_block_split_without_displaying_zero(self) -> None:
        missing_amount = self.report(
            self.worked_example() + [Transaction("NULL", "C", "700", None)]
        )
        self.assertIsNone(missing_amount["student_refund_amount"])
        self.assertIsNone(missing_amount["parent_refund_amount"])
        self.assertIn("MISSING_TRANSACTION_AMOUNT", str(missing_amount["review_reasons"]))

        future = self.report(
            self.worked_example()
            + [Transaction("FUTR", "C", "700", 1, term="210010")]
        )
        self.assertIsNone(future["student_refund_amount"])
        self.assertIn(
            "FUTURE_TERM_ACTIVITY_EXCLUDED_FROM_ALLOCATION",
            str(future["review_reasons"]),
        )

    def test_stored_balance_is_diagnostic_only(self) -> None:
        transactions = self.worked_example()
        transactions[-1] = Transaction("PAYC", "P", "000", 2000, 0)
        row = self.report(transactions)
        self.assert_split(row, "500.00", "1500.00")
        self.assertEqual(row["allocation_review_required_ind"], "Y")
        self.assertIn(
            "STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION",
            str(row["review_reasons"]),
        )

    def test_fdpl_authorization_is_applied_by_aid_year(self) -> None:
        mixed = self.report([
            Transaction("FDPL", "P", "800", 300, -300, term="209880", aid_year="9899", category="FA", title_iv="Y"),
            Transaction("FDPL", "P", "800", 300, -300, aid_year="9900", category="FA", title_iv="Y"),
        ], authorizations={"9899": "Y", "9900": "N"})
        self.assert_split(mixed, "300.00", "300.00")
        self.assertEqual(mixed["plus_to_student_status"], "MIXED")
        self.assertEqual(mixed["proposed_parent_delivery"], "RFDP")

        missing = self.report([
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y")
        ], authorizations={})
        self.assertIsNone(missing["parent_refund_amount"])
        self.assertIn("PLUS_AUTH_RECORD_MISSING", str(missing["review_reasons"]))

    def test_ach_boundaries_hold_and_standard_delivery(self) -> None:
        waiting = self.report([
            Transaction("ACHK", "P", "000", 50, -50, effective_date="2099-08-16")
        ])
        self.assertEqual(waiting["proposed_student_delivery"], "ACHK Clearing Wait until 09/01/2099")
        self.assertEqual(waiting["review_status"], "WAIT_ACH_CLEARING")

        old = self.report([
            Transaction("ACHK", "P", "000", 50, -50, effective_date="2099-03-03")
        ])
        self.assertEqual(old["proposed_student_delivery"], "AFRD (Transact) - May Be Too Old")

        check = self.report([Transaction("PAY0", "P", "000", 50, -50)], active_ed=False)
        self.assertEqual(check["proposed_student_delivery"], "RFND (CHECK)")
        hold = self.report([Transaction("PAY0", "P", "000", 50, -50)], refund_hold=True)
        self.assertEqual(hold["proposed_student_delivery"], "Refund Hold - Student")

    def test_activity_audit_columns_retain_time_of_day(self) -> None:
        row = self.report([
            Transaction(
                "PAY0", "P", "000", 50, -50,
                activity_date="2099-08-01T23:07:09",
            )
        ])
        self.assertEqual(
            row["last_ar_activity_date"],
            datetime(2099, 8, 1, 23, 7, 9),
        )


class RefundTermTests(unittest.TestCase):
    def test_mines_term_and_fiscal_year_rules(self) -> None:
        self.assertEqual(derive_target_term(date(2026, 5, 15)), "202610")
        self.assertEqual(derive_target_term(date(2026, 5, 16)), "202655")
        self.assertEqual(derive_target_term(date(2026, 7, 16)), "202680")
        self.assertEqual(fiscal_year_start("202680"), 2026)
        for term in ("202710", "202750", "202755", "202760"):
            self.assertEqual(fiscal_year_start(term), 2026)
        self.assertEqual(previous_term("202680", "202660"), "202660")


class RefundExtractTests(unittest.TestCase):
    def test_template_is_rendered_only_from_validated_values(self) -> None:
        settings = ExtractSettings("202680", 20, Path("unused"))
        rendered = render_extract_sql(
            "WITH s AS (__REFUND_SCOPE_SQL__) SELECT __BATCH_COUNT__, __BATCH_INDEX__",
            settings,
            3,
        )
        self.assertIn("t.tbraccd_term_code = '202680'", rendered)
        self.assertTrue(rendered.endswith("SELECT 20, 3"))
        with self.assertRaises(ValueError):
            ExtractSettings("202680", 1, Path("unused"), cwid="bad'value")

    def test_row_count_guard_detects_api_truncation(self) -> None:
        frame = pd.DataFrame({"extract_row_count": [3, 3], "pidm": [1, 2]})
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            _validate_complete_result(frame, "transactions", 0)

    def test_completed_batches_are_cached_and_resumable(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def run_sql(self, sql: str) -> pd.DataFrame:
                self.calls += 1
                if "t.tbraccd_amount AS amount" in sql:
                    return pd.DataFrame({"extract_row_count": [1], "pidm": [self.calls]})
                return pd.DataFrame({"extract_row_count": [1], "pidm": [self.calls]})

        with TemporaryDirectory() as directory:
            root = Path(directory)
            transaction_template = root / "transactions.sql"
            context_template = root / "context.sql"
            template = (
                "WITH batch_scope AS (__REFUND_SCOPE_SQL__) "
                "SELECT COUNT(*) OVER () AS extract_row_count, "
                "__BATCH_COUNT__ AS total, __BATCH_INDEX__ AS batch"
            )
            transaction_template.write_text(
                template + ", t.tbraccd_amount AS amount", encoding="utf-8"
            )
            context_template.write_text(template, encoding="utf-8")
            settings = ExtractSettings("202680", 2, root / "cache")
            client = FakeClient()
            first = extract_refund_data(
                client,
                settings,
                transaction_template_path=transaction_template,
                context_template_path=context_template,
            )
            self.assertEqual(client.calls, 4)
            self.assertEqual(tuple(len(frame) for frame in first), (2, 2))

            resumed_client = FakeClient()
            resumed = extract_refund_data(
                resumed_client,
                ExtractSettings("202680", 2, root / "cache", resume=True),
                transaction_template_path=transaction_template,
                context_template_path=context_template,
            )
            self.assertEqual(resumed_client.calls, 0)
            self.assertEqual(tuple(len(frame) for frame in resumed), (2, 2))

    def test_export_keeps_report_column_order(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "refunds.xlsx"
            export_refund_report(pd.DataFrame(columns=REPORT_COLUMNS), output)
            headers = pd.read_excel(output).columns.tolist()
            self.assertEqual(headers, REPORT_COLUMNS)

    def test_manual_download_reader_accepts_xlsx_and_checks_term(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "transactions.xlsx"
            pd.DataFrame({
                "Extract Row Count": [1],
                "Extract Target Term": ["202680"],
                "PIDM": [1],
            }).to_excel(path, index=False)
            result = read_refund_download(
                path,
                label="Transaction",
                expected_target_term="202680",
            )
            self.assertEqual(result.columns.tolist(), ["pidm"])
            with self.assertRaisesRegex(ValueError, "expects 202710"):
                read_refund_download(
                    path,
                    label="Transaction",
                    expected_target_term="202710",
                )


if __name__ == "__main__":
    unittest.main()
