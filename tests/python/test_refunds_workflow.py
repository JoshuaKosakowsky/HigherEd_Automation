from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
import sqlite3
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from data_processing.refunds import REPORT_COLUMNS, RefundParameters, allocate_refunds
from data_processing.refunds.export import REFUND_SHEETS, WORKBOOK_COLUMNS, export_refund_report
from data_processing.refunds.extract import (
    ExtractSettings,
    RefundExtractError,
    _wait_for_query_retry,
    _validate_complete_result,
    extract_refund_data,
    read_refund_extracts,
    render_extract_sql,
    render_manual_extract_sql,
)
from data_processing.refunds.ingest import read_refund_download
from data_processing.refunds.pipeline import _create_review
from shared.cancellation import CancellationToken, WorkflowCancelled
from shared.insights.client import InsightsAPIError
from shared.progress import ProgressReporter
from data_processing.refunds.terms import derive_target_term, fiscal_year_start, previous_term


TRANSACTION_COLUMNS = [
    "pidm", "term_code", "aidy_code", "tran_number", "detail_code", "amount",
    "stored_balance", "effective_date", "activity_date", "detail_desc", "type_ind",
    "priority", "category_code", "title_iv_ind", "feed_date", "non_allowable_charge_ind",
]
CONTEXT_COLUMNS = [
    "pidm", "cwid", "last_name", "first_name", "deceased_ind", "deceased_date",
    "confidential_ind", "account_control_row_count", "refund_hold_count",
    "raw_delinquency_code", "raw_refund_account_ind", "account_control_activity_date",
    "active_ed_row_count", "ed_activity_date", "plus_auth_row_ind", "plus_auth_aidy_code",
    "plus_to_student", "plus_auth_activity_date",
    "sponsor_names", "sponsor_ids", "contract_numbers",
    "student_address_type", "student_address_line1", "student_address_line2",
    "student_address_line3", "student_address_city", "student_address_state",
    "student_address_zip", "student_address_nation", "student_address_review",
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
    feed_date: str | None = None
    non_allowable: str | None = "N"


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
        sponsor_context: dict[str, str] | None = None,
        address_context: dict[str, str | None] | None = None,
        expected_rows: int = 1,
        progress_reporter: ProgressReporter | None = None,
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
                transaction.title_iv, transaction.feed_date, transaction.non_allowable,
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
        context_rows = [row + [None, None, None, "PR", "1 Synthetic Road", None, None,
                               "Golden", "CO", "80401", "US", None] for row in context_rows]
        context_frame = pd.DataFrame(context_rows, columns=CONTEXT_COLUMNS)
        for key, value in (sponsor_context or {}).items():
            context_frame[key] = value
        for key, value in (address_context or {}).items():
            context_frame[key] = value
        result = allocate_refunds(
            pd.DataFrame(transaction_rows, columns=TRANSACTION_COLUMNS),
            context_frame,
            RefundParameters(target_term, run_date, previous_term_override),
            progress_reporter=progress_reporter,
        )
        self.assertEqual(len(result), expected_rows)
        if expected_rows == 0:
            return {}
        self.assertTrue(set(result["title_iv_balance_due_note"]).issubset({"Yes", "No"}))
        row = result.iloc[0].to_dict()
        for recipient in ("student", "parent"):
            if row[f"{recipient}_refund_amount"] is not None:
                available = row[f"{recipient}_refund_available_amount"]
                reserved = row[f"{recipient}_clearing_reserve_amount"]
                self.assertGreaterEqual(available, Decimal(0))
                self.assertGreaterEqual(reserved, Decimal(0))
                self.assertEqual(available + reserved, row[f"{recipient}_refund_amount"])
        return row

    @staticmethod
    def worked_example() -> list[Transaction]:
        return [
            Transaction("TUIN", "C", "899", 6000),
            Transaction("FEES", "C", "897", 1000),
            Transaction("OTHR", "C", "700", 500),
            Transaction("PAYA", "P", "899", 2000),
            Transaction("PAYB", "P", "890", 1500),
            Transaction("FDPL", "P", "800", 4000, 0, category="FA", title_iv="Y"),
            Transaction("PAYC", "P", "000", 2000, -2000),
        ]

    def assert_split(self, row: dict[str, object], parent: str, student: str) -> None:
        self.assertEqual(row["parent_refund_amount"], Decimal(parent))
        self.assertEqual(row["student_refund_amount"], Decimal(student))
        self.assertEqual(row["total_refund_amount"], Decimal(parent) + Decimal(student))

    def assert_unassigned_credit(self, row: dict[str, object], credit: str) -> None:
        self.assertEqual(row["total_refund_amount"], Decimal(credit))
        self.assertIsNone(row["student_refund_amount"])
        self.assertIsNone(row["parent_refund_amount"])
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")
        self.assertEqual(row["proposed_student_delivery"], "NONE")

    def test_worked_example_and_output_contract(self) -> None:
        row = self.report(self.worked_example())
        self.assert_split(row, "0.00", "2000.00")
        self.assertEqual(list(row), REPORT_COLUMNS)
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertNotIn("FDPL", str(row["balance_sources"]))
        self.assertNotIn("PAYA", str(row["balance_sources"]))

    def test_calculation_progress_counts_accounts_without_identifiers(self):
        updates = []
        row = self.report(self.worked_example(), progress_reporter=ProgressReporter(updates.append))
        self.assert_split(row, "0.00", "2000.00")
        calculations = [update for update in updates if update.stage == "Calculating refunds by account"]
        self.assertEqual([(update.completed, update.total) for update in calculations], [(0, 1), (1, 1)])
        normalized = [update for update in updates if update.stage == "Normalizing refund transactions"]
        self.assertEqual(normalized[-1].completed, len(self.worked_example()))
        self.assertTrue(all("TEST-1" not in update.stage for update in updates))

    def test_cross_fy_title_iv_uses_200_give_and_receive_cap(self) -> None:
        row = self.report([
            Transaction("OLD1", "C", "899", 150, term="209780"),
            Transaction("OLD2", "C", "899", 150, term="209880"),
            Transaction("TIVA", "P", "000", 500, -300, category="FA", title_iv="Y"),
        ])
        self.assert_unassigned_credit(row, "200.00")
        self.assertEqual(row["total_unused_payment_amount"], Decimal("300.00"))
        self.assertEqual(row["unpaid_charge_amount"], Decimal("100.00"))
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], Decimal("200.00"))
        self.assertEqual(row["review_status"], "MANUAL_REVIEW")

        destination = self.report([
            Transaction("OLD", "C", "899", 500, term="209780"),
            Transaction("TIVA", "P", "000", 300, -100, term="209880", aid_year="9899", category="FA", title_iv="Y"),
            Transaction("TIVB", "P", "000", 300, -300, category="FA", title_iv="Y"),
        ])
        self.assert_unassigned_credit(destination, "100.00")
        self.assertEqual(destination["total_unused_payment_amount"], Decimal("400.00"))
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

    def test_common_priority_and_earliest_tie_breaker(self) -> None:
        first_800 = self.report([
            Transaction("CHG8", "C", "899", 100, tran_number=10),
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y", tran_number=2),
            Transaction("TPDT", "P", "800", 100, tran_number=3),
        ])
        self.assert_split(first_800, "0.00", "100.00")

        early_fdpl = self.report([
            Transaction("CHG8", "C", "899", 100, tran_number=10),
            Transaction("FDPL", "P", "800", 100, category="FA", title_iv="Y", tran_number=1),
            Transaction("OT8", "P", "800", 100, -100, tran_number=2),
        ])
        self.assert_split(early_fdpl, "0.00", "100.00")

        regular_000 = self.report([
            Transaction("CHG", "C", "700", 100),
            Transaction("ACHK", "P", "000", 100, -100),
            Transaction("PAY0", "P", "000", 100),
        ])
        self.assertIn("PAY0", str(regular_000["balance_sources"]))
        self.assertNotIn("ACHK", str(regular_000["balance_sources"]))
        self.assertEqual(regular_000["proposed_student_delivery"], "ARFD (System)")

        first_000 = self.report([
            Transaction("CHG", "C", "700", 100),
            Transaction("PAY0", "P", "000", 100, -100),
            Transaction("COFP", "P", "000", 100),
        ])
        self.assertNotIn("PAY0", str(first_000["balance_sources"]))
        self.assertIn("COFP", str(first_000["balance_sources"]))

    def test_title_iv_refund_leaves_non_allowable_balance(self) -> None:
        for late_fee in (100, 200, 300):
            with self.subTest(late_fee=late_fee):
                row = self.report([
                    Transaction("TUIN", "C", "899", 1000),
                    Transaction("LPPF", "C", "789", late_fee, late_fee, non_allowable="Y"),
                    Transaction("PELL", "P", "800", 1200, -200, category="FA", title_iv="Y"),
                ])
                self.assert_split(row, "0.00", "200.00")
                self.assertEqual(row["full_account_balance"], Decimal(late_fee - 200))
                self.assertEqual(row["unpaid_charge_amount"], Decimal(late_fee))
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                self.assertEqual(row["title_iv_balance_due_note"], "Yes")

    def test_cash_can_pay_non_allowable_charges(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("LPPF", "C", "789", 100, non_allowable="Y", tran_number=2),
            Transaction("PELL", "P", "800", 1200, -200, category="FA", title_iv="Y", tran_number=3),
            Transaction("CASH", "P", "000", 100, tran_number=4),
        ])
        self.assert_split(row, "0.00", "200.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal(0))
        self.assertEqual(row["title_iv_balance_due_note"], "No")

    def test_charge_flags_keep_same_priority_pools_separate(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 1000),
            Transaction("FINE", "C", "899", 100, 100, non_allowable="Y"),
            Transaction("FINE", "C", "899", -25, -25, non_allowable="Y"),
            Transaction("PELL", "P", "800", 1200, -200, category="FA", title_iv="Y"),
        ])
        self.assert_split(row, "0.00", "200.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("75.00"))
        self.assertEqual(row["title_iv_balance_due_note"], "Yes")

    def test_non_allowable_exception_requires_title_iv_and_marked_charge(self) -> None:
        for title_iv, flag in (("N", "Y"), ("Y", "N")):
            with self.subTest(title_iv=title_iv, flag=flag):
                row = self.report([
                    Transaction("TUIN", "C", "899", 1000),
                    Transaction("LPPF", "C", "789", 100, non_allowable=flag),
                    Transaction("AID", "P", "800", 1200, -100, category="FA", title_iv=title_iv),
                ])
                self.assert_split(row, "0.00", "100.00")
                self.assertEqual(row["title_iv_balance_due_note"], "No")

    def test_unknown_charge_flags_block_title_iv_and_recipient_split(self) -> None:
        for flag in (None, "", "?"):
            with self.subTest(flag=flag):
                row = self.report([
                    Transaction("TUIN", "C", "899", 1000),
                    Transaction("LPPF", "C", "789", 100, 100, non_allowable=flag),
                    Transaction("PELL", "P", "800", 1200, -200, category="FA", title_iv="Y"),
                ])
                self.assert_unassigned_credit(row, "100.00")
                self.assertEqual(row["unpaid_charge_amount"], Decimal(100))
                self.assertIn("MISSING_OR_INVALID_NON_ALLOWABLE_CHARGE_FLAG", row["review_reasons"])

    def test_title_iv_exception_uses_reconstructed_aid_and_preserves_other_debt_checks(self) -> None:
        base = [
            Transaction("TUIN", "C", "899", 1000),
            Transaction("LPPF", "C", "789", 100, 100, non_allowable="Y"),
            Transaction("PELL", "P", "800", 1200, 0, category="FA", title_iv="Y"),
        ]
        row = self.report(base)
        self.assert_split(row, "0.00", "200.00")
        self.assertEqual(row["title_iv_balance_due_note"], "Yes")
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertEqual(row["unpaid_charge_amount"], Decimal(100))
        self.assertIn("STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION", row["review_reasons"])
        other_debt = self.report([
            Transaction("OLD", "C", "899", 500, 300, term="209880"),
            Transaction("LPPF", "C", "789", 100, 100, non_allowable="Y"),
            Transaction("PELL", "P", "800", 1000, -800, category="FA", title_iv="Y"),
        ])
        self.assert_unassigned_credit(other_debt, "400.00")

    def test_title_iv_reversals_and_issued_refunds_do_not_repeat_refunds(self) -> None:
        base = [
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("LPPF", "C", "789", 100, 100, non_allowable="Y", tran_number=2),
            Transaction("PELL", "P", "800", 1300, -300, category="FA", title_iv="Y", tran_number=3),
            Transaction("PELL", "P", "800", -100, 100, category="FA", title_iv="Y", tran_number=4),
        ]
        row = self.report(base)
        self.assert_split(row, "0.00", "200.00")
        self.report(base + [Transaction("RFND", "C", "800", 200, tran_number=5)], expected_rows=0)

    def test_title_iv_balance_flag_survives_parent_hold_and_workbook_routing(self) -> None:
        base = [
            Transaction("TUIN", "C", "899", 1000),
            Transaction("LPPF", "C", "789", 100, 100, non_allowable="Y"),
            Transaction("FDPL", "P", "800", 1200, -200, category="FA", title_iv="Y"),
        ]
        for authorized, hold, sheet in (("Y", False, "Direct Deposit"),
                                       ("N", False, "Refund to Parent"),
                                       ("Y", True, "Refund Holds")):
            with self.subTest(authorized=authorized, hold=hold):
                row = self.report(base, authorizations={"9900": authorized}, refund_hold=hold)
                self.assert_split(row, "200.00" if authorized == "N" else "0.00",
                                  "200.00" if authorized == "Y" else "0.00")
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    workbook = load_workbook(output)
                    ws = workbook[sheet]
                    headers = [cell.value for cell in ws[1]]
                    flag = ws.cell(2, headers.index("Title IV Refund Leaves Balance Due") + 1).value
                    self.assertEqual(flag, "Yes")
                    self.assertEqual(ws.cell(2, headers.index("Detail_Code_Refund_Amt") + 1).value, 200)
                    workbook.close()

    def test_800_and_000_share_order_but_preserve_payment_identity(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("CASH", "P", "000", 1000, tran_number=2),
            Transaction("FDPL", "P", "800", 200, -200, category="FA", title_iv="Y", tran_number=3),
        ])
        self.assert_split(row, "200.00", "0.00")
        self.assertIn("FDPL", row["balance_sources"])
        self.assertNotIn("CASH", row["balance_sources"])

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
            Transaction("FDSL", "P", "800", "1500", "-300", tran_number=26, category="FAL", title_iv="Y"),
            Transaction("FDUL", "P", "800", "500", "-500", tran_number=27, category="FAL", title_iv="Y"),
            Transaction("PELL", "P", "800", "1500", "-1500", tran_number=28, category="FAG", title_iv="Y"),
            Transaction("SCHP", "P", "000", "6000", "-1449.75", tran_number=29, category="FAS"),
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

    def test_positive_account_balance_is_excluded_despite_restricted_funds(self) -> None:
        self.report([
            Transaction("OLD", "C", "899", 1500, 1300, term="209955"),
            Transaction("TIVA", "P", "000", 1200, -1000, category="FA", title_iv="Y"),
        ], expected_rows=0)

    def test_zero_balance_restricted_parent_plus_is_excluded(self) -> None:
        self.report([
            Transaction("OLD7", "C", "700", "4375.00", term="209880"),
            Transaction(
                "FDPL", "P", "800", "4375.00", "-4375.00",
                category="FA", title_iv="Y",
            ),
        ], expected_rows=0)

    def test_settled_old_term_is_not_reopened_by_current_priorities(self) -> None:
        row = self.report([
            Transaction("OLD7", "C", "700", 100, term="209880", tran_number=1),
            Transaction("P899", "P", "899", 100, term="209880", tran_number=2),
            Transaction("P000", "P", "000", 100, tran_number=3),
        ])
        self.assert_split(row, "0.00", "100.00")
        self.assertIn("P000", str(row["balance_sources"]))
        self.assertNotIn("P899", str(row["balance_sources"]))

    @staticmethod
    def settled_late_fee_example() -> list[Transaction]:
        # Earlier cash was manually applied to the late fee. The resulting
        # settled row balances are authoritative; Trans Paid is not required.
        return [
            Transaction("OLD", "C", "899", 200, term="209910"),
            Transaction("CASH", "P", "000", 200, term="209910"),
            Transaction("TUIN", "C", "899", 1000),
            Transaction("LPPF", "C", "789", 40, non_allowable="Y"),
            Transaction("PELL", "P", "800", 1040, category="FAG", title_iv="Y"),
        ]

    def test_fully_settled_account_including_current_term_is_excluded(self) -> None:
        for term in ("209980", "209910"):
            with self.subTest(term=term):
                rows = [replace(t, term=term) for t in self.settled_late_fee_example()]
                self.report(rows, expected_rows=0)
        self.report(self.settled_late_fee_example(), expected_rows=0)

    def test_offsetting_row_balances_keep_zero_net_account_in_review(self) -> None:
        rows = self.settled_late_fee_example()
        rows[-2] = replace(rows[-2], stored_balance=40)
        rows[-1] = replace(rows[-1], stored_balance=-40)
        row = self.report(rows)
        self.assertEqual(row["full_account_balance"], Decimal(0))
        self.assert_split(row, "0.00", "40.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal(40))
        self.assertEqual(row["title_iv_balance_due_note"], "Yes")

    def test_settlement_checks_rows_before_detail_code_balances_are_netted(self) -> None:
        rows = self.settled_late_fee_example() + [
            Transaction("LPPF", "C", "789", 40, 40, non_allowable="Y"),
            Transaction("LPPF", "C", "789", -40, -40, non_allowable="Y"),
        ]
        row = self.report(rows)
        self.assertEqual(row["total_refund_amount"], Decimal(40))
        self.assertEqual(row["unpaid_charge_amount"], Decimal(40))

    def test_missing_balances_or_amounts_do_not_prove_settlement(self) -> None:
        for index in (0, -2, -1):
            with self.subTest(missing_balance_index=index):
                rows = self.settled_late_fee_example()
                rows[index] = replace(rows[index], stored_balance=None)
                row = self.report(rows)
                self.assertEqual(row["review_status"], "MANUAL_REVIEW")
                self.assertIn("MISSING_TRANSACTION_BALANCE", row["review_reasons"])
        row = self.report(self.settled_late_fee_example() + [
            Transaction("MISS", "C", "899", None),
        ])
        self.assert_unassigned_credit(row, "40.00")
        self.assertIn("MISSING_TRANSACTION_AMOUNT", row["review_reasons"])

    def test_zero_stored_balances_do_not_hide_actual_account_credit(self) -> None:
        rows = self.settled_late_fee_example()
        rows[-1] = replace(rows[-1], amount=1050)
        row = self.report(rows)
        self.assertEqual(row["full_account_balance"], Decimal(-10))
        self.assert_split(row, "0.00", "50.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal(40))

    def test_exact_priority_offsets_on_zero_account_are_excluded(self) -> None:
        for term in ("209980", "209880"):
            with self.subTest(term=term):
                self.report([
                    Transaction("TUIN", "C", "899", 10000, 500, term=term),
                    Transaction("FEE", "C", "897", 1000, 0, term=term),
                    Transaction("P899", "P", "899", 9500, 0, term=term),
                    Transaction("P897", "P", "897", 1500, -500, term=term),
                ], expected_rows=0)

    def test_cross_term_zero_account_does_not_reopen_applied_aid(self) -> None:
        self.report([
            Transaction("TUIN", "C", "899", 1000, term="209955", tran_number=1),
            Transaction("LOAN", "P", "800", 1500, term="209955", tran_number=2,
                        category="FA", title_iv="Y"),
            Transaction("ARFD", "C", "800", 200, term="209955", tran_number=3),
            Transaction("TUIN", "C", "899", 1500, tran_number=4),
            Transaction("SCHL", "P", "890", 600, tran_number=5, category="FA"),
            Transaction("CASH", "P", "000", 600, tran_number=6),
        ], expected_rows=0)
        # A credit in Fall does not become a refund while it offsets Summer debt.
        self.report([
            Transaction("OLD", "C", "899", 5000, term="209955"),
            Transaction("AID", "P", "800", 5000, -5000, category="FA", title_iv="Y"),
        ], expected_rows=0)

    def test_earlier_aid_applies_before_later_higher_priority_scholarship(self) -> None:
        row = self.report([
            Transaction("OLD", "C", "899", 1000, term="209955", tran_number=1),
            Transaction("LOAN", "P", "800", 1200, term="209955", tran_number=2,
                        category="FA", title_iv="Y"),
            Transaction("CURR", "C", "899", 500, tran_number=3),
            Transaction("SCHL", "P", "890", 600, -300, tran_number=4, category="FA"),
        ])
        self.assert_split(row, "0.00", "300.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))
        self.assertEqual(row["title_iv_applied_to_older_fiscal_years"], Decimal("0.00"))
        self.assertIn("SCHL", row["balance_sources"])
        self.assertNotIn("LOAN", row["balance_sources"])
        self.assertNotIn("APPLIED_AID_REOPENED", row["review_reasons"] or "")
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")

    def test_cash_still_covers_other_terms_before_refunding_the_net_credit(self) -> None:
        for charge_term, payment_term in (("209955", "209980"), ("209980", "209955")):
            with self.subTest(charge_term=charge_term):
                row = self.report([
                    Transaction("TUIN", "C", "899", 5000, term=charge_term),
                    Transaction("CASH", "P", "000", 5500, -500, term=payment_term),
                ])
                self.assert_split(row, "0.00", "500.00")
                self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))

    def test_known_aid_balances_do_not_limit_reconstructed_refunds(self) -> None:
        for title_iv in ("Y", "N"):
            for stored in (0, "-99.99", "-150.00"):
                with self.subTest(title_iv=title_iv, stored=stored):
                    row = self.report([
                        Transaction("CHG7", "C", "700", 100),
                        Transaction("AID", "P", "800", 100, stored,
                                    category="FA", title_iv=title_iv, tran_number=3),
                        Transaction("CASH", "P", "000", 100, -100, tran_number=2),
                    ])
                    self.assert_split(row, "0.00", "100.00")
                    self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                    self.assertIn("AID", row["balance_sources"])
                    self.assertIn("STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION", row["review_reasons"])

    def test_missing_aid_balance_still_requires_source_data_review(self) -> None:
        for title_iv in ("Y", "N"):
            with self.subTest(title_iv=title_iv):
                row = self.report([
                    Transaction("CHG7", "C", "700", 100),
                    Transaction("CASH", "P", "000", 100, -100),
                    Transaction("AID", "P", "800", 100, None,
                                category="FA", title_iv=title_iv),
                ])
                self.assert_unassigned_credit(row, "100.00")
                self.assertIn("MISSING_TRANSACTION_BALANCE", row["review_reasons"])

    @staticmethod
    def reallocated_plus_example() -> list[Transaction]:
        # Stored scholarship credit moves to PLUS under the common 800/000
        # priority. Current payments first cover the prior term's debt.
        return [
            Transaction("OLD", "C", "899", 200, term="209910"),
            Transaction("TUIN", "C", "899", 1000),
            Transaction("SCHL", "P", "000", 500, -100, category="FAS"),
            Transaction("FDPL", "P", "800", 800, 0, category="PPL", title_iv="Y"),
        ]

    def test_reallocated_plus_uses_authorization_and_ed_for_workbook_route(self) -> None:
        for authorization, active_ed, sheet, parent, student in (
            ("N", True, "Refund to Parent", "100.00", "0.00"),
            ("N", False, "Refund to Parent", "100.00", "0.00"),
            ("Y", True, "Direct Deposit", "0.00", "100.00"),
            ("Y", False, "Refund by Check", "0.00", "100.00"),
        ):
            with self.subTest(authorization=authorization, active_ed=active_ed):
                row = self.report(self.reallocated_plus_example(),
                                  authorizations={"9900": authorization}, active_ed=active_ed)
                self.assert_split(row, parent, student)
                self.assertEqual(row["unused_fdpl_amount"], Decimal(100))
                self.assertEqual(row["unused_non_fdpl_amount"], Decimal(0))
                self.assertEqual(row["unpaid_charge_amount"], Decimal(0))
                self.assertEqual(row["allocation_review_required_ind"], "N")
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                self.assertIn("STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION", row["review_reasons"])
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], [sheet])
                    self.assertEqual(sheets[sheet].Detail_Code_Refund_Amt.sum(), 100)

    def test_reallocated_plus_preserves_authorization_and_hold_checks(self) -> None:
        for authorizations, reason in (
            ({}, "PLUS_AUTH_RECORD_MISSING"),
            ({"9899": "N"}, "PLUS_AUTH_RECORD_MISSING"),
            ({"9900": ["Y", "N"]}, "PLUS_AUTH_VALUES_CONFLICT"),
            ({"9900": "?"}, "PLUS_AUTH_VALUES_CONFLICT"),
        ):
            with self.subTest(authorizations=authorizations):
                row = self.report(self.reallocated_plus_example(), authorizations=authorizations)
                self.assert_unassigned_credit(row, "100.00")
                self.assertIn(reason, row["review_reasons"])
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], ["Manual Reviews"])
        for authorization in ("Y", "N"):
            with self.subTest(held_authorization=authorization):
                row = self.report(self.reallocated_plus_example(),
                                  authorizations={"9900": authorization}, refund_hold=True)
                self.assertEqual(row["review_status"], "HOLD")
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], ["Refund Holds"])

    def test_reconstructed_excess_goes_to_manual_review_at_net_credit_only(self) -> None:
        row = self.report([
            Transaction("OLD", "C", "899", 1000, 800, term="209955"),
            Transaction("AID", "P", "800", 1200, -1000, category="FA", title_iv="Y"),
        ])
        self.assert_unassigned_credit(row, "200.00")
        self.assertEqual(row["total_unused_payment_amount"], Decimal("1000.00"))
        with TemporaryDirectory() as directory:
            output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
            sheets = pd.read_excel(output, sheet_name=None)
            self.assertEqual(sheets["Manual Reviews"].Detail_Code_Refund_Amt.sum(), 200)
            self.assertTrue(sheets["Direct Deposit"].empty)
            self.assertTrue(sheets["Refund to Parent"].empty)

    def test_parent_source_cannot_exceed_net_credit(self) -> None:
        row = self.report([
            Transaction("CHG7", "C", "700", 500, 500),
            Transaction("FDPL", "P", "899", 600, -600, category="FA", title_iv="Y"),
        ])
        self.assert_unassigned_credit(row, "100.00")
        self.assertEqual(row["total_unused_payment_amount"], Decimal("600.00"))
        self.assertEqual(row["proposed_parent_delivery"], "NONE")

    def test_credit_without_reconstructed_payment_source_requires_review(self) -> None:
        row = self.report([Transaction("ADJ", "C", "899", -100, -100)])
        self.assert_unassigned_credit(row, "100.00")
        self.assertEqual(row["total_unused_payment_amount"], Decimal("0.00"))
        self.assertIn("NEGATIVE_NET_SOURCE_REQUIRES_REVIEW", row["review_reasons"])

    def test_exact_match_remainders_and_cross_term_title_iv_limits(self) -> None:
        for priority in ("899", "869"):
            row = self.report([
                Transaction("EXCT", "C", priority, 800),
                Transaction("PAYX", "P", priority, 1000, -200),
            ])
            self.assert_split(row, "0.00", "200.00")
        for title_iv, term, target, expected, unpaid in (
            ("Y", "209980", "210010", "200.00", "0.00"),
            ("Y", "209955", "209980", "800.00", "600.00"),
            ("N", "209955", "209980", "200.00", "0.00"),
        ):
            with self.subTest(title_iv=title_iv, term=term):
                row = self.report([
                    Transaction("EXCT", "C", "869", 800, term=term),
                    Transaction("PAYX", "P", "869", 1000, -200, term=target,
                                title_iv=title_iv, category="FA"),
                ], target_term=target)
                if Decimal(unpaid):
                    self.assert_unassigned_credit(row, "200.00")
                    self.assertEqual(row["total_unused_payment_amount"], Decimal(expected))
                else:
                    self.assert_split(row, "0.00", expected)
                self.assertEqual(row["unpaid_charge_amount"], Decimal(unpaid))

    def test_card_and_ach_remainders_route_only_their_own_funds(self) -> None:
        for code in ("ACHK", "CRAM", "CRDS", "CRMC", "CRVC"):
            with self.subTest(code=code):
                row = self.report([
                    Transaction("CHG7", "C", "700", 400, tran_number=1),
                    Transaction("COFP", "P", "000", 100, tran_number=5),
                    Transaction(code, "P", "000", 600, -300, tran_number=2),
                    Transaction("SCHP", "P", "000", 1000, -1000, tran_number=3, category="FAS"),
                    Transaction("TIVA", "P", "800", 500, -500, tran_number=4, title_iv="Y", category="FA"),
                ])
                self.assert_split(row, "0.00", "1800.00")
                route = "AFRD" if code == "ACHK" else code
                self.assertEqual(row["proposed_student_delivery"], f"{route} (Transact) 200.00; ARFD (System) 1600.00")
                self.assertEqual(row["original_payment_total"], Decimal("200.00"))
                self.assertNotIn("000Z", row["balance_sources"])

    def test_cards_immediate_ach_day_16_and_card_reversals(self) -> None:
        for code in ("CRAM", "CRDS", "CRMC", "CRVC"):
            row = self.report([
                Transaction(code, "P", "000", 100, effective_date="2099-08-31"),
                Transaction(code, "P", "000", -40, effective_date="2099-08-31"),
            ])
            self.assert_split(row, "0.00", "60.00")
            self.assertEqual(row["proposed_student_delivery"], f"{code} (Transact)")
        ready = self.report([Transaction("ACHK", "P", "000", 50, -50, effective_date="2099-08-15")])
        self.assertEqual(ready["proposed_student_delivery"], "AFRD (Transact)")

    def test_c529_and_z0le_require_current_term_unused_payment(self) -> None:
        for code in ("C529", "Z0LE"):
            for term, charge, reversal, flag in (
                ("209980", 80, 0, True),
                ("209980", 100, 0, False),
                ("209980", 0, -100, False),
                ("209880", 0, 0, False),
            ):
                with self.subTest(code=code, term=term, charge=charge, reversal=reversal):
                    row = self.report([
                        Transaction("CHG8", "C", "899", charge, term=term),
                        Transaction(code, "P", "000", 100, term=term),
                        Transaction(code, "P", "000", reversal, term=term),
                        Transaction("FREE", "P", "000", 50, -50),
                    ])
                    self.assertEqual(row["third_party_review_required_ind"], "Y" if flag else "N")
                    self.assertEqual("Possible Third Party refund" in (row["review_reasons"] or ""), flag)
                    if flag:
                        self.assertEqual(row["third_party_match_source"], code)
                        self.assertEqual(row["proposed_student_delivery"], "THIRD_PARTY_REVIEW")
                        self.assertEqual(row["review_status"], "MANUAL_REVIEW")
                        self.assertIsNotNone(row["student_refund_amount"])

    def test_tppy_review_includes_reversals_any_type_and_historical_credit_terms(self) -> None:
        for term in ("209980", "208080"):
            for type_ind, first, reversal in (("P", 100, -100), ("C", 100, -100), ("P", 0, 0)):
                with self.subTest(term=term, type_ind=type_ind, first=first):
                    row = self.report([
                        Transaction("TPPY", type_ind, "800", first, term=term,
                                    effective_date="2080-08-01"),
                        Transaction("TPPY", type_ind, "800", reversal, term=term),
                        Transaction("FREE", "P", "000", 50, -50, term=term),
                    ])
                    self.assertEqual(row["third_party_review_required_ind"], "Y")
                    self.assertEqual(row["proposed_student_delivery"], "THIRD_PARTY_REVIEW")
                    self.assertEqual(row["total_refund_amount"], Decimal("50.00"))

    def test_reversed_tppy_without_same_term_credit_does_not_trigger_new_rule(self) -> None:
        row = self.report([
            Transaction("TPPY", "P", "800", 100, term="208080"),
            Transaction("TPPY", "P", "800", -100, term="208080"),
            Transaction("FREE", "P", "000", 50, -50),
        ])
        self.assertEqual(row["third_party_review_required_ind"], "N")

    def test_third_party_details_use_calendar_term_totals_and_preserve_sponsor_context(self) -> None:
        row = self.report([
            Transaction("TPPY", "P", "800", 100, -100),
            Transaction("TPPY", "P", "800", -20, 20),
            Transaction("Z0LE", "P", "000", 50, -50),
            Transaction("Z0LE", "P", "000", -10, 10),
            Transaction("TPPY", "P", "800", 999, -999, term="209910"),
        ], target_term="209910", authorizations={"9900": ["N", "N"]}, sponsor_context={
            "sponsor_names": "Synthetic One | Synthetic Two",
            "sponsor_ids": "TPS-TEST-1 | TPS-TEST-2", "contract_numbers": "0001 | 0002",
        })
        self.assertEqual(row["third_party_current_term"], "209980")
        self.assertEqual(row["current_term_tppy_total"], Decimal("80.00"))
        self.assertEqual(row["current_term_z0le_total"], Decimal("40.00"))
        self.assertEqual(row["sponsor_ids"], "TPS-TEST-1 | TPS-TEST-2")
        self.assertEqual(row["contract_numbers"], "0001 | 0002")

    def test_missing_current_term_amount_leaves_total_unknown(self) -> None:
        row = self.report([
            Transaction("TPPY", "P", "800", None, None),
            Transaction("FREE", "P", "000", 50, -50),
        ])
        self.assertIsNone(row["current_term_tppy_total"])
        self.assertEqual(row["third_party_review_required_ind"], "Y")
        self.assertIn("MISSING_TRANSACTION_AMOUNT", row["review_reasons"])

    def test_z0le_recent_activity_uses_feed_date_including_reversals(self) -> None:
        run_date = date(2099, 8, 31)
        for age, expected in ((0, "Y"), (6, "Y"), (7, "N"), (-1, "N"), (None, "N")):
            with self.subTest(age=age):
                feed = (run_date - timedelta(days=age)).isoformat() if age is not None else None
                row = self.report([
                    Transaction("Z0LE", "P", "000", 25, term="209910"),
                    Transaction("Z0LE", "P", "000", -25, term="209910",
                                feed_date=feed, effective_date="2080-01-01"),
                    Transaction("FREE", "P", "000", 50, -50),
                ], run_date=run_date)
                self.assertEqual(row["z0le_activity_last_7_days"], expected)

    def test_third_party_workbook_details_and_hold_precedence(self) -> None:
        for held in (False, True):
            row = self.report([
                Transaction("TPPY", "P", "800", 100, -100, feed_date="2099-08-31"),
                Transaction("Z0LE", "P", "000", 25, -25, feed_date="2099-08-25"),
            ], refund_hold=held, sponsor_context={
                "sponsor_names": "Synthetic Sponsor", "sponsor_ids": "TPS-TEST", "contract_numbers": "0001",
            })
            with self.subTest(held=held), TemporaryDirectory() as directory:
                output = Path(directory) / "refunds.xlsx"
                export_refund_report(pd.DataFrame([row], columns=REPORT_COLUMNS), output)
                workbook = load_workbook(output)
                third = workbook["Third Party Reviews"]
                headers = [cell.value for cell in third[1]]
                self.assertEqual(third.max_row, 1 if held else 2)
                self.assertEqual(workbook["Refund Holds"].max_row, 2 if held else 1)
                for sheet in workbook:
                    self.assertEqual("Sponsor(s)" in [cell.value for cell in sheet[1]],
                                     sheet.title == "Third Party Reviews")
                if not held:
                    self.assertEqual(third.cell(2, headers.index("Sponsor ID(s)") + 1).value, "TPS-TEST")
                    self.assertEqual(third.cell(2, headers.index("Contract Number(s)") + 1).value, "0001")
                    self.assertEqual(third.cell(2, headers.index("Z0LE Activity_Last 7 Days") + 1).value, "Yes")
                    self.assertEqual(third.cell(2, headers.index("TPPY Current Term Total") + 1).value, 100)
                    for name in ("TPPY Current Term Total", "Z0LE Current Term Total"):
                        self.assertIn("$", third.cell(2, headers.index(name) + 1).number_format)
                workbook.close()

    def test_tppy_review_uses_surviving_payment_age_even_when_applied(self) -> None:
        run_date = date(2099, 8, 31)
        for term, age, reversal, flag in (
            ("209980", 90, 0, True),
            ("209955", 0, 0, True),
            ("209955", 32, 0, True),
            ("209955", 33, 0, False),
            ("209955", -1, 0, False),
            ("209955", None, 0, False),
            ("209980", None, 0, True),
            ("209980", 0, -100, True),
            ("209955", 32, -50, True),
        ):
            with self.subTest(term=term, age=age, reversal=reversal):
                effective = (run_date - timedelta(days=age)).isoformat() if age is not None else None
                row = self.report([
                    Transaction("CHG8", "C", "899", 100 + reversal, term=term),
                    Transaction("TPPY", "P", "800", 100, 0, term=term,
                                effective_date=effective),
                    Transaction("TPPY", "P", "800", reversal, 0, term=term),
                    Transaction("FREE", "P", "000", 50, -50),
                ])
                self.assert_split(row, "0.00", "50.00")
                self.assertEqual(row["third_party_review_required_ind"], "Y" if flag else "N")
                self.assertEqual("Possible Third Party refund" in (row["review_reasons"] or ""), flag)
                if flag:
                    self.assertEqual(row["third_party_match_source"], "TPPY")
                    self.assertEqual(row["proposed_student_delivery"], "THIRD_PARTY_REVIEW")
                    self.assertEqual(row["review_status"], "MANUAL_REVIEW")
                else:
                    self.assertEqual(row["proposed_student_delivery"], "ARFD (System)")

        held = self.report([
            Transaction("TPPY", "P", "800", 50, -50),
        ], refund_hold=True)
        self.assertEqual(held["third_party_review_required_ind"], "Y")
        self.assertEqual(held["proposed_student_delivery"], "Refund Hold - Student")
        self.assertEqual(held["review_status"], "HOLD")

    def test_homp_review_uses_surviving_charge_age_even_in_settled_history(self) -> None:
        run_date = date(2099, 8, 31)
        for term, age, reversal, flag in (
            ("209980", 90, 0, True),
            ("209955", 0, 0, True),
            ("209955", 32, 0, True),
            ("209955", 33, 0, False),
            ("209955", -1, 0, False),
            ("209955", None, 0, False),
            ("209980", None, 0, True),
            ("209980", 0, -100, False),
            ("209955", 32, -50, True),
        ):
            with self.subTest(term=term, age=age, reversal=reversal):
                effective = (run_date - timedelta(days=age)).isoformat() if age is not None else None
                row = self.report([
                    Transaction("HOMP", "C", "889", 100, 0, term=term, effective_date=effective),
                    Transaction("HOMP", "C", "889", reversal, 0, term=term),
                    Transaction("PAID", "P", "000", 100 + reversal, 0, term=term),
                    Transaction("FREE", "P", "000", 50, -50),
                ])
                self.assert_split(row, "0.00", "50.00")
                self.assertEqual("Mines Park Charge - Review" in (row["review_reasons"] or ""), flag)
                self.assertEqual(row["proposed_student_delivery"], "ARFD (System)")
                if flag:
                    self.assertEqual(row["review_status"], "MANUAL_REVIEW")

    def test_reversed_recent_homp_does_not_rejuvenate_old_surviving_charge(self) -> None:
        row = self.report([
            Transaction("HOMP", "C", "889", 100, term="209955", effective_date="2099-06-01"),
            Transaction("HOMP", "C", "889", 100, term="209955", effective_date="2099-08-20"),
            Transaction("HOMP", "C", "889", -100, term="209955", effective_date="2099-08-21"),
            Transaction("PAID", "P", "000", 100, term="209955"),
            Transaction("FREE", "P", "000", 50, -50),
        ])
        self.assert_split(row, "0.00", "50.00")
        self.assertNotIn("Mines Park Charge - Review", row["review_reasons"] or "")

    def test_authorized_plus_and_card_remainders_keep_distinct_student_routes(self) -> None:
        row = self.report([
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y"),
            Transaction("CRMC", "P", "000", 50, -50),
        ], authorizations={"9900": "Y"})
        self.assert_split(row, "0.00", "150.00")
        self.assertEqual(row["proposed_student_delivery"], "CRMC (Transact) 50.00; ARFD (System) 100.00")

    def test_third_party_review_preserves_parent_amount_but_suppresses_delivery(self) -> None:
        row = self.report([
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y"),
            Transaction("TPPY", "P", "800", 50, -50),
        ])
        self.assert_split(row, "100.00", "50.00")
        self.assertEqual(row["proposed_parent_delivery"], "THIRD_PARTY_REVIEW")
        self.assertEqual(row["proposed_student_delivery"], "THIRD_PARTY_REVIEW")

    def test_export_routes_actual_mixed_allocator_deliveries(self) -> None:
        row = self.report([
            Transaction("FDPL", "P", "800", 70, -70, category="FA", title_iv="Y"),
            Transaction("ACHK", "P", "000", 20, -20),
            Transaction("ACHK", "P", "000", 30, -30, effective_date="2099-08-30"),
            Transaction("ACHK", "P", "000", 40, -40, effective_date="2098-08-01"),
            Transaction("ACHK", "P", "000", 50, -50, effective_date="2099-08-01"),
            *(Transaction(code, "P", "000", 10, -10) for code in ("CRAM", "CRDS", "CRMC", "CRVC")),
            Transaction("SCHP", "P", "000", 100, -100, category="FA"),
        ])
        with TemporaryDirectory() as directory:
            output = Path(directory) / "refunds.xlsx"
            export_refund_report(pd.DataFrame([row]), output)
            sheets = pd.read_excel(output, sheet_name=None)
            sheets = {name: sheet.rename(columns={
                "CWID": "cwid", "Detail_Code_Refund_Amt": "tab_refund_amount",
                "Detail_Code_Note": "tab_review_note", "Detail_Code_Delivery": "tab_delivery",
                "Total_Owed_to_Student": "total_refund_amount",
            }) for name, sheet in sheets.items()}
            expected = {"ACH or CC Refunds": 110, "Payment Clearing": 65, "ACH Reviews": 40,
                        "Direct Deposit": 65, "Refund to Parent": 70}
            self.assertEqual({name: frame.tab_refund_amount.sum() for name, frame in sheets.items()
                              if not frame.empty}, expected)
            self.assertEqual(pd.Timestamp(sheets["Payment Clearing"].iloc[0]["Next Clearing Date"]),
                             pd.Timestamp("2099-09-15"))
            for code in ("CRAM", "CRDS", "CRMC", "CRVC"):
                self.assertIn(f"{code} (Transact) 10.00", sheets["ACH or CC Refunds"].iloc[0].tab_delivery)

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

    def test_later_student_refunds_reconcile_restrictive_payment_remainders(self) -> None:
        for refund_code in ("ARFD", "RFND"):
            with self.subTest(refund_code=refund_code):
                self.report([
                    Transaction("R879", "P", "879", 2500, 0, term="209955", tran_number=10),
                    Transaction(refund_code, "C", "800", 2500, 0,
                                term="209980", tran_number=20),
                ], expected_rows=0)

        partial = self.report([
            Transaction("OLD8", "C", "879", 1000, 0, term="209955", tran_number=1),
            Transaction("R879", "P", "879", 3000, -500, term="209980", tran_number=10),
            Transaction("ARFD", "C", "800", 1500, 0, term="209980", tran_number=20),
        ])
        self.assert_split(partial, "0.00", "500.00")
        self.assertEqual(partial["unpaid_charge_amount"], Decimal("0.00"))
        self.assertIn("R879", partial["balance_sources"])
        self.assertIn(
            "POSTED_STUDENT_REFUND_RECONCILED_AMOUNT_1500.00",
            partial["review_reasons"],
        )

        ordered = self.report([
            Transaction("R879", "P", "879", 2500, 0, tran_number=10),
            Transaction("FREE", "P", "000", 2500, -2500, tran_number=11),
            Transaction("ARFD", "C", "800", 2500, 0, tran_number=20),
        ])
        self.assert_split(ordered, "0.00", "2500.00")
        self.assertNotIn("R879", ordered["balance_sources"])
        self.assertIn("FREE", ordered["balance_sources"])

    def test_prior_posted_refund_does_not_justify_zero_balance_refund(self) -> None:
        self.report([
            Transaction("ARFD", "C", "800", 2500, 2500, tran_number=10),
            Transaction("R879", "P", "879", 2500, -2500, tran_number=20),
        ], expected_rows=0)
        self.report([
            Transaction("ARFD", "C", "800", 2500, 2500, tran_number=10),
            Transaction("ACHK", "P", "000", 2500, -2500, tran_number=20),
        ], expected_rows=0)

    def test_parent_refund_remains_an_ordinary_charge(self) -> None:
        parent_refund = self.report([
            Transaction("R879", "P", "879", 2600, -2600, tran_number=10),
            Transaction("RFDP", "C", "800", 2500, 2500, tran_number=20),
        ])
        self.assert_unassigned_credit(parent_refund, "100.00")
        self.assertEqual(parent_refund["unpaid_charge_amount"], Decimal("2500.00"))
        self.assertNotIn(
            "POSTED_STUDENT_REFUND_RECONCILED",
            parent_refund["review_reasons"] or "",
        )

    def test_posted_student_refund_reversals_net_before_reconciliation(self) -> None:
        row = self.report([
            Transaction("R879", "P", "879", 3000, -1000, tran_number=10),
            Transaction("ARFD", "C", "800", 2500, 2000, tran_number=20),
            Transaction("ARFD", "C", "800", -500, 0, tran_number=21),
        ])
        self.assert_split(row, "0.00", "1000.00")
        self.assertIn(
            "POSTED_STUDENT_REFUND_RECONCILED_AMOUNT_2000.00",
            row["review_reasons"],
        )

    @staticmethod
    def issued_refund_then_adjustment() -> list[Transaction]:
        return [
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("OLDP", "P", "000", 2000, tran_number=2),
            Transaction("ARFD", "C", "800", 1000, tran_number=3),
            Transaction("NEWG", "P", "000", 500, -200, tran_number=4),
            Transaction("ADJT", "C", "877", 300, tran_number=5),
        ]

    def test_settled_issued_refund_reconciles_after_later_charge(self) -> None:
        for refund_code in ("ARFD", "RFND"):
            with self.subTest(refund_code=refund_code):
                transactions = self.issued_refund_then_adjustment()
                transactions[2] = replace(transactions[2], detail_code=refund_code)
                row = self.report(transactions)
                self.assert_split(row, "0.00", "200.00")
                self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))
                self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
                self.assertIn("NEWG", row["balance_sources"])
                self.assertNotIn("OLDP", row["balance_sources"])
                self.assertIn("POSTED_STUDENT_REFUND_RECONCILED_AMOUNT_1000.00", row["review_reasons"])
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertTrue(sheets["Manual Reviews"].empty)
                    self.assertEqual(sheets["Direct Deposit"].Detail_Code_Refund_Amt.sum(), 200)

    def test_unsettled_or_missing_refund_balance_retains_chronology(self) -> None:
        for balance in (1000, None):
            with self.subTest(balance=balance):
                transactions = self.issued_refund_then_adjustment()
                transactions[2] = replace(transactions[2], stored_balance=balance)
                row = self.report(transactions)
                self.assert_unassigned_credit(row, "200.00")
                self.assertIn("POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT", row["review_reasons"])

    def test_later_payment_cannot_prove_an_unfunded_unsettled_history(self) -> None:
        row = self.report([
            Transaction("ARFD", "C", "800", 100, 0, tran_number=1),
            Transaction("PAY0", "P", "000", 150, -50, tran_number=2),
        ])
        self.assert_unassigned_credit(row, "50.00")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("100.00"))

    def test_completed_transaction_prefix_proves_later_refund_settlement(self) -> None:
        transactions = [
            Transaction("ARFD", "C", "800", 100, 0, tran_number=1),
            Transaction("PAY0", "P", "000", 100, 0, tran_number=2),
            Transaction("NEWG", "P", "000", 50, -20, tran_number=3),
            Transaction("ADJT", "C", "877", 30, 0, tran_number=4),
        ]
        self.assert_split(self.report(transactions), "0.00", "20.00")
        # Aggregate zero alone, or an unknown balance, must not establish settlement.
        for refund_balance, payment_balance in ((10, -10), (0, None)):
            with self.subTest(refund_balance=refund_balance, payment_balance=payment_balance):
                unresolved = transactions.copy()
                unresolved[0] = replace(unresolved[0], stored_balance=refund_balance)
                unresolved[1] = replace(unresolved[1], stored_balance=payment_balance)
                self.assert_unassigned_credit(self.report(unresolved), "20.00")

    def test_multiple_issued_refunds_are_deducted_once(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("OLDP", "P", "000", 2500, tran_number=2),
            Transaction("ARFD", "C", "800", 600, tran_number=3),
            Transaction("ARFD", "C", "800", 900, tran_number=4),
            Transaction("NEWG", "P", "000", 500, -200, tran_number=5),
            Transaction("ADJT", "C", "877", 300, tran_number=6),
        ])
        self.assert_split(row, "0.00", "200.00")
        self.assertIn("POSTED_STUDENT_REFUND_RECONCILED_AMOUNT_1500.00", row["review_reasons"])

    def test_issued_refund_fix_retains_parent_authorization_and_hold_routes(self) -> None:
        transactions = self.issued_refund_then_adjustment()
        transactions[3] = replace(transactions[3], detail_code="FDPL", category="FA", title_iv="Y")
        for auth, parent, student in (("N", "200.00", "0.00"), ("Y", "0.00", "200.00")):
            for ed in (True, False):
                with self.subTest(auth=auth, ed=ed):
                    row = self.report(transactions, authorizations={"9900": auth}, active_ed=ed)
                    self.assert_split(row, parent, student)
                    self.assertEqual(row["proposed_parent_delivery"], "RFDP" if auth == "N" else "NONE")
                    held = self.report(transactions, authorizations={"9900": auth},
                                       active_ed=ed, refund_hold=True)
                    with TemporaryDirectory() as directory:
                        output = export_refund_report(pd.DataFrame([held]), Path(directory) / "hold.xlsx")
                        sheets = pd.read_excel(output, sheet_name=None)
                        self.assertEqual([name for name, frame in sheets.items() if not frame.empty], ["Refund Holds"])
        for authorizations in ({}, {"9900": ["Y", "N"]}, {"9899": "Y"}):
            with self.subTest(authorizations=authorizations):
                self.assert_unassigned_credit(self.report(transactions, authorizations=authorizations), "200.00")

    def test_issued_refund_fix_retains_clearing_and_future_term_review(self) -> None:
        transactions = self.issued_refund_then_adjustment()
        transactions[3] = replace(transactions[3], detail_code="CHCK", effective_date="2099-08-30")
        row = self.report(transactions)
        self.assert_split(row, "0.00", "200.00")
        self.assertEqual(row["student_refund_available_amount"], Decimal("0.00"))
        self.assertEqual(row["student_clearing_reserve_amount"], Decimal("200.00"))
        transactions[3] = replace(transactions[3], detail_code="CRVC", term="210010")
        future = self.report(transactions)
        self.assert_unassigned_credit(future, "200.00")
        self.assertIn("FUTURE_TERM_ACTIVITY_EXCLUDED_FROM_ALLOCATION", future["review_reasons"])
        with TemporaryDirectory() as directory:
            output = export_refund_report(pd.DataFrame([future]), Path(directory) / "future.xlsx")
            sheets = pd.read_excel(output, sheet_name=None)
            self.assertEqual([name for name, frame in sheets.items() if not frame.empty], ["Future Term"])

    def test_future_term_credit_is_withheld_even_with_backdated_payment(self) -> None:
        transactions = [
            Transaction("TUIN", "C", "899", 1000),
            Transaction("PAY0", "P", "000", 1000),
            Transaction("ACHK", "P", "000", 500, -500, term="210010"),
        ]
        for active_ed in (False, True):
            with self.subTest(active_ed=active_ed):
                row = self.report(transactions, active_ed=active_ed)
                self.assert_unassigned_credit(row, "500.00")
                self.assertIn("FUTURE_TERM_CREDIT", row["review_reasons"].split("; "))
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "future.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], ["Future Term"])
                    future = sheets["Future Term"].iloc[0]
                    self.assertEqual(future["Detail_Code_Delivery"], "REVIEW REQUIRED")
                    self.assertEqual(future["Detail_Code_Refund_Amt"], 500)
                    self.assertIn("do not issue any refund", future["Detail_Code_Note"])

    def test_future_term_credit_nets_each_term_without_treating_debt_as_credit(self) -> None:
        current = [Transaction("PAY0", "P", "000", 200, -200)]
        payment = Transaction("PAY1", "P", "000", 100, -100, term="210010")
        charge = Transaction("TUIN", "C", "899", 100, 100, term="210010")
        cases = [
            ("current only", [], False, "Direct Deposit"),
            ("future debt", [charge], False, "Manual Reviews"),
            ("future zero", [charge, payment], False, "Manual Reviews"),
            ("reversed payment", [payment, replace(payment, amount=-100, stored_balance=100)], False, "Manual Reviews"),
            ("one cent credit", [replace(charge, amount="99.99"), payment], True, "Future Term"),
            ("one cent debt", [replace(charge, amount="100.01"), payment], False, "Manual Reviews"),
            ("separate future terms", [payment, replace(charge, term="210055")], True, "Future Term"),
            ("unknown future amount", [payment, replace(charge, amount=None)], False, "Manual Reviews"),
            ("unknown future balance", [replace(payment, stored_balance=None)], True, "Future Term"),
            ("invalid term", [replace(payment, term="210099")], False, "Manual Reviews"),
        ]
        for label, future, flagged, expected_sheet in cases:
            with self.subTest(case=label):
                row = self.report(current + future)
                self.assertEqual("FUTURE_TERM_CREDIT" in str(row["review_reasons"]).split("; "), flagged)
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "terms.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], [expected_sheet])
                    self.assertEqual(Decimal(str(sheets[expected_sheet].iloc[0]["Detail_Code_Refund_Amt"])),
                                     row["total_refund_amount"])

    def test_future_term_withholds_whole_account_and_preserves_hold_and_review_reasons(self) -> None:
        transactions = [
            Transaction("FDPL", "P", "800", 100, -100, category="FA", title_iv="Y"),
            Transaction("HOMP", "C", "000", 50, 50),
            Transaction("TPPY", "P", "000", 500, -500, term="210010"),
        ]
        for held, expected_sheet in ((False, "Future Term"), (True, "Refund Holds")):
            with self.subTest(held=held):
                row = self.report(transactions, refund_hold=held)
                self.assertIsNone(row["student_refund_amount"])
                self.assertIsNone(row["parent_refund_amount"])
                self.assertEqual(row["third_party_review_required_ind"], "Y")
                self.assertIn("Mines Park Charge - Review", row["review_reasons"])
                self.assertIn("FUTURE_TERM_CREDIT", row["review_reasons"].split("; "))
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "reviews.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual([name for name, frame in sheets.items() if not frame.empty], [expected_sheet])
                    self.assertEqual(sheets[expected_sheet].iloc[0]["Detail_Code_Refund_Amt"], 550)

    @staticmethod
    def voided_check_and_reissue() -> list[Transaction]:
        return [
            Transaction("TUIN", "C", "899", 100, tran_number=1),
            Transaction("SCHP", "P", "890", 2100, tran_number=2),
            Transaction("RFND", "C", "800", 2000, tran_number=3),
            Transaction("RFDV", "C", "800", -2000, tran_number=4),
            Transaction("ARFD", "C", "800", 2000, tran_number=5),
            Transaction("NEWG", "P", "000", 200, -200, tran_number=6),
        ]

    def test_unique_settled_void_cancels_check_before_ach_reissue(self) -> None:
        row = self.report(self.voided_check_and_reissue())
        self.assert_split(row, "0.00", "200.00")
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertEqual(row["unpaid_charge_amount"], Decimal("0.00"))
        self.assertIn("POSTED_STUDENT_REFUND_RECONCILED_AMOUNT_2000.00", row["review_reasons"])
        self.assertNotIn("REFUND_VOID_REQUIRES_REVIEW", row["review_reasons"])

    def test_unique_void_without_reissue_restores_only_actual_account_credit(self) -> None:
        transactions = [row for row in self.voided_check_and_reissue() if row.detail_code != "ARFD"]
        row = self.report(transactions)
        self.assert_split(row, "0.00", "2200.00")
        self.assertNotIn("POSTED_STUDENT_REFUND_RECONCILED", row["review_reasons"] or "")

    def test_unproved_refund_voids_keep_recipient_split_blocked(self) -> None:
        for label, original, void in (
            ("orphan", None, Transaction("RFDV", "C", "800", -200, tran_number=3)),
            ("partial", Transaction("RFND", "C", "800", 200, tran_number=2),
             Transaction("RFDV", "C", "800", -100, tran_number=3)),
            ("future refund", Transaction("RFND", "C", "800", 200, tran_number=4),
             Transaction("RFDV", "C", "800", -200, tran_number=3)),
            ("other term", Transaction("RFND", "C", "800", 200, term="209955", tran_number=2),
             Transaction("RFDV", "C", "800", -200, tran_number=3)),
            ("parent", Transaction("RFDP", "C", "800", 200, tran_number=2),
             Transaction("RFDV", "C", "800", -200, tran_number=3)),
            ("unknown balance", Transaction("RFND", "C", "800", 200, tran_number=2),
             Transaction("RFDV", "C", "800", -200, None, tran_number=3)),
            ("unsettled", Transaction("RFND", "C", "800", 200, 200, tran_number=2),
             Transaction("RFDV", "C", "800", -200, -200, tran_number=3)),
            ("positive void", Transaction("RFND", "C", "800", 200, tran_number=2),
             Transaction("RFDV", "C", "800", 200, tran_number=3)),
        ):
            with self.subTest(case=label):
                transactions = [Transaction("PAY0", "P", "000", 1000, -1000, tran_number=1), void]
                if original:
                    transactions.append(original)
                row = self.report(transactions)
                self.assertIsNone(row["student_refund_amount"])
                self.assertIn("REFUND_VOID_REQUIRES_REVIEW", row["review_reasons"])

    def test_ambiguous_or_duplicate_void_pairs_cannot_cancel_twice(self) -> None:
        for duplicate in (
            Transaction("ARFD", "C", "800", 200, tran_number=3),
            Transaction("ARFD", "C", "800", 200, None, tran_number=3),
            Transaction("RFDP", "C", "800", 200, tran_number=3),
            Transaction("RFDV", "C", "800", -200, tran_number=5),
        ):
            with self.subTest(duplicate=duplicate.detail_code):
                row = self.report([
                    Transaction("PAY0", "P", "000", 1000, -1000, tran_number=1),
                    Transaction("RFND", "C", "800", 200, tran_number=2),
                    duplicate,
                    Transaction("RFDV", "C", "800", -200, tran_number=4),
                ])
                self.assertIsNone(row["student_refund_amount"])
                self.assertIn("REFUND_VOID_REQUIRES_REVIEW", row["review_reasons"])

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
        self.assert_split(row, "0.00", "2000.00")
        self.assertEqual(row["allocation_review_required_ind"], "N")
        self.assertEqual(row["review_status"], "READY_FOR_STAFF_REVIEW")
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
        self.assertEqual(waiting["proposed_student_delivery"], "NONE")
        self.assertEqual(waiting["student_refund_available_amount"], Decimal(0))
        self.assertEqual(waiting["student_clearing_reserve_amount"], Decimal(50))
        self.assertEqual(waiting["clearing_next_eligible_date"], date(2099, 9, 1))
        self.assertEqual(waiting["review_status"], "WAIT_PAYMENT_CLEARING")

        old = self.report([
            Transaction("ACHK", "P", "000", 50, -50, effective_date="2099-03-03")
        ])
        self.assertEqual(old["proposed_student_delivery"], "AFRD (Transact) - May Be Too Old")

        check = self.report([Transaction("PAY0", "P", "000", 50, -50)], active_ed=False)
        self.assertEqual(check["proposed_student_delivery"], "RFND (CHECK)")
        hold = self.report([Transaction("PAY0", "P", "000", 50, -50)], refund_hold=True)
        self.assertEqual(hold["proposed_student_delivery"], "Refund Hold - Student")

    def test_chck_waits_through_day_15_and_retains_gross_amounts(self) -> None:
        ready = self.report([
            Transaction("CHCK", "P", "000", 50, -50, effective_date="2099-08-15")
        ])
        self.assertEqual(ready["proposed_student_delivery"], "ARFD (System)")
        self.assertEqual(ready["review_status"], "READY_FOR_STAFF_REVIEW")
        self.assertNotIn("CHCK_CLEARING_WAIT", ready["review_reasons"] or "")

        waiting = self.report([
            Transaction("CHCK", "P", "000", 30, -30, effective_date="2099-08-16"),
            Transaction("CHCK", "P", "000", 50, -50, effective_date="2099-08-20"),
        ])
        self.assertEqual(waiting["proposed_student_delivery"], "NONE")
        self.assertEqual(waiting["student_refund_amount"], Decimal(80))
        self.assertEqual(waiting["student_refund_available_amount"], Decimal(0))
        self.assertEqual(waiting["clearing_insurance_amount"], Decimal(70))
        self.assertEqual(waiting["review_status"], "WAIT_PAYMENT_CLEARING")
        self.assertIn(
            "CHCK_CLEARING_WAIT_UNTIL_09/05/2099_AMOUNT_80.00",
            waiting["review_reasons"],
        )

        check = self.report([
            Transaction("CHCK", "P", "000", 50, -50, effective_date="2099-08-16")
        ], active_ed=False)
        self.assertEqual(check["proposed_student_delivery"], "NONE")
        self.assertEqual(check["review_status"], "WAIT_PAYMENT_CLEARING")

        held = self.report([
            Transaction("CHCK", "P", "000", 50, -50, effective_date="2099-08-16")
        ], refund_hold=True)
        self.assertEqual(held["proposed_student_delivery"], "NONE")
        self.assertEqual(held["review_status"], "HOLD")
        self.assertIn("CHCK_CLEARING_WAIT_UNTIL_09/01/2099", held["review_reasons"])

        invalid_date = self.report([
            Transaction("CHCK", "P", "000", 50, -50, effective_date=None)
        ])
        self.assertEqual(invalid_date["proposed_student_delivery"], "NONE")
        self.assertEqual(invalid_date["review_status"], "MANUAL_REVIEW")
        self.assertIn("CHCK_EFFECTIVE_DATE_MISSING_OR_FUTURE", invalid_date["review_reasons"])

    def test_applied_check_and_ach_reserve_principal_plus_insurance_until_day_16(self) -> None:
        for code in ("CHCK", "ACHK"):
            transactions = [
                Transaction("TUIN", "C", "899", 1000, tran_number=1),
                Transaction(code, "P", "000", 1000, 0, effective_date="2099-08-16",
                            feed_date="2099-08-01", tran_number=2),
                Transaction("PELL", "P", "800", 2035, -2035, title_iv="Y", category="FA", tran_number=3),
            ]
            with self.subTest(code=code):
                waiting = self.report(transactions)
                self.assert_split(waiting, 0, 2035)
                self.assertEqual(waiting["student_refund_available_amount"], Decimal(1000))
                self.assertEqual(waiting["student_clearing_reserve_amount"], Decimal(1035))
                self.assertEqual(waiting["clearing_insurance_amount"], Decimal(35))
                self.assertEqual(waiting["clearing_next_eligible_date"], date(2099, 9, 1))
                cleared = self.report(transactions, run_date=date(2099, 9, 1))
                self.assertEqual(cleared["student_refund_available_amount"], Decimal(2035))
                self.assertEqual(cleared["student_clearing_reserve_amount"], Decimal(0))
                self.assertEqual(cleared["clearing_payment_count"], 0)
                posted = transactions + [Transaction("ARFD", "C", "800", 1000, tran_number=4)]
                self.assertEqual(self.report(posted)["student_refund_available_amount"], Decimal(0))
                self.assertEqual(self.report(posted, run_date=date(2099, 9, 1))["student_refund_available_amount"], Decimal(1035))

    def test_clearing_reserve_reversals_and_each_payment_release(self) -> None:
        transactions = [
            Transaction("TUIN", "C", "899", 600, tran_number=1),
            Transaction("CHCK", "P", "000", 1000, 0, effective_date="2099-08-16", tran_number=2),
            Transaction("CHCK", "P", "000", -400, 0, effective_date="2099-08-30", tran_number=3),
            Transaction("PELL", "P", "800", 2035, -2035, title_iv="Y", category="FA", tran_number=4),
        ]
        partial = self.report(transactions)
        self.assertEqual(partial["clearing_payment_amount"], Decimal(600))
        self.assertEqual(partial["student_clearing_reserve_amount"], Decimal(635))
        self.assertEqual(partial["student_refund_available_amount"], Decimal(1400))
        reversed_row = self.report([
            replace(transactions[0], amount=0), transactions[1],
            replace(transactions[2], amount=-1000), transactions[3],
        ])
        self.assertEqual(reversed_row["clearing_payment_count"], 0)
        self.assertEqual(reversed_row["student_refund_available_amount"], Decimal(2035))
        multiple = [
            Transaction("TUIN", "C", "899", 1000, tran_number=1),
            Transaction("CHCK", "P", "000", 500, 0, effective_date="2099-08-16", tran_number=2),
            Transaction("ACHK", "P", "000", 500, 0, effective_date="2099-08-20", tran_number=3),
            transactions[3],
        ]
        for run_date, held, count in ((date(2099, 8, 31), 1070, 2),
                                      (date(2099, 9, 1), 535, 1),
                                      (date(2099, 9, 5), 0, 0)):
            with self.subTest(run_date=run_date):
                row = self.report(multiple, run_date=run_date)
                self.assertEqual(row["student_clearing_reserve_amount"], Decimal(held))
                self.assertEqual(row["clearing_payment_count"], count)
                self.assertEqual(row["student_refund_available_amount"], Decimal(2035 - held))

    def test_student_absorbs_insurance_and_principal_before_parent(self) -> None:
        for student, insurance, parent_available in ((100, 35, 1065), (10, 10, 1000), (0, 0, 1000)):
            with self.subTest(student=student):
                row = self.report([
                    Transaction("TUIN", "C", "899", 1000, tran_number=1),
                    Transaction("CHCK", "P", "000", 1000, 0, effective_date="2099-08-16", tran_number=2),
                    Transaction("CASH", "P", "000", student, -student, tran_number=3),
                    Transaction("FDPL", "P", "800", 2000, -2000, title_iv="Y", category="FA", tran_number=4),
                ])
                self.assert_split(row, 2000, student)
                self.assertEqual(row["clearing_insurance_amount"], Decimal(insurance))
                self.assertEqual(row["student_refund_available_amount"], Decimal(0))
                self.assertEqual(row["parent_refund_available_amount"], Decimal(parent_available))
                self.assertEqual(row["parent_clearing_reserve_amount"], Decimal(2000 - parent_available))
                self.assertEqual(row["proposed_parent_delivery"], "RFDP")

    def test_recent_applied_payment_in_settled_history_still_reserves_credit(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 1000, 0, term="209955", tran_number=1),
            Transaction("CHCK", "P", "000", 1000, 0, term="209955", effective_date="2099-08-16", tran_number=2),
            Transaction("PELL", "P", "800", 2035, -2035, title_iv="Y", category="FA", tran_number=3),
        ])
        self.assertEqual(row["student_refund_available_amount"], Decimal(1000))
        self.assertEqual(row["student_clearing_reserve_amount"], Decimal(1035))

    def test_missing_or_future_applied_payment_date_blocks_recipient_amounts(self) -> None:
        for code in ("CHCK", "ACHK"):
            for effective in (None, "2099-09-01"):
                with self.subTest(code=code, effective=effective):
                    row = self.report([
                        Transaction("TUIN", "C", "899", 1000, tran_number=1),
                        Transaction(code, "P", "000", 1000, 0, effective_date=effective, tran_number=2),
                        Transaction("PELL", "P", "800", 2035, -2035, title_iv="Y", category="FA", tran_number=3),
                    ])
                    self.assertIsNone(row["student_refund_available_amount"])
                    self.assertIsNone(row["parent_refund_available_amount"])
                    self.assertEqual(row["review_status"], "MANUAL_REVIEW")
                    self.assertIn("CHCK_ACHK_EFFECTIVE_DATE_MISSING_OR_FUTURE", row["review_reasons"])

    def test_reserve_caps_original_method_amounts_at_available_student_funds(self) -> None:
        row = self.report([
            Transaction("TUIN", "C", "899", 100, tran_number=1),
            Transaction("CHCK", "P", "000", 100, 0, effective_date="2099-08-16", tran_number=2),
            Transaction("ACHK", "P", "000", 100, -100, tran_number=3),
            Transaction("CRVC", "P", "000", 100, -100, tran_number=4),
            Transaction("PELL", "P", "800", 50, -50, title_iv="Y", category="FA", tran_number=5),
        ])
        self.assertEqual(row["student_refund_available_amount"], Decimal(115))
        self.assertEqual(row["student_clearing_reserve_amount"], Decimal(135))
        self.assertEqual(row["proposed_student_delivery"], "AFRD (Transact) 100.00; CRVC (Transact) 15.00")

    def test_workbook_separates_reserves_and_applies_minimum_to_available_check(self) -> None:
        transactions = [
            Transaction("TUIN", "C", "899", 50, tran_number=1),
            Transaction("CHCK", "P", "000", 50, 0, effective_date="2099-08-16", tran_number=2),
            Transaction("CASH", "P", "000", 90, -90, tran_number=3),
        ]
        for hold, expected in ((False, {"Check Refund < 25": 5, "Payment Clearing": 85}),
                                (True, {"Refund Holds": 90})):
            with self.subTest(hold=hold):
                row = self.report(transactions, active_ed=False, refund_hold=hold)
                self.assertIn("STUDENT_CHECK_REFUND_BELOW_25", row["review_reasons"])
                with TemporaryDirectory() as directory:
                    output = export_refund_report(pd.DataFrame([row]), Path(directory) / "review.xlsx")
                    sheets = pd.read_excel(output, sheet_name=None)
                    self.assertEqual({name: frame["Detail_Code_Refund_Amt"].sum()
                                      for name, frame in sheets.items() if not frame.empty}, expected)
                    self.assertEqual(sum(expected.values()), row["total_refund_amount"])

    def test_student_check_minimum_uses_only_the_check_portion(self) -> None:
        for amount, expected in (("24.99", "WAIT_CHECK_MINIMUM"), ("25.00", "READY_FOR_STAFF_REVIEW")):
            with self.subTest(amount=amount):
                row = self.report([Transaction("CASH", "P", "000", amount, -Decimal(amount))], active_ed=False)
                self.assertEqual(row["review_status"], expected)
                self.assertEqual(row["student_refund_available_amount"], Decimal(amount))
        mixed = self.report([
            Transaction("ACHK", "P", "000", 100, -100),
            Transaction("CASH", "P", "000", 10, -10),
        ], active_ed=False)
        self.assertEqual(mixed["proposed_student_delivery"], "AFRD (Transact) 100.00; RFND (CHECK) 10.00")
        self.assertEqual(mixed["review_status"], "WAIT_CHECK_MINIMUM")
        self.assertIn("STUDENT_CHECK_REFUND_BELOW_25", mixed["review_reasons"])
        parent = self.report([Transaction("FDPL", "P", "800", 5, -5, title_iv="Y", category="FA")], active_ed=False)
        self.assertNotIn("STUDENT_CHECK_REFUND_BELOW_25", parent["review_reasons"] or "")
        self.assertEqual(parent["proposed_parent_delivery"], "RFDP")

    def test_rh_hold_overrides_mines_park_and_parent_delivery(self) -> None:
        row = self.report([
            Transaction("HOMP", "C", "889", 100),
            Transaction("FDPL", "P", "800", 200, -100, category="FA", title_iv="Y"),
        ], authorizations={"9900": "N"}, refund_hold=True)
        self.assert_split(row, "100.00", "0.00")
        self.assertEqual(row["proposed_student_delivery"], "NONE")
        self.assertEqual(row["proposed_parent_delivery"], "Refund Hold - Parent")
        self.assertEqual(row["review_status"], "HOLD")
        self.assertIn("REFUND_HOLD_RH", row["review_reasons"])
        self.assertIn("Mines Park Charge - Review", row["review_reasons"])

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


class RefundAddressReviewTests(unittest.TestCase):
    def report(self, transactions, **kwargs):
        return RefundAllocationTests().report(transactions, **kwargs)

    def workbook(self, row):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "addresses.xlsx"
        export_refund_report(pd.DataFrame([row], columns=REPORT_COLUMNS), path)
        workbook = load_workbook(path)
        self.addCleanup(workbook.close)
        return workbook

    def amounts(self, workbook):
        amounts = {}
        for sheet in workbook:
            headers = [cell.value for cell in sheet[1]]
            amount_column = headers.index("Detail_Code_Refund_Amt") + 1
            amounts[sheet.title] = sum((Decimal(str(sheet.cell(row, amount_column).value))
                                       for row in range(2, sheet.max_row + 1)), Decimal(0))
        return {sheet: amount for sheet, amount in amounts.items() if amount}

    def test_address_review_partitions_only_check_and_formats_flag_in_red(self):
        payments = [Transaction("FREE", "P", "000", 100, -100),
                    Transaction("ACHK", "P", "000", 100, -100),
                    Transaction("FDPL", "P", "800", 75, -75, category="FA", title_iv="Y")]
        for flag in ("UPDATE WORKDAY", "Withhold check refund"):
            with self.subTest(flag=flag):
                row = self.report(payments, active_ed=False, address_context={
                    "student_address_review": flag, "student_address_type": "PA",
                    "student_address_zip": "01234",
                })
                self.assertEqual(row["review_status"], "WAIT_CHECK_ADDRESS")
                self.assertEqual(row["student_refund_amount"], Decimal(200))
                self.assertEqual(row["parent_refund_amount"], Decimal(75))
                workbook = self.workbook(row)
                self.assertEqual(self.amounts(workbook), {
                    "ACH or CC Refunds": Decimal(100), "Check Address Review": Decimal(100),
                    "Refund to Parent": Decimal(75),
                })
                sheet = workbook["Check Address Review"]
                headers = [cell.value for cell in sheet[1]]
                flag_cell = sheet.cell(2, headers.index("Student Check Address Flag") + 1)
                self.assertEqual(flag_cell.value, flag)
                self.assertEqual(flag_cell.font.color.rgb[-6:], "FF0000")
                zip_cell = sheet.cell(2, headers.index("Student Address ZIP") + 1)
                self.assertEqual(zip_cell.value, "01234")
                self.assertEqual(zip_cell.data_type, "s")

    def test_noncheck_methods_and_parent_only_do_not_get_address_flag(self):
        for code, ed, amount, expected in (("FREE", True, 100, "Direct Deposit"),
                ("ACHK", False, 100, "ACH or CC Refunds"),
                ("CRVC", False, 100, "ACH or CC Refunds"),
                ("FDPL", False, 10, "Refund to Parent")):
            with self.subTest(code=code):
                row = self.report([Transaction(code, "P", "800" if code == "FDPL" else "000",
                    amount, -amount, category="FA" if code == "FDPL" else "CSH",
                    title_iv="Y" if code == "FDPL" else "N")], active_ed=ed,
                    address_context={"student_address_review": "Withhold check refund"})
                self.assertIsNone(row["student_check_address_flag"])
                self.assertEqual(self.amounts(self.workbook(row)), {expected: Decimal(amount)})

    def test_small_check_stays_withheld_after_address_review(self):
        row = self.report([Transaction("FREE", "P", "000", 10, -10)], active_ed=False,
                          address_context={"student_address_review": "UPDATE WORKDAY"})
        self.assertIn("STUDENT_CHECK_REFUND_BELOW_25", row["review_reasons"])
        workbook = self.workbook(row)
        self.assertEqual(self.amounts(workbook), {"Check Address Review": Decimal(10)})
        self.assertIn("below $25.00", workbook["Check Address Review"]["F2"].value)

    def test_address_review_preserves_clearing_reserve_and_rh_precedence(self):
        payments = [Transaction("TUIN", "C", "899", 1000),
                    Transaction("CHCK", "P", "000", 1000, effective_date="2099-08-16"),
                    Transaction("PELL", "P", "800", 2035, -2035, category="FA", title_iv="Y")]
        for hold in (False, True):
            row = self.report(payments, active_ed=False, refund_hold=hold,
                              address_context={"student_address_review": "Withhold check refund"})
            self.assertEqual(row["student_clearing_reserve_amount"], Decimal(1035))
            expected = {"Refund Holds": Decimal(2035)} if hold else {
                "Payment Clearing": Decimal(1035), "Check Address Review": Decimal(1000),
            }
            self.assertEqual(self.amounts(self.workbook(row)), expected)

    def test_conflicting_context_copies_do_not_select_an_arbitrary_address(self):
        from data_processing.refunds.allocation import _context_for_account

        rows = [{"student_address_type": "PR", "student_address_line1": street}
                for street in ("1 Synthetic Road", "2 Synthetic Road")]
        account, _ = _context_for_account(rows)
        self.assertEqual(account["student_address_review"], "Withhold check refund")
        self.assertIsNone(account["student_address_line1"])


class RefundTermTests(unittest.TestCase):
    def test_mines_term_and_fiscal_year_rules(self) -> None:
        self.assertEqual(derive_target_term(date(2026, 5, 15)), "202610")
        self.assertEqual(derive_target_term(date(2026, 5, 16)), "202655")
        self.assertEqual(derive_target_term(date(2026, 7, 16)), "202680")
        self.assertEqual(fiscal_year_start("202680"), 2026)
        for term in ("202710", "202750", "202755", "202760"):
            self.assertEqual(fiscal_year_start(term), 2026)
        self.assertEqual(previous_term("202680", "202660"), "202660")


class CappedRefundSQLClient:
    """Execute real window/range SQL over synthetic rows, then impose an API cap."""

    def __init__(self, transactions, context=None, limit=2000):
        self.database = sqlite3.connect(":memory:")
        self.database.execute("CREATE TABLE transactions (pidm INTEGER, tran_number INTEGER)")
        self.database.executemany("INSERT INTO transactions VALUES (?, ?)", transactions)
        self.database.execute("CREATE VIEW transaction_source AS SELECT pidm AS tbraccd_pidm, tran_number AS tbraccd_tran_number FROM transactions")
        self.database.execute("CREATE TABLE context (pidm INTEGER, authorization INTEGER)")
        self.database.executemany("INSERT INTO context VALUES (?, ?)", context or [(1, 1)])
        self.database.execute("CREATE VIEW context_source AS SELECT pidm AS tbraccd_pidm, authorization FROM context")
        self.limit = limit
        self.calls = []

    def run_sql(self, sql):
        self.calls.append(sql)
        cursor = self.database.execute(sql)
        return pd.DataFrame(cursor.fetchmany(self.limit), columns=[column[0] for column in cursor.description])

    def close(self):
        self.database.close()


class RefundSubdivisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.transaction_template = self.root / "transactions.sql"
        self.context_template = self.root / "context.sql"
        self.transaction_template.write_text(
            "SELECT COUNT(*) OVER () AS extract_row_count, t.tbraccd_pidm AS pidm, "
            "t.tbraccd_tran_number AS tran_number FROM transaction_source t "
            "WHERE __PIDM_FILTER__ AND __TRANSACTION_FILTER__ ORDER BY pidm, tran_number;", encoding="utf-8",
        )
        self.context_template.write_text(
            "SELECT COUNT(*) OVER () AS extract_row_count, t.tbraccd_pidm AS pidm, authorization "
            "FROM context_source t WHERE __PIDM_FILTER__ ORDER BY pidm, authorization;", encoding="utf-8",
        )
        self.settings = ExtractSettings("202680", 1, self.root / "cache")
        self.messages = []

    def client(self, transactions, context=None, limit=2000):
        client = CappedRefundSQLClient(transactions, context, limit)
        self.addCleanup(client.close)
        return client

    def extract(self, client, settings=None):
        return extract_refund_data(
            client, settings or self.settings,
            transaction_template_path=self.transaction_template,
            context_template_path=self.context_template,
            progress=self.messages.append,
        )

    def assert_transactions(self, frame, rows):
        self.assertEqual(list(frame.itertuples(index=False, name=None)), rows)
        self.assertEqual(list(frame.columns), ["pidm", "tran_number"])
        cached = pd.read_csv(self.settings.extract_directory / "transactions_000.csv")
        pd.testing.assert_frame_equal(cached, frame)

    def test_complete_empty_and_near_limit_batches_do_not_split(self):
        for count in (0, 1999, 2000):
            with self.subTest(count=count):
                rows = [(i + 1, 1) for i in range(count)]
                client = self.client(rows)
                transactions, _ = self.extract(client)
                self.assertEqual(len(client.calls), 2)
                self.assert_transactions(transactions, rows)

    def test_one_split_combines_all_rows_once_and_resumes_complete_cache(self):
        rows = [(i + 1, 1) for i in range(4000)]
        client = self.client(rows)
        transactions, _ = self.extract(client)
        self.assertEqual(len(client.calls), 4)  # root, two complete children, context
        self.assert_transactions(transactions, rows)
        self.assertTrue(any("subdividing" in message for message in self.messages))
        calls = len(client.calls)
        resumed, _ = self.extract(client, replace(self.settings, resume=True))
        self.assertEqual(len(client.calls), calls)
        pd.testing.assert_frame_equal(resumed, transactions)
        offline, _ = read_refund_extracts(self.settings)
        pd.testing.assert_frame_equal(offline, transactions)

    def test_extraction_progress_counts_only_complete_batches_and_names_partitions(self):
        updates = []
        client = self.client([(i + 1, 1) for i in range(4000)])
        extract_refund_data(
            client, self.settings, transaction_template_path=self.transaction_template,
            context_template_path=self.context_template, progress_reporter=ProgressReporter(updates.append),
        )
        query_updates = [update for update in updates if "batch/partition" in update.stage]
        self.assertTrue(any("1.1" in update.stage for update in query_updates))
        self.assertTrue(all(update.completed == 0 for update in query_updates if "transactions" in update.stage))
        completed = [update for update in updates if update.stage == "Extracting refund data — complete batches"]
        self.assertEqual([(update.completed, update.total) for update in completed], [(1, 2), (2, 2)])

    def test_multiple_account_splits_include_all_rows_once(self):
        rows = [(i // 100 + 1, i % 100 + 1) for i in range(37322)]
        client = self.client(rows)
        transactions, _ = self.extract(client)
        self.assertGreater(len(client.calls), 4)
        self.assert_transactions(transactions, rows)
        self.assertTrue(any("batch 1.1.1" in message for message in self.messages))
        self.assertTrue(any("expected 37,322 rows but received 2,000" in message for message in self.messages))

    def test_single_large_account_subdivides_by_transaction_number(self):
        rows = [(1, i + 1) for i in range(5001)]
        client = self.client(rows)
        transactions, _ = self.extract(client)
        self.assert_transactions(transactions, rows)
        self.assertTrue(any("t.tbraccd_tran_number <=" in sql for sql in client.calls))

    def test_sparse_negative_ranges_preserve_boundary_rows(self):
        rows = sorted([(pidm, number) for pidm in (-100, -1, 20, 100000) for number in (1, 20, 9999)])
        client = self.client(rows, limit=2)
        transactions, _ = self.extract(client)
        self.assert_transactions(transactions, rows)

    def test_narrowed_queries_do_not_rebuild_the_full_batch_each_time(self):
        rows = [(i // 100 + 1, i % 100 + 1) for i in range(37322)]
        client = self.client(rows)
        visits = [0]

        def visit(value):
            visits[0] += 1
            return value

        client.database.create_function("visit", 1, visit)
        self.transaction_template.write_text(
            self.transaction_template.read_text().replace(
                "t.tbraccd_tran_number AS tran_number", "visit(t.tbraccd_tran_number) AS tran_number"
            ), encoding="utf-8",
        )
        transactions, _ = self.extract(client)
        self.assert_transactions(transactions, rows)
        transaction_calls = sum("transaction_source" in sql for sql in client.calls)
        self.assertLess(visits[0], len(rows) * transaction_calls // 4)
        self.assertTrue(any("rows in" in message for message in self.messages))

    def test_cancel_after_query_prevents_subdivision_and_cache_write(self):
        token = CancellationToken()
        client = self.client([(i + 1, 1) for i in range(4000)])
        original = client.run_sql

        def cancel_on_return(sql):
            frame = original(sql)
            token.request()
            return frame

        with patch.object(client, "run_sql", side_effect=cancel_on_return):
            with self.assertRaises(WorkflowCancelled):
                extract_refund_data(
                    client, self.settings, transaction_template_path=self.transaction_template,
                    context_template_path=self.context_template, cancellation=token,
                )
        self.assertEqual(len(client.calls), 1)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_context_batches_also_subdivide_without_dropping_duplicate_authorizations(self):
        context = [(i + 1, 1) for i in range(3000)] + [(3000, 1)]
        client = self.client([(1, 1)], context)
        _, frame = self.extract(client)
        self.assertEqual(list(frame.itertuples(index=False, name=None)), context)
        self.assertTrue(any("Context batch" in message and "subdividing" in message for message in self.messages))

    def test_indivisible_transaction_partition_is_not_cached(self):
        client = self.client([(1, 1)] * 2001)
        with self.assertRaisesRegex(RefundExtractError, "smallest transactions partition"):
            self.extract(client)
        self.assertEqual(len(client.calls), 1)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())
        self.assertEqual(list(self.settings.extract_directory.glob("*.tmp")), [])

    def test_indivisible_context_leaves_only_complete_transaction_cache(self):
        client = self.client([(1, 1)], [(1, 1)] * 2001)
        with self.assertRaisesRegex(RefundExtractError, "smallest context partition"):
            self.extract(client)
        self.assertTrue((self.settings.extract_directory / "transactions_000.csv").exists())
        self.assertFalse((self.settings.extract_directory / "context_000.csv").exists())
        with self.assertRaisesRegex(FileNotFoundError, "incomplete"):
            read_refund_extracts(self.settings)

    def test_depth_limit_stops_subdivision_without_caching(self):
        client = self.client([(i + 1, 1) for i in range(5)], limit=2)
        with patch("data_processing.refunds.extract.MAX_SUBDIVISION_DEPTH", 0):
            with self.assertRaisesRegex(RefundExtractError, "safety limit"):
                self.extract(client)
        self.assertEqual(len(client.calls), 1)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_failed_child_is_not_cached_and_resume_retries_the_root(self):
        client = self.client([(i + 1, 1) for i in range(4)], limit=2)
        original = client.run_sql

        def fail_right(sql):
            if "t.tbraccd_pidm >=" in sql:
                raise RuntimeError("Synthetic connection failure")
            return original(sql)

        with patch.object(client, "run_sql", side_effect=fail_right):
            with self.assertRaisesRegex(RuntimeError, "connection failure"):
                self.extract(client)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())
        transactions, _ = self.extract(client, replace(self.settings, resume=True))
        self.assert_transactions(transactions, [(i + 1, 1) for i in range(4)])

    def test_transient_child_failure_retries_only_that_query_without_duplicate_rows(self):
        rows = [(i + 1, 1) for i in range(4)]
        client = self.client(rows, limit=2)
        original = client.run_sql
        failed = []

        def fail_right_once(sql):
            if "t.tbraccd_pidm >=" in sql and not failed:
                failed.append(sql)
                raise InsightsAPIError("Synthetic failure", code="connection")
            return original(sql)

        with (
            patch.object(client, "run_sql", side_effect=fail_right_once) as query,
            patch("data_processing.refunds.extract._wait_for_query_retry") as wait,
        ):
            transactions, _ = self.extract(client)
        self.assert_transactions(transactions, rows)
        self.assertEqual(query.call_count, 5)  # root, left, failed right, right, context
        self.assertEqual(query.call_args_list[2], query.call_args_list[3])
        wait.assert_called_once_with(2.0, None)

    def test_retry_exhaustion_keeps_completed_batches_and_resume_queries_only_missing_data(self):
        client = self.client([(1, 1)])
        original = client.run_sql

        def fail_context(sql):
            if "context_source" in sql:
                raise InsightsAPIError("Sensitive server text", code="timeout")
            return original(sql)

        with (
            patch.object(client, "run_sql", side_effect=fail_context) as query,
            patch("data_processing.refunds.extract._wait_for_query_retry") as wait,
        ):
            with self.assertRaisesRegex(RefundExtractError, "after 3 attempts") as raised:
                self.extract(client)
        self.assertNotIn("Sensitive", str(raised.exception))
        self.assertEqual(query.call_count, 4)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [2.0, 5.0])
        self.assertTrue((self.settings.extract_directory / "transactions_000.csv").exists())
        self.assertFalse((self.settings.extract_directory / "context_000.csv").exists())
        transactions, _ = self.extract(client, replace(self.settings, resume=True))
        self.assert_transactions(transactions, [(1, 1)])
        self.assertEqual(len(client.calls), 2)  # one transaction and one recovered context query

    def test_only_transient_insights_errors_are_retried(self):
        for code, status, expected_calls in (
            ("connection", None, 3), ("timeout", None, 3),
            ("http", 429, 3), ("http", 502, 3), ("http", 503, 3), ("http", 504, 3),
            ("http", 400, 1), ("http", 401, 1), ("http", 403, 1), ("http", 500, 1),
            ("query_failed", None, 1), ("invalid_response", None, 1),
        ):
            with self.subTest(code=code, status=status):
                client = self.client([(1, 1)])
                with (
                    patch.object(client, "run_sql", side_effect=InsightsAPIError(
                        "Synthetic failure", code=code, status_code=status,
                    )) as query,
                    patch("data_processing.refunds.extract._wait_for_query_retry"),
                    self.assertRaises((RefundExtractError, InsightsAPIError)),
                ):
                    self.extract(client)
                self.assertEqual(query.call_count, expected_calls)
                self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_cancellation_during_retry_delay_prevents_another_request(self):
        token = CancellationToken()
        client = self.client([(1, 1)])
        with (
            patch.object(client, "run_sql", side_effect=InsightsAPIError(
                "Synthetic failure", code="connection",
            )) as query,
            patch("data_processing.refunds.extract.sleep", side_effect=lambda _: token.request()),
            self.assertRaises(WorkflowCancelled),
        ):
            extract_refund_data(
                client, self.settings, transaction_template_path=self.transaction_template,
                context_template_path=self.context_template, cancellation=token,
            )
        self.assertEqual(query.call_count, 1)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_retry_wait_is_bounded_and_checks_cancellation_before_sleep(self):
        with (
            patch("data_processing.refunds.extract.perf_counter", side_effect=[0, 0, 2]),
            patch("data_processing.refunds.extract.sleep") as sleep,
        ):
            _wait_for_query_retry(2, None)
        sleep.assert_called_once_with(0.1)
        token = CancellationToken()
        token.request()
        with self.assertRaises(WorkflowCancelled):
            _wait_for_query_retry(2, token)

    def test_changed_population_cannot_enter_the_cache(self):
        client = self.client([(i + 1, 1) for i in range(4)], limit=2)
        original = client.run_sql

        def change_population(sql):
            if len(client.calls) == 1:
                client.database.execute("DELETE FROM transactions WHERE pidm = 4")
            return original(sql)

        with patch.object(client, "run_sql", side_effect=change_population):
            with self.assertRaisesRegex(RefundExtractError, "Recombined transactions batch"):
                self.extract(client)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_recombined_count_detects_membership_changes_with_same_root_total(self):
        client = self.client([(i + 1, 1) for i in range(4)], limit=2)
        original = client.run_sql

        def move_row(sql):
            if len(client.calls) == 2:
                client.database.execute("UPDATE transactions SET pidm = 5 WHERE pidm = 1")
            return original(sql)

        with patch.object(client, "run_sql", side_effect=move_row):
            with self.assertRaisesRegex(RefundExtractError, "Recombined transactions batch"):
                self.extract(client)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_original_root_guard_is_not_weakened(self):
        client = self.client([(1, 1)])
        original = client.run_sql

        def wrong_root_guard(sql):
            frame = original(sql)
            frame["extract_row_count"] = 2
            return frame

        with patch.object(client, "run_sql", side_effect=wrong_root_guard):
            with self.assertRaisesRegex(RefundExtractError, "conflicting.*row-count guards"):
                self.extract(client)
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())

    def test_missing_guard_cannot_trigger_a_retry_or_cache_write(self):
        client = self.client([(1, 1)])
        with patch.object(client, "run_sql", return_value=pd.DataFrame({"pidm": [1]})) as query:
            with self.assertRaisesRegex(ValueError, "lacks automatic-subdivision"):
                self.extract(client)
        query.assert_called_once()
        self.assertFalse((self.settings.extract_directory / "transactions_000.csv").exists())


class RefundCancellationTests(unittest.TestCase):
    def test_cancellation_before_allocation_prevents_calculation(self):
        token = CancellationToken()
        token.request()
        with patch("data_processing.refunds.allocation._allocate_account") as allocate:
            with self.assertRaises(WorkflowCancelled):
                allocate_refunds(pd.DataFrame(), pd.DataFrame(), RefundParameters("202680", date(2026, 10, 6)), cancellation=token)
        allocate.assert_not_called()

    def test_cancellation_during_export_discards_staged_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "review.xlsx"
            token = CancellationToken()

            def cancel_export(report, staged, **kwargs):
                staged.write_bytes(b"synthetic staged output")
                token.request()
                return staged

            with (
                patch("data_processing.refunds.pipeline.allocate_refunds", return_value=pd.DataFrame()),
                patch("data_processing.refunds.pipeline.export_refund_report", side_effect=cancel_export),
            ):
                with self.assertRaises(WorkflowCancelled):
                    _create_review(pd.DataFrame(), pd.DataFrame(), RefundParameters("202680", date(2026, 10, 6)), output, None, token)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_publication_preserves_output_and_rejects_late_cancellation(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "review.xlsx"
            token = CancellationToken()
            report = pd.DataFrame(columns=REPORT_COLUMNS)
            messages = []
            with patch("data_processing.refunds.pipeline.allocate_refunds", return_value=report):
                created, _ = _create_review(pd.DataFrame(), pd.DataFrame(), RefundParameters("202680", date(2026, 10, 6)), output, messages.append, token)
            self.assertEqual(created, output)
            self.assertTrue(output.exists())
            self.assertFalse(token.request())
            self.assertTrue(any("calculation completed in" in message for message in messages))
            self.assertTrue(any("workbook created in" in message for message in messages))
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_failed_export_leaves_existing_output_untouched(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "review.xlsx"
            output.write_bytes(b"existing review")

            def fail_export(report, staged, **kwargs):
                staged.write_bytes(b"incomplete")
                raise OSError("Synthetic save failure")

            with (
                patch("data_processing.refunds.pipeline.allocate_refunds", return_value=pd.DataFrame()),
                patch("data_processing.refunds.pipeline.export_refund_report", side_effect=fail_export),
            ):
                with self.assertRaises(OSError):
                    _create_review(pd.DataFrame(), pd.DataFrame(), RefundParameters("202680", date(2026, 10, 6)), output, None, CancellationToken())
            self.assertEqual(output.read_bytes(), b"existing review")
            self.assertEqual(list(Path(directory).iterdir()), [output])


class RefundExtractTests(unittest.TestCase):
    def test_older_download_schema_requires_refresh(self) -> None:
        transactions = pd.DataFrame(columns=TRANSACTION_COLUMNS)
        context = pd.DataFrame(columns=CONTEXT_COLUMNS)
        parameters = RefundParameters("209980", date(2099, 8, 31))
        with self.assertRaisesRegex(ValueError, "rerun the current refund export SQL.*non_allowable_charge_ind"):
            allocate_refunds(transactions.drop(columns="non_allowable_charge_ind"), context, parameters)
        with self.assertRaisesRegex(ValueError, "rerun the current refund export SQL.*feed_date"):
            allocate_refunds(transactions.drop(columns="feed_date"), context, parameters)
        with self.assertRaisesRegex(ValueError, "rerun the current refund export SQL.*sponsor_ids"):
            allocate_refunds(transactions, context.drop(columns="sponsor_ids"), parameters)
        with self.assertRaisesRegex(ValueError, "rerun the current refund export SQL.*student_address_review"):
            allocate_refunds(transactions, context.drop(columns="student_address_review"), parameters)

    def test_old_cache_format_cannot_resume_without_new_source_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ExtractSettings("209980", 1, root, run_date=date(2099, 8, 31), resume=True)
            (root / "extract_manifest.json").write_text(json.dumps({
                "format_version": 6, "target_term": "209980", "batch_count": 1,
                "cwid": None, "run_date": "2099-08-31",
            }))
            with self.assertRaisesRegex(ValueError, "manifest does not match"):
                read_refund_extracts(settings)

    def test_changed_non_allowable_snapshot_rejects_offline_and_resume_cache(self) -> None:
        from data_processing.refunds.extract import QUERY_DIRECTORY, _prepare_manifest

        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ExtractSettings("209980", 1, root / "cache",
                                       run_date=date(2099, 8, 31), resume=True)
            _prepare_manifest(settings)
            policy_name = "refund_non_allowable_detail_codes.sql"
            (root / "refund_student_addresses.sql").write_text(
                (QUERY_DIRECTORY / "refund_student_addresses.sql").read_text()
            )
            (root / policy_name).write_text(
                (QUERY_DIRECTORY / policy_name).read_text() + "\n/* Changed snapshot */\n"
            )
            with patch("data_processing.refunds.extract.QUERY_DIRECTORY", root):
                with self.assertRaisesRegex(ValueError, "manifest does not match"):
                    read_refund_extracts(settings)
                with self.assertRaisesRegex(ValueError, "manifest does not match"):
                    _prepare_manifest(settings)

    def test_cached_sponsor_identifiers_preserve_leading_zeroes(self) -> None:
        from data_processing.refunds.extract import _read_cached

        with TemporaryDirectory() as directory:
            path = Path(directory) / "context.csv"
            path.write_text("sponsor_names,sponsor_ids,contract_numbers\nSynthetic,00123,0001\n")
            row = _read_cached(path).iloc[0]
            self.assertEqual(row.sponsor_ids, "00123")
            self.assertEqual(row.contract_numbers, "0001")

    def test_cached_addresses_preserve_numeric_strings_and_reject_changed_policy(self):
        from data_processing.refunds.extract import QUERY_DIRECTORY, _prepare_manifest, _read_cached

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "context.csv"
            path.write_text("student_address_line1,student_address_zip\n1234,01234\n")
            row = _read_cached(path).iloc[0]
            self.assertEqual(row.student_address_line1, "1234")
            self.assertEqual(row.student_address_zip, "01234")
            settings = ExtractSettings("209980", 1, root / "cache", run_date=date(2099, 8, 31), resume=True)
            _prepare_manifest(settings)
            for name in ("refund_non_allowable_detail_codes.sql", "refund_student_addresses.sql"):
                (root / name).write_text((QUERY_DIRECTORY / name).read_text())
            with (root / "refund_student_addresses.sql").open("a") as policy:
                policy.write("\n/* changed rule */\n")
            with patch("data_processing.refunds.extract.QUERY_DIRECTORY", root):
                with self.assertRaisesRegex(ValueError, "manifest does not match"):
                    read_refund_extracts(settings)
                with self.assertRaisesRegex(ValueError, "manifest does not match"):
                    _prepare_manifest(settings)

    def test_ed_hold_end_date_cutoff_matches_all_sql_paths(self) -> None:
        root = Path(__file__).resolve().parents[2] / "query" / "AR" / "refunds"
        predicate = "CAST(h.sprhold_to_date AS date) >= DATE '2099-12-31'"
        for name in ("refund_context_extract.sql", "refund_context_manual.sql", "Refunds.sql"):
            with self.subTest(query=name):
                self.assertIn(predicate, (root / name).read_text(encoding="utf-8"))

    def test_template_is_rendered_only_from_validated_values(self) -> None:
        settings = ExtractSettings("202680", 20, Path("unused"))
        rendered = render_extract_sql(
            "WITH s AS (__REFUND_SCOPE_SQL__) SELECT __BATCH_COUNT__, __BATCH_INDEX__",
            settings,
            3,
        )
        self.assertIn("CAST('202680' AS varchar(6)) AS target_term_override", rendered)
        self.assertTrue(rendered.endswith("SELECT 20, 3"))
        with self.assertRaises(ValueError):
            ExtractSettings("202680", 1, Path("unused"), cwid="bad'value")

    def test_manual_exports_are_generated_from_api_scope_and_templates(self) -> None:
        root = Path(__file__).resolve().parents[2] / "query" / "AR" / "refunds"
        for name in ("transactions", "context"):
            template = (root / f"refund_{name}_extract.sql").read_text(encoding="utf-8")
            self.assertEqual(
                (root / f"refund_{name}_manual.sql").read_text(encoding="utf-8"),
                render_manual_extract_sql(template),
            )

    def test_filters_narrow_candidate_queries_and_history_without_changing_balances(self):
        root = Path(__file__).resolve().parents[2] / "query" / "AR" / "refunds"
        sql = render_extract_sql(
            (root / "refund_transactions_extract.sql").read_text(),
            ExtractSettings("202680", 20, Path("unused")), 0,
            pidm_range=(100, 200), transaction_range=(10, 20),
        )
        candidates, rest = sql.split("account_balances AS MATERIALIZED", 1)
        self.assertEqual(candidates.count("t.tbraccd_pidm >= 100 AND t.tbraccd_pidm <= 200"), 4)
        self.assertIn("i.spriden_pidm >= 100 AND i.spriden_pidm <= 200", candidates)
        balances, history = rest.split("s.target_term AS extract_target_term", 1)
        self.assertNotIn("t.tbraccd_tran_number >=", balances)
        self.assertIn("WHERE t.tbraccd_tran_number >= 10 AND t.tbraccd_tran_number <= 20", history)
        for bounds in (("bad", 10), (1.5, 2), (20, 10)):
            with self.subTest(bounds=bounds):
                with self.assertRaises(ValueError):
                    render_extract_sql("SELECT __PIDM_FILTER__", ExtractSettings("202680", 1, Path("unused")), 0, pidm_range=bounds)

    def test_row_count_guard_detects_api_truncation(self) -> None:
        frame = pd.DataFrame({"extract_row_count": [3, 3], "pidm": [1, 2]})
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            _validate_complete_result(frame, "transactions", 0)

    def test_invalid_or_inconsistent_row_count_guards_are_rejected(self) -> None:
        for counts in ([2, 3], [2.5, 2.5], [None, None], [-1, -1]):
            with self.subTest(counts=counts):
                with self.assertRaisesRegex(ValueError, "invalid.*guard"):
                    _validate_complete_result(pd.DataFrame({"extract_row_count": counts}), "transactions", 0)

    def test_completed_batches_are_cached_and_resumable(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def run_sql(self, sql: str) -> pd.DataFrame:
                self.calls += 1
                return pd.DataFrame({
                    "extract_row_count": [1], "extract_partition_row_count": [1],
                    "extract_pidm_min": [self.calls], "extract_pidm_max": [self.calls],
                    "extract_tran_min": [1], "extract_tran_max": [1], "pidm": [self.calls],
                })

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
            settings = ExtractSettings("202680", 2, root / "cache", run_date=date(2026, 9, 7))
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
                replace(settings, resume=True),
                transaction_template_path=transaction_template,
                context_template_path=context_template,
            )
            self.assertEqual(resumed_client.calls, 0)
            self.assertEqual(tuple(len(frame) for frame in resumed), (2, 2))
            self.assertEqual(tuple(len(frame) for frame in read_refund_extracts(settings)), (2, 2))
            next_day = replace(settings, resume=True, run_date=date(2026, 9, 8))
            with self.assertRaisesRegex(ValueError, "manifest does not match"):
                read_refund_extracts(next_day)
            with self.assertRaisesRegex(ValueError, "manifest does not match"):
                extract_refund_data(
                    resumed_client, next_day,
                    transaction_template_path=transaction_template,
                    context_template_path=context_template,
                )
            self.assertEqual(resumed_client.calls, 0)

    def test_export_keeps_report_column_order(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "refunds.xlsx"
            export_refund_report(pd.DataFrame(columns=REPORT_COLUMNS), output)
            workbook = load_workbook(output)
            self.assertEqual(workbook.sheetnames, list(REFUND_SHEETS))
            self.assertEqual(workbook.sheetnames[0], "ACH or CC Refunds")
            self.assertNotIn("Transact Refunds", workbook.sheetnames)
            self.assertNotIn("Check Refunds", workbook.sheetnames)
            self.assertNotIn("Parent Refunds", workbook.sheetnames)
            for name, color in {
                "Direct Deposit": "BDD7EE", "ACH or CC Refunds": "FFF2CC",
                "Refund by Check": "E2EFDA", "Refund to Parent": "FCE4D6",
            }.items():
                self.assertEqual(workbook[name].sheet_properties.tabColor.rgb[-6:], color)
            for sheet in workbook:
                headers = [cell.value for cell in sheet[1]]
                renamed = {
                    "cwid": "CWID", "last_name": "Last_Name", "first_name": "First_Name",
                    "tab_delivery": "Detail_Code_Delivery",
                    "tab_refund_amount": "Detail_Code_Refund_Amt",
                    "tab_review_note": "Detail_Code_Note",
                    "full_account_balance": "Current_Total_Balance",
                    "total_refund_amount": "Total_Owed_to_Student",
                    "title_iv_balance_due_note": "Title IV Refund Leaves Balance Due",
                    "student_refund_available_amount": "Student Available Now",
                    "parent_refund_available_amount": "Parent Available Now",
                    "student_clearing_reserve_amount": "Student Clearing Reserve",
                    "parent_clearing_reserve_amount": "Parent Clearing Reserve",
                    "clearing_payment_amount": "Uncleared Payment Principal",
                    "clearing_insurance_amount": "Student Insurance Reserve",
                    "clearing_payment_count": "Uncleared Payment Count",
                    "clearing_next_eligible_date": "Next Clearing Date",
                    "clearing_final_eligible_date": "Final Clearing Date",
                    "student_address_type": "Student Address Type",
                    "student_address_line1": "Student Address Line 1",
                    "student_address_line2": "Student Address Line 2",
                    "student_address_line3": "Student Address Line 3",
                    "student_address_city": "Student Address City",
                    "student_address_state": "Student Address State",
                    "student_address_zip": "Student Address ZIP",
                    "student_address_nation": "Student Address Nation",
                    "student_check_address_flag": "Student Check Address Flag",
                    "proposed_student_delivery": "Proposed_DetailCode&Amt",
                    "raw_delinquency_code": "Active RH",
                    "active_ed_ind": "Active ED",
                    "ed_activity_date": "ED Start",
                    "plus_to_student_status": "PPL to Student",
                }
                omitted = {
                    "original_payment_row_count", "deceased_ind", "deceased_date",
                    "confidential_ind", "ambiguous_source_pool_count",
                    "last_ar_activity_date", "account_control_activity_date",
                }
                third_party_headers = {
                    "sponsor_names": "Sponsor(s)", "sponsor_ids": "Sponsor ID(s)",
                    "contract_numbers": "Contract Number(s)", "third_party_current_term": "Current Term",
                    "current_term_tppy_total": "TPPY Current Term Total",
                    "current_term_z0le_total": "Z0LE Current Term Total",
                    "z0le_activity_last_7_days": "Z0LE Activity_Last 7 Days",
                }
                renamed.update(third_party_headers)
                if sheet.title != "Third Party Reviews":
                    omitted.update(third_party_headers)
                self.assertEqual(headers, [renamed.get(h, h) for h in WORKBOOK_COLUMNS
                                           if h not in omitted])
                self.assertFalse(sheet.tables)
                self.assertEqual(sheet.freeze_panes, "A2")
            workbook.close()

    def test_export_partitions_methods_and_preserves_review_accounts(self) -> None:
        def account(cwid, student=0, parent=0, delivery="NONE", **changes):
            row = dict.fromkeys(REPORT_COLUMNS)
            row.update(cwid=cwid, first_name="Synthetic", last_name="Example",
                       student_refund_amount=Decimal(str(student)), parent_refund_amount=Decimal(str(parent)),
                       student_refund_available_amount=Decimal(str(student)),
                       parent_refund_available_amount=Decimal(str(parent)),
                       student_clearing_reserve_amount=Decimal(0), parent_clearing_reserve_amount=Decimal(0),
                       total_refund_amount=Decimal(str(student)) + Decimal(str(parent)),
                       proposed_student_delivery=delivery,
                       proposed_parent_delivery="RFDP" if parent else "NONE",
                       plus_to_student_status="N" if parent else "NOT_APPLICABLE",
                       refund_hold_ind="N", fdpl_aidy_code="9900",
                       third_party_review_required_ind="N", review_status="READY_FOR_STAFF_REVIEW",
                       last_ar_activity_date=datetime(2099, 8, 31, 12, 30), fdpl_row_count=1)
            row.update(changes)
            return row

        rows = [
            account("TEST-MIX", 150, 75,
                    "AFRD (Transact) 20.00; CRVC (Transact) 30.00; RFND (CHECK) 100.00"),
            account("TEST-SMALL-MIX", 110, 5, "AFRD (Transact) 100.00; RFND (CHECK) 10.00"),
            account("TEST-BELOW-MIN", "24.99", delivery="RFND (CHECK)"),
            account("TEST-AT-MIN", 25, delivery="RFND (CHECK)"),
            account("TEST-ADDRESS", 60, delivery="RFND (CHECK)",
                    student_check_address_flag="UPDATE WORKDAY"),
            account("TEST-SMALL-CARD", 5, delivery="CRVC (Transact)"),
            account("TEST-RESERVED", 50, delivery="NONE", student_refund_available_amount=Decimal(0),
                    student_clearing_reserve_amount=Decimal(50)),
            account("TEST-FUTURE", total_refund_amount=Decimal(100),
                    student_refund_amount=None, parent_refund_amount=None,
                    review_reasons="FUTURE_TERM_ACTIVITY_EXCLUDED_FROM_ALLOCATION; FUTURE_TERM_CREDIT"),
            account("TEST-SYS", 90, delivery="ARFD (System)",
                    active_ed_ind="Y", ed_activity_date=datetime(2099, 8, 31, 12, 30),
                    review_status="WAIT_CHECK_CLEARING",
                    review_reasons="CHCK_CLEARING_WAIT_UNTIL_09/17/2099_AMOUNT_40.00"),
            account("TEST-SMALL-ED", 5, delivery="ARFD (System)", active_ed_ind="Y"),
            account("TEST-CHCK", 25, delivery="RFND (CHECK)",
                    review_status="WAIT_CHECK_CLEARING",
                    review_reasons="CHCK_CLEARING_WAIT_UNTIL_09/18/2099_AMOUNT_25.00"),
            account("TEST-WAIT", 100, delivery="ACHK Clearing Wait until 09/16/2099 / 40.00; ARFD (System) 60.00"),
            account("TEST-HOLD", 45, 5, "Refund Hold - Student",
                    proposed_parent_delivery="Refund Hold - Parent", refund_hold_ind="Y",
                    raw_delinquency_code="RH",
                    review_status="HOLD",
                    review_reasons=("REFUND_HOLD_RH; Mines Park Charge - Review; "
                                    "CHCK_CLEARING_WAIT_UNTIL_09/19/2099_AMOUNT_20.00")),
            account("TEST-OLD", 15, delivery="AFRD (Transact) - May Be Too Old"),
            account("TEST-DATE", 10, delivery="ACHK Date Review"),
            account("TEST-THIRD", 10, 20, "THIRD_PARTY_REVIEW",
                    third_party_review_required_ind="Y", proposed_parent_delivery="THIRD_PARTY_REVIEW"),
            account("TEST-HOMP", 70, delivery="ARFD (System)", review_reasons="Mines Park Charge - Review"),
            account("TEST-UNKNOWN", 80, delivery="NEW DELIVERY CODE"),
            account("TEST-BLOCKED", total_refund_amount=Decimal(25), student_refund_amount=None, parent_refund_amount=None),
            account("TEST-MISMATCH", 50, delivery="AFRD (Transact) 20.00; RFND (CHECK) 20.00"),
        ]
        expected = {
            "ACH or CC Refunds": {"TEST-MIX": 50, "TEST-SMALL-MIX": 100, "TEST-SMALL-CARD": 5},
            "Refund by Check": {"TEST-MIX": 100, "TEST-CHCK": 25, "TEST-AT-MIN": 25},
            "Check Refund < 25": {"TEST-SMALL-MIX": 10, "TEST-BELOW-MIN": 24.99},
            "Refund to Parent": {"TEST-MIX": 75, "TEST-SMALL-MIX": 5},
            "Direct Deposit": {"TEST-SYS": 90, "TEST-WAIT": 60, "TEST-SMALL-ED": 5},
            "Refund Holds": {"TEST-HOLD": 50},
            "Future Term": {"TEST-FUTURE": 100},
            "Payment Clearing": {"TEST-RESERVED": 50},
            "ACH Clearing": {"TEST-WAIT": 40},
            "ACH Reviews": {"TEST-OLD": 15, "TEST-DATE": 10},
            "Third Party Reviews": {"TEST-THIRD": 30},
            "Mines Park Reviews": {"TEST-HOMP": 70},
            "Manual Reviews": {"TEST-UNKNOWN": 80, "TEST-BLOCKED": 25, "TEST-MISMATCH": 50},
        }
        report = pd.DataFrame(rows)
        original = report.copy(deep=True)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "refunds.xlsx"
            export_refund_report(report, output)
            sheets = pd.read_excel(output, sheet_name=None)
            sheets = {name: sheet.rename(columns={
                "CWID": "cwid", "Detail_Code_Refund_Amt": "tab_refund_amount",
                "Detail_Code_Note": "tab_review_note", "Detail_Code_Delivery": "tab_delivery",
                "Total_Owed_to_Student": "total_refund_amount",
            }) for name, sheet in sheets.items()}
            for name, amounts in expected.items():
                self.assertEqual(dict(zip(sheets[name].cwid, sheets[name].tab_refund_amount)), amounts)
            self.assertEqual(sum(Decimal(str(amount)) for frame in sheets.values()
                                 for amount in frame.tab_refund_amount),
                             sum(row["total_refund_amount"] for row in rows))
            self.assertEqual(sheets["ACH or CC Refunds"].iloc[0].total_refund_amount, 225)
            self.assertTrue(sheets["Check Refund < 25"].tab_review_note.str.contains("do not issue a check").all())
            system_row = sheets["Direct Deposit"].loc[sheets["Direct Deposit"].cwid == "TEST-SYS"].iloc[0]
            self.assertEqual(system_row.review_status,
                             "WAIT_CHECK_CLEARING")
            self.assertEqual(system_row.tab_review_note,
                             "CHCK clearing wait: 40.00 becomes eligible on 09/17/2099.")
            self.assertEqual(sheets["Refund by Check"].loc[
                sheets["Refund by Check"].cwid == "TEST-CHCK", "tab_review_note"
            ].iloc[0], "CHCK clearing wait: 25.00 becomes eligible on 09/18/2099.")
            self.assertNotIn("TEST-HOLD", set(sheets["Mines Park Reviews"].cwid))
            self.assertEqual(
                sheets["Refund Holds"].iloc[0].tab_review_note,
                "RH account hold: do not issue any refund. "
                "CHCK clearing wait: 20.00 becomes eligible on 09/19/2099.",
            )
            self.assertTrue(sheets["Manual Reviews"].tab_review_note.notna().all())
            workbook = load_workbook(output)
            for sheet in workbook:
                self.assertFalse(sheet.tables)
                self.assertIn("$", sheet.cell(2, WORKBOOK_COLUMNS.index("tab_refund_amount") + 1).number_format)
                headers = [cell.value for cell in sheet[1]]
                for header in ("Current_Total_Balance", "Total_Owed_to_Student"):
                    self.assertIn("$", sheet.cell(2, headers.index(header) + 1).number_format)
                self.assertEqual(sheet.cell(2, headers.index("ED Start") + 1).number_format,
                                 "mm/dd/yyyy h:mm AM/PM")
                self.assertIn("refund_hold_ind", headers)
                self.assertIn("fdpl_aidy_code", headers)
                self.assertNotIn("plus_to_student_status", headers)
                self.assertIn("PPL to Student", headers)
                for column in ("student_refund_amount", "proposed_parent_delivery", "parent_refund_amount"):
                    self.assertIn(column, headers)
                source_rows = {row["cwid"]: row for row in rows}
                for values in sheet.iter_rows(min_row=2, values_only=True):
                    source = source_rows[values[headers.index("CWID")]]
                    for column in (
                        "student_refund_amount", "proposed_parent_delivery", "parent_refund_amount",
                        "plus_to_student_status", "refund_hold_ind", "fdpl_aidy_code",
                    ):
                        header = "PPL to Student" if column == "plus_to_student_status" else column
                        value = values[headers.index(header)]
                        if isinstance(source[column], Decimal):
                            value = Decimal(str(value))
                        self.assertEqual(value, source[column],
                                         (sheet.title, source["cwid"], column))
                for column in ("student_refund_amount", "parent_refund_amount"):
                    self.assertIn("$", sheet.cell(2, headers.index(column) + 1).number_format)
                if sheet.title == "Refund to Parent":
                    self.assertEqual(sheet.cell(2, headers.index("PPL to Student") + 1).value, "N")
                    self.assertEqual(sheet.cell(2, headers.index("student_refund_amount") + 1).value, 150)
                    self.assertEqual(sheet.cell(2, headers.index("proposed_parent_delivery") + 1).value, "RFDP")
                    self.assertEqual(sheet.cell(2, headers.index("parent_refund_amount") + 1).value, 75)
                if sheet.title == "Refund Holds":
                    self.assertEqual(sheet.cell(2, headers.index("Active RH") + 1).value, "RH")
                if sheet.title == "Direct Deposit":
                    self.assertEqual(sheet.cell(2, headers.index("CWID") + 1).value, "TEST-SYS")
                    self.assertEqual(sheet.cell(2, headers.index("Detail_Code_Delivery") + 1).value,
                                     "ARFD (Direct Deposit) 90.00")
                    self.assertEqual(sheet.cell(2, headers.index("Detail_Code_Refund_Amt") + 1).value, 90)
                    self.assertEqual(sheet.cell(2, headers.index("Proposed_DetailCode&Amt") + 1).value,
                                     "ARFD (Direct Deposit)")
                    self.assertEqual(sheet.cell(2, headers.index("Active ED") + 1).value, "Y")
                    self.assertEqual(sheet.cell(2, headers.index("ED Start") + 1).value,
                                     datetime(2099, 8, 31, 12, 30))
                for column in ("Detail_Code_Delivery", "Proposed_DetailCode&Amt"):
                    for cells in sheet.iter_cols(min_col=headers.index(column) + 1,
                                                max_col=headers.index(column) + 1, min_row=2):
                        self.assertTrue(all("(System)" not in str(cell.value) for cell in cells))
            self.assertIn("ARFD (Direct Deposit) 60.00", sheets["ACH Clearing"].iloc[0]["Proposed_DetailCode&Amt"])
            self.assertEqual(sheets["ACH or CC Refunds"].iloc[0].tab_delivery,
                             "AFRD (Transact) 20.00; CRVC (Transact) 30.00")
            workbook.close()
        pd.testing.assert_frame_equal(report, original)

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
