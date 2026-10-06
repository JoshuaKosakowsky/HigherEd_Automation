from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from data_processing.canadian_tax.exchange_rates import (
    convert_usd_to_cad, fetch_annual_rate, parse_annual_rate,
)
from data_processing.canadian_tax.preparation import (
    QUERY_DIRECTORY, load_rules, money, prepare_enrollment,
    prepare_payment_applications, prepare_transactions,
    render_query, summarize_codes, validate_extract, validate_inputs,
)
from workflows.canadian_tax.run_tl11a_data import build_parser, extract_data, main, write_package


def annual_payload(value: str = "1.3978") -> dict:
    return {"observations": [{"d": "2025-01-01", "FXAUSDCAD": {"v": value}}]}


class CanadianTaxPreparationTests(unittest.TestCase):
    def test_input_literals_cannot_inject_sql(self) -> None:
        for cwid in ("", "A' OR 1=1--", "A;DROP", "A B", "é", "A" * 31):
            with self.subTest(cwid=cwid), self.assertRaises(ValueError):
                validate_inputs(cwid, 2025)
        for year in (1999, 2100, "2025", True):
            with self.subTest(year=year), self.assertRaises(ValueError):
                validate_inputs("SYNTHETIC001", year)

    def test_preserve_source_and_signs_under_owner_exclusion_policy(self) -> None:
        source = pd.DataFrame([
            {"pidm": 1, "tran_number": n, "term_code": "202510",
             "detail_code": code, "type_ind": kind, "amount_usd": value}
            for n, (code, kind, value) in enumerate([
                ("FEIT", "C", "30.00"), ("CFEE", "C", "7.92"),
                ("FEAS", "C", "90.00"), ("NEW1", "C", "1000.00"),
                ("SCH1", "P", "500.00"), ("NEW1", "C", "-40.00"),
                ("NEW1", "X", "10.00"),
            ], 1)
        ])
        prepared = prepare_transactions(source, load_rules())
        self.assertNotIn("eligibility_status", source)
        self.assertEqual(prepared.eligibility_status.tolist(),
                         ["excluded", "excluded", "eligible", "eligible", "payment", "eligible", "review"])
        self.assertEqual(prepared.amount_usd.iloc[5], Decimal("-40"))
        summary = summarize_codes(prepared)
        unknown = summary[(summary.detail_code == "NEW1") & (summary.type_ind == "C")].iloc[0]
        self.assertEqual(unknown.net_source_amount_usd, Decimal("960"))
        self.assertEqual(unknown.transaction_count, 2)

    def test_custom_rules_without_default_still_require_unknown_code_review(self) -> None:
        source = pd.DataFrame([{"pidm": 1, "tran_number": 1, "term_code": "202510",
                                "detail_code": "NEW1", "type_ind": "C", "amount_usd": "100"}])
        self.assertEqual(prepare_transactions(source, {}).eligibility_status.iloc[0], "review")

    def test_course_duration_boundaries_dropped_missing_and_conflicting_dates(self) -> None:
        rows = []
        for start, end, part_start, part_end, enrolled in [
            ("2025-05-01", "2025-05-21", "2025-05-01", "2025-05-21", "Y"),
            ("2025-05-01", "2025-05-20", "2025-05-01", "2025-05-20", "Y"),
            ("2025-05-01", "2025-05-21", "2025-05-01", "2025-05-21", "N"),
            (None, None, "2025-05-01", "2025-05-21", "Y"),
            (None, None, None, None, "Y"),
            ("2025-05-01", "2025-05-21", "2025-05-02", "2025-05-21", "Y"),
            ("bad-date", "2025-05-21", "2025-05-01", "2025-05-21", "Y"),
            ("NaT", "2025-05-21", "2025-05-01", "2025-05-21", "Y"),
            ("2025-05-21", "2025-05-01", None, None, "Y"),
            ("2025-05-01", "2025-05-21", None, None, None),
        ]:
            rows.append(dict(section_start_date=start, section_end_date=end,
                             part_of_term_start_date=part_start, part_of_term_end_date=part_end,
                             counts_in_enrollment=enrolled))
        source = pd.DataFrame(rows)
        result = prepare_enrollment(source)
        self.assertEqual(result.course_duration_status.tolist(), [
            "meets_minimum", "below_minimum", "not_enrolled", "meets_minimum",
            "review_dates", "review_dates", "review_dates", "review_dates", "review_dates", "review_enrollment_status",
        ])
        self.assertEqual(result.scheduled_duration_days.iloc[0], 21)
        self.assertEqual(result.scheduled_duration_days.iloc[1], 20)
        self.assertNotIn("course_duration_status", source)

    def test_reject_duplicate_transactions_and_invalid_amounts(self) -> None:
        row = {"pidm": 1, "tran_number": 1, "term_code": "202510",
               "detail_code": "FEIT", "type_ind": "C", "amount_usd": "30"}
        with self.assertRaisesRegex(ValueError, "duplicated"):
            prepare_transactions(pd.DataFrame([row, row]), load_rules())
        for value in (None, "NaN", "Infinity", "0.001", "bad", "1e100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    def test_completeness_year_and_account_controls(self) -> None:
        good = pd.DataFrame({"extract_row_count": [1], "extract_tax_year": [2025], "pidm": [1]})
        validate_extract(good, 2025)
        for column, value in (("extract_row_count", 2), ("extract_row_count", None),
                              ("extract_tax_year", 2024), ("pidm", None)):
            bad = good.copy()
            bad[column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                validate_extract(bad, 2025)
        with self.assertRaises(ValueError):
            validate_extract(pd.DataFrame(), 2025)
        validate_extract(good.iloc[:0], 2025)

    def test_rule_validation_requires_reason_and_known_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"schemaVersion": 1, "rules": {"TEST": {"status": "eligible"}}}))
            with self.assertRaises(ValueError):
                load_rules(path)

    def test_output_is_exclusive_and_partial_write_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new"
            frames = {"source": pd.DataFrame({"amount": [1]})}
            write_package(output, frames, {"eligible_paid_usd": None})
            with self.assertRaises(FileExistsError):
                write_package(output, frames, {})
            self.assertIsNone(json.loads((output / "manifest.json").read_text())["eligible_paid_usd"])
            second = Path(directory) / "partial"
            with patch.object(pd.DataFrame, "to_csv", side_effect=OSError("synthetic write failure")):
                with self.assertRaises(OSError):
                    write_package(second, frames, {})
            self.assertFalse(second.exists())
            self.assertTrue(output.exists())

    def test_test_environment_is_default(self) -> None:
        self.assertEqual(build_parser().parse_args([]).environment, "TEST")


class CanadianTaxRatesTests(unittest.TestCase):
    def test_official_series_direction_precision_and_rounding(self) -> None:
        rate = parse_annual_rate(annual_payload(), 2025)
        self.assertEqual(rate, Decimal("1.3978"))
        self.assertEqual(convert_usd_to_cad(Decimal("100.01"), rate), Decimal("139.79"))
        self.assertEqual(convert_usd_to_cad(Decimal("1.00"), Decimal("1.005")), Decimal("1.01"))

    def test_missing_year_does_not_fall_back(self) -> None:
        self.assertIsNone(parse_annual_rate(annual_payload(), 2026))
        self.assertIsNone(parse_annual_rate({"observations": []}, 2025))

    def test_reject_malformed_duplicate_or_invalid_rates(self) -> None:
        bad = [annual_payload(value) for value in ("0", "-1", "NaN", "Infinity", "bad")]
        bad += [{}, {"observations": [1]}, {"observations": annual_payload()["observations"] * 2},
                {"observations": [{"d": "2025-01-01", "FXUSDCAD": {"v": "1.4"}}]}]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_annual_rate(payload, 2025)

    @patch("data_processing.canadian_tax.exchange_rates.requests.get")
    def test_fetch_retains_public_response_and_audit_source(self, get: Mock) -> None:
        get.return_value.json.return_value = annual_payload()
        get.return_value.url = "https://www.bankofcanada.ca/valet/example"
        metadata, payload = fetch_annual_rate(2025)
        self.assertEqual(metadata["status"], "published")
        self.assertEqual(metadata["cad_per_usd"], "1.3978")
        self.assertEqual(metadata["direction"], "CAD per 1 USD")
        self.assertIn("guidance_url", metadata)
        self.assertEqual(payload, annual_payload())
        self.assertEqual(get.call_args.kwargs["params"],
                         {"start_date": "2025-01-01", "end_date": "2025-12-31"})

    @patch("data_processing.canadian_tax.exchange_rates.requests.get")
    def test_unavailable_rate_is_visible_without_made_up_value(self, get: Mock) -> None:
        get.side_effect = requests.ConnectionError("synthetic network failure")
        metadata, payload = fetch_annual_rate(2025)
        self.assertEqual(metadata["status"], "unavailable")
        self.assertIsNone(metadata["cad_per_usd"])
        self.assertIsNone(payload)
        self.assertIn("start_date=2025-01-01", metadata["api_url"])


class CanadianTaxQueryExecutionTests(unittest.TestCase):
    """Execute synthetic SQL in SQLite with only PG casts/date syntax adapted."""

    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("ATTACH DATABASE ':memory:' AS saturn; ATTACH DATABASE ':memory:' AS taismgr;")
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS information_schema;
            CREATE TABLE information_schema.columns (
                table_schema TEXT, table_name TEXT, column_name TEXT,
                data_type TEXT, ordinal_position INTEGER
            );
        """)
        self.db.create_function("MAKE_DATE", 3, lambda y, m, d: f"{y:04}-{m:02}-{d:02}")
        schema = (QUERY_DIRECTORY / "validate_canadian_tax_schema.sql").read_text()
        self.fields = re.findall(r"\('(saturn|taismgr)', '(\w+)', '(\w+)'\)", schema)
        tables = {}
        for schema_name, table, suffix in self.fields:
            kind = "NUMERIC" if suffix in {"pidm", "tran_number", "amount", "balance", "credit_hr", "bill_hr", "surrogate_id", "version", "pay_tran_number", "chg_tran_number"} else "TEXT"
            tables.setdefault((schema_name, table), []).append(f"{table}_{suffix} {kind}")
        for (schema_name, table), columns in tables.items():
            self.db.execute(f"CREATE TABLE {schema_name}.{table} ({', '.join(columns)})")
            for index, column in enumerate(columns, 1):
                name, kind = column.split()
                self.db.execute("INSERT INTO information_schema.columns VALUES (?, ?, ?, ?, ?)",
                                (schema_name, table, name, kind, index))
        self.insert("saturn", "spriden", pidm=1, id="SYNTHETIC001", first_name="Synthetic", last_name="Example")
        self.insert("saturn", "stvterm", code="202510", desc="Spring 2025", start_date="2025-01-01", end_date="2025-05-31")
        self.insert("saturn", "stvterm", code="202480", desc="Fall 2024", start_date="2024-08-01", end_date="2024-12-31")
        self.insert("saturn", "stvterm", code="202499", desc="Cross-year", start_date="2024-12-20", end_date="2025-01-15")
        self.insert("taismgr", "tbbdetc", detail_code="TU01", type_ind="C", desc="Synthetic tuition")
        self.insert("taismgr", "tbbdetc", detail_code="FEIT", type_ind="C", desc="Transportation")
        self.insert("taismgr", "tbbdetc", detail_code="SCH1", type_ind="P", desc="Synthetic scholarship")
        for n, term, code, amount, date in [(1, "202510", "TU01", 1000, "2024-12-15"),
                                          (2, "202510", "FEIT", 30, "2025-01-01"),
                                          (3, "202510", "SCH1", 1030, "2026-01-01"),
                                          (4, "202480", "TU01", -50, "2024-08-01")]:
            self.insert("taismgr", "tbraccd", pidm=1, tran_number=n, term_code=term,
                        detail_code=code, amount=amount, effective_date=date)
        for key, charge, amount, reapplied in [(10, 1, 1000, "N"), (11, 2, 30, "N"), (12, 1, -100, "Y")]:
            self.insert("taismgr", "tbrappl", pidm=1, surrogate_id=key, version=1,
                        pay_tran_number=3, chg_tran_number=charge, amount=amount,
                        direct_pay_ind="N", reappl_ind=reapplied, activity_date="2026-01-01")
        self.insert("saturn", "stvrsts", code="RE", incl_sect_enrl="Y")
        self.insert("saturn", "stvrsts", code="DD", incl_sect_enrl="N")
        for crn, status in [(101, "RE"), (102, "DD")]:
            self.insert("saturn", "sfrstcr", pidm=1, term_code="202510", crn=str(crn), rsts_code=status, credit_hr=12)
            self.insert("saturn", "ssbsect", term_code="202510", crn=str(crn), ptrm_code="1",
                        ptrm_start_date="2025-01-14", ptrm_end_date="2025-05-21")
        self.insert("saturn", "sobptrm", term_code="202510", ptrm_code="1", desc="Full term",
                    start_date="2025-01-10", end_date="2025-05-25")
        for term, program in [("202480", "OLD"), ("202510", "NEW"), ("202680", "FUTURE")]:
            self.insert("saturn", "sgbstdn", pidm=1, term_code_eff=term, program_1=program, levl_code="UG", degc_code_1="BS")
        self.client = Mock()
        self.client.run_sql.side_effect = self.execute

    def insert(self, schema: str, table: str, **values: object) -> None:
        columns = ", ".join(f"{table}_{key}" for key in values)
        placeholders = ", ".join("?" for _ in values)
        self.db.execute(f"INSERT INTO {schema}.{table} ({columns}) VALUES ({placeholders})", tuple(values.values()))

    def execute(self, sql: str) -> pd.DataFrame:
        sql = re.sub(r"::(?:text|integer)\b", "", sql)
        return pd.read_sql_query(sql, self.db)

    def test_advance_late_and_prior_term_transactions_preserved(self) -> None:
        frames = extract_data(self.client, "SYNTHETIC001", 2025)
        transactions = frames["transactions"]
        self.assertEqual(transactions.tran_number.tolist(), [1, 2, 3, 4])
        self.assertEqual(transactions.year_term_candidate.tolist(), ["Y", "Y", "Y", "N"])
        self.assertEqual(transactions.term_description.iloc[0], "Spring 2025")
        self.assertEqual(transactions.amount_usd.iloc[-1], -50)

    def test_dropped_courses_and_both_date_sources_preserved(self) -> None:
        frame = extract_data(self.client, "SYNTHETIC001", 2025)["enrollment"]
        self.assertEqual(frame.registration_status.tolist(), ["RE", "DD"])
        self.assertEqual(frame.section_start_date.iloc[0], "2025-01-14")
        self.assertEqual(frame.part_of_term_start_date.iloc[0], "2025-01-10")

    def test_application_extract_preserves_signed_rows_and_links_scholarships(self) -> None:
        frames = extract_data(self.client, "SYNTHETIC001", 2025)
        raw = frames["payment_applications"]
        self.assertEqual(len(raw), 3)
        self.assertEqual(raw.application_amount_usd.tolist(), [1000, 30, -100])
        self.assertTrue(raw.application_activity_date.eq("2026-01-01").all())
        prepared = prepare_payment_applications(raw, prepare_transactions(frames["transactions"], load_rules()))
        self.assertEqual(prepared.application_review_status.tolist(), ["linked"] * 3)
        self.assertEqual(prepared.payment_detail_code.tolist(), ["SCH1"] * 3)
        self.assertEqual(prepared.charge_eligibility_status.tolist(), ["eligible", "excluded", "eligible"])
        self.assertEqual(prepared.application_amount_usd.iloc[2], Decimal("-100"))
        self.assertEqual(prepared.reapplication_ind.iloc[2], "Y")
        self.assertNotIn("application_review_status", raw)

    def test_missing_or_unexpected_application_references_are_visible(self) -> None:
        self.insert("taismgr", "tbrappl", pidm=1, surrogate_id=13, pay_tran_number=999, chg_tran_number=1, amount=5)
        self.insert("taismgr", "tbrappl", pidm=1, surrogate_id=14, pay_tran_number=1, chg_tran_number=2, amount=5)
        frames = extract_data(self.client, "SYNTHETIC001", 2025)
        prepared = prepare_payment_applications(frames["payment_applications"], prepare_transactions(frames["transactions"], load_rules()))
        self.assertEqual(prepared.application_review_status.tolist()[-2:], ["missing_transaction", "review_transaction_types"])

    def test_duplicate_application_ids_fail_but_empty_extract_stays_empty(self) -> None:
        frames = extract_data(self.client, "SYNTHETIC001", 2025)
        transactions = prepare_transactions(frames["transactions"], load_rules())
        raw = frames["payment_applications"]
        with self.assertRaisesRegex(ValueError, "identifiers are missing or duplicated"):
            prepare_payment_applications(pd.concat([raw, raw.iloc[:1]]), transactions)
        self.assertTrue(prepare_payment_applications(raw.iloc[:0], transactions).empty)

    def test_program_is_term_effective_and_keeps_cross_year_term(self) -> None:
        frame = extract_data(self.client, "SYNTHETIC001", 2025)["programs"]
        self.assertEqual(frame.program_code.tolist(), ["OLD", "NEW"])
        self.assertEqual(frame.term_code.tolist(), ["202499", "202510"])

    def test_program_ties_visible_and_duplicate_registration_joins_rejected(self) -> None:
        self.insert("saturn", "sgbstdn", pidm=1, term_code_eff="202510", program_1="TIE")
        frame = extract_data(self.client, "SYNTHETIC001", 2025)["programs"]
        self.assertEqual(len(frame[frame.term_code == "202510"]), 2)
        self.insert("saturn", "sobptrm", term_code="202510", ptrm_code="1")
        with self.assertRaisesRegex(ValueError, "Registration rows are duplicated"):
            extract_data(self.client, "SYNTHETIC001", 2025)

    def test_unknown_or_duplicate_identity_stops_before_financial_queries(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one current identity"):
            extract_data(self.client, "SYNTHETIC002", 2025)
        self.insert("saturn", "spriden", pidm=2, id="SYNTHETIC001")
        with self.assertRaises(ValueError):
            extract_data(self.client, "SYNTHETIC001", 2025)

    def test_schema_inventory_covers_every_referenced_banner_column(self) -> None:
        expected = {f"{table}_{suffix}" for _, table, suffix in self.fields}
        for name in ("identity", "transactions", "enrollment", "programs", "payment_applications"):
            query = render_query(name, "SYNTHETIC001", 2025)
            used = set(re.findall(r"\b(?:spriden|stvterm|tbraccd|tbrappl|tbbdetc|sfrstcr|stvrsts|ssbsect|sobptrm|sgbstdn)_\w+", query))
            self.assertFalse(used - expected)

    def test_schema_query_reports_missing_fields_and_cli_stops_before_student_queries(self) -> None:
        sql = (QUERY_DIRECTORY / "validate_canadian_tax_schema.sql").read_text()
        complete = self.execute(sql)
        self.assertEqual(len(complete), len(self.fields))
        self.assertTrue(complete.validation_status.eq("FOUND").all())
        self.db.execute("DELETE FROM information_schema.columns WHERE column_name = 'sgbstdn_program_1'")
        schema = self.execute(sql)
        self.assertEqual(schema.validation_status.eq("MISSING").sum(), 1)
        self.client.run_sql_file.side_effect = [schema, pd.DataFrame(columns=["column_name"])]
        self.client.run_sql.reset_mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "package"
            args = ["tl11a", "--cwid", "SYNTHETIC001", "--tax-year", "2025", "--output-dir", str(output)]
            with patch("sys.argv", args), patch("workflows.canadian_tax.run_tl11a_data.build_authenticated_client", return_value=(self.client, "synthetic")), patch("builtins.print"):
                self.client.__enter__ = Mock(return_value=self.client)
                self.client.__exit__ = Mock(return_value=False)
                with self.assertRaisesRegex(ValueError, "Required Banner columns are missing"):
                    main()
            self.client.run_sql.assert_not_called()
            self.assertFalse(output.exists())

    def test_end_to_end_cli_package_with_mocked_auth_and_rate(self) -> None:
        schema = pd.DataFrame({"validation_status": ["FOUND"]})
        self.client.run_sql_file.side_effect = [schema, pd.DataFrame(columns=["column_name"])]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "package"
            args = ["tl11a", "--cwid", "SYNTHETIC001", "--tax-year", "2025", "--output-dir", str(output)]
            rate = {"status": "published", "cad_per_usd": "1.3978"}
            with patch("sys.argv", args), patch("workflows.canadian_tax.run_tl11a_data.build_authenticated_client", return_value=(self.client, "synthetic")), patch("workflows.canadian_tax.run_tl11a_data.fetch_annual_rate", return_value=(rate, annual_payload())), patch("builtins.print"):
                self.client.__enter__ = Mock(return_value=self.client)
                self.client.__exit__ = Mock(return_value=False)
                self.assertEqual(main(), 0)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertIsNone(manifest["eligible_paid_usd"])
            self.assertEqual(manifest["exchange_rate"]["cad_per_usd"], "1.3978")
            self.assertEqual(manifest["row_counts"]["transactions"], 4)
            self.assertEqual(manifest["row_counts"]["payment_applications"], 3)
            self.assertEqual(manifest["enrollment_policy"]["minimum_consecutive_days"], 21)
            self.assertTrue((output / "payment_applications_prepared.csv").exists())
            self.assertTrue((output / "enrollment_prepared.csv").exists())
            self.assertTrue((output / "detail_code_review.csv").exists())


if __name__ == "__main__":
    unittest.main()
