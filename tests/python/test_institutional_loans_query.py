from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUERY_PATH = (
    REPOSITORY_ROOT
    / "query"
    / "AR"
    / "loans"
    / "less_than_half_time_institutional_loans.sql"
)
SCHEMA_PATH = QUERY_PATH.with_name("validate_loan_schema.sql")
SUMMER_BAND_QUERY_PATH = QUERY_PATH.with_name(
    "half_time_less_than_full_time_institutional_loans_summer.sql"
)
FULL_TIME_QUERY_PATH = QUERY_PATH.with_name(
    "full_time_and_above_institutional_loans_summer.sql"
)
COMBINED_QUERY_PATH = QUERY_PATH.with_name(
    "all_enrollment_load_categories_institutional_loans_summer.sql"
)


class InstitutionalLoansQueryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.query = QUERY_PATH.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.query).upper()
        cls.summer_band_query = SUMMER_BAND_QUERY_PATH.read_text(encoding="utf-8")
        cls.summer_band_normalized = re.sub(
            r"\s+", " ", cls.summer_band_query
        ).upper()
        cls.full_time_query = FULL_TIME_QUERY_PATH.read_text(encoding="utf-8")
        cls.full_time_normalized = re.sub(
            r"\s+", " ", cls.full_time_query
        ).upper()
        cls.combined_query = COMBINED_QUERY_PATH.read_text(encoding="utf-8")
        cls.combined_normalized = re.sub(
            r"\s+", " ", cls.combined_query
        ).upper()

    def test_uses_one_required_target_term_parameter(self) -> None:
        self.assertEqual(self.query.count("{{target_term}}"), 1)
        self.assertIn("P.TARGET_TERM", self.normalized)
        self.assertNotIn("CAST('202655' AS VARCHAR(6))", self.normalized)

    def test_loan_activity_is_scoped_to_target_term(self) -> None:
        section = self.query[
            self.query.index("loan_activity AS") :
            self.query.index("loan_population AS")
        ].upper()
        self.assertIn("T.TBRACCD_TERM_CODE = P.TARGET_TERM", section)

    def test_hours_include_only_enrollment_counting_statuses(self) -> None:
        section = self.query[
            self.query.index("registration_hours AS") :
            self.query.index("loan_activity AS")
        ].upper()
        self.assertIn("SATURN.STVRSTS", section)
        self.assertIn("STVRSTS_INCL_SECT_ENRL", section)
        self.assertIn("= 'Y'", section)
        self.assertIn("SFRSTCR_BILL_HR", section)
        self.assertIn("AS BILLABLE_HOURS", section)

    def test_zero_hour_loan_recipients_are_retained(self) -> None:
        self.assertIn("LEFT JOIN REGISTRATION_HOURS", self.normalized)
        self.assertIn(
            "COALESCE(HOURS.CREDIT_HOURS, 0)",
            self.normalized,
        )

    def test_output_distinguishes_enrollment_from_billing(self) -> None:
        self.assertIn('AS "CREDIT HOURS"', self.normalized)
        self.assertIn('AS "BILLABLE HOURS"', self.normalized)
        self.assertNotIn('AS "NON-ENROLLED BILLABLE HOURS"', self.normalized)
        self.assertNotIn('AS "BILLABLE REGISTRATION STATUS CODES"', self.normalized)
        self.assertNotIn('AS "ENROLLMENT/BILLING NOTE"', self.normalized)

    def test_requested_output_column_order_and_removed_summaries(self) -> None:
        final_select = self.query[self.query.rindex("SELECT\n") :].upper()
        headings = (
            "FIRST NAME",
            "DETAIL CODE",
            "DETAIL CODE DESCRIPTION",
            "DETAIL CODE LOAN ACTIVITY",
            "LAST LOAN ACTIVITY DATE",
            "LEVEL",
        )
        positions = [final_select.index(f'AS "{heading}"') for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('AS "TOTAL SELECTED LOAN ACTIVITY"', final_select)
        self.assertNotIn('AS "TRANSACTION COUNT"', final_select)
        self.assertNotIn("COUNT(*) AS TRANSACTION_COUNT", self.normalized)

    def test_less_than_half_time_thresholds_are_preserved(self) -> None:
        self.assertRegex(
            self.normalized,
            r"STUDENT\.STUDENT_LEVEL = 'UG'.+?HOURS\.CREDIT_HOURS, 0\) < 6",
        )
        self.assertRegex(
            self.normalized,
            r"STUDENT\.STUDENT_LEVEL = 'GR'.+?HOURS\.CREDIT_HOURS, 0\) < 4\.5",
        )

    def test_summer_half_time_to_less_than_full_time_thresholds(self) -> None:
        self.assertRegex(
            self.summer_band_normalized,
            r"STUDENT\.STUDENT_LEVEL = 'UG'.+?CREDIT_HOURS, 0\) >= 6"
            r".+?CREDIT_HOURS, 0\) < 12",
        )
        self.assertRegex(
            self.summer_band_normalized,
            r"STUDENT\.STUDENT_LEVEL = 'GR'.+?CREDIT_HOURS, 0\) >= 4\.5"
            r".+?CREDIT_HOURS, 0\) < 9",
        )
        self.assertNotIn("CREDIT_HOURS, 0) <= 12", self.summer_band_normalized)
        self.assertNotIn("CREDIT_HOURS, 0) <= 9", self.summer_band_normalized)

    def test_summer_band_report_preserves_the_same_output_columns(self) -> None:
        original_select = self.query[self.query.rindex("SELECT\n") :]
        summer_band_select = self.summer_band_query[
            self.summer_band_query.rindex("SELECT\n") :
        ]
        self.assertEqual(summer_band_select, original_select)
        self.assertEqual(self.summer_band_query.count("{{target_term}}"), 1)
        for code in ("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001"):
            with self.subTest(code=code):
                self.assertIn(f"('{code}')", self.summer_band_normalized)

    def test_summer_full_time_and_above_thresholds(self) -> None:
        self.assertRegex(
            self.full_time_normalized,
            r"STUDENT\.STUDENT_LEVEL = 'UG'.+?CREDIT_HOURS, 0\) >= 12",
        )
        self.assertRegex(
            self.full_time_normalized,
            r"STUDENT\.STUDENT_LEVEL = 'GR'.+?CREDIT_HOURS, 0\) >= 9",
        )
        full_time_filter = self.full_time_query[
            self.full_time_query.index("    WHERE\n        (", self.full_time_query.index("report_rows AS")) :
            self.full_time_query.rindex("\n)\n\nSELECT")
        ].upper()
        self.assertNotIn("CREDIT_HOURS, 0) <", full_time_filter)

    def test_full_time_report_preserves_the_same_output_columns(self) -> None:
        original_select = self.query[self.query.rindex("SELECT\n") :]
        full_time_select = self.full_time_query[
            self.full_time_query.rindex("SELECT\n") :
        ]
        self.assertEqual(full_time_select, original_select)
        self.assertEqual(self.full_time_query.count("{{target_term}}"), 1)
        for code in ("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001"):
            with self.subTest(code=code):
                self.assertIn(f"('{code}')", self.full_time_normalized)

    def test_combined_report_covers_each_summer_enrollment_band(self) -> None:
        for fragment in (
            "STUDENT.STUDENT_LEVEL = 'UG'",
            "HOURS.CREDIT_HOURS, 0) < 6",
            "HOURS.CREDIT_HOURS, 0) < 12",
            "STUDENT.STUDENT_LEVEL = 'GR'",
            "HOURS.CREDIT_HOURS, 0) < 4.5",
            "HOURS.CREDIT_HOURS, 0) < 9",
            "THEN 'LESS THAN HALF TIME'",
            "THEN 'HALF TIME BUT LESS THAN FULL TIME'",
            "THEN 'FULL TIME AND ABOVE'",
            "WHERE STUDENT.STUDENT_LEVEL IN ('UG', 'GR')",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.combined_normalized)
        self.assertIn(
            'AS "ENROLLMENT LOAD CATEGORY"', self.combined_normalized
        )

    def test_combined_report_preserves_all_base_output_columns(self) -> None:
        original_select = self.query[self.query.rindex("SELECT\n") :]
        combined_select = self.combined_query[
            self.combined_query.rindex("SELECT\n") :
        ]
        without_category = combined_select.replace(
            '    r.enrollment_load_category AS "Enrollment Load Category",\n',
            "",
        )
        self.assertEqual(without_category.rstrip(), original_select.rstrip())
        self.assertEqual(self.combined_query.count("{{target_term}}"), 1)

    def test_student_record_is_term_effective(self) -> None:
        self.assertIn("S.SGBSTDN_TERM_CODE_EFF <= P.TARGET_TERM", self.normalized)
        self.assertIn("ORDER BY S.SGBSTDN_TERM_CODE_EFF DESC", self.normalized)
        self.assertIn("STUDENT.RECORD_RANK = 1", self.normalized)
        self.assertIn("S.SGBSTDN_EXP_GRAD_DATE", self.normalized)
        self.assertIn('AS "EXPECTED GRADUATION DATE"', self.normalized)

    def test_total_earned_credits_use_overall_level_totals_only(self) -> None:
        section = self.query[
            self.query.index("accumulated_earned_credits AS") :
            self.query.index("student_record_candidates AS")
        ].upper()
        self.assertIn("SATURN.SHRLGPA", section)
        self.assertIn("SHRLGPA_HOURS_EARNED", section)
        self.assertIn("SHRLGPA_GPA_TYPE_IND = 'O'", section)
        self.assertNotIn("SHRLGPA_GPA_TYPE_IND = 'I'", section)
        self.assertNotIn("SHRLGPA_GPA_TYPE_IND = 'T'", section)
        self.assertIn('AS "TOTAL EARNED CREDIT HOURS"', self.normalized)

    def test_returning_type_check_explains_yes_and_no_results(self) -> None:
        self.assertIn("STUDENT.STUDENT_TYPE_CODE = 'X'", self.normalized)
        self.assertIn("YES - X (RETURNING STUDENT)", self.normalized)
        self.assertIn("NO - STUDENT TYPE IS BLANK", self.normalized)
        self.assertIn("AS RETURNING_STUDENT_TYPE_CHECK", self.normalized)
        self.assertIn('AS "RETURNING STUDENT TYPE CHECK"', self.normalized)
        self.assertNotIn('AS "RETURNING STUDENT"', self.normalized)

    def test_returning_source_is_documented_for_banner_users(self) -> None:
        documentation = QUERY_PATH.with_name("README.md").read_text(
            encoding="utf-8"
        )
        for term in ("SGASTDN", "Learner", "SGBSTDN_STYP_CODE", "STVSTYP"):
            with self.subTest(term=term):
                self.assertIn(term, documentation)
        self.assertIn("`X` = Returning Student", documentation)
        self.assertIn("`C` = Continuing", documentation)

    def test_contact_fields_are_ranked_without_multiplying_report_rows(self) -> None:
        self.assertIn("ADDRESS_CANDIDATES AS", self.normalized)
        self.assertIn("EMAIL_CANDIDATES AS", self.normalized)
        self.assertIn("PHONE_CANDIDATES AS", self.normalized)
        self.assertIn("ROW_NUMBER() OVER", self.normalized)
        self.assertIn("ADDRESS.ADDRESS_RANK = 1", self.normalized)
        self.assertIn("PHONE.PHONE_RANK = 1", self.normalized)
        for heading in (
            "STREET",
            "CITY",
            "STATE",
            "ZIP",
            "SCHOOL EMAIL",
            "PERSONAL EMAIL",
            "PHONE NUMBER",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f'AS "{heading}"', self.normalized)

    def test_contact_type_assumptions_are_explicit(self) -> None:
        for code in ("MA", "PR", "UNIV", "PER1"):
            with self.subTest(code=code):
                self.assertIn(f"'{code}'::VARCHAR", self.normalized)

    def test_original_detail_code_population_is_preserved(self) -> None:
        for code in ("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001"):
            with self.subTest(code=code):
                self.assertIn(f"('{code}')", self.normalized)
        self.assertNotIn("('CLTL')", self.normalized)
        self.assertNotIn("('LEWL')", self.normalized)

    def test_schema_inventory_covers_report_sources(self) -> None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8").upper()
        self.assertIn("('SATURN', 'STVRSTS', 'INCL_SECT_ENRL')", schema)
        self.assertIn("('SATURN', 'SFRSTCR', 'BILL_HR')", schema)
        self.assertIn("('SATURN', 'SGBSTDN', 'STYP_CODE')", schema)
        self.assertIn("('SATURN', 'SGBSTDN', 'EXP_GRAD_DATE')", schema)
        self.assertIn("('SATURN', 'SHRLGPA', 'HOURS_EARNED')", schema)
        self.assertIn("('SATURN', 'SHRLGPA', 'GPA_TYPE_IND')", schema)
        self.assertIn("('SATURN', 'STVSTYP', 'DESC')", schema)
        self.assertIn("('SATURN', 'SPRADDR', 'STREET_LINE1')", schema)
        self.assertIn("('GENERAL', 'GOREMAL', 'EMAIL_ADDRESS')", schema)
        self.assertIn("('SATURN', 'SPRTELE', 'PHONE_NUMBER')", schema)
        self.assertIn("'MISSING'", schema)
        self.assertIn("'FOUND'", schema)


class InstitutionalLoansPostgresTests(unittest.TestCase):
    """Execute the report against temporary tables containing synthetic data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = os.environ.get("REFUNDS_TEST_DSN")
        cls.psql = os.environ.get("REFUNDS_TEST_PSQL") or shutil.which("psql")
        if not cls.dsn:
            raise unittest.SkipTest(
                "Set REFUNDS_TEST_DSN for synthetic PostgreSQL tests"
            )
        if not cls.psql:
            raise RuntimeError("REFUNDS_TEST_DSN is set but psql is unavailable")

        query = QUERY_PATH.read_text(encoding="utf-8")
        cls.query = re.sub(
            r"\b(?:general|taismgr|saturn)\.", "pg_temp.", query
        )
        cls.query = cls.query.replace("{{target_term}}", "'209980'")
        combined_query = COMBINED_QUERY_PATH.read_text(encoding="utf-8")
        cls.combined_query = re.sub(
            r"\b(?:general|taismgr|saturn)\.", "pg_temp.", combined_query
        )
        cls.combined_query = cls.combined_query.replace(
            "{{target_term}}", "'209980'"
        )

    def run_report(self, report_query: str | None = None) -> list[dict]:
        schemas = {
            "sfrstcr": "pidm int, term_code text, rsts_code text, credit_hr numeric, bill_hr numeric",
            "stvrsts": "code text, incl_sect_enrl text",
            "tbraccd": "pidm int, term_code text, detail_code text, amount numeric, activity_date timestamp",
            "sgbstdn": "pidm int, term_code_eff text, levl_code text, styp_code text, exp_grad_date date",
            "shrlgpa": "pidm int, levl_code text, gpa_type_ind text, hours_earned numeric",
            "spriden": "pidm int, id text, last_name text, first_name text, change_ind text",
            "stvstyp": "code text, desc text",
            "tbbdetc": "detail_code text, desc text, type_ind text",
            "spraddr": "pidm int, atyp_code text, seqno int, street_line1 text, street_line2 text, street_line3 text, city text, stat_code text, zip text, status_ind text, from_date date, to_date date",
            "goremal": "pidm int, emal_code text, email_address text, status_ind text, preferred_ind text, activity_date timestamp",
            "sprtele": "pidm int, seqno int, phone_area text, phone_number text, phone_ext text, primary_ind text, status_ind text",
        }
        sql = ["BEGIN; SET LOCAL statement_timeout = '15s';"]
        for table, columns in schemas.items():
            prefixed = ", ".join(
                f"{table}_{column}" for column in columns.split(", ")
            )
            sql.append(f"CREATE TEMP TABLE {table} ({prefixed});")

        def insert(table: str, values: tuple) -> None:
            literals = [
                "NULL"
                if value is None
                else "'" + str(value).replace("'", "''") + "'"
                for value in values
            ]
            sql.append(f"INSERT INTO {table} VALUES ({', '.join(literals)});")

        insert("stvrsts", ("RE", "Y"))
        insert("stvrsts", ("WD", "N"))
        insert("stvstyp", ("C", "Continuing"))
        insert("stvstyp", ("X", "Returning Student"))
        for code in ("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001"):
            insert("tbbdetc", (code, f"Synthetic {code}", "P"))

        # PIDM 1 is a returning undergraduate with five enrolled credits.
        # Its withdrawn course and prior-term loan must not affect the report.
        insert("sfrstcr", (1, "209980", "RE", 5, 5))
        insert("sfrstcr", (1, "209980", "WD", 3, 3))
        insert("tbraccd", (1, "209980", "PERK", 100, "2099-08-01"))
        insert("tbraccd", (1, "209980", "CFDN", 50, "2099-08-02"))
        insert("tbraccd", (1, "209910", "PERK", 900, "2099-01-01"))
        insert(
            "spraddr",
            (1, "PR", 1, "1 Permanent Rd", None, None, "Golden", "CO", "80401", None, "2020-01-01", None),
        )
        insert(
            "spraddr",
            (1, "MA", 2, "2 Mailing St", "Apt 3", None, "Denver", "CO", "80202", None, "2024-01-01", None),
        )
        insert(
            "goremal",
            (1, "UNIV", "student@mines.edu", "A", "Y", "2025-01-01"),
        )
        insert(
            "goremal",
            (1, "PER1", "student@example.com", "A", None, "2025-01-02"),
        )
        insert("sprtele", (1, 1, "303", "5550101", None, "Y", None))
        insert("sprtele", (1, 2, "720", "5550102", None, None, None))
        # Overall rows are summed across levels; component I/T rows are ignored.
        insert("shrlgpa", (1, "UG", "I", 15))
        insert("shrlgpa", (1, "UG", "T", 5))
        insert("shrlgpa", (1, "UG", "O", 20))
        insert("shrlgpa", (1, "GR", "O", 2))

        # Boundary students at exactly half time must be excluded.
        insert("sfrstcr", (2, "209980", "RE", 6, 6))
        insert("tbraccd", (2, "209980", "PERK", 200, "2099-08-01"))
        insert("sfrstcr", (4, "209980", "RE", Decimal("4.5"), Decimal("4.5")))
        insert("tbraccd", (4, "209980", "PERK", 400, "2099-08-01"))

        # A four-credit graduate and a zero-hour undergraduate must be included.
        insert("sfrstcr", (3, "209980", "RE", 4, 4))
        insert("tbraccd", (3, "209980", "PERK", 300, "2099-08-01"))
        insert("tbraccd", (5, "209980", "PERK", 500, "2099-08-01"))

        # A dropped-only student can have billable hours but zero enrolled credits.
        insert("sfrstcr", (6, "209980", "WD", 3, 3))
        insert("tbraccd", (6, "209980", "PERK", 600, "2099-08-01"))

        # Exact Summer full-time boundaries belong in the highest band.
        insert("sfrstcr", (7, "209980", "RE", 12, 12))
        insert("tbraccd", (7, "209980", "PERK", 700, "2099-08-01"))
        insert("sfrstcr", (8, "209980", "RE", 9, 9))
        insert("tbraccd", (8, "209980", "PERK", 800, "2099-08-01"))

        levels = {
            1: "UG",
            2: "UG",
            3: "GR",
            4: "GR",
            5: "UG",
            6: "UG",
            7: "UG",
            8: "GR",
        }
        for pidm, level in levels.items():
            insert("spriden", (pidm, f"TEST-{pidm}", "Synthetic", f"Person{pidm}", None))
            insert("sgbstdn", (pidm, "209910", level, "C", "2099-05-01"))
            insert(
                "sgbstdn",
                (
                    pidm,
                    "209980",
                    level,
                    "X" if pidm == 1 else "C",
                    "2100-05-01" if pidm == 1 else None,
                ),
            )
        # A future Returning record must not change PIDM 5's target-term flag.
        insert("sgbstdn", (5, "210010", "UG", "X", "2101-05-01"))

        sql.append(
            "SELECT COALESCE(JSON_AGG(report), '[]'::json) FROM ("
            + (report_query or self.query).rstrip().removesuffix(";")
            + ") report; ROLLBACK;"
        )
        result = subprocess.run(
            [self.psql, "-X", "-qAt", "--set=ON_ERROR_STOP=1", "--dbname", self.dsn],
            input="\n".join(sql),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout, parse_float=Decimal)

    def test_population_hours_term_scope_and_returning_flag(self) -> None:
        rows = self.run_report()
        self.assertEqual(
            [row["ID"] for row in rows],
            ["TEST-1", "TEST-1", "TEST-3", "TEST-5", "TEST-6"],
        )

        first = rows[0]
        self.assertEqual(first["Credit Hours"], 5)
        self.assertEqual(first["Billable Hours"], 8)
        self.assertEqual(
            first["Returning Student Type Check"],
            "Yes - X (Returning Student)",
        )
        self.assertEqual(first["Total Earned Credit Hours"], 22)
        self.assertEqual(first["Expected Graduation Date"], "2100-05-01")
        self.assertIn(first["Detail Code Loan Activity"], (50, 100))
        self.assertNotIn("Total Selected Loan Activity", first)
        self.assertNotIn("Transaction Count", first)
        self.assertEqual(first["Street"], "2 Mailing St, Apt 3")
        self.assertEqual(first["City"], "Denver")
        self.assertEqual(first["State"], "CO")
        self.assertEqual(first["Zip"], "80202")
        self.assertEqual(first["School Email"], "student@mines.edu")
        self.assertEqual(first["Personal Email"], "student@example.com")
        self.assertEqual(first["Phone Number"], "(303) 5550101")

        graduate = next(row for row in rows if row["ID"] == "TEST-3")
        self.assertEqual(graduate["Credit Hours"], 4)
        self.assertEqual(
            graduate["Returning Student Type Check"],
            "No - C (Continuing)",
        )

        zero_hour = next(row for row in rows if row["ID"] == "TEST-5")
        self.assertEqual(zero_hour["Credit Hours"], 0)
        self.assertEqual(zero_hour["Billable Hours"], 0)
        self.assertEqual(
            zero_hour["Returning Student Type Check"],
            "No - C (Continuing)",
        )
        self.assertEqual(zero_hour["Total Earned Credit Hours"], 0)
        self.assertIsNone(zero_hour["Expected Graduation Date"])

        dropped = next(row for row in rows if row["ID"] == "TEST-6")
        self.assertEqual(dropped["Credit Hours"], 0)
        self.assertEqual(dropped["Billable Hours"], 3)

    def test_combined_report_assigns_every_boundary_once(self) -> None:
        rows = self.run_report(self.combined_query)
        categories = {
            row["ID"]: row["Enrollment Load Category"] for row in rows
        }
        self.assertEqual(categories["TEST-1"], "Less Than Half Time")
        self.assertEqual(
            categories["TEST-2"], "Half Time but Less Than Full Time"
        )
        self.assertEqual(categories["TEST-3"], "Less Than Half Time")
        self.assertEqual(
            categories["TEST-4"], "Half Time but Less Than Full Time"
        )
        self.assertEqual(categories["TEST-5"], "Less Than Half Time")
        self.assertEqual(categories["TEST-6"], "Less Than Half Time")
        self.assertEqual(categories["TEST-7"], "Full Time and Above")
        self.assertEqual(categories["TEST-8"], "Full Time and Above")
        self.assertEqual(len(rows), 9)


if __name__ == "__main__":
    unittest.main()
