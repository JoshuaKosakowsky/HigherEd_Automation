from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


QUERY_ROOT = Path(__file__).resolve().parents[2] / "query" / "AR" / "late_fees"


class LateFeeQueryTests(unittest.TestCase):
    """Execute the report SQL with synthetic Banner tables and explicit scopes."""

    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("BTRIM", 1, lambda s: None if s is None else s.strip())
        self.db.create_function(
            "TRANSLATE", 3,
            lambda s, chars, unused: None if s is None else s.translate(
                str.maketrans("", "", chars)
            ),
        )
        self.db.executescript("ATTACH DATABASE ':memory:' AS general;")
        schemas = {
            "glbextr": "application TEXT, selection TEXT, creator_id TEXT, user_id TEXT, "
                       "key TEXT, activity_date TEXT, sys_ind TEXT, slct_ind TEXT",
            "glbslct": "application TEXT, selection TEXT, creator_id TEXT, desc TEXT, "
                       "type_ind TEXT, activity_date TEXT",
            "glrsfrm": "application TEXT, selection TEXT, creator_id TEXT, "
                       "select_clause TEXT, from_clause TEXT, order_by TEXT, "
                       "group_by TEXT, activity_date TEXT",
            "glrslct": "application TEXT, selection TEXT, creator_id TEXT, key_no INTEGER, "
                       "line_no INTEGER, data_element TEXT, operator TEXT, value TEXT, "
                       "open_paren TEXT, close_paren TEXT, separator TEXT, activity_date TEXT",
            "glrappl": "application TEXT, key_no INTEGER, line_no INTEGER, data_element TEXT, "
                       "operator TEXT, value TEXT, open_paren TEXT, close_paren TEXT, "
                       "separator TEXT, activity_date TEXT",
            "glrcmpl": "application TEXT, vrbl_or_slct TEXT, creator_id TEXT, seq_no INTEGER, "
                       "sub_seq_no INTEGER, sql_length INTEGER, sql_statement TEXT, "
                       "sql_parms TEXT, activity_date TEXT",
        }
        for table, columns in schemas.items():
            definitions = ", ".join(f"{table}_{c}" for c in columns.split(", "))
            self.db.execute(f"CREATE TABLE general.{table} ({definitions})")

    def query(self, filename: str) -> str:
        return (QUERY_ROOT / filename).read_text(encoding="utf-8")

    def rows(self, query: str) -> list[dict]:
        rows = [dict(row) for row in self.db.execute(query).fetchall()]
        self.assertTrue(rows)
        self.assertTrue(all(row["Report Row Count"] == len(rows) for row in rows))
        return rows

    def insert(self, table: str, **fields: object) -> None:
        columns = ", ".join(f"{table}_{key}" for key in fields)
        placeholders = ", ".join("?" for _ in fields)
        self.db.execute(
            f"INSERT INTO general.{table} ({columns}) VALUES ({placeholders})",
            tuple(fields.values()),
        )

    def population(
        self, selection: str, keys: list[str | None], *,
        application: str = "AR_STU", creator: str = "JPHOU", user: str = "TEST_RUNNER",
        date: str | None = "2099-10-01 12:00:00",
    ) -> None:
        for key in keys:
            self.insert(
                "glbextr", application=application, selection=selection,
                creator_id=creator, user_id=user, key=key, activity_date=date,
                sys_ind="S", slct_ind=None,
            )

    def comparison(self, **overrides: str | None) -> list[dict]:
        query = self.query("compare_late_fee_populations.sql")
        values: dict[str, str | None] = {
            "creator_id": "JPHOU", "run_user_id": "TEST_RUNNER",
            "baseline_selection": "TEST_BASELINE",
        }
        values.update(overrides)
        for field, value in values.items():
            literal = "NULL" if value is None else "'" + value.replace("'", "''") + "'"
            query = query.replace(
                f"CAST(NULL AS varchar(30)) AS {field}", f"{literal} AS {field}"
            )
        return self.rows(query)

    def test_same_keys_in_different_order_require_external_run_evidence(self) -> None:
        self.population("TEST_BASELINE", ["101", "102", "103"])
        self.population("AR_LATEFEES_FINAL", ["103", "101", "102"])
        rows = self.comparison()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Comparison Status"], "MATCH_REQUIRES_RUN_EVIDENCE")
        self.assertEqual(rows[0]["Baseline Total Rows"], 3)
        self.assertEqual(rows[0]["Baseline Only Keys"], 0)
        self.assertEqual(rows[0]["Candidate Only Keys"], 0)

    def test_equal_counts_with_different_members_do_not_match(self) -> None:
        self.population("TEST_BASELINE", ["101", "102"])
        self.population("AR_LATEFEES_FINAL", ["102", "103"])
        rows = self.comparison()
        self.assertEqual(rows[0]["Comparison Status"], "DIFFERENT")
        self.assertEqual(rows[0]["Baseline Only Keys"], 1)
        self.assertEqual(rows[0]["Candidate Only Keys"], 1)
        self.assertEqual(
            [(r["Population Key"], r["Membership Status"]) for r in rows[1:]],
            [("101", "BASELINE_ONLY"), ("103", "CANDIDATE_ONLY")],
        )

    def test_duplicate_keys_require_review_even_if_both_sides_have_them(self) -> None:
        self.population("TEST_BASELINE", ["101", "101", "102"])
        self.population("AR_LATEFEES_FINAL", ["101", "101", "101", "102"])
        rows = self.comparison()
        self.assertEqual(rows[0]["Comparison Status"], "DUPLICATE_KEYS_REVIEW")
        self.assertEqual(rows[0]["Baseline Duplicate Rows"], 1)
        self.assertEqual(rows[0]["Candidate Duplicate Rows"], 2)
        self.assertEqual(rows[0]["Candidate Key Groups"], 2)
        self.assertEqual(rows[1]["Membership Status"], "DUPLICATE_KEY")

    def test_missing_both_or_one_population_never_passes(self) -> None:
        self.assertEqual(self.comparison()[0]["Comparison Status"], "INCONCLUSIVE_EMPTY_SIDE")
        self.population("TEST_BASELINE", ["101"])
        self.assertEqual(self.comparison()[0]["Comparison Status"], "INCONCLUSIVE_EMPTY_SIDE")
        self.db.execute("DELETE FROM general.glbextr")
        self.population("AR_LATEFEES_FINAL", ["101"])
        self.assertEqual(self.comparison()[0]["Comparison Status"], "INCONCLUSIVE_EMPTY_SIDE")

    def test_default_and_blank_inputs_are_invalid(self) -> None:
        rows = self.rows(self.query("compare_late_fee_populations.sql"))
        self.assertEqual(rows[0]["Comparison Status"], "INVALID_PARAMETERS")
        for field in ("creator_id", "run_user_id", "baseline_selection"):
            for value in (None, "", " ", " PADDED "):
                with self.subTest(field=field, value=value):
                    self.assertEqual(
                        self.comparison(**{field: value})[0]["Comparison Status"],
                        "INVALID_PARAMETERS",
                    )

    def test_same_population_cannot_be_its_own_baseline(self) -> None:
        self.population("AR_LATEFEES_FINAL", ["101"])
        rows = self.comparison(baseline_selection="AR_LATEFEES_FINAL")
        self.assertEqual(rows[0]["Comparison Status"], "SAME_POPULATION")

    def test_application_creator_and_run_user_all_scope_membership(self) -> None:
        self.population("TEST_BASELINE", ["101"])
        self.population("AR_LATEFEES_FINAL", ["101"])
        self.population("AR_LATEFEES_FINAL", ["201"], application="OTHER")
        self.population("AR_LATEFEES_FINAL", ["202"], creator="OTHER")
        self.population("AR_LATEFEES_FINAL", ["203"], user="OTHER")
        self.population("AR_LATEFEES_5", ["204"])
        rows = self.comparison()
        self.assertEqual(rows[0]["Candidate Total Rows"], 1)
        self.assertEqual(rows[0]["Comparison Status"], "MATCH_REQUIRES_RUN_EVIDENCE")

    def test_comparison_accepts_the_actual_creator_without_a_staff_default(self) -> None:
        self.population("TEST_BASELINE", ["101"], creator="RESULT_OWNER")
        self.population("AR_LATEFEES_FINAL", ["101"], creator="RESULT_OWNER")
        self.population("AR_LATEFEES_FINAL", ["999"])
        rows = self.comparison(creator_id="RESULT_OWNER")
        self.assertEqual(rows[0]["Candidate Total Rows"], 1)
        self.assertEqual(rows[0]["Comparison Status"], "MATCH_REQUIRES_RUN_EVIDENCE")

    def test_invalid_keys_remain_visible_and_block_match(self) -> None:
        keys = [None, "", " ", " 101", "101 ", "abc", "1.0", "-1", "101"]
        self.population("TEST_BASELINE", keys)
        self.population("AR_LATEFEES_FINAL", keys)
        rows = self.comparison()
        self.assertEqual(rows[0]["Comparison Status"], "INVALID_KEYS")
        self.assertEqual(rows[0]["Baseline Invalid Rows"], 8)
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r["Membership Status"] == "INVALID_KEY" for r in rows[1:]))

    def test_raw_keys_are_not_silently_normalized(self) -> None:
        self.population("TEST_BASELINE", ["00101"])
        self.population("AR_LATEFEES_FINAL", ["101"])
        self.assertEqual(self.comparison()[0]["Comparison Status"], "DIFFERENT")

    def test_old_or_null_activity_dates_do_not_certify_freshness(self) -> None:
        self.population("TEST_BASELINE", ["101"], date="1900-01-01")
        self.population("AR_LATEFEES_FINAL", ["101"], date=None)
        rows = self.comparison()
        self.assertEqual(rows[0]["Baseline Oldest Activity"], "1900-01-01")
        self.assertIsNone(rows[0]["Candidate Latest Activity"])
        self.assertEqual(rows[0]["Comparison Status"], "MATCH_REQUIRES_RUN_EVIDENCE")

    def test_inventory_exposes_manual_waiver_scopes_and_preserves_duplicates(self) -> None:
        selection = "AR_WAIVE_MANUAL_LATEFEES"
        self.population(selection, ["101", "101"])
        self.population(selection, ["201"], application="OTHER", creator="OTHER", user="OTHER")
        rows = self.rows(self.query("late_fee_populations.sql"))
        stored = [r for r in rows if r["Evidence Type"] == "STORED_ROW"]
        self.assertEqual(len(stored), 3)
        self.assertEqual({r["Application"] for r in stored}, {"AR_STU", "OTHER"})
        self.assertEqual([r["Rows For Key In Scope"] for r in stored], [2, 2, 1])
        self.assertEqual([r["Stored Rows In Scope"] for r in stored], [2, 2, 1])

    def test_inventory_reports_absence_without_claiming_empty_success(self) -> None:
        rows = self.rows(self.query("late_fee_populations.sql"))
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r["Evidence Type"] == "NO_VISIBLE_ROWS" for r in rows))
        self.assertTrue(all(r["Stored Rows In Scope"] == 0 for r in rows))
        self.assertIn("AR_PP,CO,TO,WO_HOLDS", {r["Selection ID"] for r in rows})

    def test_rules_preserve_order_parentheses_and_unresolved_dynamic_values(self) -> None:
        selection = "AR_LATEFEES_3"
        self.insert("glbslct", application="AR_STU", selection=selection, creator_id="JPHOU",
                    desc="Synthetic FA rule", type_ind=None)
        self.insert("glrsfrm", application="AR_STU", selection=selection, creator_id="JPHOU",
                    select_clause="ROBUSDF_PIDM", from_clause="ROBUSDF,SPRIDEN")
        for line, element, value, op, cl, sep in (
            (2, "ROBUSDF_AIDY_CODE", "&Aid_Year", None, ")", None),
            (1, "ROBUSDF_VALUE_21", "'Y'", "(", None, "AND"),
        ):
            self.insert("glrslct", application="AR_STU", selection=selection,
                        creator_id="JPHOU", key_no=1, line_no=line, data_element=element,
                        operator="=", value=value, open_paren=op, close_paren=cl, separator=sep)
        rows = [r for r in self.rows(self.query("late_fee_rules.sql"))
                if r["Selection ID"] == selection]
        self.assertEqual([r["Evidence Type"] for r in rows],
                         ["SELECTION_HEADER", "SELECT_FROM", "SELECTION_RULE", "SELECTION_RULE"])
        self.assertEqual(rows[1]["From Clause"], "ROBUSDF,SPRIDEN")
        self.assertEqual(rows[2]["Open Paren"], "(")
        self.assertEqual(rows[2]["And/Or"], "AND")
        self.assertEqual(rows[3]["Value"], "&Aid_Year")
        self.assertEqual(rows[3]["Close Paren"], ")")

    def test_headers_preserve_all_owners_and_mark_absent_selections(self) -> None:
        for application, creator, type_ind in (
            ("AR_STU", "JPHOU", None), ("OTHER", "OTHER", "M"),
        ):
            self.insert("glbslct", application=application, selection="AR_LATEFEES_FINAL",
                        creator_id=creator, desc="Synthetic description", type_ind=type_ind)
        self.insert("glbslct", application="AR_STU", selection="UNRELATED",
                    creator_id="JPHOU", desc="Not part of this inventory")
        rows = self.rows(self.query("late_fee_selection_headers.sql"))
        found = [r for r in rows if r["Evidence Type"] == "SELECTION_HEADER"]
        self.assertEqual(len(rows), 11)
        self.assertEqual([(r["Application"], r["Creator ID"], r["Raw Type Indicator"])
                          for r in found], [("AR_STU", "JPHOU", None), ("OTHER", "OTHER", "M")])
        self.assertEqual(sum(r["Evidence Type"] == "NO_VISIBLE_HEADER" for r in rows), 9)
        self.assertNotIn("UNRELATED", {r["Selection ID"] for r in rows})

    def test_available_extracts_work_without_the_missing_rule_tables(self) -> None:
        for table in ("glrsfrm", "glrslct", "glrappl", "glrcmpl"):
            self.db.execute(f"DROP TABLE general.{table}")
        self.insert("glbslct", application="AR_STU", selection="AR_LATEFEES_FINAL",
                    creator_id="JPHOU", desc="Synthetic result")
        self.population("TEST_BASELINE", ["101"])
        self.population("AR_LATEFEES_FINAL", ["101"])
        headers = self.rows(self.query("late_fee_selection_headers.sql"))
        populations = self.rows(self.query("late_fee_populations.sql"))
        self.assertEqual(sum(r["Evidence Type"] == "SELECTION_HEADER" for r in headers), 1)
        self.assertEqual(sum(r["Evidence Type"] == "STORED_ROW" for r in populations), 1)
        self.assertEqual(self.comparison()[0]["Comparison Status"], "MATCH_REQUIRES_RUN_EVIDENCE")

    def waiver_check(self) -> list[dict]:
        return self.rows(self.query("late_fee_waiver_source_check.sql"))

    def test_waiver_source_differences_preserve_scope_and_show_pre_final_membership(self) -> None:
        self.population("AR_LATEFEES_6", ["101", "102"], user="JPHOU")
        self.population("AR_LATEFEES_5", ["101", "104"], user="JPHOU")
        self.population("AR_WAIVE_MANUAL_LATEFEES", ["102"], creator="WAIVER_OWNER")
        self.population("AR_WAIVE_MANUAL_LATEFEES", ["102", "103"], application="STUDENT",
                        creator="OTHER", user="OTHER")
        self.population("AR_LATEFEES_6", ["999"], user="OTHER")
        self.population("AR_LATEFEES_5", ["103"], creator="OTHER", user="JPHOU")
        report = self.waiver_check()
        rows = {r["Population Key"]: r for r in report
                if r["Definition Creator ID"] == "JPHOU" and r["Run User ID"] == "JPHOU"}
        self.assertEqual(set(rows), {"101", "102", "103"})
        self.assertEqual(rows["101"]["Membership Status"], "STORED_EXTRACT_ONLY")
        self.assertEqual(rows["101"]["In Stored Pre-final"], "Y")
        self.assertEqual(rows["102"]["Membership Status"], "BOTH")
        self.assertEqual(rows["102"]["Source Rows For Key"], 2)
        self.assertEqual(rows["102"]["Source Applications For Key"], 2)
        self.assertEqual(rows["102"]["Source Creators For Key"], 2)
        self.assertEqual(rows["102"]["Source Run Users For Key"], 2)
        self.assertEqual(rows["103"]["Membership Status"], "CURRENT_SOURCE_ONLY")
        self.assertEqual(rows["103"]["In Stored Pre-final"], "N")
        self.assertEqual(rows["101"]["Stored Waiver Key Groups"], 2)
        self.assertEqual(rows["101"]["Source Waiver Key Groups"], 2)
        other_run = {r["Population Key"]: r for r in report if r["Run User ID"] == "OTHER"}
        self.assertEqual(set(other_run), {"102", "103", "999"})
        self.assertEqual(other_run["102"]["Membership Status"], "CURRENT_SOURCE_ONLY")
        self.assertEqual(other_run["999"]["Membership Status"], "STORED_EXTRACT_ONLY")
        self.assertIsNone(other_run["103"]["In Stored Pre-final"])
        other_creator = {r["Population Key"]: r for r in report
                         if r["Definition Creator ID"] == "OTHER"}
        self.assertEqual(set(other_creator), {"102", "103"})
        self.assertEqual(other_creator["103"]["In Stored Pre-final"], "Y")
        self.assertEqual(other_creator["103"]["Stored Waiver Key Groups"], 0)

    def test_waiver_diagnostic_keeps_applications_and_invalid_keys_separate(self) -> None:
        self.population("AR_LATEFEES_6", [None, "101"])
        self.population("AR_LATEFEES_6", [None, None, "102"], application="OTHER")
        self.population("AR_LATEFEES_5", ["102"], application="OTHER")
        self.population("AR_WAIVE_MANUAL_LATEFEES", [None, "101", "102"])
        rows = {(r["Application"], r["Population Key"]): r for r in self.waiver_check()}
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[("AR_STU", None)]["Stored Rows For Key"], 1)
        self.assertEqual(rows[("OTHER", None)]["Stored Rows For Key"], 2)
        self.assertEqual(rows[("OTHER", None)]["Membership Status"], "INVALID_KEY")
        self.assertEqual(rows[("AR_STU", "102")]["Membership Status"], "CURRENT_SOURCE_ONLY")
        self.assertIsNone(rows[("AR_STU", "102")]["In Stored Pre-final"])
        self.assertEqual(rows[("OTHER", "102")]["Membership Status"], "BOTH")
        self.assertEqual(rows[("OTHER", "102")]["In Stored Pre-final"], "Y")

    def test_waiver_diagnostic_marks_missing_populations(self) -> None:
        rows = self.waiver_check()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Membership Status"], "NO_VISIBLE_WAIVER_ROWS")
        self.assertEqual(rows[0]["Stored Waiver Key Groups"], 0)
        self.population("AR_WAIVE_MANUAL_LATEFEES", ["101"])
        rows = self.waiver_check()
        self.assertEqual(rows[0]["Membership Status"], "SOURCE_WITHOUT_STORED_SCOPE")
        self.assertIsNone(rows[0]["Application"])
        self.assertIsNone(rows[0]["Definition Creator ID"])
        self.assertIsNone(rows[0]["Run User ID"])
        self.assertIsNone(rows[0]["In Stored Pre-final"])
        self.assertEqual(rows[0]["Stored Pre-final Key Groups"], 0)

    def test_pre_final_only_scope_retains_a_missing_waiver_marker(self) -> None:
        self.population("AR_LATEFEES_5", ["101"], creator="RESULT_OWNER", user="OPERATOR")
        rows = self.waiver_check()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Membership Status"], "NO_VISIBLE_WAIVER_ROWS")
        self.assertEqual(rows[0]["Stored Pre-final Key Groups"], 1)
        self.assertEqual(rows[0]["Definition Creator ID"], "RESULT_OWNER")
        self.assertEqual(rows[0]["Run User ID"], "OPERATOR")

    def test_waiver_diagnostic_exposes_invalid_keys_and_duplicate_stored_rows(self) -> None:
        self.population("AR_LATEFEES_6", [None, "bad", "101", "101"], user="JPHOU")
        self.population("AR_WAIVE_MANUAL_LATEFEES", [None, "bad", "101"])
        rows = {r["Population Key"]: r for r in self.waiver_check()}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[None]["Membership Status"], "INVALID_KEY")
        self.assertEqual(rows["bad"]["Membership Status"], "INVALID_KEY")
        self.assertEqual(rows["101"]["Stored Rows For Key"], 2)

    def test_application_rules_and_missing_headers_are_distinct(self) -> None:
        self.insert("glrappl", application="AR_STU", key_no=1, line_no=1,
                    data_element="SPRIDEN_CHANGE_IND", operator="IS NULL")
        self.insert("glrappl", application="OTHER", key_no=1, line_no=1,
                    data_element="DO_NOT_INCLUDE")
        self.insert("glbslct", application="AR_STU", selection="AR_LATEFEES_FINAL",
                    creator_id="JPHOU", desc="Generated result")
        self.insert("glbslct", application="AR_STU", selection="AR_LATEFEES_1",
                    creator_id="OTHER", desc="Another result creator")
        self.insert("glbslct", application="STUDENT", selection="AR_WAIVE_MANUAL_LATEFEES",
                    creator_id="WAIVER_OWNER", desc="Another application")
        self.insert("glrappl", application="STUDENT", key_no=1, line_no=1,
                    data_element="SYNTHETIC_STUDENT_RULE")
        rows = self.rows(self.query("late_fee_rules.sql"))
        app_rules = [r for r in rows if r["Evidence Type"] == "APPLICATION_RULE"]
        self.assertEqual({r["Application"] for r in app_rules}, {"AR_STU", "STUDENT"})
        self.assertNotIn("DO_NOT_INCLUDE", {r["Data Element"] for r in app_rules})
        self.assertEqual(sum(r["Evidence Type"] == "SELECTION_HEADER" for r in rows), 3)
        missing = [r for r in rows if r["Evidence Type"] == "MISSING_HEADER"]
        self.assertEqual(len(missing), 7)
        self.assertTrue(all(r["Application"] is None and r["Creator ID"] is None for r in missing))

    def test_no_visible_application_rules_has_an_explicit_marker(self) -> None:
        self.insert("glbslct", application="STUDENT", selection="AR_WAIVE_MANUAL_LATEFEES",
                    creator_id="WAIVER_OWNER")
        rows = self.rows(self.query("late_fee_rules.sql"))
        missing = [r for r in rows if r["Evidence Type"] == "NO_VISIBLE_APPLICATION_RULES"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["Application"], "STUDENT")

    def test_rule_inventory_keeps_other_staff_metadata_when_a_header_is_missing(self) -> None:
        for selection in ("AR_WAIVE_MANUAL_LATEFEES", "UNRELATED"):
            self.insert("glrsfrm", application="STUDENT", selection=selection,
                        creator_id="WAIVER_OWNER", select_clause="SPRIDEN_PIDM",
                        from_clause="SPRIDEN")
            self.insert("glrslct", application="STUDENT", selection=selection,
                        creator_id="WAIVER_OWNER", key_no=1, line_no=1,
                        data_element="SYNTHETIC_ELEMENT", operator="=", value="'Y'")
        self.insert("glrappl", application="STUDENT", key_no=1, line_no=1,
                    data_element="SYNTHETIC_APPLICATION_RULE")
        rows = self.rows(self.query("late_fee_rules.sql"))
        definitions = [r for r in rows if r["Evidence Type"] in ("SELECT_FROM", "SELECTION_RULE")]
        self.assertEqual(len(definitions), 2)
        self.assertTrue(all(r["Application"] == "STUDENT" for r in definitions))
        self.assertTrue(all(r["Creator ID"] == "WAIVER_OWNER" for r in definitions))
        self.assertNotIn("UNRELATED", {r["Selection ID"] for r in rows})
        self.assertEqual(sum(r["Evidence Type"] == "APPLICATION_RULE" for r in rows), 1)
        self.assertEqual(sum(r["Evidence Type"] == "MISSING_HEADER" for r in rows), 10)

    def test_compiled_chunks_are_preserved_and_sorted_without_execution(self) -> None:
        for seq, subseq in [(2, 1), (1, 2), (1, 1)]:
            self.insert("glrcmpl", application="AR_STU", vrbl_or_slct="AR_LATEFEES_3",
                        creator_id="JPHOU", seq_no=seq, sub_seq_no=subseq,
                        sql_length=300, sql_statement="X" * 300, sql_parms="&Aid_Year")
        self.insert("glrcmpl", application="AR_STU", vrbl_or_slct="AR_LATEFEES_3",
                    creator_id="OTHER", seq_no=0, sql_statement="OTHER")
        rows = [r for r in self.rows(self.query("late_fee_compiled_sql.sql"))
                if r["Evidence Type"] == "COMPILED_ROW"]
        self.assertEqual([(r["Creator ID"], r["Sequence No"], r["Subsequence No"]) for r in rows],
                         [("JPHOU", 1, 1), ("JPHOU", 1, 2), ("JPHOU", 2, 1), ("OTHER", 0, None)])
        self.assertTrue(all(len(r["SQL Statement"]) == 300 for r in rows[:3]))

    def test_schema_inventory_distinguishes_wrong_schema_from_found(self) -> None:
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS information_schema;
            CREATE TABLE information_schema.columns (
                table_schema TEXT, table_name TEXT, column_name TEXT, data_type TEXT
            );
            INSERT INTO information_schema.columns VALUES
                ('general', 'glbextr', 'glbextr_key', 'character varying'),
                ('other', 'glbextr', 'glbextr_selection', 'character varying');
        """)
        # SQLite lacks ordered STRING_AGG; only the display aggregation differs.
        query = self.query("validate_late_fee_schema.sql").replace(
            "STRING_AGG(DISTINCT a.table_schema, ', ' ORDER BY a.table_schema)",
            "GROUP_CONCAT(DISTINCT a.table_schema)",
        )
        rows = {r["Expected Column"]: dict(r) for r in self.db.execute(query)}
        self.assertEqual(rows["glbextr_key"]["Validation Status"], "FOUND")
        self.assertEqual(rows["glbextr_selection"]["Validation Status"], "MISSING")
        self.assertEqual(rows["glbextr_selection"]["Schemas With This Column"], "other")
        self.assertIsNone(rows["glbextr_user_id"]["Schemas With This Column"])


if __name__ == "__main__":
    unittest.main()
