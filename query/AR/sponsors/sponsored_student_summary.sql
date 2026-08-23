/*
Sponsored Student Account Summary
Colorado School of Mines | Banner Insights (PostgreSQL-flavored SQL)

PURPOSE
  Return students with a third-party contract attached in TBBCSTU for the
  current or immediately previous Mines term. Show student and sponsor account
  activity from TBRACCD.

IMPORTANT DEFINITIONS
  * TBBCSTU_STU_PIDM identifies the student.
  * TBBCSTU_CONTRACT_PIDM identifies the sponsor/third-party account.
  * A charge is TBBDETC_TYPE_IND = 'C'.
  * A payment/credit is TBBDETC_TYPE_IND = 'P'.
  * Term Balance is charges minus payments for only the displayed term.
  * Full Account Balance is charges minus payments across every term. It is
    included because payments can be posted in a different term than charges.
  * The linked amounts use TBRACCD_CROSSREF_PIDM. They are a validation aid for
    transactions connecting this student and sponsor; verify them against
    TSACONT/TSAAREV before treating them as contract-specific accounting totals.

The report intentionally exposes TBBCSTU_DEL_IND and TBBCSTU_AUTH_IND instead
of assuming local meanings for their values. After Mines validates those values,
an active/authorized filter can be added without silently changing population.
*/

WITH
term_context AS (
    SELECT
        CURRENT_DATE AS run_date,
        /*
        Leave NULL for the term containing RUN_DATE. Set a valid Mines Banner
        term only for an intentional historical validation run.
        */
        CAST(NULL AS varchar(6)) AS current_term_override
),

current_term AS (
    SELECT
        CAST(
            COALESCE(
                current_term_override,
                CONCAT(
                    CAST(EXTRACT(YEAR FROM run_date) AS integer),
                    CASE
                        WHEN run_date <= MAKE_DATE(
                            CAST(EXTRACT(YEAR FROM run_date) AS integer),
                            5,
                            15
                        ) THEN '10'
                        WHEN run_date <= MAKE_DATE(
                            CAST(EXTRACT(YEAR FROM run_date) AS integer),
                            7,
                            15
                        ) THEN '55'
                        ELSE '80'
                    END
                )
            ) AS varchar(6)
        ) AS term_code
    FROM term_context
),

term_params AS (
    SELECT
        c.term_code AS current_term,
        CAST(
            CASE RIGHT(c.term_code, 2)
                WHEN '10' THEN CONCAT(
                    CAST(SUBSTRING(c.term_code FROM 1 FOR 4) AS integer) - 1,
                    '80'
                )
                WHEN '55' THEN CONCAT(
                    SUBSTRING(c.term_code FROM 1 FOR 4),
                    '10'
                )
                WHEN '80' THEN CONCAT(
                    SUBSTRING(c.term_code FROM 1 FOR 4),
                    '55'
                )
            END AS varchar(6)
        ) AS previous_term
    FROM current_term c
),

relevant_terms AS (
    SELECT p.current_term AS term_code, 'Current' AS term_context
    FROM term_params p

    UNION ALL

    SELECT p.previous_term AS term_code, 'Previous' AS term_context
    FROM term_params p
),

/* One row per TBBCSTU contract attachment and priority. */
sponsor_roster AS (
    SELECT DISTINCT
        r.term_context,
        r.term_code,
        cs.tbbcstu_stu_pidm AS student_pidm,
        cs.tbbcstu_contract_pidm AS sponsor_pidm,
        cs.tbbcstu_contract_number AS contract_number,
        cs.tbbcstu_contract_priority AS contract_priority,
        cs.tbbcstu_auth_ind AS authorization_ind,
        cs.tbbcstu_auth_number AS authorization_number,
        cs.tbbcstu_sponsor_ref_number AS sponsor_reference_number,
        cs.tbbcstu_max_student_amount AS max_student_amount,
        cs.tbbcstu_del_ind AS deletion_ind,
        cs.tbbcstu_term_code_expiration AS student_expiration_term,
        cs.tbbcstu_activity_date AS attachment_activity_date
    FROM relevant_terms r
    INNER JOIN taismgr.tbbcstu cs
        ON cs.tbbcstu_term_code = r.term_code
),

/* Remove contract-level duplication when matching PIDM cross-references. */
sponsor_relationships AS (
    SELECT DISTINCT
        r.term_code,
        r.student_pidm,
        r.sponsor_pidm
    FROM sponsor_roster r
),

account_population AS (
    SELECT DISTINCT r.student_pidm AS pidm
    FROM sponsor_roster r

    UNION

    SELECT DISTINCT r.sponsor_pidm AS pidm
    FROM sponsor_roster r
),

current_identity AS (
    SELECT
        s.spriden_pidm AS pidm,
        s.spriden_id AS cwid,
        s.spriden_last_name AS last_name,
        s.spriden_first_name AS first_name
    FROM saturn.spriden s
    WHERE s.spriden_change_ind IS NULL
),

/*
Positive charge/payment columns are easier to read; NET_BALANCE retains the
accounting sign (charge positive, payment negative).
*/
account_term_rollup AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        t.tbraccd_term_code AS term_code,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS charges,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS payments,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS net_balance,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(d.tbbdetc_type_ind, '')))
                  NOT IN ('C', 'P')
        ) AS unclassified_detail_type_count
    FROM taismgr.tbraccd t
    INNER JOIN account_population p
        ON p.pidm = t.tbraccd_pidm
    INNER JOIN relevant_terms r
        ON r.term_code = t.tbraccd_term_code
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY
        t.tbraccd_pidm,
        t.tbraccd_term_code
),

full_account_rollup AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS net_balance,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(d.tbbdetc_type_ind, '')))
                  NOT IN ('C', 'P')
        ) AS unclassified_detail_type_count
    FROM taismgr.tbraccd t
    INNER JOIN account_population p
        ON p.pidm = t.tbraccd_pidm
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY t.tbraccd_pidm
),

/* Student-side credits cross-referenced to this sponsor. */
student_link_rollup AS (
    SELECT
        rel.term_code,
        rel.student_pidm,
        rel.sponsor_pidm,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS linked_student_credits,
        COUNT(*) AS linked_student_transaction_count
    FROM sponsor_relationships rel
    INNER JOIN taismgr.tbraccd t
        ON t.tbraccd_pidm = rel.student_pidm
       AND t.tbraccd_crossref_pidm = rel.sponsor_pidm
       AND t.tbraccd_term_code = rel.term_code
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY
        rel.term_code,
        rel.student_pidm,
        rel.sponsor_pidm
),

/* Sponsor-side charges cross-referenced to this student. */
sponsor_link_rollup AS (
    SELECT
        rel.term_code,
        rel.student_pidm,
        rel.sponsor_pidm,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS linked_sponsor_charges,
        COUNT(*) AS linked_sponsor_transaction_count
    FROM sponsor_relationships rel
    INNER JOIN taismgr.tbraccd t
        ON t.tbraccd_pidm = rel.sponsor_pidm
       AND t.tbraccd_crossref_pidm = rel.student_pidm
       AND t.tbraccd_term_code = rel.term_code
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY
        rel.term_code,
        rel.student_pidm,
        rel.sponsor_pidm
)

SELECT
    r.term_context AS "Term Context",
    r.term_code AS "Term",
    term.stvterm_desc AS "Term Description",

    student.cwid AS "Student CWID",
    student.last_name AS "Student Last Name",
    student.first_name AS "Student First Name",

    sponsor.cwid AS "Sponsor ID",
    sponsor.last_name AS "Sponsor Last Name/Name",
    sponsor.first_name AS "Sponsor First Name",

    r.contract_number AS "Contract Number",
    r.contract_priority AS "Contract Priority",
    contract.tbbcont_desc AS "Contract Description",
    contract.tbbcont_detail_pay_code AS "Contract Student Payment Code",
    contract.tbbcont_detail_chg_code AS "Contract Sponsor Charge Code",
    r.authorization_ind AS "Authorization Indicator",
    r.authorization_number AS "Authorization Number",
    r.sponsor_reference_number AS "Sponsor Reference Number",
    r.max_student_amount AS "Maximum Student Amount",
    r.deletion_ind AS "Deletion Indicator",
    r.student_expiration_term AS "Student Contract Expiration Term",
    r.attachment_activity_date AS "Attachment Activity Date",

    COALESCE(student_term.charges, 0) AS "Student Term Charges",
    COALESCE(student_term.payments, 0) AS "Student Term Payments",
    COALESCE(student_term.net_balance, 0) AS "Student Term Balance",
    COALESCE(student_full.net_balance, 0) AS "Student Full Account Balance",

    COALESCE(sponsor_term.charges, 0) AS "Sponsor Term Charges - All Students",
    COALESCE(sponsor_term.payments, 0) AS "Sponsor Term Payments - All Students",
    COALESCE(sponsor_term.net_balance, 0) AS "Sponsor Term Balance - All Students",
    COALESCE(sponsor_full.net_balance, 0) AS "Sponsor Full Account Balance",

    COALESCE(student_link.linked_student_credits, 0)
        AS "Student Credits Linked to Sponsor",
    COALESCE(sponsor_link.linked_sponsor_charges, 0)
        AS "Sponsor Charges Linked to Student",
    COALESCE(student_link.linked_student_transaction_count, 0)
        AS "Linked Student Transaction Count",
    COALESCE(sponsor_link.linked_sponsor_transaction_count, 0)
        AS "Linked Sponsor Transaction Count",

    COALESCE(student_term.unclassified_detail_type_count, 0)
        AS "Student Term Unclassified Detail Count",
    COALESCE(sponsor_term.unclassified_detail_type_count, 0)
        AS "Sponsor Term Unclassified Detail Count",
    COALESCE(student_full.unclassified_detail_type_count, 0)
        AS "Student Full Account Unclassified Detail Count",
    COALESCE(sponsor_full.unclassified_detail_type_count, 0)
        AS "Sponsor Full Account Unclassified Detail Count"

FROM sponsor_roster r

LEFT JOIN current_identity student
    ON student.pidm = r.student_pidm

LEFT JOIN current_identity sponsor
    ON sponsor.pidm = r.sponsor_pidm

LEFT JOIN saturn.stvterm term
    ON term.stvterm_code = r.term_code

LEFT JOIN taismgr.tbbcont contract
    ON contract.tbbcont_pidm = r.sponsor_pidm
   AND contract.tbbcont_contract_number = r.contract_number
   AND contract.tbbcont_term_code = r.term_code

LEFT JOIN account_term_rollup student_term
    ON student_term.pidm = r.student_pidm
   AND student_term.term_code = r.term_code

LEFT JOIN account_term_rollup sponsor_term
    ON sponsor_term.pidm = r.sponsor_pidm
   AND sponsor_term.term_code = r.term_code

LEFT JOIN full_account_rollup student_full
    ON student_full.pidm = r.student_pidm

LEFT JOIN full_account_rollup sponsor_full
    ON sponsor_full.pidm = r.sponsor_pidm

LEFT JOIN student_link_rollup student_link
    ON student_link.student_pidm = r.student_pidm
   AND student_link.sponsor_pidm = r.sponsor_pidm
   AND student_link.term_code = r.term_code

LEFT JOIN sponsor_link_rollup sponsor_link
    ON sponsor_link.student_pidm = r.student_pidm
   AND sponsor_link.sponsor_pidm = r.sponsor_pidm
   AND sponsor_link.term_code = r.term_code

ORDER BY
    r.term_code DESC,
    student.cwid,
    sponsor.cwid,
    r.contract_priority,
    r.contract_number;
