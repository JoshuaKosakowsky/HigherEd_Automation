"""1305 GUI service authorization, native extraction and manual-path contracts."""

import csv
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.graduate_contract_recon import run_graduate_contract_recon
from shared.cancellation import CancellationToken, WorkflowCancelled
from shared.mines_paths import get_graduate_contract_recon_directory, get_shared_reconciliations_directory
from test_graduate_contract_recon import BN_HEADERS, WD_HEADERS, banner_from_frame, bn_row, workday, wd_row
from test_graduate_contract_worktags import worktag_source
from openpyxl import Workbook, load_workbook


class GraduateContractServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "review.xlsx"
        self.inputs = dict(banner_source="manual", workday_file=Path(self.temp.name) / "wd.xlsx",
            banner_file=Path(self.temp.name) / "bn.xlsx", output_file=self.output,
            start_date="2026-09-01", end_date="2026-09-30", detail_codes="TPDT")
        self.sources = [workday([wd_row()]), banner_from_frame(pd.DataFrame([bn_row()], columns=BN_HEADERS))]

    def context(self, mode=None, **kwargs):
        return WorkflowContext("graduate_contract_recon", self.inputs, mode, **kwargs)

    def write_csv(self, name, headers, rows):
        path = Path(self.temp.name) / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def test_manual_path_uploads_only_and_never_authenticates(self):
        with patch("app.gui.services.graduate_contract_recon.read_source", side_effect=self.sources), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            result = run_graduate_contract_recon(self.context())
        self.assertTrue(result.success)
        self.assertTrue(self.output.is_file())
        auth.assert_not_called()

    def test_default_output_directory_uses_mines_fiscal_period_for_run_date(self):
        environment = {"OneDriveCommercial": self.temp.name}
        base = (Path(self.temp.name) / "GRP-Bursar Office - General"
                / "Y-Brswork" / "Reconciliations")
        for run_day, year, period in (
            (date(2026, 6, 30), "FY26", "P12 - June 2026"),
            (date(2026, 7, 1), "FY27", "P01 - July 2026"),
            (date(2026, 11, 22), "FY27", "P05 - November 2026"),
            (date(2027, 1, 1), "FY27", "P07 - January 2027"),
        ):
            with self.subTest(run_day=run_day):
                self.assertEqual(get_graduate_contract_recon_directory(run_day, environment),
                                 base / year / "1305 - Grad Contract (1323)" / period)
        self.assertFalse(base.exists())

    def test_shared_output_creates_missing_fiscal_folders_and_keeps_existing_file(self):
        with patch.dict("os.environ", {"OneDriveCommercial": self.temp.name}):
            base = get_shared_reconciliations_directory()
            base.mkdir(parents=True)
            self.output = get_graduate_contract_recon_directory(date(2026, 11, 22)) / "review.xlsx"
            self.inputs["output_file"] = self.output
            self.assertFalse((base / "FY27").exists())
            with patch("app.gui.services.graduate_contract_recon.read_source", side_effect=self.sources):
                self.assertTrue(run_graduate_contract_recon(self.context()).success)
            with self.assertRaisesRegex(ValueError, "Output already exists"):
                run_graduate_contract_recon(self.context())
        self.assertTrue(self.output.is_file())
        book = load_workbook(self.output)
        try:
            self.assertIn("1305 Period Totals", book.sheetnames)
        finally:
            book.close()

    def test_missing_shared_root_or_custom_folder_is_not_created(self):
        with patch.dict("os.environ", {"OneDriveCommercial": self.temp.name}):
            shared = get_graduate_contract_recon_directory(date(2026, 11, 22))
            for folder, error in ((shared, "shared OneDrive Reconciliations folder is unavailable"),
                                  (Path(self.temp.name) / "custom", "output folder does not exist")):
                with self.subTest(folder=folder):
                    self.inputs["output_file"] = folder / "review.xlsx"
                    with self.assertRaisesRegex(ValueError, error):
                        run_graduate_contract_recon(self.context())
                    self.assertFalse(folder.exists())

    def test_upload_scope_uses_file_dates_and_all_codes_not_hidden_inputs(self):
        self.inputs.update(start_date="invalid", end_date="invalid", detail_codes="")
        sources = [workday([wd_row(day="2025-07-15")]),
                   banner_from_frame(pd.DataFrame([bn_row(day="2025-07-15", code="HLTH")], columns=BN_HEADERS))]
        with patch("app.gui.services.graduate_contract_recon.read_source", side_effect=sources), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            result = run_graduate_contract_recon(self.context())
        self.assertTrue(result.success)
        auth.assert_not_called()
        book = load_workbook(self.output)
        try:
            self.assertEqual(book["1305 Doc Recon"]["E2"].value, 60)
            self.assertEqual(book["1305 Period Totals"]["A2"].value, "FY2026")
            self.assertEqual(book["1305 Period Totals"]["B2"].value, "P01")
            self.assertEqual(sources[1].dispositions[2], "Selected")
        finally:
            book.close()

    def test_non_admin_cannot_forge_prod_source(self):
        self.inputs["banner_source"] = "sql"
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            policy.return_value.is_administrator.return_value = False
            with self.assertRaisesRegex(ValueError, "Only an administrator"):
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        auth.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_worktag_upload_is_read_and_added_to_student_output(self):
        self.inputs["worktag_file"] = Path(self.temp.name) / "tags.xlsx"
        tags = worktag_source([["10000001 SU26 Synthetic", "Grant: 123456"]])
        with patch("app.gui.services.graduate_contract_recon.read_source",
                   side_effect=[self.sources[0], tags, self.sources[1]]) as reader:
            result = run_graduate_contract_recon(self.context())
        self.assertTrue(result.success)
        self.assertEqual(reader.call_args_list[1].args, (self.inputs["worktag_file"], "Worktags"))
        book = load_workbook(self.output)
        try:
            self.assertEqual(book["1305 CWID Recon"]["I2"].value, "123456")
            self.assertIn("Worktags", book.sheetnames)
        finally:
            book.close()

    def test_batches_reconcile_across_years_and_keep_source_rows_traceable(self):
        exports = [
            wd_row(40, memo="800001", day="2025-08-15", line="1"),
            wd_row(70, memo="900002", day="2026-08-20", line="2"),
            wd_row(60, memo="900001", day="08/01/2026", line="3"),
        ]
        older = self.write_csv("earlier-1305.csv", WD_HEADERS, exports[:1])
        newer = Path(self.temp.name) / "later-1305.xlsx"
        source_book = Workbook()
        source_book.active.title = "Journal Lines"
        source_book.active.append(["Workday Report"])
        # The newer report has a different column order and amount aliases.
        headers = [header.replace("Workday ", "") for header in reversed(WD_HEADERS)]
        source_book.active.append([*headers, "Additional Info"])
        for row in exports[1:]:
            source_book.active.append([*reversed(row), "Later export only"])
        source_book.save(newer)
        source_book.close()
        banner = self.write_csv("banner.csv", BN_HEADERS, [
            bn_row(70, feed="900002", day="2026-08-20"),
            bn_row(60, feed="900001", day="2026-08-01"),
            bn_row(40, feed="800001", day="2025-08-15"),
        ])
        early_tags = self.write_csv("earlier-worktags.csv", ["Line Memo", "Worktags"], [
            ["10000001 FA25 Earlier", "Grant: 012345"],
        ])
        late_tags = self.write_csv("later-worktags.csv", ["Worktags", "Accounting Date", "Line Memo"], [
            ["Project: 654321", "2026-08-20", "10000001 SU26 Later"],
            ["Grant: 012345", "2026-08-02", "10000001 FA25 Repeated"],
            ["Operating Account: 123456", "2026-08-01", "10000001 FA26 Later"],
        ])
        self.inputs.update(workday_file=(newer, older), worktag_file=(late_tags, early_tags), banner_file=banner)

        result = run_graduate_contract_recon(self.context())

        self.assertTrue(result.success)
        with self.output.open("rb") as handle:
            book = load_workbook(handle)
        try:
            combined = list(book["1305 Combined"].values)[1:]
            self.assertEqual([(row[3], row[5], row[6]) for row in combined], [
                ("800001", "Workday", 40), ("800001", "Banner", 40),
                ("900001", "Workday", 60), ("900001", "Banner", 60),
                ("900002", "Workday", 70), ("900002", "Banner", 70),
            ])
            period_rows = [row for row in list(book["1305 Period Totals"].values)[1:] if row[3]]
            self.assertEqual([row[:7] for row in period_rows], [
                ("FY2026", "P02", "Q1", 40, 0, 40, 0),
                ("FY2027", "P02", "Q1", 130, 0, 130, 0),
            ])
            headers, *raw_rows = book["Workday Data"].values
            self.assertEqual([row[:2] for row in raw_rows], [
                (2, "earlier-1305.csv / CSV"), (4, "later-1305.xlsx / Journal Lines"),
                (3, "later-1305.xlsx / Journal Lines"),
            ])
            self.assertEqual([row[headers.index("Additional Info")] for row in raw_rows],
                             [None, "Later export only", "Later export only"])
            self.assertNotIn("Workday Debit Amount", headers)
            self.assertEqual([row[headers.index("Debit Amount")] for row in raw_rows],
                             ["40", 60, 70])
            self.assertEqual([row[-1] for row in raw_rows], ["Selected"] * 3)
            self.assertEqual([(row[1], row[4]) for row in list(book["Worktags"].values)[1:]],
                             [("FA25", "012345"), ("FA26", "123456"), ("SU26", "654321")])
            for row in list(book["1305 CWID Recon"].values)[1:]:
                self.assertEqual(row[7:10], ("654321", "012345", "123456"))
        finally:
            book.close()

    def test_bad_file_in_either_batch_names_the_export_and_saves_nothing(self):
        workday_path = self.write_csv("1305.csv", WD_HEADERS, [wd_row()])
        worktag_path = self.write_csv("worktags.csv", ["Line Memo", "Worktags"], [
            ["10000001 SU26 Synthetic", "Grant: 123456"],
        ])
        wrong = self.write_csv("wrong-report.csv", ["Unrelated"], [["Content"]])
        for key in ("workday_file", "worktag_file"):
            with self.subTest(key=key):
                self.inputs.update(workday_file=(workday_path,), worktag_file=(worktag_path,))
                self.inputs[key] += (wrong,)
                with self.assertRaisesRegex(ValueError, "wrong-report.csv.*required headers"):
                    run_graduate_contract_recon(self.context())
                self.assertFalse(self.output.exists())

    def test_admin_prod_uses_existing_parameterized_complete_extract(self):
        self.inputs["banner_source"] = "sql"
        self.inputs["workday_file"] = (self.inputs["workday_file"], Path(self.temp.name) / "older.xlsx")
        sources = [self.sources[0], workday([wd_row(day="2025-09-30")])]
        client = MagicMock(); client.__enter__.return_value = client
        frame = pd.DataFrame([bn_row()], columns=BN_HEADERS); frame["__activity_row_count"] = 1
        client.run_sql.return_value = frame
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.read_source", side_effect=sources), patch(
            "app.gui.services.graduate_contract_recon.load_department_profiles") as profiles, patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client", return_value=(client, "cached")) as auth:
            policy.return_value.is_administrator.return_value = True
            result = run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        self.assertTrue(result.success)
        self.assertTrue(auth.call_args.kwargs["use_saved_mines_login"])
        self.assertIn("IN ('TPDT')", client.run_sql.call_args.args[0])
        self.assertIn("COUNT(*) OVER ()", client.run_sql.call_args.args[0])
        profiles.return_value.__getitem__.assert_called_with("PROD")
        self.assertEqual(sources[0].dispositions[2], "Selected")
        self.assertEqual(sources[1].dispositions[2], "Excluded date range")

    def test_invalid_codes_output_or_mode_stops_before_authentication(self):
        with patch("app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            self.inputs["detail_codes"] = ""
            self.inputs["banner_source"] = "sql"
            with self.assertRaises(ValueError):
                run_graduate_contract_recon(self.context())
            self.inputs["detail_codes"] = "TPDT"
            self.inputs["banner_source"] = "manual"
            with self.assertRaisesRegex(ValueError, "does not use TEST or PROD"):
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
            self.output.write_bytes(b"existing")
            with self.assertRaises(ValueError):
                run_graduate_contract_recon(self.context())
            self.assertEqual(self.output.read_bytes(), b"existing")
        auth.assert_not_called()

    def test_cancelled_request_cannot_publish(self):
        token = CancellationToken(); token.request()
        with patch.dict("os.environ", {"OneDriveCommercial": self.temp.name}), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            get_shared_reconciliations_directory().mkdir(parents=True)
            self.output = get_graduate_contract_recon_directory(date(2026, 11, 22)) / "review.xlsx"
            self.inputs["output_file"] = self.output
            with self.assertRaises(WorkflowCancelled):
                run_graduate_contract_recon(self.context(cancellation=token))
        auth.assert_not_called()
        self.assertFalse(self.output.parent.exists())

    def test_auth_errors_are_sanitized_before_general_logger(self):
        self.inputs["banner_source"] = "sql"
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.read_source", return_value=self.sources[0]), patch(
            "app.gui.services.graduate_contract_recon.load_department_profiles"), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client", side_effect=RuntimeError("synthetic-secret")):
            policy.return_value.is_administrator.return_value = True
            with self.assertRaises(ValueError) as caught:
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
