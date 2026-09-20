from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from data_processing.jpmlb import (
    JPMLBTransformationError,
    transform_jpmlb_csv,
)
from data_processing.jpmlb.transform import ACCOUNTING_FORMAT


class JPMLBTransformationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_source(
        self,
        *,
        name: str = "Transaction_Results_07_31_2026_14_05_09.csv",
        amount_values: tuple[str, str] = ("1,234.50", "(34.50)"),
    ) -> Path:
        path = self.root / name
        headers = [f"Header {chr(64 + number)}" for number in range(1, 19)]
        rows = []
        for row_number, amount in enumerate(amount_values, start=1):
            row = [f"R{row_number}{chr(64 + number)}" for number in range(1, 19)]
            row[15] = amount
            rows.append(row)

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def test_transform_reproduces_macro_layout_and_formatting(self) -> None:
        source = self.write_source()
        output = self.root / "JPMLB 07-31-2026.xlsx"

        result = transform_jpmlb_csv(
            source_path=source,
            output_path=output,
        )

        self.assertEqual(result.data_row_count, 2)
        self.assertEqual(result.source_column_count, 18)
        self.assertEqual(result.output_column_count, 17)
        self.assertTrue(output.is_file())

        workbook = load_workbook(output, data_only=False)
        self.addCleanup(workbook.close)
        worksheet = workbook.active

        self.assertEqual(worksheet["L1"].value, "Header O")
        self.assertEqual(worksheet["M1"].value, "Header P")
        self.assertEqual(worksheet["N1"].value, "Header Q")
        self.assertEqual(worksheet["O1"].value, "CWID")
        self.assertEqual(worksheet["P1"].value, "NAME")
        self.assertEqual(worksheet["Q1"].value, "Header R")
        self.assertEqual(worksheet["M2"].value, 1234.5)
        self.assertEqual(worksheet["M3"].value, -34.5)

        self.assertEqual(worksheet["K4"].value, "Total Import")
        self.assertEqual(worksheet["M4"].value, "=SUM(M2:M3)")
        self.assertEqual(worksheet["J7"].value, "Void Above, then post")
        self.assertEqual(worksheet["K9"].value, "Total Post")
        self.assertEqual(worksheet["M9"].value, "=SUM(M6:M8)")
        self.assertEqual(worksheet["K12"].value, "Scholarships: FA")
        self.assertEqual(worksheet["M12"].value, "=SUM(M11)")
        self.assertEqual(worksheet["K15"].value, "Total Lockbox")
        self.assertEqual(worksheet["M15"].value, "=M4+M9+M12")
        self.assertEqual(worksheet["K18"].value, "Unclaimed")
        self.assertEqual(worksheet["M18"].value, "=SUM(M17)")

        self.assertEqual(worksheet.auto_filter.ref, "A1:Q3")
        self.assertEqual(worksheet.freeze_panes, "A2")
        self.assertTrue(worksheet.column_dimensions["E"].hidden)
        self.assertEqual(worksheet.column_dimensions["A"].width, 14)
        self.assertEqual(worksheet.column_dimensions["M"].width, 13)
        self.assertEqual(
            worksheet.column_dimensions["M"].number_format,
            ACCOUNTING_FORMAT,
        )
        self.assertEqual(worksheet.column_dimensions["O"].number_format, "0")
        self.assertEqual(worksheet.column_dimensions["P"].number_format, "@")
        self.assertEqual(worksheet["M2"].number_format, ACCOUNTING_FORMAT)
        self.assertEqual(worksheet["O2"].number_format, "0")
        self.assertEqual(worksheet["P2"].number_format, "@")
        self.assertFalse(worksheet["K4"].alignment.wrap_text)
        self.assertTrue(workbook.calculation.fullCalcOnLoad)
        self.assertTrue(workbook.calculation.forceFullCalc)

    def test_existing_output_is_never_overwritten(self) -> None:
        source = self.write_source()
        output = self.root / "JPMLB 07-31-2026.xlsx"
        output.write_bytes(b"existing")

        with self.assertRaisesRegex(
            JPMLBTransformationError,
            "already exists",
        ):
            transform_jpmlb_csv(source_path=source, output_path=output)

        self.assertEqual(output.read_bytes(), b"existing")

    def test_invalid_amount_does_not_leave_an_output(self) -> None:
        source = self.write_source(amount_values=("not an amount", "10.00"))
        output = self.root / "JPMLB 07-31-2026.xlsx"

        with self.assertRaisesRegex(
            JPMLBTransformationError,
            "nonnumeric value",
        ):
            transform_jpmlb_csv(source_path=source, output_path=output)

        self.assertFalse(output.exists())

    def test_source_requires_macro_amount_column(self) -> None:
        source = self.root / "Transaction_Results_07_31_2026_14_05_09.csv"
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([f"Column {number}" for number in range(15)])
            writer.writerow([str(number) for number in range(15)])

        with self.assertRaisesRegex(
            JPMLBTransformationError,
            "expected at least 16",
        ):
            transform_jpmlb_csv(
                source_path=source,
                output_path=self.root / "JPMLB 07-31-2026.xlsx",
            )


if __name__ == "__main__":
    unittest.main()
