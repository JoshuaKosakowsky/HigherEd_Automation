"""Synthetic reference extraction, publication and GUI authorization checks."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.trends import run_refresh_detail_codes
from app.gui.workflow_registry import get_workflow
from shared.cancellation import CancellationToken, WorkflowCancelled
from shared.insights.client import InsightsAPIError
from shared.insights.detail_codes import extract_detail_codes, refresh_detail_codes

COLUMNS = ["detail_code", "type", "category", "detail_code_description", "priority", "active", "title_iv", "extract_remaining_count"]


class ReferenceExecutor:
    def __init__(self, cap=1000, rows=None):
        self.cap = cap
        self.rows = rows if rows is not None else [
            ("0001", "C", "FEE", "Synthetic fee"), ("TUIT", "C", "TUI", "Tuition"),
            ("WOFF", "P", "WOF", "Write-off")]
        self.calls = []

    def run_sql(self, sql):
        self.calls.append(sql)
        marker = re.search(r"> E?'((?:[^']|'')*)'", sql)
        eligible = [row for row in self.rows if marker is None or row[0] > marker.group(1).replace("''", "'").replace("\\\\", "\\")]
        limit = int(re.search(r"LIMIT (\d+)", sql).group(1))
        return pd.DataFrame([list(row) + (["001", "Y", "N"] if len(row) == 4 else []) + [len(eligible)] for row in eligible[:min(limit, self.cap)]], columns=COLUMNS)


class DetailCodeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "detail_codes.json"

    def test_refresh_initializes_missing_file_with_leading_zero_codes(self):
        self.assertEqual(refresh_detail_codes(ReferenceExecutor(), self.path), 3)
        records = json.loads(self.path.read_text())
        self.assertIn("0001", records)
        self.assertEqual(records["WOFF"]["type"], "P")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_refresh_preserves_extra_excel_metadata_updates_current_fields(self):
        self.path.write_text(json.dumps({"TUIT": {"type": "P", "category": "OLD", "refundable": True}, "OLD1": {}}))
        refresh_detail_codes(ReferenceExecutor(), self.path)
        records = json.loads(self.path.read_text())
        self.assertTrue(records["TUIT"]["refundable"])
        self.assertEqual(records["TUIT"]["type"], "C")
        self.assertNotIn("OLD1", records)

    def test_refresh_updates_priority_and_boolean_flags_preserving_extra_fields(self):
        self.path.write_text(json.dumps({"TUIT": {"priority": "999", "active": False,
            "title_iv": False, "refundable": True}}))
        executor = ReferenceExecutor(rows=[("TUIT", "C", "TUI", "Tuition", " 001 ", " y ", "Y")])
        refresh_detail_codes(executor, self.path)
        metadata = json.loads(self.path.read_text())["TUIT"]
        self.assertEqual(metadata["priority"], "001")
        self.assertIs(metadata["active"], True)
        self.assertIs(metadata["title_iv"], True)
        self.assertIs(metadata["refundable"], True)
        sql = executor.calls[0]
        self.assertIn("d.tbbdetc_priority", sql)
        self.assertIn("d.tbbdetc_detc_active_ind", sql)
        self.assertIn("d.tbbdetc_tiv_ind", sql)

    def test_inactive_and_non_title_iv_codes_remain_in_reference(self):
        result = extract_detail_codes(ReferenceExecutor(rows=[("OLD1", "C", "FEE", "Old", "000", "N", "N")]))
        self.assertEqual(result["OLD1"]["priority"], "000")
        self.assertIs(result["OLD1"]["active"], False)
        self.assertIs(result["OLD1"]["title_iv"], False)

    def test_blank_flags_and_priority_remain_null(self):
        for values in ((None, None, None), ("", " ", "")):
            result = extract_detail_codes(ReferenceExecutor(rows=[("NULL", "C", "FEE", "Unknown", *values)]))
            self.assertIsNone(result["NULL"]["priority"])
            self.assertIsNone(result["NULL"]["active"])
            self.assertIsNone(result["NULL"]["title_iv"])

    def test_missing_or_invalid_new_metadata_preserves_previous_reference(self):
        for field in ("priority", "active", "title_iv"):
            for missing in (True, False):
                with self.subTest(field=field, missing=missing):
                    self.path.write_text('{}')
                    executor = ReferenceExecutor(); run_sql = executor.run_sql
                    def bad(sql):
                        frame = run_sql(sql)
                        if missing: return frame.drop(columns=field)
                        frame[field] = "INVALID"
                        return frame
                    executor.run_sql = bad
                    with self.assertRaises(InsightsAPIError): refresh_detail_codes(executor, self.path)
                    self.assertEqual(self.path.read_text(), '{}')

    def test_reference_accepts_text_codes_and_escapes_paging_cursor(self):
        rows = sorted([
            ("01", "C", "FEE", "Short code"),
            ("A'01", "C", "FEE", "Apostrophe code"),
            ("A-01", "P", "FEE", "Punctuation code"),
            ("ABCDE", "C", "TUI", "Longer code"),
            ("A\\01", "C", "FEE", "Backslash code"),
            ("ZZZZ", "P", "FEE", "Final code"),
        ])
        executor = ReferenceExecutor(cap=1, rows=rows)
        records = extract_detail_codes(executor)
        self.assertEqual(set(records), {row[0] for row in rows})
        self.assertTrue(any("E'A''01'" in sql for sql in executor.calls))
        self.assertTrue(any("E'A\\\\01'" in sql for sql in executor.calls))
        self.assertTrue(any('COLLATE "C"' in sql for sql in executor.calls))

    def test_invalid_value_error_identifies_bad_metadata_without_replacing_file(self):
        for code in (None, "", "   ", "A\n01"):
            with self.subTest(code=code):
                self.path.write_text('{}')
                executor = ReferenceExecutor(rows=[(code, "C", "FEE", "Synthetic")])
                with self.assertRaisesRegex(InsightsAPIError, "invalid detail-code value") as caught:
                    refresh_detail_codes(executor, self.path)
                self.assertIn(repr(code), str(caught.exception))
                self.assertEqual(self.path.read_text(), '{}')

    def test_api_cap_retries_without_skipping_codes(self):
        executor = ReferenceExecutor(cap=1)
        records = extract_detail_codes(executor)
        self.assertEqual(set(records), {"0001", "TUIT", "WOFF"})
        self.assertIn("WHERE TRUE", executor.calls[1])
        self.assertIn("LIMIT 1", executor.calls[1])
        self.assertEqual(len(executor.calls), 4)

    def test_invalid_or_incomplete_results_preserve_saved_reference(self):
        for kind in ("empty", "missing", "duplicate", "code", "type", "category", "count", "changing"):
            with self.subTest(kind=kind):
                original = '{"TUIT": {"type": "C", "category": "TUI"}}'
                self.path.write_text(original)
                executor = ReferenceExecutor(cap=1 if kind == "changing" else 1000)
                run_sql = executor.run_sql
                def bad(sql):
                    frame = run_sql(sql)
                    if kind == "empty": return pd.DataFrame(columns=COLUMNS)
                    if kind == "missing": return frame.drop(columns="category")
                    if kind == "duplicate": frame["detail_code"] = "TUIT"
                    if kind == "code": frame["detail_code"] = ""
                    if kind == "type": frame["type"] = "X"
                    if kind == "category": frame["category"] = None
                    if kind == "count": frame["extract_remaining_count"] = 3.5
                    if kind == "changing" and "> E'" in sql: frame["extract_remaining_count"] = 999
                    return frame
                executor.run_sql = bad
                with self.assertRaises(InsightsAPIError): refresh_detail_codes(executor, self.path)
                self.assertEqual(self.path.read_text(), original)
                self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_cancelled_fetch_and_replace_failure_preserve_previous_file(self):
        self.path.write_text('{}')
        token = CancellationToken()
        executor = ReferenceExecutor(); run_sql = executor.run_sql
        def cancel(sql):
            result = run_sql(sql); token.request(); return result
        executor.run_sql = cancel
        with self.assertRaises(WorkflowCancelled): refresh_detail_codes(executor, self.path, cancellation=token)
        self.assertEqual(self.path.read_text(), '{}')
        with patch.object(Path, "replace", side_effect=PermissionError("synthetic")):
            with self.assertRaises(PermissionError): refresh_detail_codes(ReferenceExecutor(), self.path)
        self.assertEqual(self.path.read_text(), '{}')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_failed_query_preserves_reference_and_releases_lock(self):
        self.path.write_text('{}')
        executor = MagicMock()
        executor.run_sql.side_effect = InsightsAPIError("Synthetic query failure")
        with self.assertRaises(InsightsAPIError): refresh_detail_codes(executor, self.path)
        self.assertEqual(self.path.read_text(), '{}')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_concurrent_edit_and_existing_lock_are_not_overwritten(self):
        self.path.write_text('{}')
        executor = ReferenceExecutor(); run_sql = executor.run_sql
        def changed(sql):
            self.path.write_text('{"NEW1": {}}'); return run_sql(sql)
        executor.run_sql = changed
        with self.assertRaisesRegex(ValueError, "changed during refresh"):
            refresh_detail_codes(executor, self.path)
        self.assertEqual(self.path.read_text(), '{"NEW1": {}}')
        lock = self.path.with_name('.detail_codes.json.lock'); lock.touch()
        with self.assertRaisesRegex(ValueError, "already running"):
            refresh_detail_codes(ReferenceExecutor(), self.path)
        self.assertTrue(lock.exists())

    def test_malformed_existing_metadata_is_preserved(self):
        for content in ('invalid', '[]', '{"TUIT": 1}'):
            self.path.write_text(content)
            executor = ReferenceExecutor()
            with self.assertRaises(ValueError): refresh_detail_codes(executor, self.path)
            self.assertEqual(self.path.read_text(), content)
            self.assertEqual(executor.calls, [])

    def test_gui_refresh_is_admin_only_prod_and_uses_shared_destination(self):
        definition = get_workflow('refresh_detail_codes')
        self.assertTrue(definition.administrator_only)
        self.assertEqual(definition.supported_modes, (WorkflowMode.PRODUCTION,))
        executor = ReferenceExecutor()
        client = MagicMock(); client.run_sql.side_effect = executor.run_sql
        with patch('app.gui.services.trends.get_shared_gui_access_path', return_value=self.root / 'gui_access.json'), patch('app.gui.services.trends.get_shared_detail_codes_path', return_value=self.path), patch('app.gui.services.trends.load_access_configuration') as policy, patch('app.gui.services.trends.load_department_profiles', return_value={'PROD': MagicMock()}), patch('app.gui.services.trends.build_authenticated_client', return_value=(client, None)) as auth:
            policy.return_value.is_administrator.return_value = False
            with self.assertRaisesRegex(ValueError, 'administrator'):
                run_refresh_detail_codes(WorkflowContext('refresh_detail_codes', {}, WorkflowMode.PRODUCTION))
            policy.return_value.is_administrator.return_value = True
            with self.assertRaisesRegex(ValueError, 'PROD'):
                run_refresh_detail_codes(WorkflowContext('refresh_detail_codes', {}, WorkflowMode.TEST))
            auth.assert_not_called()
            result = run_refresh_detail_codes(WorkflowContext('refresh_detail_codes', {}, WorkflowMode.PRODUCTION))
        self.assertTrue(result.success)
        self.assertEqual(result.output_path, self.path)
        self.assertIn('0001', json.loads(self.path.read_text()))
