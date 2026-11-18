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


def journal_row(account="1621", day="2026-07-15", debit=100, credit=None, project="694511", memo="Synthetic activity", journal="J-001"):
    return [project, account + ":Synthetic account", journal, day, "Manual Journal", memo, debit, credit]


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
        self.assertTrue(all(row.section == "1621" for row in activity.rows))

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
                self.assertEqual([sheet.cell(row, 3).value.date().isoformat() for row in (10, 11, 14, 15)],
                                 ["2026-08-05", "2026-07-05", "2026-08-07", "2026-07-02"])
                self.assertEqual([sheet.cell(row, 8).value for row in (10, 11, 14, 15)], [200, 100, 60, 50])
                self.assertEqual(sheet["A7"].value, "Beginning Balance of the FY")
                self.assertEqual(sheet["H12"].value, "=SUM(H10:H11)")
                self.assertEqual(sheet["H16"].value, "=SUM(H14:H15)")
        self.assertEqual([cell.value for cell in book["Journal Lines"]["E"]][1:], [row[3] for row in rows])

    def test_source_direction_and_original_values_are_preserved(self):
        self.write_journal([journal_row(debit=None, credit=25), journal_row(debit=-5),
                            journal_row(debit=0, credit=None)])
        self.run_workflow()
        sheet = self.workbook()["Parsons - 694511"]
        self.assertEqual([(sheet.cell(row, 6).value, sheet.cell(row, 7).value, sheet.cell(row, 8).value)
                          for row in (10, 11, 12)], [(25, "Credit", 25), (-5, "Debit", -5), (0, "Debit", 0)])

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
        self.write_journal([journal_row(account=account) for account in
                            ("1021", "1036", "1382", "1621", "2100", "2402", "2881", "5909R", "8309R", "9999")]
                           + [journal_row(project="999999")])
        result = self.run_workflow()
        book = self.workbook(); sheet = book["Parsons - 694511"]
        self.assertEqual(len(book["Journal Lines"]["A"]), 12)
        labels = [cell.value for cell in sheet["A"] if cell.value]
        self.assertIn("1621 — Unclassified", labels)
        self.assertIn("Payables — 2100", labels)
        self.assertIn("Payables — 2402", labels)
        self.assertIn("Payables (2881)", labels)
        self.assertIn("Other — 9999", labels)
        self.assertNotIn("Receivables", " ".join(labels))
        self.assertIn("7 activity rows", result.message)
        self.assertIn("1 rows use unmapped", result.message)

    def test_zero_two_and_five_rows_place_totals_and_next_section_correctly(self):
        for count, total_row, next_row in ((0, 10, 12), (2, 12, 14), (5, 15, 17)):
            with self.subTest(count=count):
                self.write_journal([journal_row() for _ in range(count)] + [journal_row(account="2100")])
                output = self.root / f"count-{count}.xlsx"
                self.run_workflow(output=output)
                sheet = self.workbook(output)["Parsons - 694511"]
                self.assertEqual(sheet.cell(total_row, 1).value, "1621 — Unclassified Total")
                self.assertEqual(sheet.cell(next_row, 1).value, "Payables — 2100")
                self.assertEqual(sheet.cell(total_row, 8).value,
                                 f"=SUM(H10:H{total_row - 1})" if count else 0)
                self.assertEqual(sheet["H8"].value, '=IF(COUNT(H7)=0,"",SUM(H7:H7))')
                self.assertIsNone(sheet.cell(total_row + 1, 1).value)

    def test_seven_loan_tabs_empty_current_recon_and_literal_source_text(self):
        self.write_journal([journal_row(memo='=HYPERLINK("https://invalid.example")')])
        self.run_workflow()
        book = self.workbook()
        self.assertEqual(book.sheetnames[:8], ["Current Recon", *(f"{name} - {project}" for project, name in LOANS.items())])
        self.assertTrue(all(cell.value is None for row in book["Current Recon"] for cell in row))
        self.assertEqual(book["Parsons - 694511"]["E10"].data_type, "s")
        self.assertEqual(book["Journal Lines"]["G2"].data_type, "s")
        self.assertIn("0.00", book["Parsons - 694511"]["F10"].number_format)
        self.assertEqual(book["Combined - 694512"]["H7"].value, -1001)

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
            self.assertEqual(book["Parsons - 694511"]["H10"].value, 100)
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
