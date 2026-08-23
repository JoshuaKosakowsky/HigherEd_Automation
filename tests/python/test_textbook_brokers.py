from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from data_processing.textbook_brokers.pipeline import (
    TSPLOAD_HEADER,
    TransformationError,
    run_transformation,
)


class TextbookBrokersTransformationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_source(
        self,
        name: str,
        rows: list[list[str]],
    ) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerows(rows)
        return path

    def test_combines_sources_into_exact_tspload_layout(self) -> None:
        finaid = self.write_source(
            "finaid_20260801.csv",
            [["ignored", "ignored", "900000001", "BKFA", "ignored", "125.50"]],
        )
        institutional_aid = self.write_source(
            "ia_20260801.csv",
            [["ignored", "ignored", "900000002", "BKIA", "ignored", "75.00"]],
        )
        output = self.root / "output" / "TSPLOAD.csv"

        result = run_transformation(
            term_code="202680",
            output_path=output,
            source_paths=[finaid, institutional_aid],
        )

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(
            [(summary.source_type, summary.row_count) for summary in result.source_summaries],
            [("Finaid", 1), ("IA", 1)],
        )

        with output.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))

        self.assertEqual(rows[0], TSPLOAD_HEADER)
        self.assertEqual(
            rows[1],
            [
                "900000001",
                "BKFA",
                "202680",
                "T",
                "125.50",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        )
        self.assertEqual(rows[2][0:5], ["900000002", "BKIA", "202680", "T", "75.00"])
        self.assertEqual(len(rows[2]), len(TSPLOAD_HEADER))

        content = output.read_bytes()
        self.assertIn(b"\r\n", content)
        self.assertNotIn(b"\n", content.replace(b"\r\n", b""))

    def test_rejects_invalid_source_data(self) -> None:
        invalid_cases = {
            "wrong_column_count": ["a", "b", "900000001", "BKFA", "e"],
            "blank_student_id": ["a", "b", "", "BKFA", "e", "10.00"],
            "blank_detail_code": ["a", "b", "900000001", "", "e", "10.00"],
            "invalid_amount": ["a", "b", "900000001", "BKFA", "e", "ten dollars"],
        }

        for case_name, row in invalid_cases.items():
            with self.subTest(case=case_name):
                source = self.write_source(f"finaid_{case_name}.csv", [row])
                with self.assertRaises(TransformationError):
                    run_transformation(
                        term_code="202680",
                        output_path=self.root / f"{case_name}.csv",
                        source_paths=[source],
                    )

    def test_rejects_invalid_term_and_filename(self) -> None:
        source = self.write_source(
            "accounts.csv",
            [["a", "b", "900000001", "BKFA", "e", "10.00"]],
        )

        with self.assertRaisesRegex(TransformationError, "six digits"):
            run_transformation(
                term_code="Fall 2026",
                output_path=self.root / "invalid_term.csv",
                source_paths=[source],
            )

        with self.assertRaisesRegex(TransformationError, "finaid_\*\.csv or ia_\*\.csv"):
            run_transformation(
                term_code="202680",
                output_path=self.root / "invalid_filename.csv",
                source_paths=[source],
            )

    def test_rejects_duplicate_source_path(self) -> None:
        source = self.write_source(
            "finaid_duplicate.csv",
            [["a", "b", "900000001", "BKFA", "e", "10.00"]],
        )

        with self.assertRaisesRegex(TransformationError, "more than once"):
            run_transformation(
                term_code="202680",
                output_path=self.root / "duplicate.csv",
                source_paths=[source, source],
            )

    def test_never_overwrites_existing_output(self) -> None:
        source = self.write_source(
            "ia_existing.csv",
            [["a", "b", "900000001", "BKIA", "e", "10.00"]],
        )
        output = self.root / "TSPLOAD.csv"
        original_content = b"existing Banner file\r\n"
        output.write_bytes(original_content)

        with self.assertRaisesRegex(TransformationError, "not overwritten"):
            run_transformation(
                term_code="202680",
                output_path=output,
                source_paths=[source],
            )

        self.assertEqual(output.read_bytes(), original_content)


if __name__ == "__main__":
    unittest.main()
