"""Synthetic R1 import, exact amount, FY storage and output acceptance cases."""

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.csmf_loans import run_csmf_loans
from data_processing.csmf_loans.balances import BalanceStore, balance_summary, prepare_opening_balances
from data_processing.csmf_loans.sources import (
    LOANS, opening_values, prepare_activity, project_number, read_journal, read_trial_balance,
)
from shared.cancellation import CancellationToken, WorkflowCancelled


JOURNAL_HEADERS = ["Project", "Ledger Account", "Journal Number", "Accounting Date", "Source",
                   "Line Memo", "Ledger Debit Amount", "Ledger Credit Amount"]
JULY = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
AUGUST = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)


def journal_row(account="1621", day="2026-07-15", debit=100, credit=None, project="694511", memo="Synthetic activity", journal="J-001", source="Manual Journal"):
    return [project, account + ":Synthetic account", journal, day, source, memo, debit, credit]


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Synthetic report"])
        writer.writerow(headers)
        writer.writerows(rows)


class CsmfTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "shared" / "balances"
        self.journal = self.root / "journal.csv"
        self.trial = self.root / "trial.csv"
        self.output = self.root / "review.xlsx"
        self.balance_rows = [[f"Fund: 32 Other data <br> Project: {project} Synthetic Loan", 1000 + i]
                             for i, project in enumerate(LOANS)]
        self.write_trial()
        self.write_journal([journal_row()])
        directory = patch("data_processing.csmf_loans.balances.get_shared_csmf_balances_directory", return_value=self.cache)
        directory.start(); self.addCleanup(directory.stop)

    def write_trial(self, rows=None):
        write_csv(self.trial, ["Worktags", "Debit Amount"], self.balance_rows if rows is None else rows)

    def write_journal(self, rows):
        write_csv(self.journal, JOURNAL_HEADERS, rows)

    def selection(self, now=JULY):
        return prepare_opening_balances(2027, self.trial, now=now)

    def run_workflow(self, selection=None, upload=True, cancellation=None, output=None):
        return run_csmf_loans(WorkflowContext("csmf_loans", {
            "fiscal_year": 2027, "journal_file": self.journal,
            "trial_balance_file": self.trial if upload else None,
            "output_file": output or self.output,
            **({"_opening_balances": selection} if selection is not None else {}),
        }, cancellation=cancellation))

    def workbook(self, path=None):
        book = load_workbook(path or self.output)
        self.addCleanup(book.close)
        return book

    def test_project_tags_match_exact_identifier_and_ignore_unrelated_tags(self):
        for value in ("Fund: 694511 <br> Project: 694512 Loan", "Fund: 32\nProject: 694512 Loan",
                      "<span>Project: 694512</span>"):
            self.assertEqual(project_number(value, worktags=True), "694512")
        self.assertEqual(project_number("Fund: 694511", worktags=True), "")
        self.assertEqual(project_number("Project: 6945119", worktags=True), "")
        self.assertEqual(project_number(694511.0), "694511")
        with self.assertRaisesRegex(ValueError, "More than one"):
            project_number("Project: 694511 Project: 694512")

    def test_trial_accepts_partial_projects_without_accounting_date_but_rejects_duplicates(self):
        source = read_trial_balance(self.trial)
        self.assertEqual(dict(opening_values(source))["694511"], Decimal("1000.00"))
        self.write_trial(self.balance_rows + [self.balance_rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.selection()
        self.write_trial(self.balance_rows[:-1])
        self.assertNotIn("694521", dict(opening_values(read_trial_balance(self.trial))))
        self.assertIsNone(dict(self.selection().balances.values)["694521"])
        self.assertFalse(self.cache.exists())

    def test_invalid_opening_value_is_not_silently_zero_or_rounded(self):
        for amount in ("invalid", "NaN", "1.234", "=SUM(A1)"):
            with self.subTest(amount=amount):
                self.write_trial([[self.balance_rows[0][0], amount], *self.balance_rows[1:]])
                with self.assertRaisesRegex(ValueError, "Debit Amount"):
                    self.selection()

    def test_workbook_header_detection_and_reordered_columns(self):
        path = self.root / "journal.xlsx"
        book = Workbook(); sheet = book.active
        sheet.append(["Workday"]); sheet.append(["Company: CSM"])
        sheet.append(list(reversed(JOURNAL_HEADERS)))
        sheet.append(list(reversed(journal_row())))
        book.save(path); book.close()
        activity = prepare_activity(read_journal(path), 2027)
        self.assertEqual(activity.rows[0].amount, 100)
        self.assertEqual(activity.rows[0].project, "694511")
        self.assertEqual(activity.rows[0].source_row, 4)

    def test_source_dates_sort_newest_first_and_preserve_same_date_ties_and_duplicates(self):
        self.write_journal([journal_row(day="2026-07-05", debit=20, journal="J-002"),
                            journal_row(day="2026-08-05", debit=None, credit=15),
                            journal_row(day="2026-08-05", debit=30, journal="J-002"),
                            journal_row(day="2026-08-05", debit=40),
                            journal_row(day="2026-07-05", debit=20, journal="J-002")])
        activity = prepare_activity(read_journal(self.journal), 2027)
        self.assertEqual(activity.periods, ("P01", "P02"))
        self.assertEqual([row.amount for row in activity.rows], [15, 40, 30, 20, 20])
        self.assertEqual([row.direction for row in activity.rows], ["Credit", "Debit", "Debit", "Debit", "Debit"])
        self.assertEqual([row.source_row for row in activity.rows], [4, 6, 5, 3, 7])
        self.assertTrue(all(row.section == "payment" for row in activity.rows))

    def test_loan_worksheets_show_newest_dates_first_within_each_section(self):
        rows = []
        for project in ("694511", "694516"):
            rows.extend([journal_row(project=project, day="2026-07-05", debit=100),
                         journal_row(project=project, day="2026-08-05", debit=200),
                         journal_row(project=project, account="2100", day="2026-07-02", debit=50),
                         journal_row(project=project, account="2402", day="2026-08-07", debit=None, credit=60)])
        self.write_journal(rows)
        self.run_workflow()
        book = self.workbook()
        for project in ("694511", "694516"):
            with self.subTest(project=project):
                sheet = book[f"{LOANS[project]} - {project}"]
                self.assertEqual([sheet.cell(row, 3).value.date().isoformat() for row in (10, 11, 18, 19)],
                                 ["2026-08-05", "2026-07-05", "2026-08-07", "2026-07-02"])
                self.assertEqual([sheet.cell(row, 8).value for row in (10, 11, 18, 19)], [-200, -100, 60, -50])
                self.assertEqual(sheet["A7"].value, "Beginning Balance of the FY")
                self.assertEqual(sheet["H12"].value, "=SUM(H10:H11)")
                self.assertEqual(sheet["H20"].value, "=SUM(H18:H19)")
        self.assertEqual([cell.value for cell in book["Journal Lines"]["E"]][1:], [row[3] for row in rows])

    def test_source_direction_and_original_values_are_preserved(self):
        self.write_journal([journal_row(debit=None, credit=25), journal_row(debit=-5),
                            journal_row(debit=0, credit=None)])
        self.run_workflow()
        sheet = self.workbook()["Parsons - 694511"]
        self.assertEqual([(sheet.cell(row, 6).value, sheet.cell(row, 7).value, sheet.cell(row, 8).value)
                          for row in (10, 11, 12)], [(25, "Credit", 25), (-5, "Debit", 5), (0, "Debit", 0)])

    def test_1621_source_classification_and_adjusted_signs(self):
        cases = [
            ("SIS", 100, None, "loan_activity", "Loan Disbursement", -100),
            ("SIS", None, 25, "loan_activity", "Loan Reversal", 25),
            ("SIS", -5, None, "loan_activity", "Loan Disbursement", 5),
            ("SIS", None, -7, "loan_activity", "Loan Reversal", -7),
            ("SIS", 0, None, "loan_activity", "Loan Disbursement", 0),
            ("SIS", None, 0, "loan_activity", "Loan Reversal", 0),
            (" sis ", 10, None, "loan_activity", "Loan Disbursement", -10),
            ("Journal", 10, None, "payment", "Payment", -10),
            ("Manual Journal", None, 15, "payment", "Payment", 15),
            ("Journal Import", -5, None, "payment", "Payment", 5),
            ("External JOURNAL Import", None, -7, "payment", "Payment", -7),
            ("SIS Journal", 10, None, "payment", "Payment", -10),
            ("SIS Import", 10, None, "1621", "1621 — Unclassified", -10),
            ("Manual Entry", None, 15, "1621", "1621 — Unclassified", 15),
            ("", -5, None, "1621", "1621 — Unclassified", 5),
        ]
        for source, debit, credit, section, label, adjusted in cases:
            with self.subTest(source=source, debit=debit, credit=credit):
                self.write_journal([journal_row(source=source, debit=debit, credit=credit)])
                row, = prepare_activity(read_journal(self.journal), 2027).rows
                self.assertEqual(row.section, section)
                self.assertEqual(row.label, label)
                self.assertEqual(row.adjusted_amount, Decimal(str(adjusted)))
                self.assertEqual(row.amount, Decimal(str(debit if debit is not None else credit)))
                self.assertEqual(row.direction, "Debit" if debit is not None else "Credit")
                self.assertEqual(row.source, source.strip())

    def test_other_accounts_keep_classification_and_apply_debit_credit_sign_rule(self):
        for source in ("SIS", "Manual Journal"):
            for account, section in (("2100", "payables"), ("2402", "payables"), ("2881", "2881"), ("1382", "1382"),
                                     ("5909R", "5909R"), ("8309R", "8309R"), ("9999", "other")):
                with self.subTest(source=source, account=account):
                    self.write_journal([journal_row(account=account, source=source),
                                        journal_row(account=account, source=source, debit=None, credit=-25)])
                    rows = prepare_activity(read_journal(self.journal), 2027).rows
                    self.assertEqual([row.section for row in rows], [section, section])
                    self.assertEqual([row.adjusted_amount for row in rows], [-100, -25])

    def test_every_section_and_footnote_negates_debits_and_preserves_credits(self):
        categories = [
            ("1621", "SIS"), ("1621", "Manual Journal"), ("1621", "Unknown"),
            ("2100", "Manual Journal"), ("2100", "Supplier Invoice Payment"),
            ("2402", "SIS"), ("2881", "Manual Journal"), ("1382", "SIS"), ("5909R", "SIS"),
            ("8309R", "Manual Journal"), ("9999", "Unknown"),
        ]
        cases = [(125.5, None, -125.5), (-5.25, None, 5.25), (0, None, 0),
                 (None, 125.5, 125.5), (None, -5.25, -5.25), (None, 0, 0)]
        rows = []
        expected = {}
        for account, source in categories:
            for debit, credit, adjusted in cases:
                journal = f"J-{len(rows):03d}"
                rows.append(journal_row(account=account, source=source, debit=debit, credit=credit, journal=journal))
                expected[journal] = (debit if debit is not None else credit,
                                     "Debit" if debit is not None else "Credit", adjusted)
        self.write_journal(rows)
        original = self.journal.read_bytes()
        self.run_workflow()
        saved = BalanceStore(2027).path.read_bytes()
        self.run_workflow(upload=False, output=self.root / "reuse.xlsx")
        self.assertEqual(self.journal.read_bytes(), original)
        self.assertEqual(BalanceStore(2027).path.read_bytes(), saved)
        for path in (self.output, self.root / "reuse.xlsx"):
            sheet = self.workbook(path)["Parsons - 694511"]
            details = [row for row in sheet.iter_rows(min_row=7) if row[1].value in expected]
            self.assertEqual(len(details), len(expected))
            self.assertEqual({row[1].value: (row[5].value, row[6].value, row[7].value) for row in details}, expected)
            self.assertEqual((sheet["F7"].value, sheet["H7"].value), (1000, -1000))

    def test_classified_1621_sections_sort_and_total_independently_for_every_loan(self):
        rows = []
        for project in LOANS:
            rows.extend([
                journal_row(project=project, source="SIS", debit=100, day="2026-07-15"),
                journal_row(project=project, source="SIS", debit=None, credit=25, day="2026-08-15"),
                journal_row(project=project, debit=40, day="2026-07-15"),
                journal_row(project=project, source="Journal Import", debit=None, credit=15, day="2026-08-15"),
                journal_row(project=project, source="SIS Import", debit=7, day="2026-09-15"),
            ])
        self.write_journal(rows)
        original = self.journal.read_bytes()
        result = self.run_workflow()
        self.assertIn("35 activity rows", result.message)
        self.assertIn("7 1621 rows have unclassified sources", result.message)
        saved = BalanceStore(2027).path.read_bytes()
        self.run_workflow(upload=False, output=self.root / "reuse.xlsx")
        self.assertEqual(self.journal.read_bytes(), original)
        self.assertEqual(BalanceStore(2027).path.read_bytes(), saved)
        for path in (self.output, self.root / "reuse.xlsx"):
            book = self.workbook(path)
            self.assertEqual(book["Current Month Recon"]["H2"].value, "Included periods: P01, P02, P03")
            for project, loan in LOANS.items():
                with self.subTest(workbook=path.name, project=project):
                    sheet = book[f"{loan} - {project}"]
                    self.assertEqual([sheet.cell(row, 1).value for row in (10, 11, 14, 15, 18)],
                                     ["Payment", "Payment", "Loan Reversal", "Loan Disbursement", "1621 — Unclassified"])
                    self.assertEqual([sheet.cell(row, 3).value.month for row in (10, 11, 14, 15, 18)],
                                     [8, 7, 8, 7, 9])
                    self.assertEqual([sheet.cell(row, 6).value for row in (10, 11, 14, 15, 18)], [15, 40, 25, 100, 7])
                    self.assertEqual([sheet.cell(row, 8).value for row in (10, 11, 14, 15, 18)], [15, -40, 25, -100, -7])
                    self.assertEqual([sheet.cell(row, 7).value for row in (10, 11, 14, 15, 18)],
                                     ["Credit", "Debit", "Credit", "Debit", "Debit"])
                    self.assertEqual(sheet["H12"].value, "=SUM(H10:H11)")
                    self.assertEqual(sheet["A16"].value, "Loan Activity Total")
                    self.assertEqual(sheet["H16"].value, "=SUM(H14:H15)")
                    self.assertEqual(sheet["H19"].value, "=SUM(H18:H18)")
                    for blank_row in (13, 17, 20):
                        self.assertTrue(all(cell.value is None for cell in sheet[blank_row]))
            self.assertEqual([cell.value for cell in book["Journal Lines"]["H"]][1:],
                             [str(row[6]) if row[6] is not None else None for row in rows])
            self.assertEqual([cell.value for cell in book["Journal Lines"]["F"]][1:], [row[4] for row in rows])

    def test_ambiguous_or_invalid_journal_lines_fail_without_writes(self):
        for row in (journal_row(debit=20, credit=10), journal_row(debit=None, credit=None),
                    journal_row(debit=0, credit=0), journal_row(day="bad-date"),
                    journal_row(debit="1.001"), journal_row(day="2025-08-01")):
            with self.subTest(row=row):
                self.write_journal([row])
                with self.assertRaises(ValueError):
                    self.run_workflow()
                self.assertFalse(self.output.exists())
                self.assertFalse(self.cache.exists())

    def test_account_rules_and_unknown_accounts_preserve_review_evidence(self):
        self.write_journal([journal_row(account=account, day="2026-08-15") for account in
                            ("1021", "1036", "1382", "1621", "2100", "2402", "2881", "5909R", "8309R", "9999")]
                           + [journal_row(project="999999")])
        result = self.run_workflow()
        book = self.workbook(); sheet = book["Parsons - 694511"]
        self.assertEqual(len(book["Journal Lines"]["A"]), 12)
        labels = [cell.value for cell in sheet["A"] if cell.value]
        self.assertIn("Payment", labels)
        self.assertIn("Payables — 2100", labels)
        self.assertIn("Payables — 2402", labels)
        self.assertIn("Payables (2881)", labels)
        self.assertIn("AR", labels)
        self.assertIn("1382 Totals", labels)
        self.assertIn("Other — 9999", labels)
        self.assertNotIn("Receivables", " ".join(labels))
        self.assertIn("8 activity rows", result.message)
        self.assertIn("1 rows use unmapped", result.message)
        self.assertNotIn("unclassified sources", result.message)

    def test_ar_only_upload_follows_2881_and_contributes_once_to_each_loan_total(self):
        rows = []
        for project in LOANS:
            rows.extend([
                journal_row(project=project, account="1382", source="SIS",
                            day="2026-08-01", debit=100, journal="AR-001"),
                journal_row(project=project, account="1382", source="Manual Journal",
                            day="2026-09-01", debit=None, credit=25, journal="AR-002"),
            ])
        self.write_journal(rows)
        original = self.journal.read_bytes()
        activity = prepare_activity(read_journal(self.journal), 2027)
        self.assertEqual(len(activity.rows), 14)
        self.assertEqual(activity.other_account_count, 0)
        self.assertTrue(all(row.section == "1382" and row.label == "AR" and not row.prior_year_activity
                            for row in activity.rows))
        result = self.run_workflow()
        self.assertIn("14 activity rows", result.message)
        self.assertEqual(self.journal.read_bytes(), original)
        book = self.workbook()
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                self.assertEqual(sheet["A18"].value, "Payables (2881) Total")
                self.assertEqual(sheet["H18"].value, 0)
                self.assertEqual([sheet.cell(row, 1).value for row in (20, 21)], ["AR", "AR"])
                self.assertEqual([sheet.cell(row, 2).value for row in (20, 21)], ["AR-002", "AR-001"])
                self.assertEqual([sheet.cell(row, 3).value.month for row in (20, 21)], [9, 8])
                self.assertEqual([(sheet.cell(row, 6).value, sheet.cell(row, 7).value, sheet.cell(row, 8).value)
                                  for row in (20, 21)], [(25, "Credit", 25), (100, "Debit", -100)])
                self.assertEqual(sheet["A22"].value, "1382 Totals")
                self.assertEqual(sheet["H22"].value, "=SUM(H20:H21)")
                self.assertEqual(sheet["A24"].value, "Interest on loans Total")
                self.assertEqual(sheet["A28"].value, "Loan Total")
                self.assertEqual(sheet["H28"].value, "=SUM(H8,H10,H12,H14,H16,H18,H22,H24,H26)")
                self.assertTrue(all(cell.value is None for row in (19, 23) for cell in sheet[row]))
        source = book["Journal Lines"]
        self.assertEqual([cell.value for cell in source["D"]][1:], [row[2] for row in rows])
        self.assertTrue(all(cell.value == "Included" for cell in list(source["J"])[1:]))

    def test_zero_two_and_five_rows_place_totals_and_next_section_correctly(self):
        for count, total_row, next_row in ((0, 10, 12), (2, 12, 14), (5, 15, 17)):
            with self.subTest(count=count):
                self.write_journal([journal_row() for _ in range(count)] + [journal_row(account="2100")])
                output = self.root / f"count-{count}.xlsx"
                self.run_workflow(output=output)
                sheet = self.workbook(output)["Parsons - 694511"]
                self.assertEqual(sheet.cell(total_row, 1).value, "Payment Total")
                self.assertEqual(sheet.cell(next_row, 1).value, "Loan Activity Total")
                self.assertEqual(sheet.cell(next_row, 8).value, 0)
                self.assertEqual(sheet.cell(next_row + 2, 1).value, "1621 — Unclassified Total")
                self.assertEqual(sheet.cell(next_row + 2, 8).value, 0)
                self.assertEqual(sheet.cell(next_row + 4, 1).value, "Payables — 2100")
                self.assertEqual(sheet.cell(total_row, 8).value,
                                 f"=SUM(H10:H{total_row - 1})" if count else 0)
                self.assertEqual(sheet["H8"].value, '=IF(COUNT(H7)=0,"",SUM(H7:H7))')
                self.assertIsNone(sheet.cell(total_row + 1, 1).value)
                self.assertEqual(sheet.cell(sheet.max_row, 1).value, "Loan Total")
                self.assertEqual(sheet.cell(sheet.max_row, 8).value,
                                 f"=SUM(H8,H{total_row},H{next_row},H{next_row + 2},"
                                 f"H{next_row + 5},H{next_row + 7},H{next_row + 9},H{next_row + 11},H{next_row + 13})")

    def test_loan_total_includes_opening_and_all_sections_without_counting_details_twice(self):
        self.write_journal([
            journal_row(debit=100), journal_row(debit=None, credit=20),
            journal_row(source="SIS", debit=80), journal_row(source="SIS", debit=None, credit=10),
            journal_row(source="Unknown", debit=3),
            journal_row(account="2100", debit=40), journal_row(account="2402", debit=None, credit=40),
            journal_row(account="2881", debit=9), journal_row(account="1382", debit=8, day="2026-08-15"),
            journal_row(account="5909R", debit=2),
            journal_row(account="8309R", debit=1), journal_row(account="9999", debit=7),
        ])
        self.run_workflow()
        book = self.workbook()
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                if project == "694511":
                    total_row = 40
                    formula = "=SUM(H8,H12,H16,H19,H23,H26,H29,H32,H35,H38)"
                    self.assertEqual(sheet["A29"].value, "1382 Totals")
                    self.assertEqual(sheet["A38"].value, "Other ledger activity — review Total")
                else:
                    total_row = 26
                    formula = "=SUM(H8,H10,H12,H14,H16,H18,H20,H22,H24)"
                    self.assertEqual(sheet["A20"].value, "1382 Totals")
                    self.assertEqual(sheet["H20"].value, 0)
                self.assertEqual(sheet.max_row, total_row)
                self.assertEqual(sheet.cell(total_row, 1).value, "Loan Total")
                self.assertEqual(sheet.cell(total_row, 8).value, formula)
                self.assertEqual(sheet.cell(total_row, 8).data_type, "f")
                self.assertTrue(sheet.cell(total_row, 8).font.bold)
                self.assertEqual(sheet.cell(total_row, 8).number_format, sheet["H8"].number_format)
                self.assertTrue(all(cell.value is None for cell in sheet[total_row - 1]))
                self.assertTrue(all(sheet.cell(total_row, column).value is None for column in range(2, 8)))

    def test_loan_total_keeps_blank_and_zero_opening_balances_distinct(self):
        self.write_trial([[self.balance_rows[0][0], 0]])
        self.write_journal([journal_row(project="694516", debit=None, credit=75)])
        self.run_workflow()
        book = self.workbook()
        bruce = book["Bruce - 694516"]
        self.assertIsNone(bruce["H7"].value)
        self.assertEqual(bruce["H8"].value, '=IF(COUNT(H7)=0,"",SUM(H7:H7))')
        self.assertEqual(bruce["H11"].value, "=SUM(H10:H10)")
        self.assertEqual(bruce["H27"].value, "=SUM(H8,H11,H13,H15,H17,H19,H21,H23,H25)")
        for project in ("694511", "694512"):
            sheet = book[f"{LOANS[project]} - {project}"]
            self.assertEqual(sheet["H7"].value, 0 if project == "694511" else None)
            self.assertEqual(sheet["H26"].value, "=SUM(H8,H10,H12,H14,H16,H18,H20,H22,H24)")

    def test_prior_year_payment_requires_exact_account_source_and_opening_july_cutoff(self):
        source_name = "Supplier Invoice Payment"
        cases = [
            (2027, "2100", source_name, "2026-07-01", True),
            (2027, "2100", source_name, "2026-07-31", True),
            (2027, "2100", " supplier invoice payment ", "2026-07-15", True),
            (2027, "2100", source_name, "2026-08-01", False),
            (2027, "2100", source_name, "2027-06-30", False),
            (2028, "2100", source_name, "2027-07-31", True),
            (2028, "2100", source_name, "2027-08-01", False),
            (2027, "2402", source_name, "2026-07-31", False),
            (2027, "1621", source_name, "2026-07-31", False),
            (2027, "2100", "Supplier Invoice Payment Adjustment", "2026-07-31", False),
            (2027, "2100", "Manual Journal", "2026-07-31", False),
            (2027, "2100", "", "2026-07-31", False),
        ]
        for year, account, source, day, expected in cases:
            with self.subTest(year=year, account=account, source=source, day=day):
                self.write_journal([journal_row(account=account, source=source, day=day)])
                activity = prepare_activity(read_journal(self.journal), year)
                row, = activity.rows
                self.assertEqual(row.prior_year_activity, expected)
                self.assertEqual(row.amount, 100)
                self.assertEqual(row.adjusted_amount, -100)
                if expected:
                    self.assertEqual(row.section, "payables")
                    self.assertIn("excluded from activity totals", activity.source.dispositions[row.source_row])
        for day in ("2026-06-30", "2027-07-01", "2027-07-31"):
            with self.subTest(outside_fy=day):
                self.write_journal([journal_row(account="2100", source=source_name, day=day)])
                with self.assertRaisesRegex(ValueError, "not selected FY2027"):
                    prepare_activity(read_journal(self.journal), 2027)

    def test_prior_year_payments_move_below_loan_total_and_are_excluded_from_both_totals(self):
        rows = []
        for project in ("694511", "694516"):
            rows.extend([
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-07-01", debit=100, journal="PY-001"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-08-01", debit=40, journal="CURRENT-001"),
                journal_row(project=project, account="2402", source="Supplier Invoice Payment",
                            day="2026-07-15", debit=30, journal="CURRENT-002"),
                journal_row(project=project, account="2100", day="2026-07-15", debit=20, journal="CURRENT-003"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-07-31", debit=None, credit=-25, journal="PY-002"),
            ])
        self.write_journal(rows)
        original = self.journal.read_bytes()
        self.run_workflow()
        book = self.workbook()
        self.assertEqual(self.journal.read_bytes(), original)
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                if project not in {"694511", "694516"}:
                    self.assertEqual(sheet.max_row, 26)
                    self.assertEqual(sheet["A26"].value, "Loan Total")
                    continue
                self.assertEqual(sheet["A19"].value, "Payables (2100/2402) Total")
                self.assertEqual(sheet["H19"].value, "=SUM(H16:H18)")
                self.assertEqual([sheet.cell(row, 8).value for row in (16, 17, 18)], [-40, -30, -20])
                self.assertEqual(sheet["A29"].value, "Loan Total")
                self.assertEqual(sheet["H29"].value, "=SUM(H8,H10,H12,H14,H19,H21,H23,H25,H27)")
                self.assertTrue(all(cell.value is None for cell in sheet[30]))
                self.assertEqual(sheet["A31"].value,
                                 "Footnote* — Payment of a prior fiscal year obligation recorded in the current fiscal year.")
                self.assertIn("A31:H31", sheet.merged_cells)
                self.assertTrue(sheet["A31"].font.italic)
                self.assertEqual(sheet.max_row, 33)
                self.assertEqual([sheet.cell(row, 1).value for row in (32, 33)], ["Payables — 2100*", "Payables — 2100*"])
                self.assertEqual([sheet.cell(row, 2).value for row in (32, 33)], ["PY-002", "PY-001"])
                self.assertEqual([sheet.cell(row, 3).value.day for row in (32, 33)], [31, 1])
                self.assertEqual([(sheet.cell(row, 6).value, sheet.cell(row, 7).value, sheet.cell(row, 8).value)
                                  for row in (32, 33)], [(-25, "Credit", -25), (100, "Debit", -100)])
                journals = [cell.value for cell in sheet["B"] if cell.row >= 7 and cell.value]
                self.assertEqual(sorted(journals), ["CURRENT-001", "CURRENT-002", "CURRENT-003", "PY-001", "PY-002"])
        source = book["Journal Lines"]
        self.assertEqual([cell.value for cell in source["D"]][1:], [row[2] for row in rows])
        self.assertEqual(sum("excluded from activity totals" in str(cell.value) for cell in source["J"]), 4)
        self.assertEqual(book["Current Month Recon"]["N7"].value, "Pending")

    def test_prior_year_ar_uses_inclusive_opening_july_cutoff_for_every_source(self):
        for year in (2027, 2028):
            for source_name in ("SIS", "Manual Journal", "Supplier Invoice Payment", ""):
                for day, expected in ((f"{year - 1}-07-01", True), (f"{year - 1}-07-31", True),
                                      (f"{year - 1}-08-01", False), (f"{year}-06-30", False)):
                    with self.subTest(year=year, source=source_name, day=day):
                        self.write_journal([journal_row(account="1382", source=source_name, day=day)])
                        activity = prepare_activity(read_journal(self.journal), year)
                        row, = activity.rows
                        self.assertEqual(row.prior_year_activity, expected)
                        self.assertEqual((row.section, row.label, row.amount, row.adjusted_amount),
                                         ("1382", "AR", 100, -100))
                        status = activity.source.dispositions[row.source_row]
                        if expected:
                            self.assertEqual(status, "Footnote; prior fiscal year accounts receivable activity excluded from activity totals")
                        else:
                            self.assertEqual(status, "Included")
        for day in ("2026-06-30", "2027-07-01"):
            with self.subTest(outside_fy=day):
                self.write_journal([journal_row(account="1382", day=day)])
                with self.assertRaisesRegex(ValueError, "not selected FY2027"):
                    prepare_activity(read_journal(self.journal), 2027)

    def test_ar_and_payable_footnotes_are_separate_and_excluded_from_current_totals(self):
        rows = []
        for project in LOANS:
            rows.extend([
                journal_row(project=project, account="1382", source="SIS", day="2026-07-01", debit=80, journal="AR-PRIOR-001"),
                journal_row(project=project, account="1382", source="", day="2026-07-31", debit=None, credit=10, journal="AR-PRIOR-002"),
                journal_row(project=project, account="1382", day="2026-08-01", debit=100, journal="AR-CURRENT-001"),
                journal_row(project=project, account="1382", day="2026-09-01", debit=None, credit=25, journal="AR-CURRENT-002"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment", day="2026-07-31", debit=None, credit=30, journal="PAY-PRIOR"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment", day="2026-08-01", debit=20, journal="PAY-CURRENT"),
                journal_row(project=project, account="2100", day="2026-07-15", debit=5, journal="PAY-MANUAL"),
            ])
        self.write_journal(rows)
        original = self.journal.read_bytes()
        self.run_workflow()
        self.assertEqual(self.journal.read_bytes(), original)
        book = self.workbook()
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                self.assertEqual(sheet["H18"].value, "=SUM(H16:H17)")
                self.assertEqual(sheet["A20"].value, "Payables (2881) Total")
                self.assertEqual([sheet.cell(row, 1).value for row in (22, 23)], ["AR", "AR"])
                self.assertEqual(sheet["A24"].value, "1382 Totals")
                self.assertEqual(sheet["H24"].value, "=SUM(H22:H23)")
                self.assertEqual([sheet.cell(row, 8).value for row in (22, 23)], [25, -100])
                self.assertEqual(sheet["A30"].value, "Loan Total")
                self.assertEqual(sheet["H30"].value, "=SUM(H8,H10,H12,H14,H18,H20,H24,H26,H28)")
                self.assertEqual(sheet["A32"].value,
                                 "Footnote* — Payment of a prior fiscal year obligation recorded in the current fiscal year.")
                self.assertEqual(sheet["A33"].value, "Payables — 2100*")
                self.assertEqual(sheet["A35"].value,
                                 "Footnote** — Prior fiscal year accounts receivable activity recorded in the current fiscal year.")
                self.assertEqual([sheet.cell(row, 1).value for row in (36, 37)], ["AR**", "AR**"])
                self.assertEqual([sheet.cell(row, 3).value.day for row in (36, 37)], [31, 1])
                self.assertEqual([(sheet.cell(row, 6).value, sheet.cell(row, 7).value, sheet.cell(row, 8).value)
                                  for row in (33, 36, 37)], [(30, "Credit", 30), (10, "Credit", 10), (80, "Debit", -80)])
                self.assertEqual(sheet.max_row, 37)
                for heading in (32, 35):
                    self.assertIn(f"A{heading}:H{heading}", sheet.merged_cells)
                    self.assertTrue(sheet.cell(heading, 1).font.italic)
                    self.assertTrue(all(cell.value is None for cell in sheet[heading - 1]))
                journals = [cell.value for cell in sheet["B"] if cell.row >= 7 and cell.value]
                self.assertEqual(sorted(journals), sorted(row[2] for row in rows if row[0] == project))
                self.assertNotIn("AR Total", [cell.value for cell in sheet["A"]])
        statuses = [cell.value for cell in list(book["Journal Lines"]["J"])[1:]]
        self.assertEqual(sum("accounts receivable activity excluded" in status for status in statuses), 14)
        self.assertEqual(sum("payment excluded" in status for status in statuses), 7)

    def test_ar_only_footnotes_leave_1382_totals_zero_and_preserve_ties(self):
        rows = []
        for project in LOANS:
            rows.extend([
                journal_row(project=project, account="1382", source="SIS", day="2026-07-31", debit=25, journal="AR-002"),
                journal_row(project=project, account="1382", source="", day="2026-07-31", debit=0, journal="AR-001"),
                journal_row(project=project, account="1382", day="2026-07-31", debit=50, journal="AR-001"),
            ])
        self.write_journal(rows)
        self.run_workflow()
        book = self.workbook()
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                self.assertEqual(sheet["A20"].value, "1382 Totals")
                self.assertEqual(sheet["H20"].value, 0)
                self.assertEqual(sheet["A26"].value, "Loan Total")
                self.assertEqual(sheet["H26"].value, "=SUM(H8,H10,H12,H14,H16,H18,H20,H22,H24)")
                self.assertEqual(sheet["A28"].value,
                                 "Footnote** — Prior fiscal year accounts receivable activity recorded in the current fiscal year.")
                self.assertEqual(sheet.max_row, 31)
                self.assertEqual([sheet.cell(row, 8).value for row in (29, 30, 31)], [0, -50, -25])

    def test_all_footnoted_activity_keeps_payables_zero_and_loan_total_at_opening_balance(self):
        rows = []
        for project in LOANS:
            rows.extend([
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-07-31", debit=25, journal="PY-002"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-07-31", debit=0, journal="PY-001"),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment",
                            day="2026-07-31", debit=50, journal="PY-001"),
            ])
        self.write_journal(rows)
        self.run_workflow()
        book = self.workbook()
        for project, loan in LOANS.items():
            with self.subTest(project=project):
                sheet = book[f"{loan} - {project}"]
                self.assertEqual(sheet["A16"].value, "Payables (2100/2402) Total")
                self.assertEqual(sheet["H16"].value, 0)
                self.assertEqual(sheet["A26"].value, "Loan Total")
                self.assertEqual(sheet["H26"].value, "=SUM(H8,H10,H12,H14,H16,H18,H20,H22,H24)")
                self.assertEqual(sheet.max_row, 31)
                self.assertEqual([sheet.cell(row, 8).value for row in (29, 30, 31)], [0, -50, -25])

    def test_seven_loan_tabs_current_month_recon_and_literal_source_text(self):
        self.write_journal([journal_row(memo='=HYPERLINK("https://invalid.example")')])
        self.run_workflow()
        book = self.workbook()
        self.assertEqual(book.sheetnames[:8], ["Current Month Recon", *(f"{name} - {project}" for project, name in LOANS.items())])
        self.assertEqual(book.active.title, "Current Month Recon")
        self.assertEqual(book["Parsons - 694511"]["E10"].data_type, "s")
        self.assertEqual(book["Journal Lines"]["G2"].data_type, "s")
        self.assertIn("0.00", book["Parsons - 694511"]["F10"].number_format)
        self.assertEqual(book["Combined - 694512"]["H7"].value, -1001)

    def test_current_month_recon_links_dynamic_subtotals_for_all_uploaded_periods(self):
        rows = []
        for index, project in enumerate(LOANS):
            rows.extend([
                journal_row(project=project, source="SIS", day="2026-07-15", debit=100),
                journal_row(project=project, source="SIS", day="2026-09-15", debit=None, credit=25),
                journal_row(project=project, source="Unknown", day="2026-09-15", debit=3),
                journal_row(project=project, day="2026-07-15", debit=None, credit=40),
                journal_row(project=project, account="5909R", day="2026-07-15", debit=None, credit=10),
                journal_row(project=project, account="8309R", day="2026-09-15", debit=2),
                journal_row(project=project, account="2100", day="2026-09-15", debit=5),
                journal_row(project=project, account="2402", day="2026-09-15", debit=None, credit=5),
                journal_row(project=project, account="2881", day="2026-09-15", debit=None, credit=7),
                journal_row(project=project, account="1382", day="2026-09-15", debit=None, credit=11),
                journal_row(project=project, account="9999", day="2026-09-15", debit=4),
                journal_row(project=project, account="2100", source="Supplier Invoice Payment", day="2026-07-31", debit=800),
                journal_row(project=project, account="1382", day="2026-07-31", debit=900),
            ])
            # Distinct row counts move each loan's subtotals independently.
            rows.extend(journal_row(project=project, day="2026-09-15", debit=None, credit=1)
                        for _ in range(index))
        self.write_journal(rows)
        original = self.journal.read_bytes()
        result = self.run_workflow()
        self.assertIn("AP, AR and variance calculations remain pending", result.message)
        self.assertEqual(self.journal.read_bytes(), original)
        book = self.workbook()
        summary = book["Current Month Recon"]
        self.assertEqual(summary["A2"].value, "FY2027 — All uploaded activity")
        self.assertEqual(summary["H2"].value, "Included periods: P01, P03")
        self.assertEqual(summary["E6"].value, "1621\nUnclassified")
        self.assertEqual(summary["J6"].value, "Interest\n5909R")
        self.assertEqual(summary["K6"].value, "Late Fees\n8309R")
        expected_projects = ("694511", "694512", "694513", "694514", "694518", "694521", "694516")
        for row, project in enumerate(expected_projects, 7):
            with self.subTest(project=project):
                loan = book[f"{LOANS[project]} - {project}"]
                total_cells = {cell.value: f"H{cell.row}" for cell in loan["A"]
                               if isinstance(cell.value, str) and cell.value.endswith("Total")}
                self.assertEqual(summary.cell(row, 1).value, LOANS[project].upper())
                self.assertEqual(summary.cell(row, 3).value, project)
                for column, label in ((5, "1621 — Unclassified Total"), (6, "Loan Activity Total"),
                                      (7, "Payment Total"), (10, "Interest on loans Total"),
                                      (11, "Late fees on loans Total")):
                    self.assertEqual(summary.cell(row, column).value, f"='{loan.title}'!{total_cells[label]}")
                self.assertEqual(summary.cell(row, 4).value, f'=IF(\'{loan.title}\'!H8="","",\'{loan.title}\'!H8)')
                self.assertEqual(summary.cell(row, 8).value, f"=SUM(E{row}:G{row})")
                self.assertEqual(summary.cell(row, 12).value, f"=SUM(J{row}:K{row})")
                self.assertEqual(summary.cell(row + 13, 5).value, f"='{loan.title}'!{total_cells['Loan Total']}")
                self.assertEqual(summary.cell(row, 14).value, "Pending")
                self.assertEqual(summary.cell(row, 16).value, "Pending")
                self.assertEqual(summary.cell(row + 13, 6).value, "Pending")
                self.assertIsNone(summary.cell(row + 13, 4).value)
                self.assertIsNone(summary.cell(row + 13, 7).value)
        self.assertEqual(summary["D14"].value, '=IF(COUNT(D7:D13)=7,SUM(D7:D13),"Pending")')
        self.assertEqual(summary["E27"].value, "=SUM(E20:E26)")
        self.assertEqual([summary[cell].value for cell in ("N14", "P14", "D27", "F27")], ["Pending"] * 4)
        self.assertEqual([summary[cell].value for cell in ("C32", "C33", "C34", "C35")], [None] * 4)
        self.assertEqual(summary["C33"].number_format, "mm/dd/yyyy")
        self.assertEqual(summary.page_setup.orientation, "landscape")
        self.assertIn("$A$1:$P$35", str(summary.print_area))
        self.assertTrue({"A1:P1", "A5:H5", "J5:L5", "A18:L18", "A31:D31"}.issubset(
            {str(region) for region in summary.merged_cells}))
        all_text = " ".join(str(cell.value) for row in summary for cell in row if cell.value is not None)
        for obsolete in ("Banner", "Acct 4580", "Acct 4511", "'A 4580'", "'A 4511'", "[1]", "-1360", "-1365"):
            self.assertNotIn(obsolete, all_text)

    def test_current_month_recon_retains_unisa_identifiers_in_both_sections(self):
        self.run_workflow()
        summary = self.workbook()["Current Month Recon"]
        self.assertEqual(summary["B6"].value, "Unisa\nAcct")
        self.assertEqual(summary["B19"].value, "Unisa\nAcct")
        expected = [("694511", "6304"), ("694512", "6308"), ("694513", "6309"),
                    ("694514", "6311"), ("694518", "6313"), ("694521", "6315"), ("694516", None)]
        for row, (project, account) in enumerate(expected, 7):
            with self.subTest(project=project):
                self.assertEqual(summary.cell(row, 3).value, project)
                self.assertEqual(summary.cell(row, 2).value, account)
                self.assertEqual(summary.cell(row + 13, 2).value, f'=IF(B{row}="","",B{row})')
                for visible_row in (row, row + 13, 6, 19):
                    self.assertNotIn(f"B{visible_row}", summary.merged_cells)
        self.assertIsNone(summary["B13"].value)

    def test_current_month_recon_preserves_blank_openings_and_zero_activity_sections(self):
        self.write_trial([["Project: 694511 Parsons", 0], ["Project: 694516 Bruce", None]])
        self.write_journal([journal_row(project="694516", account="1382", day="2026-07-31")])
        self.run_workflow()
        book = self.workbook()
        summary = book["Current Month Recon"]
        for row in range(7, 14):
            project = summary.cell(row, 3).value
            loan = book[f"{LOANS[project]} - {project}"]
            self.assertEqual(loan["H7"].value, 0 if project == "694511" else None)
            self.assertEqual(summary.cell(row, 4).value, f'=IF(\'{loan.title}\'!H8="","",\'{loan.title}\'!H8)')
            for column in (5, 6, 7, 10, 11):
                formula = summary.cell(row, column).value
                target = formula.rsplit("!", 1)[1]
                self.assertEqual(loan[target].value, 0)
        self.assertIn("Blank beginning balances remain unknown", summary["A29"].value)

    def test_current_month_recon_uses_selected_fy_and_all_twelve_periods(self):
        from dataclasses import replace
        from data_processing.csmf_loans.export import build_workbook

        self.write_journal([journal_row(day=f"{2027 if month >= 7 else 2028}-{month:02d}-15")
                            for month in range(1, 13)])
        activity = prepare_activity(read_journal(self.journal), 2028)
        book = build_workbook(activity, replace(self.selection().balances, fiscal_year=2028), app_version="test")
        self.addCleanup(book.close)
        summary = book["Current Month Recon"]
        self.assertEqual(summary["A2"].value, "FY2028 — All uploaded activity")
        self.assertEqual(summary["H2"].value, "Included periods: " + ", ".join(f"P{i:02d}" for i in range(1, 13)))
        self.assertEqual(summary["F6"].value, "FY2028\nLoan Activity (Net)")
        self.assertEqual(summary["G6"].value, "FY2028\nPayments")

    def test_beginning_adjusted_amount_flips_sign_without_changing_saved_or_source_values(self):
        cases = [(1000, -1000), (-25, 25), (0, 0), (None, None),
                 (250, -250), (-500, 500), (123.45, -123.45)]
        for row, (amount, _) in zip(self.balance_rows, cases):
            row[1] = amount
        self.write_trial()
        self.run_workflow(self.selection())
        store = BalanceStore(2027); saved, _ = store.load(); raw = store.path.read_bytes()
        self.run_workflow(upload=False, output=self.root / "reuse.xlsx")
        self.assertEqual(store.path.read_bytes(), raw)
        for path in (self.output, self.root / "reuse.xlsx"):
            book = self.workbook(path)
            for row_number, ((project, loan), (amount, adjusted)) in enumerate(zip(LOANS.items(), cases), 2):
                with self.subTest(workbook=path.name, project=project):
                    sheet = book[f"{loan} - {project}"]
                    self.assertEqual(sheet["F7"].value, amount)
                    self.assertEqual(sheet["G7"].value, "Debit" if amount is not None else None)
                    self.assertEqual(sheet["H7"].value, adjusted)
                    self.assertEqual(sheet["H8"].value, '=IF(COUNT(H7)=0,"",SUM(H7:H7))')
                    self.assertEqual(book["Opening Balances"].cell(row_number, 4).value, amount)
                    self.assertEqual(dict(saved.values)[project], Decimal(str(amount)) if amount is not None else None)
            self.assertEqual(book["Parsons - 694511"]["H10"].value, -100)
        trial = self.workbook()["Trial Balance"]
        self.assertEqual([trial.cell(row_number, 3).value for row_number in range(2, 9)],
                         [str(amount) if amount is not None else None for amount, _ in cases])

    def test_first_use_requires_trial_and_preview_does_not_write(self):
        with self.assertRaisesRegex(ValueError, "Upload Trial Balance"):
            prepare_opening_balances(2027)
        selection = self.selection()
        self.assertIn("2026-07-10", balance_summary(selection))
        self.assertIn("$1,000.00", balance_summary(selection))
        self.assertFalse(self.cache.exists())

    def test_july_upload_august_reuse_preserves_exact_cache_and_date(self):
        self.run_workflow(self.selection())
        store = BalanceStore(2027)
        raw = store.path.read_bytes(); mtime = store.path.stat().st_mtime_ns
        selection = prepare_opening_balances(2027, now=AUGUST)
        self.assertIn("2026-07-10", selection.balances.updated_at)
        self.run_workflow(selection, upload=False, output=self.root / "august.xlsx")
        self.assertEqual(store.path.read_bytes(), raw)
        self.assertEqual(store.path.stat().st_mtime_ns, mtime)
        self.assertIn("2026-07-10", self.workbook(self.root / "august.xlsx")["Opening Balances"]["E2"].value)

    def test_replacement_updates_date_and_values_preserves_other_year_and_backup(self):
        self.run_workflow(self.selection())
        store = BalanceStore(2027); old = store.path.read_bytes()
        other = self.cache / "FY2026.json"; other.write_text("other FY remains untouched")
        self.balance_rows[0][1] = 1500; self.write_trial()
        self.run_workflow(self.selection(AUGUST), output=self.root / "replacement.xlsx")
        saved, _ = store.load()
        self.assertEqual(dict(saved.values)["694511"], 1500)
        self.assertIn("2026-08-10", saved.updated_at)
        self.assertEqual(store.path.with_suffix(".backup.json").read_bytes(), old)
        self.assertEqual(other.read_text(), "other FY remains untouched")

    def test_bad_replacement_preserves_saved_values(self):
        self.run_workflow(self.selection()); store = BalanceStore(2027)
        old = store.path.read_bytes()
        self.write_trial([[self.balance_rows[0][0], "invalid"]])
        with self.assertRaises(ValueError):
            self.run_workflow(output=self.root / "bad.xlsx")
        self.assertEqual(store.path.read_bytes(), old)
        self.assertFalse((self.root / "bad.xlsx").exists())

    def test_stale_preview_and_changed_upload_cannot_publish(self):
        stale = self.selection()
        self.run_workflow(self.selection())
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            self.run_workflow(stale, output=self.root / "stale.xlsx")
        current = self.selection(); self.balance_rows[0][1] = 999; self.write_trial()
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            self.run_workflow(current, output=self.root / "changed.xlsx")
        self.assertFalse((self.root / "stale.xlsx").exists())
        self.assertFalse((self.root / "changed.xlsx").exists())

    def test_existing_output_cancel_and_cache_failure_preserve_sources(self):
        originals = (self.journal.read_bytes(), self.trial.read_bytes())
        self.output.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            self.run_workflow()
        self.assertEqual(self.output.read_bytes(), b"existing")
        token = CancellationToken(); token.request()
        with self.assertRaises(WorkflowCancelled):
            self.run_workflow(cancellation=token, output=self.root / "cancel.xlsx")
        with patch.object(BalanceStore, "save_locked", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.run_workflow(output=self.root / "failed.xlsx")
        self.assertFalse((self.root / "failed.xlsx").exists())
        self.assertFalse(BalanceStore(2027).path.exists())
        self.assertEqual(originals, (self.journal.read_bytes(), self.trial.read_bytes()))

    def test_cache_atomic_failure_keeps_previous_file(self):
        self.run_workflow(self.selection()); store = BalanceStore(2027); old = store.path.read_bytes()
        self.write_trial([[self.balance_rows[0][0], 1500]])
        selection = self.selection(AUGUST)
        with patch("data_processing.csmf_loans.balances.os.replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.run_workflow(selection, output=self.root / "failed.xlsx")
        self.assertEqual(store.path.read_bytes(), old)
        self.assertFalse((self.root / "failed.xlsx").exists())
        self.assertEqual(list(self.cache.glob("*.lock")), [])
        self.assertEqual(list(self.cache.glob("*.tmp")), [])

    def test_invalid_saved_balance_payload_does_not_fall_back(self):
        self.run_workflow(self.selection()); store = BalanceStore(2027)
        payload = json.loads(store.path.read_text()); payload["balances"].pop("694511")
        store.path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "Saved FY2027"):
            prepare_opening_balances(2027)

    def test_no_prod_mode_can_be_selected(self):
        with self.assertRaisesRegex(ValueError, "do not use TEST or PROD"):
            run_csmf_loans(WorkflowContext("csmf_loans", {}, WorkflowMode.PRODUCTION))

    def test_missing_bruce_opening_balance_keeps_tab_and_collection_activity(self):
        self.write_trial([row for row in self.balance_rows if "694516" not in row[0]])
        self.write_journal([journal_row(project="694516", debit=None, credit=75)])
        self.run_workflow(self.selection())
        book = self.workbook(); sheet = book["Bruce - 694516"]
        self.assertEqual(len(book.sheetnames[:8]), 8)
        for cell in ("F7", "G7", "H7"):
            self.assertIsNone(sheet[cell].value)
        self.assertEqual(sheet["H8"].value, '=IF(COUNT(H7)=0,"",SUM(H7:H7))')
        self.assertEqual((sheet["F10"].value, sheet["G10"].value, sheet["H10"].value), (75, "Credit", 75))
        self.assertIsNone(book["Opening Balances"]["D6"].value)
        self.assertIsNone(book["Opening Balances"]["E6"].value)
        payload = json.loads(BalanceStore(2027).path.read_text())
        self.assertIsNone(payload["balances"]["694516"]["amount"])
        self.assertIsNone(payload["balances"]["694516"]["updated_at"])
        self.assertIn("694516 · Bruce: Blank", balance_summary(prepare_opening_balances(2027)))

    def test_first_upload_may_contain_only_one_loan(self):
        self.write_trial([self.balance_rows[0]])
        self.run_workflow(self.selection())
        selection = prepare_opening_balances(2027)
        self.assertEqual(dict(selection.balances.values), {p: Decimal("1000.00") if p == "694511" else None for p in LOANS})
        self.run_workflow(selection, upload=False, output=self.root / "reuse.xlsx")
        self.assertIsNone(self.workbook(self.root / "reuse.xlsx")["Combined - 694512"]["H7"].value)

    def test_partial_update_preserves_other_values_dates_sources_and_fiscal_years(self):
        self.run_workflow(self.selection())
        store = BalanceStore(2027); old = store.path.read_bytes(); original, _ = store.load()
        other = self.cache / "FY2026.json"; other.write_text("other FY")
        self.trial = self.root / "one-loan.csv"
        self.write_trial([[self.balance_rows[0][0], 1500]])
        selection = self.selection(AUGUST)
        self.assertEqual(store.path.read_bytes(), old)
        self.assertEqual(selection.uploaded_projects, ("694511",))
        self.run_workflow(selection, output=self.root / "partial.xlsx")
        updated, _ = store.load(); projects = dict(updated.projects)
        self.assertEqual(projects["694511"].amount, Decimal("1500.00"))
        self.assertIn("2026-08-10", projects["694511"].updated_at)
        self.assertEqual(projects["694511"].source_name, "one-loan.csv")
        for project, balance in original.projects:
            if project != "694511":
                self.assertEqual(projects[project], balance)
        sheet = self.workbook(self.root / "partial.xlsx")["Opening Balances"]
        self.assertIn("2026-08-10", sheet["E2"].value)
        self.assertIn("2026-07-10", sheet["E3"].value)
        self.assertEqual((sheet["F2"].value, sheet["F3"].value), ("one-loan.csv", "trial.csv"))
        self.assertEqual(other.read_text(), "other FY")
        self.assertEqual(store.path.with_suffix(".backup.json").read_bytes(), old)
        saved = store.path.read_bytes(); mtime = store.path.stat().st_mtime_ns
        self.run_workflow(upload=False, output=self.root / "reuse.xlsx")
        self.assertEqual(store.path.read_bytes(), saved)
        self.assertEqual(store.path.stat().st_mtime_ns, mtime)

    def test_explicit_blank_null_and_zero_updates_remain_distinct(self):
        self.run_workflow(self.selection())
        store = BalanceStore(2027); original, _ = store.load()
        for i, amount in enumerate((None, "", " ", "null", "NULL", 0)):
            with self.subTest(amount=amount):
                self.write_trial([[self.balance_rows[4][0], amount]])
                output = self.root / f"blank-{i}.xlsx"
                self.run_workflow(self.selection(AUGUST), output=output)
                saved, _ = store.load(); projects = dict(saved.projects)
                value = projects["694516"].amount
                if amount == 0:
                    self.assertEqual(value, Decimal("0.00"))
                    self.assertEqual(self.workbook(output)["Bruce - 694516"]["G7"].value, "Debit")
                else:
                    self.assertIsNone(value)
                    self.assertIsNone(self.workbook(output)["Bruce - 694516"]["H7"].value)
                self.assertIn("2026-08-10", projects["694516"].updated_at)
                self.assertEqual(projects["694511"], dict(original.projects)["694511"])

    def test_empty_or_unrelated_trial_does_not_create_or_update_saved_balances(self):
        for rows in ([], [["Project: 999999 Other", 100]]):
            with self.subTest(rows=rows):
                self.write_trial(rows)
                with self.assertRaisesRegex(ValueError, "no configured loan projects"):
                    self.selection()
                self.assertFalse(self.cache.exists())

    def test_legacy_cache_reuses_without_writes_and_migrates_on_partial_upload(self):
        initial = self.selection().balances
        legacy = {"schema_version": 1, "fiscal_year": 2027, "updated_at": initial.updated_at,
                  "source_name": initial.source_name, "source_sha256": initial.source_digest,
                  "balances": {p: str(amount) for p, amount in initial.values}}
        store = BalanceStore(2027); self.cache.mkdir(parents=True)
        store.path.write_text(json.dumps(legacy), encoding="utf-8")
        raw = store.path.read_bytes(); mtime = store.path.stat().st_mtime_ns
        cached = prepare_opening_balances(2027)
        self.run_workflow(cached, upload=False)
        self.assertEqual(store.path.read_bytes(), raw)
        self.assertEqual(store.path.stat().st_mtime_ns, mtime)
        self.assertEqual(cached.balances, initial)
        self.write_trial([[self.balance_rows[0][0], 1500]])
        self.run_workflow(self.selection(AUGUST), output=self.root / "update.xlsx")
        self.assertEqual(json.loads(store.path.read_text())["schema_version"], 2)
        self.assertEqual(store.path.with_suffix(".backup.json").read_bytes(), raw)
        saved, _ = store.load()
        self.assertEqual(dict(saved.projects)["694512"], dict(initial.projects)["694512"])

    def test_invalid_project_provenance_is_not_treated_as_a_blank_balance(self):
        self.run_workflow(self.selection()); store = BalanceStore(2027)
        raw = store.path.read_text()
        for fields in ({"amount": "invalid"}, {"source_sha256": "invalid"}, {"updated_at": "2026-07-10"},
                       {"updated_at": None, "source_name": None, "source_sha256": None}):
            with self.subTest(fields=fields):
                payload = json.loads(raw); payload["balances"]["694511"].update(fields)
                store.path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ValueError, "Saved FY2027"):
                    prepare_opening_balances(2027)


if __name__ == "__main__":
    unittest.main()
