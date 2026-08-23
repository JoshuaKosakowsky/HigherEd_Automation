from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from data_processing.shared.tgiaccd import fiscal_year_from_filename
from data_processing.trends.analysis import (
    analyze_all_files,
    analyze_tgiaccd_file,
    build_reporting_group_totals,
)
from data_processing.trends.config import REQUIRED_COLUMNS, TrendsConfig


DETAIL_CODES = {
    "TUIT": {
        "type": "C",
        "category": "TUI",
        "detail_code_description": "Tuition charge",
    },
    "TUIR": {
        "type": "P",
        "category": "TUI",
        "detail_code_description": "Tuition credit",
    },
    "WOFF": {
        "type": "P",
        "category": "WOF",
        "detail_code_description": "Write-off",
    },
    "BDRC": {
        "type": "C",
        "category": "BDR",
        "detail_code_description": "Bad debt recovery",
    },
    "COLL": {
        "type": "C",
        "category": "COL",
        "detail_code_description": "Collections",
    },
    "PCCS": {
        "type": "C",
        "category": "COL",
        "detail_code_description": "Collection service",
    },
}


class TrendsAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_workbook(
        self,
        rows: list[list[object]],
        *,
        filename: str = "TGIACCD_fy26.xlsx",
        headers: tuple[str, ...] = REQUIRED_COLUMNS,
    ) -> Path:
        path = self.root / filename
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(list(headers))
        for row in rows:
            worksheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def test_calculates_financial_signs_and_exact_detail_code_totals(self) -> None:
        path = self.write_workbook(
            [
                ["900000001", "TUIT", "Tuition charge", 1000, 800, "202610"],
                ["900000002", "TUIR", "Tuition credit", 200, -200, "202610"],
                ["900000003", "WOFF", "Write-off", 50, 0, "202610"],
                ["900000004", "BDRC", "Bad debt recovery", 30, 0, "202620"],
                ["900000005", "COLL", "Collections", 70, 70, "202620"],
            ]
        )

        result = analyze_all_files(
            [path],
            detail_codes=DETAIL_CODES,
            config=TrendsConfig(),
        )
        analysis = result.fiscal_years[0]
        detail_totals = result.detail_codes
        group_averages = result.group_averages
        term_group_totals = result.term_groups
        term_collection_totals = result.term_collections

        self.assertEqual(analysis.fiscal_year, 2026)
        self.assertEqual(analysis.row_count, 5)
        self.assertEqual(analysis.student_count, 5)
        self.assertEqual(analysis.charge_activity, 1100)
        self.assertEqual(analysis.payment_credit_activity, 250)
        self.assertEqual(analysis.net_ar_activity, 850)
        self.assertEqual(analysis.gross_tuition_charges, 1000)
        self.assertEqual(analysis.tuition_offsets, 200)
        self.assertEqual(analysis.net_tuition_revenue, 800)
        self.assertEqual(analysis.writeoff_count, 1)
        self.assertEqual(analysis.writeoff_amount, 50)
        self.assertEqual(analysis.unmapped_row_count, 0)

        totals_by_code = {total.detail_code: total for total in detail_totals}
        self.assertEqual(totals_by_code["WOFF"].signed_ar_effect, -50)
        self.assertEqual(totals_by_code["BDRC"].signed_ar_effect, 30)

        tuition = next(total for total in group_averages if total.label == "Tuition")
        self.assertEqual(tuition.charge_amount, 1000)
        self.assertEqual(tuition.payment_credit_amount, 200)
        self.assertEqual(tuition.net_category_amount, 800)

        term_tuition = next(
            total
            for total in term_group_totals
            if total.term == "202610" and total.label == "Tuition"
        )
        self.assertEqual(term_tuition.net_amount, 800)

        collection_by_code = {
            total.detail_code: total for total in term_collection_totals
        }
        self.assertEqual(collection_by_code["COLL"].transaction_count, 1)
        self.assertEqual(collection_by_code["COLL"].total_amount, 70)
        self.assertEqual(collection_by_code["PCCS"].transaction_count, 0)

        reporting = build_reporting_group_totals(
            fiscal_year_results=[analysis],
            detail_code_results=detail_totals,
            group_average_results=group_averages,
        )
        reporting_by_label = {total.label: total for total in reporting}
        self.assertEqual(reporting_by_label["Write-Off Bad Debt"].net_amount, -50)
        self.assertEqual(reporting_by_label["BDRC - Bad Debt Recovery"].net_amount, 30)

    def test_strict_mode_rejects_unmapped_detail_codes(self) -> None:
        path = self.write_workbook(
            [["900000001", "MISS", "Unknown code", 10, 0, "202610"]]
        )

        with self.assertRaisesRegex(ValueError, "MISS"):
            analyze_tgiaccd_file(
                path,
                detail_codes=DETAIL_CODES,
                config=TrendsConfig(strict_detail_codes=True),
            )

    def test_non_strict_mode_reports_unmapped_detail_codes(self) -> None:
        path = self.write_workbook(
            [["900000001", "MISS", "Unknown code", 10, 0, "202610"]]
        )

        result = analyze_tgiaccd_file(
            path,
            detail_codes=DETAIL_CODES,
            config=TrendsConfig(strict_detail_codes=False),
        )
        analysis = result.fiscal_year
        detail_totals = result.detail_codes

        self.assertEqual(analysis.unmapped_row_count, 1)
        self.assertEqual(analysis.unmapped_detail_codes, {"MISS"})
        self.assertEqual(detail_totals[0].detail_code, "MISS")
        self.assertEqual(detail_totals[0].signed_ar_effect, 0)

    def test_rejects_workbook_missing_required_columns(self) -> None:
        path = self.write_workbook(
            [["900000001", "TUIT", "Tuition charge", 1000, "202610"]],
            headers=("ID", "Detail Code", "Description", "Amount", "Term"),
        )

        with self.assertRaisesRegex(ValueError, "Balance"):
            analyze_tgiaccd_file(
                path,
                detail_codes=DETAIL_CODES,
                config=TrendsConfig(),
            )

    def test_extracts_fiscal_year_from_supported_filenames(self) -> None:
        self.assertEqual(fiscal_year_from_filename(Path("TGIACCD_fy26.xlsx")), 2026)
        self.assertEqual(fiscal_year_from_filename(Path("TGIACCD_fy2027.xlsx")), 2027)
        self.assertEqual(fiscal_year_from_filename(Path("TGIACCD_fy99.xlsx")), 1999)
        with self.assertRaises(ValueError):
            fiscal_year_from_filename(Path("TGIACCD.xlsx"))


if __name__ == "__main__":
    unittest.main()
