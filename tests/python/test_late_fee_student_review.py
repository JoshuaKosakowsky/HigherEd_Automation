"""Student enrichment and complete API extraction with synthetic data only."""
from __future__ import annotations

import re
import sqlite3
import unittest
from unittest.mock import MagicMock

import pandas as pd

from shared.insights.client import InsightsAPIError
from shared.insights.paged_report import extract_paged_report
from shared.insights.query_catalog import get_query


QUERY = get_query("late_fee_student_review")


class LateFeeStudentReviewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.create_function("TRANSLATE", 3, lambda value, chars, _: None if value is None
                                else value.translate(str.maketrans("", "", chars)))
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS general;
            ATTACH DATABASE ':memory:' AS saturn;
            ATTACH DATABASE ':memory:' AS taismgr;
            CREATE TABLE general.glbextr (glbextr_application TEXT, glbextr_selection TEXT,
                glbextr_creator_id TEXT, glbextr_user_id TEXT, glbextr_key TEXT,
                glbextr_activity_date TEXT);
            CREATE TABLE general.glbslct (glbslct_application TEXT, glbslct_selection TEXT,
                glbslct_creator_id TEXT, glbslct_desc TEXT);
            CREATE TABLE general.goremal (goremal_pidm INTEGER, goremal_emal_code TEXT,
                goremal_email_address TEXT, goremal_status_ind TEXT, goremal_activity_date TEXT);
            CREATE TABLE saturn.spriden (spriden_pidm INTEGER, spriden_id TEXT,
                spriden_first_name TEXT, spriden_last_name TEXT, spriden_change_ind TEXT);
            CREATE TABLE saturn.sprhold (sprhold_pidm INTEGER, sprhold_hldd_code TEXT,
                sprhold_from_date TEXT, sprhold_to_date TEXT);
            CREATE TABLE taismgr.tbraccd (tbraccd_pidm INTEGER, tbraccd_term_code TEXT,
                tbraccd_detail_code TEXT, tbraccd_amount NUMERIC, tbraccd_balance NUMERIC);
            CREATE TABLE taismgr.tbbdetc (tbbdetc_detail_code TEXT, tbbdetc_type_ind TEXT);
            INSERT INTO taismgr.tbbdetc VALUES ('CHRG','C'),('PAYM','P'),('LPPF','C');
        """)

    def member(self, key, selection="AR_LATEFEES_FINAL", app="AR_STU", creator="OWNER", user="RUNNER"):
        self.db.execute("INSERT INTO general.glbextr VALUES (?,?,?,?,?,?)",
                        (app,selection,creator,user,key,"2099-10-01 10:00:00"))

    def identity(self, pidm=101, cwid="TEST-101", change=None):
        self.db.execute("INSERT INTO saturn.spriden VALUES (?,?,'Synthetic','Student',?)",
                        (pidm,cwid,change))

    def transaction(self, amount, code="CHRG", term="209980", balance=0, pidm=101):
        self.db.execute("INSERT INTO taismgr.tbraccd VALUES (?,?,?,?,?)", (pidm,term,code,amount,balance))

    def sql(self):
        sql = QUERY.render_sql("209980").replace("CURRENT_DATE", "'2099-10-02'")
        # Only syntax adapters: SQLite's DISTINCT aggregate takes one argument.
        sql = re.sub(r"STRING_AGG\(DISTINCT (.*?), '(?:, |; )'\)", r"GROUP_CONCAT(DISTINCT \1)", sql, flags=re.S)
        sql = re.sub(r"CAST\((h\.sprhold_(?:from|to)_date) AS date\)", r"date(\1)", sql)
        return sql

    def rows(self):
        rows = [dict(r) for r in self.db.execute(self.sql())]
        self.assertTrue(all(r["Report Row Count"] == len(rows) for r in rows))
        self.assertEqual([r["__Report Row Number"] for r in rows], list(range(1,len(rows)+1)))
        return rows

    def test_identity_and_selected_term_financials_preserve_reversal_signs(self):
        self.member("101")
        self.identity()
        self.identity(cwid="OLD-101", change="I")
        for amount,code in ((1000,"CHRG"),(-100,"CHRG"),(200,"PAYM"),(-50,"PAYM")):
            self.transaction(amount,code)
        self.transaction(15,"LPPF",balance=5)
        self.transaction(50,"PAYM",term="209955")
        self.db.execute("INSERT INTO general.goremal VALUES (101,'UNIV','synthetic@example.invalid','A','2099-10-01')")
        row = self.rows()[0]
        self.assertEqual((row["CWID"],row["Identity Status"]),("TEST-101","MATCHED"))
        self.assertEqual(row["PIDM"], "101")
        self.assertEqual(row["Mines Email"],"synthetic@example.invalid")
        self.assertEqual((row["Current Term Charges"],row["Current Term Payments"],row["Current Term Net Balance"]),(915,150,765))
        self.assertEqual(row["Current All-Term Account Balance"],715)
        self.assertEqual(row["Other Term Credit"],"Yes")
        self.assertEqual(row["Posted LPPF Amount - Selected Term"],15)
        self.assertEqual(row["Remaining LPPF Balance - Selected Term"],5)
        self.assertEqual(row["Financial Context Term"],"209980")

    def test_all_staff_sources_are_deduplicated_without_mixing_result_scopes(self):
        self.member("101")
        self.member("101",user="SECOND_RUNNER",creator="SECOND_OWNER")
        for app,user in (("AR_STU","STAFF_A"),("STUDENT","STAFF_B")):
            self.member("101","AR_WAIVE_MANUAL_LATEFEES",app,creator="WAIVER_OWNER",user=user)
        self.member("101","AR_LATEFEES_3",creator="RULE_OWNER")
        self.identity()
        rows = self.rows()
        self.assertEqual(len(rows),5)
        finals = [r for r in rows if r["Selection ID"]=="AR_LATEFEES_FINAL"]
        self.assertEqual(len(finals),2)
        self.assertTrue(all(r["Manual Waiver Source Rows"]==2 and r["Manual Waiver Staff Count"]==2 for r in finals))
        self.assertTrue(all(r["In Current Shared Manual Waivers"]=="Y" for r in finals))
        self.assertIn("AR_LATEFEES_3",next(r for r in finals if r["Run User ID"]=="RUNNER")["Stored Selections For This Run User"])
        self.assertNotIn("AR_LATEFEES_3",next(r for r in finals if r["Run User ID"]=="SECOND_RUNNER")["Stored Selections For This Run User"])

    def test_missing_ambiguous_and_invalid_identities_never_remove_members(self):
        for key in ("101","102","103","bad",None,"00101"):
            self.member(key)
        self.identity()
        self.identity(102,"TEST-102-A")
        self.identity(102,"TEST-102-B")
        rows = {r["Population Key"]:r for r in self.rows()}
        self.assertEqual(len(rows),6)
        self.assertEqual(rows["102"]["Identity Status"],"MULTIPLE_CURRENT_IDENTITIES")
        self.assertIsNone(rows["102"]["CWID"])
        self.assertEqual(rows["103"]["Identity Status"],"MISSING_IDENTITY")
        self.assertEqual(rows["bad"]["Identity Status"],"INVALID_KEY")
        self.assertEqual(rows[None]["Identity Status"],"INVALID_KEY")
        self.assertEqual(rows["00101"]["CWID"],"TEST-101")

    def test_duplicate_metadata_contacts_and_members_do_not_multiply_amounts(self):
        self.member("101")
        self.member("101")
        self.identity()
        self.transaction(100)
        for _ in range(2):
            self.db.execute("INSERT INTO general.glbslct VALUES ('AR_STU','AR_LATEFEES_FINAL','OWNER','Synthetic')")
            self.db.execute("INSERT INTO general.goremal VALUES (101,'UNIV','synthetic@example.invalid','A','2099-10-01')")
            self.db.execute("INSERT INTO saturn.sprhold VALUES (101,'PP','2099-01-01','2100-01-01')")
        rows = self.rows()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["Current Term Net Balance"],100)
        self.assertEqual(rows[0]["Stored Rows For Key"],2)
        self.assertEqual(rows[0]["Hold Record Count"],2)

    def test_unknown_financial_inputs_stay_blank_instead_of_plausible_totals(self):
        self.member("101")
        self.identity()
        self.transaction(100)
        self.db.execute("INSERT INTO taismgr.tbbdetc VALUES ('CHRG','C')")
        row = self.rows()[0]
        self.assertEqual(row["Invalid Financial Rows"],1)
        self.assertIsNone(row["Current Term Net Balance"])
        self.assertIsNone(row["Current All-Term Account Balance"])
        self.assertEqual(row["Other Term Credit"],"Unknown")

    def test_no_transactions_differ_from_zero_activity_in_selected_term(self):
        self.member("101")
        self.identity()
        self.assertIsNone(self.rows()[0]["Current Term Net Balance"])
        self.transaction(100,term="209955")
        row = self.rows()[0]
        self.assertEqual(row["Current Term Net Balance"],0)
        self.assertEqual(row["Current All-Term Account Balance"],100)

    def test_missing_amount_and_lppf_balance_never_become_zero(self):
        self.member("101")
        self.identity()
        self.transaction(None, "LPPF", balance=None)
        row = self.rows()[0]
        self.assertEqual(row["Invalid Financial Rows"], 1)
        self.assertIsNone(row["Current Term Net Balance"])
        self.assertIsNone(row["Posted LPPF Amount - Selected Term"])
        self.assertIsNone(row["Remaining LPPF Balance - Selected Term"])
        self.assertIn("Missing remaining balance", row["Review Notes"])

    def test_blank_cwid_is_flagged_and_latest_active_university_email_is_used(self):
        self.member("101")
        self.identity(cwid=" ")
        for code, email, status, day in (
            ("UNIV", "old@example.invalid", "A", "2099-10-01"),
            ("UNIV", "latest@example.invalid", "A", "2099-10-02"),
            ("UNIV", "inactive@example.invalid", "I", "2099-10-03"),
            ("PERS", "personal@example.invalid", "A", "2099-10-03"),
        ):
            self.db.execute("INSERT INTO general.goremal VALUES (101,?,?,?,?)", (code, email, status, day))
        row = self.rows()[0]
        self.assertEqual(row["Identity Status"], "MISSING_CWID")
        self.assertEqual(row["Mines Email"], "latest@example.invalid")
        self.assertIn("no CWID", row["Review Notes"])

    def test_hold_dates_are_context_and_never_filter_population(self):
        self.member("101")
        self.identity()
        for code,start,end in (("PP",None,"2100-01-01"),("CO","2099-11-01","2100-01-01"),
                               ("AU","2099-01-01","2099-10-02"),("TO",None,None)):
            self.db.execute("INSERT INTO saturn.sprhold VALUES (101,?,?,?)",(code,start,end))
        row = self.rows()[0]
        self.assertEqual(row["Active Hold Codes"],"PP")
        for code in ("PP","CO","AU","TO"):
            self.assertIn(code,row["Hold History"])

    def test_unrelated_population_does_not_enter_review(self):
        self.member("101",selection="UNRELATED")
        self.assertEqual(self.rows(),[])

    def test_actual_query_can_be_paged_under_a_smaller_api_cap(self):
        for key in ("101","102","103","104","105"):
            self.member(key)
        class Executor:
            def run_sql(inner, sql):
                return pd.read_sql_query(sql,self.db).iloc[:2].copy()
        result = extract_paged_report(Executor(),self.sql(),page_size=3)
        self.assertEqual(result["Population Key"].tolist(),["101","102","103","104","105"])
        self.assertNotIn("__Report Row Number",result.columns)


class PagedReportTests(unittest.TestCase):
    def frame(self, ordinals, total=3):
        return pd.DataFrame({"CWID":[f"TEST-{n}" for n in ordinals],
                             "__Report Row Number":ordinals,"Report Row Count":[total]*len(ordinals)})

    def test_changed_counts_missing_pages_and_repeated_ordinals_fail_closed(self):
        for pages in ([self.frame([1,2]),self.frame([3],4)],
                      [self.frame([1,2]),self.frame([])],
                      [self.frame([1,2]),self.frame([2])],
                      [self.frame([1,3])],
                      [self.frame([1,2]).drop(columns="Report Row Count")]):
            with self.subTest(pages=len(pages)):
                executor=MagicMock()
                executor.run_sql.side_effect=pages
                with self.assertRaises(InsightsAPIError):
                    extract_paged_report(executor,"SELECT 1",page_size=2)

    def test_empty_result_preserves_columns_and_invalid_guard_values_fail(self):
        executor=MagicMock()
        executor.run_sql.return_value=self.frame([])
        self.assertTrue(extract_paged_report(executor,"SELECT 1").empty)
        for value in (None,True,-1,"bad",1.5):
            executor.run_sql.return_value=self.frame([1],value)
            with self.subTest(value=value),self.assertRaises(InsightsAPIError):
                extract_paged_report(executor,"SELECT 1")

    def test_report_too_large_for_excel_is_rejected_before_more_pages(self):
        executor=MagicMock()
        executor.run_sql.return_value=self.frame([1],1_048_576)
        with self.assertRaises(InsightsAPIError):
            extract_paged_report(executor,"SELECT 1")
        executor.run_sql.assert_called_once()


if __name__ == "__main__":
    unittest.main()
