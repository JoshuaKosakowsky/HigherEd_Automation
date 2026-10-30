/*
Issue #21: term balances without a current AU hold. Read-only PostgreSQL.
Current Mines term plus two previous terms; one row per student/term.
Amount = signed charges minus payments posted to that term, not stored balance.
Account Balance includes ALL terms, including future and older activity.
Any negative net term flags the account for cross-term-credit review. Never
allocate that credit or suppress a positive term because the account nets zero.
Amount w/ LF = ROUND(Amount * 1.015, 2), blank for review accounts.
AU uses ONLY TO_DATE > today. PP remains included with the existing delinquency
report's start/end rule. See term_balances_no_au_README.md for accepted rules.
*/
WITH
params AS (
    SELECT CURRENT_DATE AS report_date
),
/* Same boundaries as config/institutions/mines/banner_terms.json. */
term_context AS (
    SELECT CAST(EXTRACT(YEAR FROM report_date) AS integer) AS report_year,
        CASE
            WHEN report_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM report_date) AS integer), 5, 15) THEN 0
            WHEN report_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM report_date) AS integer), 7, 15) THEN 1
            ELSE 2
        END AS term_index
    FROM params
),
term_offsets (term_offset) AS (VALUES (0), (1), (2)),
report_terms AS (
    SELECT CONCAT(
        CASE WHEN c.term_index - n.term_offset < 0
            THEN c.report_year - 1 ELSE c.report_year END,
        CASE (c.term_index - n.term_offset + 3) % 3
            WHEN 0 THEN '10' WHEN 1 THEN '55' ELSE '80' END
    ) AS term_code
    FROM term_context c CROSS JOIN term_offsets n
),
population AS (
    SELECT DISTINCT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN report_terms r ON r.term_code = t.tbraccd_term_code
    WHERE EXISTS (
        SELECT 1 FROM saturn.sgbstdn student
        WHERE student.sgbstdn_pidm = t.tbraccd_pidm
    )
      AND NOT EXISTS (
          SELECT 1 FROM saturn.sprhold h CROSS JOIN params p
          WHERE h.sprhold_pidm = t.tbraccd_pidm
            AND UPPER(TRIM(h.sprhold_hldd_code)) = 'AU'
            AND CAST(h.sprhold_to_date AS date) > p.report_date
      )
),
/* Group metadata first so a duplicate code cannot multiply monetary rows. */
detail_types AS (
    SELECT d.tbbdetc_detail_code AS detail_code,
        CASE WHEN COUNT(*) = 1 THEN MAX(UPPER(TRIM(d.tbbdetc_type_ind))) END AS detail_type
    FROM taismgr.tbbdetc d
    GROUP BY d.tbbdetc_detail_code
),
term_balances AS (
    SELECT t.tbraccd_pidm AS pidm, t.tbraccd_term_code AS term_code,
        SUM(CASE WHEN t.tbraccd_amount IS NULL
                       OR d.detail_type IS NULL OR d.detail_type NOT IN ('C', 'P')
            THEN 1 ELSE 0 END) AS invalid_rows,
        SUM(CASE WHEN NULLIF(TRIM(t.tbraccd_term_code), '') IS NULL
            THEN 1 ELSE 0 END) AS missing_term_rows,
        SUM(CASE d.detail_type WHEN 'C' THEN t.tbraccd_amount
            WHEN 'P' THEN -t.tbraccd_amount END) AS raw_amount,
        CASE WHEN SUM(CASE WHEN t.tbraccd_amount IS NULL
                                    OR d.detail_type IS NULL OR d.detail_type NOT IN ('C', 'P')
            THEN 1 ELSE 0 END) > 0 THEN NULL
            ELSE ROUND(SUM(CASE d.detail_type
                WHEN 'C' THEN t.tbraccd_amount WHEN 'P' THEN -t.tbraccd_amount END), 2)
        END AS amount
    FROM taismgr.tbraccd t
    INNER JOIN population p ON p.pidm = t.tbraccd_pidm
    LEFT JOIN detail_types d ON d.detail_code = t.tbraccd_detail_code
    GROUP BY t.tbraccd_pidm, t.tbraccd_term_code
),
account_context AS (
    SELECT pidm,
        CASE WHEN SUM(invalid_rows) > 0 THEN NULL
            ELSE ROUND(SUM(raw_amount), 2) END AS account_balance,
        SUM(invalid_rows) AS invalid_rows,
        SUM(missing_term_rows) AS missing_term_rows,
        MAX(CASE WHEN amount < 0 THEN 1 ELSE 0 END) AS cross_term_credit
    FROM term_balances
    GROUP BY pidm
),
identities AS (
    SELECT s.spriden_pidm AS pidm, s.spriden_id, s.spriden_last_name,
        s.spriden_first_name,
        COUNT(*) OVER (PARTITION BY s.spriden_pidm) AS identity_count,
        ROW_NUMBER() OVER (PARTITION BY s.spriden_pidm
            ORDER BY s.spriden_id, s.spriden_last_name, s.spriden_first_name) AS identity_rank
    FROM saturn.spriden s
    INNER JOIN population p ON p.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
),
pp_holds AS (
    SELECT DISTINCT h.sprhold_pidm AS pidm
    FROM saturn.sprhold h CROSS JOIN params p
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'PP'
      AND (h.sprhold_from_date IS NULL OR CAST(h.sprhold_from_date AS date) <= p.report_date)
      AND CAST(h.sprhold_to_date AS date) > p.report_date
)
SELECT
    s.spriden_id AS "CWID",
    s.spriden_last_name AS "Last Name",
    s.spriden_first_name AS "First Name",
    b.term_code AS "Term",
    b.amount AS "Amount",
    CASE WHEN a.cross_term_credit = 0 AND a.invalid_rows = 0
                   AND a.missing_term_rows = 0 AND s.identity_count = 1
        THEN ROUND(b.amount * 1.015, 2) END AS "Amount w/ LF",
    a.account_balance AS "Account Balance",
    CASE WHEN a.cross_term_credit = 1 THEN 'Yes'
        WHEN a.invalid_rows > 0 OR a.missing_term_rows > 0 THEN 'Unknown'
        ELSE 'No' END AS "Cross-Term Credit",
    CASE WHEN pp.pidm IS NOT NULL THEN 'PP' END AS "PP Hold",
    NULLIF(
        CASE WHEN a.cross_term_credit = 1 THEN 'Cross-term credit; review payment application. ' ELSE '' END
        || CASE WHEN a.invalid_rows > 0 THEN 'Missing amount or unknown/duplicate detail type; review balances. ' ELSE '' END
        || CASE WHEN a.missing_term_rows > 0 THEN 'Missing transaction term; review account context. ' ELSE '' END
        || CASE WHEN COALESCE(s.identity_count, 0) <> 1 THEN 'Missing or duplicate current identity; review. ' ELSE '' END,
        ''
    ) AS "Review Notes",
    COUNT(*) OVER () AS "Report Row Count"
FROM term_balances b
INNER JOIN report_terms r ON r.term_code = b.term_code
INNER JOIN account_context a ON a.pidm = b.pidm
LEFT JOIN identities s ON s.pidm = b.pidm AND s.identity_rank = 1
LEFT JOIN pp_holds pp ON pp.pidm = b.pidm
/* Keep uncomputable selected terms visibly marked for review, never as zero. */
WHERE b.amount > 0 OR b.invalid_rows > 0
ORDER BY s.spriden_last_name, s.spriden_first_name, s.spriden_id, b.term_code DESC, b.pidm;
