from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path


QUERY_ROOT = Path(__file__).resolve().parents[2] / "query" / "AR" / "holds"


class DeliquentStudentAccountsTests(unittest.TestCase):
    """Execute the report with synthetic accounts and a fixed run date."""

    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS taismgr;
            ATTACH DATABASE ':memory:' AS saturn;
            ATTACH DATABASE ':memory:' AS general;
            CREATE TABLE taismgr.tbraccd (
                tbraccd_pidm INTEGER, tbraccd_amount NUMERIC,
                tbraccd_detail_code TEXT, tbraccd_term_code TEXT,
                tbraccd_balance NUMERIC, tbraccd_due_date TEXT
            );
            CREATE TABLE taismgr.tbbdetc (
                tbbdetc_detail_code TEXT, tbbdetc_type_ind TEXT
            );
            INSERT INTO taismgr.tbbdetc VALUES
                ('CHARGE', 'C'), ('PAYMENT', 'P'), ('UNKNOWN', 'X');
            CREATE TABLE saturn.sgbstdn (
                sgbstdn_pidm INTEGER, sgbstdn_term_code_eff TEXT
            );
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT,
                spriden_first_name TEXT, spriden_last_name TEXT,
                spriden_change_ind TEXT
            );
            CREATE TABLE saturn.sprhold (
                sprhold_pidm INTEGER, sprhold_hldd_code TEXT,
                sprhold_from_date TEXT, sprhold_to_date TEXT
            );
            CREATE TABLE general.goremal (
                goremal_pidm INTEGER, goremal_emal_code TEXT,
                goremal_email_address TEXT, goremal_status_ind TEXT,
                goremal_preferred_ind TEXT, goremal_activity_date TEXT
            );
            CREATE TABLE saturn.sprtele (
                sprtele_pidm INTEGER, sprtele_seqno INTEGER,
                sprtele_phone_area TEXT, sprtele_phone_number TEXT,
                sprtele_phone_ext TEXT, sprtele_primary_ind TEXT,
                sprtele_status_ind TEXT
            );
        """)
        query = (QUERY_ROOT / "deliquent_student_accounts.sql").read_text()
        # SQLite's CAST(... AS date) is not a date conversion. Adapt only that
        # syntax and the clock; run the actual report for all selection logic.
        self.query = re.sub(
            r"CAST\(([ht]\.\w+_date) AS date\)", r"date(\1)", query
        ).replace("CURRENT_DATE", "'2099-10-02'")

    def add_account(
        self, pidm: int, transactions: list[tuple[str, float | None]],
        *, student: bool = True,
    ) -> None:
        self.db.execute(
            "INSERT INTO saturn.spriden VALUES (?, ?, 'Synthetic', 'Student', NULL)",
            (pidm, f"TEST-{pidm}"),
        )
        if student:
            self.db.execute(
                "INSERT INTO saturn.sgbstdn VALUES (?, '209810')", (pidm,)
            )
        for index, (detail, amount) in enumerate(transactions):
            self.db.execute(
                "INSERT INTO taismgr.tbraccd VALUES (?, ?, ?, ?, ?, ?)",
                (pidm, amount, detail, '209810' if index == 0 else '209980',
                 amount if detail == 'CHARGE' else 0, '2099-10-01'),
            )

    def add_hold(
        self, pidm: int, start: str | None, end: str | None,
        code: str = "PP",
    ) -> None:
        self.db.execute(
            "INSERT INTO saturn.sprhold VALUES (?, ?, ?, ?)",
            (pidm, code, start, end),
        )

    def results(self) -> dict[str, float]:
        cursor = self.db.execute(self.query)
        self.assertEqual(
            [column[0] for column in cursor.description],
            ["CWID", "First Name", "Last Name", "Amt", "Past Due Amt",
             "Preferred Email", "Preferred Phone", "Hold"],
        )
        return {row[0]: row[3] for row in cursor.fetchall()}

    def test_cross_term_netting_and_signed_reversals(self) -> None:
        self.add_account(1, [("CHARGE", 100), ("PAYMENT", 40)])
        self.add_account(2, [("CHARGE", 100), ("PAYMENT", 100)])
        self.add_account(3, [("CHARGE", 100), ("PAYMENT", 150)])
        self.add_account(4, [("CHARGE", 100), ("CHARGE", -25),
                             ("PAYMENT", 20), ("PAYMENT", -5)])
        self.add_account(5, [("CHARGE", 0.004)])
        self.assertEqual(self.results(), {"TEST-1": 60, "TEST-4": 60})

    def test_hold_start_end_and_null_boundaries(self) -> None:
        for pidm in range(1, 10):
            self.add_account(pidm, [("CHARGE", 100)])
        self.add_hold(1, "2099-10-02", "2099-10-03")  # active
        self.add_hold(2, "2099-10-01", "2099-10-02 23:59:59")  # ends today
        self.add_hold(3, "2099-10-01", "2099-10-01")  # expired
        self.add_hold(4, "2099-10-03", "2099-12-31")  # future start
        self.add_hold(5, None, "2099-12-31")  # active, unspecified start
        self.add_hold(6, "2099-10-01", None)  # no qualifying end
        self.add_hold(7, "2099-10-01", "2099-12-31", "ED")
        self.add_hold(8, "2099-10-02 14:00:00", "2099-12-31", " pp ")
        self.assertEqual(self.results(), {f"TEST-{pidm}": 100 for pidm in range(1, 10)})
        holds = {row[0]: row[7] for row in self.db.execute(self.query)}
        self.assertEqual(holds, {
            f"TEST-{pidm}": 'PP' if pidm in (1, 5, 8) else None
            for pidm in range(1, 10)
        })

    def test_multiple_pp_holds_mark_account_without_multiplying_balances(self) -> None:
        self.add_account(1, [("CHARGE", 100)])
        self.add_account(2, [("CHARGE", 100)])
        for _ in range(2):
            self.add_hold(1, "2099-01-01", "2099-01-02")
            self.add_hold(2, "2099-01-01", "2099-01-02")
        self.add_hold(2, "2099-01-01", "2099-12-31")
        self.add_hold(2, "2099-01-01", "2099-12-31")
        rows = self.db.execute(self.query).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([(row[0], row[3], row[7]) for row in rows], [
            ("TEST-1", 100, None), ("TEST-2", 100, 'PP'),
        ])

    def test_collections_holds_exclude_accounts_regardless_of_dates(self) -> None:
        for pidm in range(1, 8):
            self.add_account(pidm, [("CHARGE", 100)])
        self.add_hold(1, "2099-10-01", "2099-12-31", "CO")
        self.add_hold(2, "2099-01-01", "2099-01-02", "CO")  # expired
        self.add_hold(3, "2099-10-03", "2099-12-31", "CO")  # future start
        self.add_hold(4, None, None, " co ")
        self.add_hold(5, "2099-10-01", "2099-10-02", "CO")  # ends today
        self.add_hold(6, "2099-01-01", "2099-01-02", "PP")
        self.add_hold(6, "2099-01-01", "2099-12-31", "PP")
        self.add_hold(6, "2099-01-01", "2099-01-02", "CO")
        self.add_hold(6, "2099-10-01", "2099-12-31", "CO")
        # A CO record belonging to another account must not exclude pidm 7.
        self.assertEqual(self.results(), {"TEST-7": 100})

    def test_student_history_and_current_identity(self) -> None:
        self.add_account(1, [("CHARGE", 100)])
        self.add_account(2, [("CHARGE", 100)], student=False)
        self.db.execute("INSERT INTO saturn.sgbstdn VALUES (1, '209910')")
        self.db.execute(
            "INSERT INTO saturn.spriden VALUES (1, 'TEST-OLD', 'Old', 'Name', 'N')"
        )
        rows = self.db.execute(self.query).fetchall()
        self.assertEqual(
            rows, [("TEST-1", "Synthetic", "Student", 100, 100, None, None, None)]
        )

    def test_incomplete_balances_are_excluded(self) -> None:
        for pidm, detail, amount in (
            (1, "MISSING", 10), (2, "UNKNOWN", 10), (3, "CHARGE", None),
        ):
            self.add_account(pidm, [("CHARGE", 100), (detail, amount)])
        self.assertEqual(self.results(), {})

    def test_past_due_uses_remaining_charges_and_excludes_due_today(self) -> None:
        self.add_account(1, [("CHARGE", 100), ("PAYMENT", 40)])
        self.db.execute(
            "UPDATE taismgr.tbraccd SET tbraccd_balance = 60 "
            "WHERE tbraccd_detail_code = 'CHARGE'"
        )
        self.db.executemany(
            "INSERT INTO taismgr.tbraccd VALUES (1, ?, 'CHARGE', '209980', ?, ?)",
            [(20, 20, '2099-10-02 01:00:00'),
             (30, 30, '2099-10-03'), (10, 0, '2099-09-01'),
             (-5, -5, '2099-09-01')],
        )
        row = self.db.execute(self.query).fetchone()
        self.assertEqual(row[3:5], (115, 60))

    def test_missing_past_due_data_is_blank_and_known_not_due_is_zero(self) -> None:
        for pidm in range(1, 6):
            self.add_account(pidm, [("CHARGE", 100)])
        self.db.execute(
            "UPDATE taismgr.tbraccd SET tbraccd_balance = NULL WHERE tbraccd_pidm = 1"
        )
        self.db.execute(
            "UPDATE taismgr.tbraccd SET tbraccd_due_date = NULL WHERE tbraccd_pidm = 2"
        )
        self.db.execute(
            "UPDATE taismgr.tbraccd SET tbraccd_due_date = '2099-10-03' "
            "WHERE tbraccd_pidm = 3"
        )
        self.db.execute(
            "UPDATE taismgr.tbraccd SET tbraccd_balance = 0, tbraccd_due_date = NULL "
            "WHERE tbraccd_pidm = 4"
        )
        self.add_account(6, [("CHARGE", 100), ("PAYMENT", 90)])
        rows = {row[0]: row[3:5] for row in self.db.execute(self.query)}
        self.assertEqual(rows, {
            'TEST-1': (100, None), 'TEST-2': (100, None), 'TEST-3': (100, 0),
            'TEST-4': (100, 0), 'TEST-5': (100, 100), 'TEST-6': (10, 100),
        })

    def test_contacts_rank_without_duplicates_and_keep_missing_contacts(self) -> None:
        for pidm in range(1, 4):
            self.add_account(pidm, [("CHARGE", 100)])
        self.db.executemany(
            "INSERT INTO general.goremal VALUES (?, ?, ?, ?, ?, ?)",
            [(1, 'PERS', 'personal@example.invalid', 'A', 'Y', '2099-10-02'),
             (1, 'UNIV', 'old@example.invalid', 'A', 'Y', '2099-01-01'),
             (1, 'UNIV', 'school@example.invalid', 'A', 'Y', '2099-10-01'),
             (1, 'UNIV', 'inactive@example.invalid', 'I', 'Y', '2099-10-02'),
             (1, 'UNIV', 'unpreferred@example.invalid', 'A', 'N', '2099-10-02'),
             (1, 'UNIV', 'undated@example.invalid', 'A', 'Y', None),
             (1, 'UNIV', ' ', 'A', 'Y', '2099-10-02'),
             (2, 'PERS', 'fallback@example.invalid', 'A', 'Y', '2099-01-01')],
        )
        self.db.executemany(
            "INSERT INTO saturn.sprtele VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(1, 1, '303', '5550101', None, 'Y', None),
             (1, 2, '720', '5550102', '123', 'Y', None),
             (1, 3, '720', '5550103', None, 'Y', 'I'),
             (1, 4, '720', '5550104', None, 'N', None),
             (1, 5, '720', ' ', None, 'Y', None),
             (2, 1, None, '5550105', None, 'Y', None)],
        )
        rows = self.db.execute(self.query).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual([row[3] for row in rows], [100, 100, 100])
        self.assertEqual([row[5:7] for row in rows], [
            ('school@example.invalid', '(720) 5550102 x123'),
            ('fallback@example.invalid', '5550105'), (None, None),
        ])


if __name__ == "__main__":
    unittest.main()
