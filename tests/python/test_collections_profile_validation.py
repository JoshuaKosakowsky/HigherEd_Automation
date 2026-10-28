"""Exercise aggregate-only validation, including deliberately wrong report output."""
import unittest

from test_collections_student_profile import CollectionsProfileSQLFixture, sqlite_sql


class CollectionsProfileValidationTests(CollectionsProfileSQLFixture):
    def setUp(self):
        super().setUp()
        self.validation_sql = self.query.sql_path.with_name(
            "validate_collections_profile_indicators.sql",
        ).read_text(encoding="utf-8")

    def validation_rows(self, sql=None):
        return [dict(row) for row in self.db.execute(sqlite_sql(sql or self.validation_sql))]

    def replace_report_expression(self, old, new):
        self.assertEqual(self.validation_sql.count(old), 1)
        return self.validation_sql.replace(old, new, 1)

    def test_all_combinations_totals_duplicate_attributes_and_identifier_free_output(self):
        for pidm, codes in ((1, ("FGA", "FGA")), (2, ("FGF",)),
                            (3, (" fga ", "fgf")), (4, ()), (5, ("BLSS",))):
            self.student(pidm)
            for code in codes:
                self.insert("saturn.sgrsatt", pidm, "209980", code)
        self.insert("saturn.sgrsatt", 1, "209910", "FGF")
        self.insert("saturn.sprhold", 1, "CO", "2099-02-01", "2099-05-10")
        self.insert("saturn.sprhold", 1, "CO", "2099-09-10", "9999-12-31")
        rows = self.validation_rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual(list(rows[0]), [
            "Summary", "First Generation Admissions", "First Generation FAFSA",
            "CO Hold Rows", "Distinct Students", "Admissions Mismatch Rows",
            "FAFSA Mismatch Rows", "Attribute Term Mismatch Rows", "Mismatch Rows",
            "Rows Without CO Term", "Rows With CO Term But No Attribute Set", "Validation Status",
        ])
        self.assertEqual(rows[0]["CO Hold Rows"], 6)
        self.assertEqual(rows[0]["Distinct Students"], 5)
        combinations = {(r["First Generation Admissions"], r["First Generation FAFSA"]): r
                        for r in rows[1:]}
        self.assertEqual({key: row["CO Hold Rows"] for key, row in combinations.items()}, {
            ("Yes", "Yes"): 1, ("Yes", "Unknown"): 1,
            ("Unknown", "Yes"): 2, ("Unknown", "Unknown"): 2,
        })
        self.assertTrue(all(row["Mismatch Rows"] == 0 for row in rows))
        self.assertTrue(all(row["Validation Status"] == "OK" for row in rows))
        self.assertNotIn("TEST-", repr(rows))
        self.assertNotIn("Synthetic", repr(rows))
        self.assertEqual(sum(r["Distinct Students"] for r in rows[1:]), 6)

    def test_empty_population_keeps_total_and_four_zero_combinations(self):
        rows = self.validation_rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["Summary"], "Total")
        for row in rows:
            self.assertEqual(row["CO Hold Rows"], 0)
            self.assertEqual(row["Distinct Students"], 0)
            self.assertEqual(row["Mismatch Rows"], 0)
            self.assertEqual(row["Validation Status"], "NO ROWS")

    def test_wrong_admissions_mapping_is_detected_from_source_attributes(self):
        self.student()
        self.insert("saturn.sgrsatt", 1, "209980", "FGA")
        bad = self.replace_report_expression(
            "CASE WHEN a.first_generation_admissions = 1 THEN 'Yes' ELSE 'Unknown'",
            "CASE WHEN a.first_generation_fafsa = 1 THEN 'Yes' ELSE 'Unknown'",
        )
        total = self.validation_rows(bad)[0]
        self.assertEqual(total["Admissions Mismatch Rows"], 1)
        self.assertEqual(total["FAFSA Mismatch Rows"], 0)
        self.assertEqual(total["Mismatch Rows"], 1)
        self.assertEqual(total["Validation Status"], "MISMATCH")

    def test_wrong_fafsa_mapping_is_detected_from_source_attributes(self):
        self.student()
        self.insert("saturn.sgrsatt", 1, "209980", "FGF")
        bad = self.replace_report_expression(
            "CASE WHEN a.first_generation_fafsa = 1 THEN 'Yes' ELSE 'Unknown'",
            "CASE WHEN a.first_generation_admissions = 1 THEN 'Yes' ELSE 'Unknown'",
        )
        total = self.validation_rows(bad)[0]
        self.assertEqual(total["Admissions Mismatch Rows"], 0)
        self.assertEqual(total["FAFSA Mismatch Rows"], 1)
        self.assertEqual(total["Validation Status"], "MISMATCH")

    def test_no_null_blank_and_unexpected_values_are_flagged_and_visible(self):
        self.student()
        old = ("CASE WHEN a.first_generation_admissions = 1 THEN 'Yes' ELSE 'Unknown'\n"
               "         END AS \"First Generation Admissions\"")
        for expression, displayed in (("'No'", "[INVALID]"), ("NULL", "[NULL]"),
                                      ("''", "[BLANK]"), ("'YES'", "[INVALID]"),
                                      ("i.spriden_id", "[INVALID]"),
                                      ("i.spriden_last_name", "[INVALID]")):
            with self.subTest(expression=expression):
                bad = self.replace_report_expression(
                    old, expression + ' AS "First Generation Admissions"',
                )
                rows = self.validation_rows(bad)
                self.assertEqual(len(rows), 6)
                self.assertEqual(rows[0]["Admissions Mismatch Rows"], 1)
                unexpected = next(r for r in rows[1:] if r["First Generation Admissions"] == displayed)
                self.assertEqual(unexpected["CO Hold Rows"], 1)
                self.assertEqual(unexpected["Validation Status"], "MISMATCH")
                self.assertNotIn("TEST-", repr(rows))
                self.assertNotIn("Synthetic", repr(rows))

    def test_wrong_attribute_term_is_detected_even_when_both_flags_agree(self):
        self.student()
        self.insert("saturn.sgrsatt", 1, "209910", "FGA")
        self.insert("saturn.sgrsatt", 1, "210010", "FGF")
        bad = self.replace_report_expression(
            'a.attribute_term AS "Attribute Effective Term"',
            '\'210010\' AS "Attribute Effective Term"',
        )
        total = self.validation_rows(bad)[0]
        self.assertEqual(total["Admissions Mismatch Rows"], 0)
        self.assertEqual(total["FAFSA Mismatch Rows"], 0)
        self.assertEqual(total["Attribute Term Mismatch Rows"], 1)
        self.assertEqual(total["Mismatch Rows"], 1)

    def test_multiple_mismatches_in_one_report_row_are_counted_once(self):
        self.student()
        self.insert("saturn.sgrsatt", 1, "209980", "FGA")
        self.insert("saturn.sgrsatt", 1, "209980", "FGF")
        bad = self.validation_sql
        for source in ("admissions", "fafsa"):
            bad = bad.replace(
                f"CASE WHEN a.first_generation_{source} = 1 THEN 'Yes' ELSE 'Unknown'",
                "CASE WHEN 1 = 0 THEN 'Yes' ELSE 'Unknown'",
                1,
            )
        bad = bad.replace('a.attribute_term AS "Attribute Effective Term"',
                          '\'210010\' AS "Attribute Effective Term"', 1)
        total = self.validation_rows(bad)[0]
        self.assertEqual(total["Admissions Mismatch Rows"], 1)
        self.assertEqual(total["FAFSA Mismatch Rows"], 1)
        self.assertEqual(total["Attribute Term Mismatch Rows"], 1)
        self.assertEqual(total["Mismatch Rows"], 1)

    def test_missing_or_ambiguous_context_is_counted_without_false_mismatch(self):
        self.student(1, start="2099-02-01")
        self.student(2, start="2099-07-01")
        self.student(3, start=None)
        self.student(4)
        self.insert("saturn.stvterm", "209981", "Overlapping", "2099-08-01", "2099-12-31")
        for pidm in (1, 2, 3, 4):
            self.insert("saturn.sgrsatt", pidm, "210010", "FGA")
            self.insert("saturn.sgrsatt", pidm, "210010", "FGF")
        for pidm in (2, 3, 4):
            self.insert("saturn.sgrsatt", pidm, "209810", "FGA")
        total = self.validation_rows()[0]
        self.assertEqual(total["CO Hold Rows"], 4)
        self.assertEqual(total["Rows Without CO Term"], 3)
        self.assertEqual(total["Rows With CO Term But No Attribute Set"], 1)
        self.assertEqual(total["Mismatch Rows"], 0)
        self.assertEqual(total["Validation Status"], "OK")

    def test_embedded_sql_matches_the_authoritative_report(self):
        marker = "-- BEGIN COLLECTIONS PROFILE SQL\n"
        end = "\n-- END COLLECTIONS PROFILE SQL"
        self.assertEqual(self.validation_sql.count(marker), 1)
        self.assertEqual(self.validation_sql.count(end), 1)
        embedded = self.validation_sql.split(marker, 1)[1].split(end, 1)[0]
        self.assertEqual(embedded, self.query.render_sql().strip().removesuffix(";"))


if __name__ == "__main__":
    unittest.main()
