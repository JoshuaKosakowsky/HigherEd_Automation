/*
Student Refund Review
Colorado School of Mines | Banner Insights (PostgreSQL-flavored SQL)

PURPOSE AND SAFETY
  Read-only decision support. This query calculates expected source ownership
  and delivery routes; it does not approve or issue a refund and does not create
  a Transact or TSARFND file. Rerun it immediately before staff take action.
  Full-population runs can exceed the Insights timeout. The supported
  operational path is launcher/run_refunds.ps1, which uses flat SQL extracts
  and performs this allocation locally. Retain this query as an auditable rule
  reference and targeted-account diagnostic.

TERM AND FISCAL-YEAR RULES
  * TARGET_TERM defaults from RUN_DATE: Spring 10, Summer 55, and Fall 80.
    Historical Summer 50 and 60 are recognized. PREVIOUS_TERM_OVERRIDE exists
    for an old Fall whose immediately preceding Summer was 60 rather than 55.
  * A Mines fiscal year runs Fall through Summer. Term 80 starts the fiscal
    year; following terms 10, 50, 55, and 60 belong to that fiscal year.
  * Previous term is shown separately. All older terms are one audit total, but
    allocation retains fiscal-year boundaries because the Title IV caps require
    them.
  * The unfiltered operational population starts with accounts that have target-
    term TBRACCD activity, then reads full history only for those PIDMs. A CWID
    or last-name validation filter can deliberately inspect historical-only
    accounts.

PAYMENT CLASSIFICATION AND CROSS-TERM POLICY
  * TBBDETC_TIV_IND = 'Y' makes a payment Title IV and overrides category.
    Otherwise a TBBDETC_DCAT_CODE beginning FA is non-Title-IV aid, CSH is cash,
    and remaining categories are unrestricted for this allocation.
  * Title IV may pay any charge in the same fiscal year. Across different fiscal
    years, each source fiscal year may give at most $200 in total and each
    destination fiscal year may receive at most $200 in total. Give and receive
    are independent ledgers. The oldest unpaid fiscal year receives funds first.
  * Non-Title-IV aid and other unrestricted payments may cross terms and fiscal
    years without a dollar cap. Prior or previous surpluses may pay current-term
    charges; Title IV retains the cross-fiscal-year cap when doing so.
  * A balanced or debit pre-current fiscal year is carried forward as one net
    amount. Only a pre-current fiscal year with an actual credit reconstructs
    source-level priority application, because only that year can contribute a
    refundable historical source.
  * Positive payments are netted with reversals within PIDM, term, aid year,
    and detail code. Charge-side credits are netted within PIDM, term, and
    charge priority so paired detail codes such as HLTH/HIWR cancel before
    allocation. Reversals reduce the newest positive row first so the earliest
    surviving transaction remains the tie winner.

PRIORITY APPLICATION
  * Current charges are processed from priority 999 down. A payment priority
    matches the charge positionally, with zero as a wildcard: 899 matches 899,
    890 matches 89x, 800 matches 8xx, and 000 matches any charge.
  * Payment order is 999..801, 800A, 800, 799..001, 000A, 000, 000Z. Within an
    effective priority the lowest TBRACCD_TRAN_NUMBER applies first.
  * TPDT and TPPY are 800A; COFP is 000A; ACHK, CRAM, CRDS, CRMC, and CRVC are
    000Z. These suffixes change order only. Eligibility still uses the stored
    three-digit TBBDETC_PRIORITY. A configured base priority that conflicts with
    an artificial rule triggers review rather than silently changing matching.

REFUND OWNERSHIP AND DELIVERY
  * TOTAL_REFUND_AMOUNT is reconstructed unused payment principal. This may be
    larger than the full-account credit when lawful Title IV limits leave an
    older charge unpaid. FULL_ACCOUNT_BALANCE and TBRACCD_BALANCE remain audit
    evidence and never replace the reconstructed source allocation.
  * Every unused FDPL source is matched to RLRPAPP by PIDM and its own aid year.
    An N authorization sends that source to the parent; Y sends it to the
    student. Missing or conflicting authorization blocks the split. A parent
    refund uses RFDP.
  * A student refund with an RH refund hold displays Refund Hold - Student.
    Otherwise ordinary funds use ARFD (System) with one active ED hold or RFND
    (CHECK) without ED. CRVC uses CRVC (Transact).
  * ACHK age uses TBRACCD_EFFECTIVE_DATE. Eligibility begins on effective date
    plus 16 calendar days (for example, August 1 becomes eligible August 17).
    Through day 180 it uses AFRD (Transact); after day 180 it remains AFRD with
    a May Be Too Old note. Waiting rows show their exact eligible date.

FIRST-RUN VALIDATION
  1. Run validate_refund_schema.sql and resolve every missing column.
  2. Confirm FULL_ACCOUNT_BALANCE against TSAAREV and inspect any policy refund
     difference or stored-balance difference. Those are review evidence because
     Banner balances may reflect an application that staff must correct.
  3. Validate current TBBDETC priorities, DCAT categories, and Title IV flags.
     These values are not historical snapshots.
  4. Confirm the artificial-priority detail codes and the $200 give/receive
     policy with the functional owner before production use.
  5. Treat every status other than READY_FOR_STAFF_REVIEW as requiring the
     stated staff action or review.
*/

WITH RECURSIVE
term_context AS (
    SELECT
        CURRENT_DATE AS run_date,
        /*
        Leave NULL to derive the Mines term containing RUN_DATE. Set a valid
        six-digit Banner term only for an intentional prior-term or work-ahead run.
        */
        CAST(NULL AS varchar(6)) AS target_term_override,
        /* Set only when validating a historical Fall that followed term 60. */
        CAST(NULL AS varchar(6)) AS previous_term_override
),

current_term AS (
    SELECT
        CAST(
            COALESCE(
                target_term_override,
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
        ) AS target_term,
        run_date,
        previous_term_override
    FROM term_context
),

params AS (
    SELECT
        c.target_term,
        CAST(COALESCE(
            c.previous_term_override,
            CASE RIGHT(c.target_term, 2)
                WHEN '10' THEN CONCAT(
                    CAST(SUBSTRING(c.target_term FROM 1 FOR 4) AS integer) - 1,
                    '80'
                )
                WHEN '50' THEN CONCAT(
                    SUBSTRING(c.target_term FROM 1 FOR 4), '10'
                )
                WHEN '55' THEN CONCAT(
                    SUBSTRING(c.target_term FROM 1 FOR 4), '10'
                )
                WHEN '60' THEN CONCAT(
                    SUBSTRING(c.target_term FROM 1 FOR 4), '50'
                )
                WHEN '80' THEN CONCAT(
                    SUBSTRING(c.target_term FROM 1 FOR 4), '55'
                )
            END
        ) AS varchar(6)) AS previous_term,
        CASE RIGHT(c.target_term, 2)
            WHEN '80' THEN CAST(SUBSTRING(c.target_term FROM 1 FOR 4) AS integer)
            ELSE CAST(SUBSTRING(c.target_term FROM 1 FOR 4) AS integer) - 1
        END AS current_fiscal_year_start,
        c.run_date,
        CAST(200.00 AS numeric) AS title_iv_cross_fy_cap,
        /* Set only for a fast one-account validation run. */
        CAST(NULL AS varchar(30)) AS cwid_filter,
        /* Replace NULL with 'SMITH%' for an optional last-name validation run. */
        CAST(NULL AS varchar(60)) AS last_name_filter
    FROM current_term c
),

/*
LEGACY THIRD-PARTY CWIDS
New third-party accounts use a TPS-prefixed CWID. Add older CWIDs that do not
follow that convention here. Keep the NULL placeholder and add one row per CWID:

    -- , ('LEGACY_CWID_1')
    -- , ('LEGACY_CWID_2')

Remove only the leading -- when activating a row. Matching ignores case and
surrounding spaces.
*/
legacy_third_party_cwids AS (
    SELECT DISTINCT UPPER(TRIM(v.cwid)) AS cwid
    FROM (
        VALUES
            (CAST(NULL AS varchar(30)))
            -- , ('LEGACY_CWID_1')
            -- , ('LEGACY_CWID_2')
    ) AS v(cwid)
    WHERE NULLIF(TRIM(v.cwid), '') IS NOT NULL
),

/*
Resolve a validation filter to PIDM before touching account history. An
unfiltered operational report starts from accounts with target-term activity;
there cannot be a current-term refund without a current-term transaction. A
CWID/last-name validation run may still inspect an account without target-term
activity. Both paths then reach full AR history through selected PIDM values.
*/
validation_scope_pidms AS (
    SELECT DISTINCT s.spriden_pidm AS pidm
    FROM saturn.spriden s
    CROSS JOIN params p
    WHERE (p.cwid_filter IS NOT NULL OR p.last_name_filter IS NOT NULL)
      AND s.spriden_change_ind IS NULL
      AND (p.cwid_filter IS NULL OR s.spriden_id = TRIM(p.cwid_filter))
      AND (p.last_name_filter IS NULL
           OR UPPER(s.spriden_last_name) LIKE UPPER(p.last_name_filter))
),

report_scope_pidms AS (
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND p.last_name_filter IS NULL
      AND t.tbraccd_term_code = p.target_term
    GROUP BY t.tbraccd_pidm

    UNION ALL

    SELECT v.pidm
    FROM validation_scope_pidms v
),

screening_transactions AS (
    SELECT
        t.tbraccd_pidm,
        t.tbraccd_term_code,
        t.tbraccd_detail_code,
        t.tbraccd_amount,
        t.tbraccd_balance,
        t.tbraccd_activity_date
    FROM report_scope_pidms v
    INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = v.pidm
),

/*
Group one selected AR stream for the full balance, fiscal-year credits, and
target-term stored unapplied payments before the smaller candidate set is allocated.
*/
account_fiscal_rollup AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}80$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer)
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60)$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer) - 1
            ELSE NULL
        END AS fiscal_year_start,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS full_account_balance_component,
        ROUND(SUM(CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60|80)$'
             AND CAST(TRIM(t.tbraccd_term_code) AS integer)
                    <= CAST(p.target_term AS integer)
             AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60|80)$'
             AND CAST(TRIM(t.tbraccd_term_code) AS integer)
                    <= CAST(p.target_term AS integer)
             AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS allocation_fiscal_year_balance,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(d.tbbdetc_type_ind, '')))
                  NOT IN ('C', 'P')
        ) AS unclassified_detail_type_count,
        COUNT(*) FILTER (
            WHERE TRIM(t.tbraccd_term_code) = p.target_term
        ) AS target_term_activity_count,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
              AND t.tbraccd_balance < 0
              AND TRIM(t.tbraccd_term_code) = p.target_term
        ) AS negative_stored_payment_count,
        MAX(t.tbraccd_activity_date) AS last_ar_activity_date
    FROM screening_transactions t
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    GROUP BY
        t.tbraccd_pidm,
        CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}80$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer)
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60)$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer) - 1
            ELSE NULL
        END
),

/*
Calculate one row per account from the fiscal-year screening groups. Detail
codes without a C/P type are counted so an indeterminate account is never
presented as a reliable refund amount.
*/
account_balance_rollup AS (
    SELECT
        f.pidm,
        ROUND(SUM(f.full_account_balance_component), 2) AS full_account_balance,
        SUM(f.unclassified_detail_type_count) AS unclassified_detail_type_count,
        SUM(f.target_term_activity_count) AS target_term_activity_count,
        SUM(f.negative_stored_payment_count) AS negative_stored_payment_count,
        MIN(f.allocation_fiscal_year_balance) FILTER (
            WHERE f.fiscal_year_start IS NOT NULL
        ) AS lowest_fiscal_year_balance,
        MAX(f.last_ar_activity_date) AS last_ar_activity_date
    FROM account_fiscal_rollup f
    GROUP BY f.pidm
),

/*
Full-account credits remain in scope. A target-term stored unapplied payment is
a fast additional signal. Fiscal-year credits enter only for accounts active in the
target term, preventing dormant historical credits from entering recursion.
*/
account_balances AS (
    SELECT
        r.pidm,
        r.full_account_balance,
        r.last_ar_activity_date
    FROM account_balance_rollup r
    WHERE r.unclassified_detail_type_count = 0
      AND (
        r.full_account_balance < 0
        OR r.negative_stored_payment_count > 0
        OR (
            r.target_term_activity_count > 0
            AND r.lowest_fiscal_year_balance < 0
        )
      )
),

/*
These small account-level lookups are deliberately materialized. PostgreSQL may
otherwise inline them into the wide final join and repeatedly rescan the same
Banner tables for every candidate account.
*/
current_identity AS MATERIALIZED (
    SELECT
        s.spriden_pidm AS pidm,
        s.spriden_id AS cwid,
        s.spriden_last_name AS last_name,
        s.spriden_first_name AS first_name
    FROM saturn.spriden s
    INNER JOIN account_balances b ON b.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
),

person_controls AS MATERIALIZED (
    SELECT
        p.spbpers_pidm AS pidm,
        p.spbpers_dead_ind AS deceased_ind,
        p.spbpers_dead_date AS deceased_date,
        p.spbpers_confid_ind AS confidential_ind,
        p.spbpers_activity_date AS person_activity_date
    FROM saturn.spbpers p
    INNER JOIN account_balances b ON b.pidm = p.spbpers_pidm
),

account_controls AS MATERIALIZED (
    SELECT
        a.tbbacct_pidm AS pidm,
        COUNT(*) AS account_control_row_count,
        MAX(CASE
            WHEN UPPER(TRIM(COALESCE(a.tbbacct_deli_code, ''))) = 'RH'
                THEN 1
            ELSE 0
        END) AS refund_hold_count,
        MAX(NULLIF(TRIM(a.tbbacct_deli_code), '')) AS raw_delinquency_code,
        MAX(NULLIF(TRIM(a.tbbacct_refund_ind), '')) AS raw_refund_account_ind,
        MAX(a.tbbacct_activity_date) AS account_control_activity_date
    FROM taismgr.tbbacct a
    INNER JOIN account_balances b ON b.pidm = a.tbbacct_pidm
    GROUP BY a.tbbacct_pidm
),

active_ed AS MATERIALIZED (
    SELECT
        h.sprhold_pidm AS pidm,
        COUNT(*) AS active_ed_row_count,
        MAX(h.sprhold_activity_date) AS ed_activity_date
    FROM saturn.sprhold h
    INNER JOIN account_balances b ON b.pidm = h.sprhold_pidm
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'ED'
      AND CAST(h.sprhold_to_date AS date) = DATE '9999-12-31'
    GROUP BY h.sprhold_pidm
),

/*
Classify every transaction on a potential refund account. Only recognized Mines
terms at or before the target term enter allocation. The full-account balance
above stays unrestricted so excluded/future activity produces a reconciliation
exception rather than disappearing.
*/
candidate_transactions AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        TRIM(t.tbraccd_term_code) AS term_code,
        t.tbraccd_aidy_code AS aidy_code,
        t.tbraccd_tran_number AS tran_number,
        UPPER(TRIM(t.tbraccd_detail_code)) AS detail_code,
        COALESCE(d.tbbdetc_desc, '[Description unavailable]') AS detail_desc,
        UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
        UPPER(TRIM(COALESCE(d.tbbdetc_dcat_code, ''))) AS category_code,
        CASE WHEN UPPER(TRIM(COALESCE(d.tbbdetc_tiv_ind, ''))) = 'Y'
            THEN 1 ELSE 0 END AS is_title_iv,
        CASE
            WHEN TRIM(CAST(d.tbbdetc_priority AS text)) ~ '^[0-9]{1,3}$'
                THEN LPAD(TRIM(CAST(d.tbbdetc_priority AS text)), 3, '0')
            ELSE NULL
        END AS priority_code,
        CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60|80)$'
                THEN CAST(TRIM(t.tbraccd_term_code) AS integer)
            ELSE NULL
        END AS term_sort,
        CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}80$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer)
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60)$'
                THEN CAST(SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4) AS integer) - 1
            ELSE NULL
        END AS fiscal_year_start,
        CASE WHEN t.tbraccd_amount IS NULL THEN 1 ELSE 0 END
            AS amount_missing_ind,
        COALESCE(t.tbraccd_amount, 0) AS raw_amount,
        CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE NULL
        END AS accounting_amount,
        t.tbraccd_balance AS raw_transaction_balance,
        t.tbraccd_effective_date AS effective_date,
        t.tbraccd_activity_date AS activity_date
    FROM taismgr.tbraccd t
    INNER JOIN account_balances b ON b.pidm = t.tbraccd_pidm
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
),

/* Account-level summaries are materialized once for the same join-plan reason. */
balance_input_checks AS MATERIALIZED (
    SELECT
        b.pidm,
        COUNT(*) FILTER (
            WHERE x.raw_amount <> 0 AND x.priority_code IS NULL
        ) AS invalid_priority_count,
        COUNT(*) FILTER (WHERE x.amount_missing_ind = 1)
            AS missing_transaction_amount_count,
        COUNT(*) FILTER (WHERE x.raw_amount < 0) AS negative_source_count,
        COUNT(*) FILTER (
            WHERE x.raw_amount <> 0 AND x.term_sort IS NULL
        ) AS invalid_term_count,
        COUNT(*) FILTER (
            WHERE x.raw_amount <> 0
              AND x.term_sort > CAST(p.target_term AS integer)
        ) AS future_term_count,
        COUNT(*) FILTER (
            WHERE x.raw_amount <> 0
              AND (
                (x.detail_code IN ('TPDT', 'TPPY') AND x.priority_code <> '800')
                OR (x.detail_code = 'COFP' AND x.priority_code <> '000')
                OR (x.detail_code IN ('ACHK', 'CRAM', 'CRDS', 'CRMC', 'CRVC')
                    AND x.priority_code <> '000')
              )
        ) AS special_priority_mismatch_count,
        COUNT(*) FILTER (WHERE x.raw_transaction_balance IS NULL)
            AS missing_transaction_balance_count
    FROM account_balances b
    CROSS JOIN params p
    LEFT JOIN candidate_transactions x ON x.pidm = b.pidm
    GROUP BY b.pidm
),

/* Reversals reduce the newest positive row in the same source group first. */
payment_rows AS (
    SELECT
        x.*,
        SUM(x.raw_amount) OVER (
            PARTITION BY x.pidm, x.term_code, x.aidy_code, x.detail_code
        ) AS payment_group_net,
        COALESCE(SUM(CASE WHEN x.raw_amount > 0 THEN x.raw_amount ELSE 0 END)
            OVER (
                PARTITION BY x.pidm, x.term_code, x.aidy_code, x.detail_code
                ORDER BY x.tran_number
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ), 0) AS prior_positive_payment_amount
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.type_ind = 'P'
      AND x.term_sort IS NOT NULL
      AND x.term_sort <= CAST(p.target_term AS integer)
),

payment_sources AS (
    SELECT
        r.pidm,
        r.term_code,
        r.term_sort,
        r.fiscal_year_start,
        r.aidy_code,
        r.tran_number,
        r.detail_code,
        r.detail_desc,
        r.category_code,
        r.is_title_iv,
        CASE
            WHEN r.is_title_iv = 1 THEN 'TITLE_IV'
            WHEN r.category_code LIKE 'FA%' THEN 'NON_TITLE_IV_FA'
            WHEN r.category_code = 'CSH' THEN 'CASH'
            ELSE 'OTHER_UNRESTRICTED'
        END AS fund_type,
        r.priority_code,
        CASE
            WHEN r.detail_code IN ('TPDT', 'TPPY') AND r.priority_code = '800'
                THEN '800A'
            WHEN r.detail_code = 'COFP' AND r.priority_code = '000'
                THEN '000A'
            WHEN r.detail_code IN ('ACHK', 'CRAM', 'CRDS', 'CRMC', 'CRVC')
             AND r.priority_code = '000' THEN '000Z'
            ELSE r.priority_code
        END AS effective_priority_code,
        CASE
            WHEN r.detail_code IN ('TPDT', 'TPPY') AND r.priority_code = '800'
                THEN 8002
            WHEN r.priority_code = '800' THEN 8001
            WHEN r.detail_code = 'COFP' AND r.priority_code = '000' THEN 2
            WHEN r.detail_code IN ('ACHK', 'CRAM', 'CRDS', 'CRMC', 'CRVC')
             AND r.priority_code = '000' THEN 0
            WHEN r.priority_code IS NOT NULL
                THEN CAST(r.priority_code AS integer) * 10 + 1
            ELSE NULL
        END AS payment_priority_sort,
        ROUND(LEAST(
            r.raw_amount,
            GREATEST(r.payment_group_net - r.prior_positive_payment_amount, 0)
        ), 2) AS source_amount,
        ROUND(GREATEST(-COALESCE(r.raw_transaction_balance, 0), 0), 2)
            AS stored_unused_amount,
        r.effective_date,
        r.activity_date
    FROM payment_rows r
    WHERE r.raw_amount > 0
      AND LEAST(
          r.raw_amount,
          GREATEST(r.payment_group_net - r.prior_positive_payment_amount, 0)
      ) > 0
),

/*
Historical fiscal years that are balanced or debit-balance years contribute no
refundable payment source. Carry their net deficit forward directly. Only an
actual historical fiscal-year credit needs source-level reconstruction so its
remaining fund type and owner can be determined. This implements the requested
prior-term lumping and keeps closed years out of the recursive allocator.
*/
precurrent_fiscal_balances AS (
    SELECT
        x.pidm,
        x.fiscal_year_start,
        ROUND(SUM(x.accounting_amount), 2) AS fiscal_balance
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.term_sort IS NOT NULL
      AND x.term_sort < CAST(p.target_term AS integer)
      AND x.fiscal_year_start IS NOT NULL
    GROUP BY x.pidm, x.fiscal_year_start
),

precurrent_credit_fiscal_years AS (
    SELECT f.pidm, f.fiscal_year_start, f.fiscal_balance
    FROM precurrent_fiscal_balances f
    WHERE f.fiscal_balance < 0
),

charge_rows AS (
    SELECT
        x.*,
        SUM(x.raw_amount) OVER (
            PARTITION BY x.pidm, x.term_code, x.priority_code
        ) AS charge_group_net,
        COALESCE(SUM(CASE WHEN x.raw_amount > 0 THEN x.raw_amount ELSE 0 END)
            OVER (
                PARTITION BY x.pidm, x.term_code, x.priority_code
                ORDER BY x.tran_number
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ), 0) AS prior_positive_charge_amount
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.type_ind = 'C'
      AND x.term_sort IS NOT NULL
      AND x.term_sort <= CAST(p.target_term AS integer)
      AND (
          x.term_sort = CAST(p.target_term AS integer)
          OR EXISTS (
              SELECT 1
              FROM precurrent_credit_fiscal_years f
              WHERE f.pidm = x.pidm
                AND f.fiscal_year_start = x.fiscal_year_start
          )
      )
),

charge_source_rows AS (
    SELECT
        r.pidm,
        r.term_code,
        r.term_sort,
        r.fiscal_year_start,
        r.tran_number,
        r.detail_code,
        r.detail_desc,
        r.priority_code,
        ROUND(LEAST(
            r.raw_amount,
            GREATEST(r.charge_group_net - r.prior_positive_charge_amount, 0)
        ), 2) AS charge_amount
    FROM charge_rows r
    WHERE r.raw_amount > 0
      AND LEAST(
          r.raw_amount,
          GREATEST(r.charge_group_net - r.prior_positive_charge_amount, 0)
      ) > 0
),

/* Charge-row identity does not affect allocation within one term/priority. */
charge_sources AS (
    SELECT
        r.pidm,
        r.term_code,
        r.term_sort,
        r.fiscal_year_start,
        MIN(r.tran_number) AS tran_number,
        CONCAT('PRIORITY_', COALESCE(r.priority_code, 'INVALID')) AS detail_code,
        'Aggregated charges at the same term and priority' AS detail_desc,
        r.priority_code,
        ROUND(SUM(r.charge_amount), 2) AS charge_amount
    FROM charge_source_rows r
    GROUP BY
        r.pidm,
        r.term_code,
        r.term_sort,
        r.fiscal_year_start,
        r.priority_code
),

net_source_checks AS MATERIALIZED (
    SELECT
        b.pidm,
        COALESCE(p.negative_payment_group_count, 0)
            + COALESCE(c.negative_charge_group_count, 0)
            AS negative_net_source_count
    FROM account_balances b
    LEFT JOIN (
        SELECT pidm, COUNT(*) AS negative_payment_group_count
        FROM (
            SELECT pidm, term_code, aidy_code, detail_code
            FROM payment_rows
            GROUP BY pidm, term_code, aidy_code, detail_code
            HAVING SUM(raw_amount) < 0
        ) g
        GROUP BY pidm
    ) p ON p.pidm = b.pidm
    LEFT JOIN (
        SELECT pidm, COUNT(*) AS negative_charge_group_count
        FROM (
            SELECT pidm, term_code, priority_code
            FROM charge_rows
            GROUP BY pidm, term_code, priority_code
            HAVING SUM(raw_amount) < 0
        ) g
        GROUP BY pidm
    ) c ON c.pidm = b.pidm
),

/*
For the comparatively small set of pre-current fiscal years with a real credit,
reconstruct source application inside that fiscal year. Charges in the oldest
term are handled first, then by descending priority. Debit and balanced years
were already reduced to one fiscal-year amount above and never enter recursion.
*/
precurrent_local_payments AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.pidm, s.fiscal_year_start
            ORDER BY s.payment_priority_sort DESC NULLS LAST,
                     s.tran_number, s.term_sort, s.detail_code
        ) AS local_payment_sequence,
        CONCAT('LP', ROW_NUMBER() OVER (
            PARTITION BY s.pidm, s.fiscal_year_start
            ORDER BY s.payment_priority_sort DESC NULLS LAST,
                     s.tran_number, s.term_sort, s.detail_code
        )) AS local_payment_key
    FROM payment_sources s
    INNER JOIN precurrent_credit_fiscal_years f
        ON f.pidm = s.pidm
       AND f.fiscal_year_start = s.fiscal_year_start
),

precurrent_local_charges AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (
            PARTITION BY c.pidm, c.fiscal_year_start
            ORDER BY c.term_sort,
                     c.priority_code DESC NULLS LAST,
                     c.tran_number, c.detail_code
        ) AS local_charge_sequence,
        CONCAT('LC', ROW_NUMBER() OVER (
            PARTITION BY c.pidm, c.fiscal_year_start
            ORDER BY c.term_sort,
                     c.priority_code DESC NULLS LAST,
                     c.tran_number, c.detail_code
        )) AS local_charge_key
    FROM charge_sources c
    INNER JOIN precurrent_credit_fiscal_years f
        ON f.pidm = c.pidm
       AND f.fiscal_year_start = c.fiscal_year_start
),

precurrent_local_pairs AS (
    SELECT
        c.pidm,
        c.fiscal_year_start,
        c.local_charge_sequence,
        c.local_charge_key,
        c.charge_amount,
        s.local_payment_sequence,
        s.local_payment_key,
        s.source_amount AS payment_amount,
        ROW_NUMBER() OVER (
            PARTITION BY c.pidm, c.fiscal_year_start
            ORDER BY c.local_charge_sequence,
                     s.local_payment_sequence
        ) AS local_allocation_step
    FROM precurrent_local_charges c
    INNER JOIN precurrent_local_payments s
        ON s.pidm = c.pidm
       AND s.fiscal_year_start = c.fiscal_year_start
    WHERE c.priority_code LIKE REPLACE(s.priority_code, '0', '_')
),

precurrent_local_pair_counts AS (
    SELECT pidm, fiscal_year_start, COUNT(*) AS pair_count
    FROM precurrent_local_pairs
    GROUP BY pidm, fiscal_year_start
),

precurrent_local_allocation AS (
    SELECT
        f.pidm,
        f.fiscal_year_start,
        CAST(0 AS bigint) AS local_allocation_step,
        CAST('{}' AS jsonb) AS charge_remaining,
        CAST('{}' AS jsonb) AS payment_remaining
    FROM precurrent_credit_fiscal_years f

    UNION ALL

    SELECT
        a.pidm,
        a.fiscal_year_start,
        e.local_allocation_step,
        JSONB_SET(
            a.charge_remaining,
            ARRAY[e.local_charge_key],
            TO_JSONB(v.charge_available - applied.amount),
            TRUE
        ),
        JSONB_SET(
            a.payment_remaining,
            ARRAY[e.local_payment_key],
            TO_JSONB(v.payment_available - applied.amount),
            TRUE
        )
    FROM precurrent_local_allocation a
    INNER JOIN precurrent_local_pairs e
        ON e.pidm = a.pidm
       AND e.fiscal_year_start = a.fiscal_year_start
       AND e.local_allocation_step = a.local_allocation_step + 1
    CROSS JOIN LATERAL (
        SELECT
            COALESCE(CAST(a.charge_remaining ->> e.local_charge_key AS numeric),
                     e.charge_amount) AS charge_available,
            COALESCE(CAST(a.payment_remaining ->> e.local_payment_key AS numeric),
                     e.payment_amount) AS payment_available
    ) v
    CROSS JOIN LATERAL (
        SELECT ROUND(LEAST(v.charge_available, v.payment_available), 2) AS amount
    ) applied
),

precurrent_local_final AS (
    SELECT a.*
    FROM precurrent_local_allocation a
    LEFT JOIN precurrent_local_pair_counts n
        ON n.pidm = a.pidm
       AND n.fiscal_year_start = a.fiscal_year_start
    WHERE a.local_allocation_step = COALESCE(n.pair_count, 0)
),

precurrent_payment_remaining AS (
    SELECT
        s.*,
        ROUND(COALESCE(
            CAST(a.payment_remaining ->> s.local_payment_key AS numeric),
            s.source_amount
        ), 2) AS remaining_after_local_fy
    FROM precurrent_local_payments s
    INNER JOIN precurrent_local_final a
        ON a.pidm = s.pidm
       AND a.fiscal_year_start = s.fiscal_year_start
),

precurrent_fiscal_summary AS (
    /* Debit fiscal years carry forward as one amount with no source recursion. */
    SELECT
        f.pidm,
        f.fiscal_year_start,
        f.fiscal_balance AS fiscal_deficit
    FROM precurrent_fiscal_balances f
    WHERE f.fiscal_balance > 0

    UNION ALL

    /* A credit year may still have a priority-restricted unpaid charge. */
    SELECT
        f.pidm,
        f.fiscal_year_start,
        ROUND(COALESCE(SUM(COALESCE(
            CAST(a.charge_remaining ->> c.local_charge_key AS numeric),
            c.charge_amount
        )), 0), 2) AS fiscal_deficit
    FROM precurrent_credit_fiscal_years f
    INNER JOIN precurrent_local_final a
        ON a.pidm = f.pidm
       AND a.fiscal_year_start = f.fiscal_year_start
    LEFT JOIN precurrent_local_charges c
        ON c.pidm = f.pidm
       AND c.fiscal_year_start = f.fiscal_year_start
    GROUP BY f.pidm, f.fiscal_year_start
    HAVING COALESCE(SUM(COALESCE(
        CAST(a.charge_remaining ->> c.local_charge_key AS numeric),
        c.charge_amount
    )), 0) > 0
),

stage_payment_inputs AS (
    SELECT
        s.*,
        CASE
            WHEN s.term_sort < CAST(p.target_term AS integer)
             AND f.pidm IS NULL THEN 0
            WHEN s.term_sort < CAST(p.target_term AS integer)
                THEN COALESCE(r.remaining_after_local_fy, s.source_amount)
            ELSE s.source_amount
        END AS stage_source_amount
    FROM payment_sources s
    CROSS JOIN params p
    LEFT JOIN precurrent_credit_fiscal_years f
        ON f.pidm = s.pidm
       AND f.fiscal_year_start = s.fiscal_year_start
    LEFT JOIN precurrent_payment_remaining r
        ON r.pidm = s.pidm
       AND r.fiscal_year_start = s.fiscal_year_start
       AND r.term_code = s.term_code
       AND r.tran_number = s.tran_number
       AND r.detail_code = s.detail_code
    WHERE s.term_sort <= CAST(p.target_term AS integer)
),

numbered_payment_sources AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.pidm
            ORDER BY s.payment_priority_sort DESC NULLS LAST,
                     s.tran_number, s.term_sort, s.detail_code
        ) AS payment_sequence,
        CONCAT('P', ROW_NUMBER() OVER (
            PARTITION BY s.pidm
            ORDER BY s.payment_priority_sort DESC NULLS LAST,
                     s.tran_number, s.term_sort, s.detail_code
        )) AS payment_key
    FROM stage_payment_inputs s
    WHERE s.stage_source_amount > 0
),

stage_charge_inputs AS (
    SELECT
        f.pidm,
        f.fiscal_year_start,
        CAST(NULL AS varchar(6)) AS term_code,
        CAST(NULL AS integer) AS term_sort,
        CAST(0 AS bigint) AS tran_number,
        'PRIOR_FY_BALANCE' AS detail_code,
        CONCAT('Fiscal year ', f.fiscal_year_start, '-', f.fiscal_year_start + 1,
               ' balance') AS detail_desc,
        CAST(NULL AS varchar(3)) AS priority_code,
        f.fiscal_deficit AS charge_amount,
        'HISTORICAL_FY_DEFICIT' AS charge_kind
    FROM precurrent_fiscal_summary f
    WHERE f.fiscal_deficit > 0

    UNION ALL

    SELECT
        c.pidm,
        c.fiscal_year_start,
        c.term_code,
        c.term_sort,
        c.tran_number,
        c.detail_code,
        c.detail_desc,
        c.priority_code,
        c.charge_amount,
        'CURRENT_TERM_CHARGE' AS charge_kind
    FROM charge_sources c
    CROSS JOIN params p
    WHERE c.term_sort = CAST(p.target_term AS integer)
),

numbered_charges AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (
            PARTITION BY c.pidm
            ORDER BY
                CASE WHEN c.charge_kind = 'HISTORICAL_FY_DEFICIT' THEN 0 ELSE 1 END,
                c.fiscal_year_start,
                c.priority_code DESC NULLS LAST,
                c.tran_number,
                c.detail_code
        ) AS charge_sequence,
        CONCAT('C', ROW_NUMBER() OVER (
            PARTITION BY c.pidm
            ORDER BY
                CASE WHEN c.charge_kind = 'HISTORICAL_FY_DEFICIT' THEN 0 ELSE 1 END,
                c.fiscal_year_start,
                c.priority_code DESC NULLS LAST,
                c.tran_number,
                c.detail_code
        )) AS charge_key
    FROM stage_charge_inputs c
),

/*
Historical deficits accept every payment allowed by fiscal-year policy. Current
charges retain Banner's positional-zero priority matching. Artificial suffixes
change payment order only; matching always uses the original three digits.
*/
allocation_pairs AS (
    SELECT
        c.pidm,
        c.charge_sequence,
        c.charge_key,
        c.charge_amount,
        c.fiscal_year_start AS charge_fiscal_year_start,
        c.charge_kind,
        s.payment_sequence,
        s.payment_key,
        s.stage_source_amount AS payment_amount,
        s.fiscal_year_start AS payment_fiscal_year_start,
        s.is_title_iv,
        s.fund_type,
        ROW_NUMBER() OVER (
            PARTITION BY c.pidm
            ORDER BY c.charge_sequence, s.payment_sequence
        ) AS allocation_step
    FROM numbered_charges c
    INNER JOIN numbered_payment_sources s ON s.pidm = c.pidm
    WHERE c.charge_kind = 'HISTORICAL_FY_DEFICIT'
       OR c.priority_code LIKE REPLACE(s.priority_code, '0', '_')
),

allocation_pair_counts AS (
    SELECT pidm, COUNT(*) AS pair_count
    FROM allocation_pairs
    GROUP BY pidm
),

priority_allocation AS (
    SELECT
        b.pidm,
        CAST(0 AS bigint) AS allocation_step,
        CAST('{}' AS jsonb) AS charge_remaining,
        CAST('{}' AS jsonb) AS payment_remaining,
        CAST('{}' AS jsonb) AS title_iv_given_by_fy,
        CAST('{}' AS jsonb) AS title_iv_received_by_fy,
        CAST(0 AS numeric) AS last_applied_amount,
        CAST(NULL AS integer) AS last_payment_fiscal_year_start,
        CAST(NULL AS integer) AS last_charge_fiscal_year_start,
        CAST(NULL AS integer) AS last_is_title_iv,
        CAST(NULL AS varchar(40)) AS last_fund_type,
        CAST(NULL AS varchar(40)) AS last_charge_kind
    FROM account_balances b

    UNION ALL

    SELECT
        a.pidm,
        e.allocation_step,
        JSONB_SET(
            a.charge_remaining,
            ARRAY[e.charge_key],
            TO_JSONB(v.charge_available - applied.amount),
            TRUE
        ),
        JSONB_SET(
            a.payment_remaining,
            ARRAY[e.payment_key],
            TO_JSONB(v.payment_available - applied.amount),
            TRUE
        ),
        CASE WHEN limits.cross_fy_title_iv = 1 THEN JSONB_SET(
            a.title_iv_given_by_fy,
            ARRAY[CAST(e.payment_fiscal_year_start AS text)],
            TO_JSONB(limits.given_so_far + applied.amount),
            TRUE
        ) ELSE a.title_iv_given_by_fy END,
        CASE WHEN limits.cross_fy_title_iv = 1 THEN JSONB_SET(
            a.title_iv_received_by_fy,
            ARRAY[CAST(e.charge_fiscal_year_start AS text)],
            TO_JSONB(limits.received_so_far + applied.amount),
            TRUE
        ) ELSE a.title_iv_received_by_fy END,
        applied.amount,
        e.payment_fiscal_year_start,
        e.charge_fiscal_year_start,
        e.is_title_iv,
        CAST(e.fund_type AS varchar(40)),
        CAST(e.charge_kind AS varchar(40))
    FROM priority_allocation a
    INNER JOIN allocation_pairs e
        ON e.pidm = a.pidm
       AND e.allocation_step = a.allocation_step + 1
    CROSS JOIN params p
    CROSS JOIN LATERAL (
        SELECT
            COALESCE(CAST(a.charge_remaining ->> e.charge_key AS numeric),
                     e.charge_amount) AS charge_available,
            COALESCE(CAST(a.payment_remaining ->> e.payment_key AS numeric),
                     e.payment_amount) AS payment_available
    ) v
    CROSS JOIN LATERAL (
        SELECT
            CASE WHEN e.is_title_iv = 1
                       AND e.payment_fiscal_year_start <> e.charge_fiscal_year_start
                THEN 1 ELSE 0 END AS cross_fy_title_iv,
            COALESCE(CAST(a.title_iv_given_by_fy
                ->> CAST(e.payment_fiscal_year_start AS text) AS numeric), 0)
                AS given_so_far,
            COALESCE(CAST(a.title_iv_received_by_fy
                ->> CAST(e.charge_fiscal_year_start AS text) AS numeric), 0)
                AS received_so_far
    ) limits
    CROSS JOIN LATERAL (
        SELECT ROUND(LEAST(
            v.charge_available,
            v.payment_available,
            CASE WHEN limits.cross_fy_title_iv = 1 THEN GREATEST(LEAST(
                p.title_iv_cross_fy_cap - limits.given_so_far,
                p.title_iv_cross_fy_cap - limits.received_so_far
            ), 0) ELSE v.payment_available END
        ), 2) AS amount
    ) applied
),

allocation_final AS (
    SELECT a.*
    FROM priority_allocation a
    LEFT JOIN allocation_pair_counts n ON n.pidm = a.pidm
    WHERE a.allocation_step = COALESCE(n.pair_count, 0)
),

allocation_transfer_summary AS MATERIALIZED (
    SELECT
        a.pidm,
        ROUND(SUM(a.last_applied_amount) FILTER (
            WHERE a.last_is_title_iv = 1
              AND a.last_payment_fiscal_year_start
                    > a.last_charge_fiscal_year_start
        ), 2) AS title_iv_to_older_fy,
        ROUND(SUM(a.last_applied_amount) FILTER (
            WHERE a.last_is_title_iv = 0
              AND a.last_charge_kind = 'HISTORICAL_FY_DEFICIT'
        ), 2) AS unrestricted_to_older_terms
    FROM priority_allocation a
    WHERE a.allocation_step > 0
    GROUP BY a.pidm
),

selected_balance_sources AS (
    SELECT
        s.*,
        ROUND(COALESCE(
            CAST(a.payment_remaining ->> s.payment_key AS numeric),
            s.stage_source_amount
        ), 2) AS source_credit_amount
    FROM numbered_payment_sources s
    INNER JOIN allocation_final a ON a.pidm = s.pidm
    WHERE COALESCE(
        CAST(a.payment_remaining ->> s.payment_key AS numeric),
        s.stage_source_amount
    ) > 0
),

unpaid_charge_summary AS MATERIALIZED (
    SELECT
        c.pidm,
        ROUND(SUM(COALESCE(
            CAST(a.charge_remaining ->> c.charge_key AS numeric),
            c.charge_amount
        )), 2) AS unpaid_charge_amount
    FROM numbered_charges c
    INNER JOIN allocation_final a ON a.pidm = c.pidm
    GROUP BY c.pidm
),

stored_balance_comparison AS MATERIALIZED (
    SELECT
        b.pidm,
        COUNT(s.payment_key) FILTER (
            WHERE ABS(
                COALESCE(r.source_credit_amount, 0) - s.stored_unused_amount
            ) > 0.01
        ) AS stored_balance_difference_count
    FROM account_balances b
    LEFT JOIN numbered_payment_sources s ON s.pidm = b.pidm
    LEFT JOIN selected_balance_sources r
        ON r.pidm = s.pidm AND r.payment_key = s.payment_key
    GROUP BY b.pidm
),

balance_source_summary AS MATERIALIZED (
    SELECT
        r.pidm,
        COUNT(*) AS balance_source_group_count,
        ROUND(SUM(r.source_credit_amount), 2) AS balance_source_credit_total,
        ROUND(SUM(CASE WHEN r.detail_code = 'FDPL'
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_fdpl_amount,
        ROUND(SUM(CASE WHEN r.detail_code <> 'FDPL'
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_non_fdpl_amount,
        CAST(0 AS bigint) AS ambiguous_source_pool_count,
        STRING_AGG(
            CONCAT(
                r.effective_priority_code,
                ' / ', r.term_code,
                ' / tran ', r.tran_number,
                ' / ', r.detail_code, ' (', TRIM(r.detail_desc), ')',
                ' / ', r.fund_type,
                ' / remaining ', TO_CHAR(r.source_credit_amount, 'FM999999990.00')
            ),
            ' | ' ORDER BY r.payment_sequence
        ) AS balance_sources
    FROM selected_balance_sources r
    GROUP BY r.pidm
),

term_balance_summary AS MATERIALIZED (
    SELECT
        x.pidm,
        ROUND(SUM(x.accounting_amount) FILTER (
            WHERE x.term_code = p.previous_term
        ), 2) AS previous_term_balance,
        ROUND(SUM(x.accounting_amount) FILTER (
            WHERE x.term_sort < CAST(p.previous_term AS integer)
        ), 2) AS prior_terms_balance
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.term_sort IS NOT NULL
      AND x.term_sort < CAST(p.target_term AS integer)
    GROUP BY x.pidm
),

/* Current-term FDPL context remains visible; refund ownership can span FYs. */
fdpl_summary AS MATERIALIZED (
    SELECT
        s.pidm,
        COUNT(*) AS fdpl_row_count,
        MIN(s.tran_number) AS first_fdpl_tran_number,
        MAX(s.tran_number) AS last_fdpl_tran_number,
        ROUND(SUM(s.source_amount), 2) AS fdpl_credit_amount,
        ROUND(-SUM(s.source_amount), 2) AS fdpl_net_amount,
        COUNT(DISTINCT s.aidy_code) AS fdpl_aidy_count,
        MIN(s.aidy_code) AS fdpl_aidy_code_min,
        STRING_AGG(DISTINCT s.aidy_code, ', ' ORDER BY s.aidy_code)
            AS fdpl_aidy_code
    FROM payment_sources s
    CROSS JOIN params p
    WHERE s.term_code = p.target_term
      AND s.detail_code = 'FDPL'
    GROUP BY s.pidm
),

unused_fdpl_aid_years AS (
    SELECT DISTINCT s.pidm, s.aidy_code
    FROM selected_balance_sources s
    WHERE s.detail_code = 'FDPL'
),

plus_authorization_by_aid_year AS MATERIALIZED (
    SELECT
        f.pidm,
        f.aidy_code,
        COUNT(r.rlrpapp_pidm) AS plus_auth_row_count,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(r.rlrpapp_plus_to_student, ''))) = 'Y'
        ) AS plus_auth_y_count,
        COUNT(*) FILTER (
            WHERE r.rlrpapp_pidm IS NOT NULL
              AND UPPER(TRIM(COALESCE(r.rlrpapp_plus_to_student, ''))) = 'N'
        ) AS plus_auth_n_count,
        COUNT(*) FILTER (
            WHERE r.rlrpapp_pidm IS NOT NULL
              AND UPPER(TRIM(COALESCE(r.rlrpapp_plus_to_student, '')))
                    NOT IN ('Y', 'N')
        ) AS plus_auth_invalid_count,
        STRING_AGG(DISTINCT COALESCE(
            NULLIF(TRIM(r.rlrpapp_plus_to_student), ''), '[blank]'
        ), ', ') AS plus_auth_raw_values,
        MAX(r.rlrpapp_activity_date) AS plus_auth_activity_date
    FROM unused_fdpl_aid_years f
    LEFT JOIN faismgr.rlrpapp r
        ON r.rlrpapp_pidm = f.pidm
       AND r.rlrpapp_aidy_code IS NOT DISTINCT FROM f.aidy_code
    GROUP BY f.pidm, f.aidy_code
),

unused_fdpl_authorized_sources AS (
    SELECT
        s.*,
        CASE
            WHEN a.plus_auth_row_count = 0 THEN 'MISSING'
            WHEN a.plus_auth_invalid_count > 0
              OR (a.plus_auth_y_count > 0 AND a.plus_auth_n_count > 0)
                THEN 'CONFLICT'
            WHEN a.plus_auth_y_count > 0 THEN 'Y'
            WHEN a.plus_auth_n_count > 0 THEN 'N'
            ELSE 'CONFLICT'
        END AS source_plus_to_student_status
    FROM selected_balance_sources s
    INNER JOIN plus_authorization_by_aid_year a
        ON a.pidm = s.pidm
       AND a.aidy_code IS NOT DISTINCT FROM s.aidy_code
    WHERE s.detail_code = 'FDPL'
),

fdpl_refund_summary AS MATERIALIZED (
    SELECT
        s.pidm,
        COUNT(*) AS unused_fdpl_source_count,
        ROUND(SUM(s.source_credit_amount), 2) AS unused_fdpl_amount,
        ROUND(SUM(CASE WHEN s.source_plus_to_student_status = 'N'
            THEN s.source_credit_amount ELSE 0 END), 2) AS parent_fdpl_amount,
        COUNT(*) FILTER (
            WHERE s.source_plus_to_student_status = 'MISSING'
        ) AS missing_fdpl_auth_count,
        COUNT(*) FILTER (
            WHERE s.source_plus_to_student_status = 'CONFLICT'
        ) AS conflicting_fdpl_auth_count,
        COUNT(*) FILTER (
            WHERE s.source_plus_to_student_status = 'Y'
        ) AS student_fdpl_source_count,
        COUNT(*) FILTER (
            WHERE s.source_plus_to_student_status = 'N'
        ) AS parent_fdpl_source_count
    FROM unused_fdpl_authorized_sources s
    GROUP BY s.pidm
),

plus_authorization AS MATERIALIZED (
    SELECT
        a.pidm,
        SUM(a.plus_auth_row_count) AS plus_auth_row_count,
        STRING_AGG(
            CONCAT(COALESCE(a.aidy_code, '[no aid year]'), ': ',
                   COALESCE(a.plus_auth_raw_values, '[missing]')),
            ' | ' ORDER BY a.aidy_code
        ) AS plus_auth_raw_values,
        MAX(a.plus_auth_activity_date) AS plus_auth_activity_date
    FROM plus_authorization_by_aid_year a
    GROUP BY a.pidm
),

original_payment_summary AS MATERIALIZED (
    SELECT
        s.pidm,
        COUNT(*) AS original_payment_row_count,
        ROUND(SUM(s.source_credit_amount), 2) AS original_payment_total,
        MAX(s.tran_number) AS latest_original_payment_tran,
        MAX(s.activity_date) AS latest_original_payment_activity_date,
        STRING_AGG(
            CONCAT(
                s.term_code, ' / ', s.detail_code,
                ' / priority ', s.effective_priority_code,
                ' / tran ', s.tran_number,
                ' / ', TO_CHAR(s.source_credit_amount, 'FM999999990.00')
            ),
            ' | ' ORDER BY s.term_sort, s.tran_number
        ) AS original_payment_detail
    FROM selected_balance_sources s
    WHERE s.detail_code IN ('ACHK', 'CRDS', 'CRED', 'CRVC', 'CRAM', 'CRMC')
    GROUP BY s.pidm
),

student_delivery_sources AS MATERIALIZED (
    SELECT
        s.pidm,
        ROUND(SUM(CASE
            WHEN s.detail_code = 'ACHK'
             AND s.effective_date IS NOT NULL
             AND p.run_date < CAST(s.effective_date AS date) + 16
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_clearing_wait_amount,
        MIN(CAST(s.effective_date AS date) + 16) FILTER (
            WHERE s.detail_code = 'ACHK'
              AND s.effective_date IS NOT NULL
              AND p.run_date < CAST(s.effective_date AS date) + 16
        ) AS achk_next_eligible_date,
        ROUND(SUM(CASE
            WHEN s.detail_code = 'ACHK'
             AND s.effective_date IS NOT NULL
             AND p.run_date >= CAST(s.effective_date AS date) + 16
             AND (p.run_date - CAST(s.effective_date AS date)) <= 180
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_transact_eligible_amount,
        ROUND(SUM(CASE
            WHEN s.detail_code = 'ACHK'
             AND s.effective_date IS NOT NULL
             AND (p.run_date - CAST(s.effective_date AS date)) > 180
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_too_old_amount,
        ROUND(SUM(CASE
            WHEN s.detail_code = 'ACHK'
             AND (s.effective_date IS NULL
               OR CAST(s.effective_date AS date) > p.run_date)
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_date_review_amount,
        ROUND(SUM(CASE WHEN s.detail_code = 'CRVC'
            THEN s.source_credit_amount ELSE 0 END), 2) AS crvc_transact_amount
    FROM selected_balance_sources s
    CROSS JOIN params p
    GROUP BY s.pidm
),

joined AS (
    SELECT
        b.pidm,
        i.cwid,
        i.last_name,
        i.first_name,
        pc.deceased_ind,
        pc.deceased_date,
        pc.confidential_ind,
        CASE
            WHEN UPPER(TRIM(COALESCE(i.cwid, ''))) LIKE 'TPS%'
              OR legacy_tps.cwid IS NOT NULL
                THEN 'Y'
            ELSE 'N'
        END AS third_party_review_required_ind,
        CASE
            WHEN UPPER(TRIM(COALESCE(i.cwid, ''))) LIKE 'TPS%'
                THEN 'TPS_CWID_PREFIX'
            WHEN legacy_tps.cwid IS NOT NULL
                THEN 'LEGACY_CWID_LIST'
            ELSE NULL
        END AS third_party_match_source,
        b.full_account_balance,
        COALESCE(bs.balance_source_credit_total, 0) AS total_refund_amount,
        bs.balance_sources,
        COALESCE(bs.balance_source_group_count, 0) AS balance_source_group_count,
        COALESCE(bs.balance_source_credit_total, 0) AS balance_source_credit_total,
        COALESCE(bs.unused_fdpl_amount, 0) AS unused_fdpl_amount,
        COALESCE(bs.unused_non_fdpl_amount, 0) AS unused_non_fdpl_amount,
        v.invalid_priority_count,
        v.missing_transaction_amount_count,
        v.negative_source_count,
        v.invalid_term_count,
        v.future_term_count,
        v.special_priority_mismatch_count,
        v.missing_transaction_balance_count,
        COALESCE(n.negative_net_source_count, 0) AS negative_net_source_count,
        COALESCE(sc.stored_balance_difference_count, 0)
            AS stored_balance_difference_count,
        COALESCE(uc.unpaid_charge_amount, 0) AS unpaid_charge_amount,
        COALESCE(bs.ambiguous_source_pool_count, 0) AS ambiguous_source_pool_count,
        COALESCE(tb.previous_term_balance, 0) AS previous_term_balance,
        COALESCE(tb.prior_terms_balance, 0) AS prior_terms_balance,
        COALESCE(ts.title_iv_to_older_fy, 0) AS title_iv_to_older_fy,
        COALESCE(ts.unrestricted_to_older_terms, 0)
            AS unrestricted_to_older_terms,
        CASE WHEN v.invalid_priority_count > 0
               OR v.missing_transaction_amount_count > 0
               OR v.invalid_term_count > 0
               OR v.future_term_count > 0
               OR v.special_priority_mismatch_count > 0
               OR COALESCE(n.negative_net_source_count, 0) > 0
               OR COALESCE(fr.missing_fdpl_auth_count, 0) > 0
               OR COALESCE(fr.conflicting_fdpl_auth_count, 0) > 0
            THEN 'Y' ELSE 'N' END AS refund_split_blocked_ind,
        b.last_ar_activity_date,
        COALESCE(ac.account_control_row_count, 0) AS account_control_row_count,
        CASE WHEN COALESCE(ac.refund_hold_count, 0) > 0 THEN 'Y' ELSE 'N' END
            AS refund_hold_ind,
        ac.raw_delinquency_code,
        ac.raw_refund_account_ind,
        CASE
            WHEN UPPER(TRIM(COALESCE(ac.raw_refund_account_ind, ''))) = 'Y'
                THEN 'Y'
            WHEN UPPER(TRIM(COALESCE(ac.raw_refund_account_ind, ''))) IN ('', 'N')
                THEN 'N'
            ELSE 'UNKNOWN'
        END AS refund_account_selected_ind,
        ac.account_control_activity_date,
        CASE WHEN COALESCE(ed.active_ed_row_count, 0) > 0 THEN 'Y' ELSE 'N' END
            AS active_ed_ind,
        COALESCE(ed.active_ed_row_count, 0) AS active_ed_row_count,
        ed.ed_activity_date,
        COALESCE(f.fdpl_row_count, 0) AS fdpl_row_count,
        f.first_fdpl_tran_number,
        f.last_fdpl_tran_number,
        f.fdpl_credit_amount,
        f.fdpl_net_amount,
        COALESCE(f.fdpl_aidy_count, 0) AS fdpl_aidy_count,
        f.fdpl_aidy_code_min,
        f.fdpl_aidy_code,
        COALESCE(pa.plus_auth_row_count, 0) AS plus_auth_row_count,
        pa.plus_auth_raw_values,
        pa.plus_auth_activity_date,
        CASE
            WHEN COALESCE(fr.unused_fdpl_source_count, 0) = 0 THEN 'NOT_APPLICABLE'
            WHEN COALESCE(fr.missing_fdpl_auth_count, 0) > 0 THEN 'MISSING'
            WHEN COALESCE(fr.conflicting_fdpl_auth_count, 0) > 0 THEN 'CONFLICT'
            WHEN fr.student_fdpl_source_count > 0
             AND fr.parent_fdpl_source_count > 0 THEN 'MIXED'
            WHEN fr.student_fdpl_source_count > 0 THEN 'Y'
            ELSE 'N'
        END AS plus_to_student_status,
        COALESCE(fr.parent_fdpl_amount, 0) AS authorized_parent_fdpl_amount,
        COALESCE(fr.missing_fdpl_auth_count, 0) AS missing_fdpl_auth_count,
        COALESCE(fr.conflicting_fdpl_auth_count, 0) AS conflicting_fdpl_auth_count,
        COALESCE(op.original_payment_row_count, 0) AS original_payment_row_count,
        CASE WHEN COALESCE(op.original_payment_row_count, 0) = 0 THEN 0
            ELSE op.original_payment_total END AS original_payment_total,
        op.latest_original_payment_tran,
        op.latest_original_payment_activity_date,
        op.original_payment_detail,
        COALESCE(ds.achk_transact_eligible_amount, 0)
            AS achk_transact_eligible_amount,
        COALESCE(ds.achk_clearing_wait_amount, 0) AS achk_clearing_wait_amount,
        ds.achk_next_eligible_date,
        COALESCE(ds.achk_too_old_amount, 0) AS achk_too_old_amount,
        COALESCE(ds.achk_date_review_amount, 0) AS achk_date_review_amount,
        COALESCE(ds.crvc_transact_amount, 0) AS crvc_transact_amount
    FROM account_balances b
    INNER JOIN balance_input_checks v ON v.pidm = b.pidm
    LEFT JOIN current_identity i
        ON i.pidm = b.pidm
    LEFT JOIN person_controls pc
        ON pc.pidm = b.pidm
    LEFT JOIN legacy_third_party_cwids legacy_tps
        ON legacy_tps.cwid = UPPER(TRIM(i.cwid))
    LEFT JOIN account_controls ac
        ON ac.pidm = b.pidm
    LEFT JOIN active_ed ed
        ON ed.pidm = b.pidm
    LEFT JOIN balance_source_summary bs
        ON bs.pidm = b.pidm
    LEFT JOIN fdpl_summary f
        ON f.pidm = b.pidm
    LEFT JOIN unpaid_charge_summary uc ON uc.pidm = b.pidm
    LEFT JOIN net_source_checks n ON n.pidm = b.pidm
    LEFT JOIN stored_balance_comparison sc ON sc.pidm = b.pidm
    LEFT JOIN term_balance_summary tb ON tb.pidm = b.pidm
    LEFT JOIN allocation_transfer_summary ts ON ts.pidm = b.pidm
    LEFT JOIN fdpl_refund_summary fr ON fr.pidm = b.pidm
    LEFT JOIN plus_authorization pa
        ON pa.pidm = b.pidm
    LEFT JOIN original_payment_summary op
        ON op.pidm = b.pidm
    LEFT JOIN student_delivery_sources ds
        ON ds.pidm = b.pidm
),

parent_plus_calculation AS (
    SELECT
        j.*,
        /* Stored balances are diagnostic; reconstructed allocation controls ownership. */
        CASE WHEN j.refund_split_blocked_ind = 'Y'
               OR j.missing_transaction_balance_count > 0
               OR j.stored_balance_difference_count > 0
               OR j.unpaid_charge_amount > 0
               OR j.balance_source_credit_total
                    <> GREATEST(-j.full_account_balance, 0)
               OR j.ambiguous_source_pool_count > 0
            THEN 'Y' ELSE 'N' END AS allocation_review_required_ind,
        CASE
            WHEN j.refund_split_blocked_ind = 'Y' THEN NULL
            ELSE ROUND(LEAST(
                j.total_refund_amount,
                j.authorized_parent_fdpl_amount
            ), 2)
        END AS calculated_fdpl_created_credit
    FROM joined j
),

refund_split AS (
    SELECT
        c.*,
        CASE
            WHEN c.refund_split_blocked_ind = 'Y' THEN NULL
            ELSE c.calculated_fdpl_created_credit
        END AS proposed_parent_refund_amount,
        CASE
            WHEN c.refund_split_blocked_ind = 'Y' THEN NULL
            ELSE c.total_refund_amount - c.calculated_fdpl_created_credit
        END AS proposed_student_refund_amount
    FROM parent_plus_calculation c
),

delivery_amounts AS (
    SELECT
        s.*,
        ROUND(GREATEST(
            COALESCE(s.proposed_student_refund_amount, 0)
                - s.achk_transact_eligible_amount
                - s.achk_clearing_wait_amount
                - s.achk_too_old_amount
                - s.achk_date_review_amount
                - s.crvc_transact_amount,
            0
        ), 2) AS standard_student_delivery_amount,
        (CASE WHEN s.achk_transact_eligible_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_clearing_wait_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_too_old_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_date_review_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.crvc_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN COALESCE(s.proposed_student_refund_amount, 0)
                    - s.achk_transact_eligible_amount
                    - s.achk_clearing_wait_amount
                    - s.achk_too_old_amount
                    - s.achk_date_review_amount
                    - s.crvc_transact_amount > 0
                THEN 1 ELSE 0 END) AS student_delivery_component_count
    FROM refund_split s
),

delivery AS (
    SELECT
        s.*,
        CASE
            WHEN COALESCE(s.proposed_student_refund_amount, 0) <= 0 THEN 'NONE'
            WHEN s.refund_hold_ind = 'Y' THEN 'Refund Hold - Student'
            WHEN s.third_party_review_required_ind = 'Y'
                THEN 'THIRD_PARTY_REVIEW'
            WHEN s.student_delivery_component_count = 1
             AND s.achk_transact_eligible_amount > 0 THEN 'AFRD (Transact)'
            WHEN s.student_delivery_component_count = 1
             AND s.achk_clearing_wait_amount > 0 THEN CONCAT(
                'ACHK Clearing Wait until ',
                TO_CHAR(s.achk_next_eligible_date, 'MM/DD/YYYY')
             )
            WHEN s.student_delivery_component_count = 1
             AND s.achk_too_old_amount > 0
                THEN 'AFRD (Transact) - May Be Too Old'
            WHEN s.student_delivery_component_count = 1
             AND s.achk_date_review_amount > 0 THEN 'ACHK Date Review'
            WHEN s.student_delivery_component_count = 1
             AND s.crvc_transact_amount > 0 THEN 'CRVC (Transact)'
            WHEN s.student_delivery_component_count = 1
             AND s.standard_student_delivery_amount > 0
                THEN CASE WHEN s.active_ed_ind = 'Y'
                    THEN 'ARFD (System)' ELSE 'RFND (CHECK)' END
            ELSE CONCAT_WS(
                '; ',
                CASE WHEN s.achk_transact_eligible_amount > 0 THEN CONCAT(
                    'AFRD (Transact) ',
                    TO_CHAR(s.achk_transact_eligible_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.crvc_transact_amount > 0 THEN CONCAT(
                    'CRVC (Transact) ',
                    TO_CHAR(s.crvc_transact_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.achk_clearing_wait_amount > 0 THEN CONCAT(
                    'ACHK Clearing Wait until ',
                    TO_CHAR(s.achk_next_eligible_date, 'MM/DD/YYYY'), ' / ',
                    TO_CHAR(s.achk_clearing_wait_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.achk_too_old_amount > 0 THEN CONCAT(
                    'AFRD (Transact) - May Be Too Old ',
                    TO_CHAR(s.achk_too_old_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.achk_date_review_amount > 0 THEN CONCAT(
                    'ACHK Date Review ',
                    TO_CHAR(s.achk_date_review_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.standard_student_delivery_amount > 0 THEN CONCAT(
                    CASE WHEN s.active_ed_ind = 'Y'
                        THEN 'ARFD (System) ' ELSE 'RFND (CHECK) ' END,
                    TO_CHAR(s.standard_student_delivery_amount, 'FM999999990.00')
                ) END
            )
        END AS proposed_student_delivery,
        CASE
            WHEN COALESCE(s.proposed_parent_refund_amount, 0) > 0
             AND s.plus_to_student_status IN ('N', 'MIXED') THEN 'RFDP'
            WHEN COALESCE(s.proposed_parent_refund_amount, 0) > 0
                THEN 'PARENT_PLUS_AUTH_REVIEW'
            ELSE 'NONE'
        END AS proposed_parent_delivery
    FROM delivery_amounts s
),

final_review AS (
    SELECT
        d.*,
        CONCAT_WS(
            '; ',
            CASE WHEN d.invalid_priority_count > 0
                THEN 'MISSING_OR_INVALID_DETAIL_PRIORITY' END,
            CASE WHEN d.missing_transaction_amount_count > 0
                THEN 'MISSING_TRANSACTION_AMOUNT' END,
            CASE WHEN d.missing_transaction_balance_count > 0
                THEN 'MISSING_TRANSACTION_BALANCE' END,
            CASE WHEN d.stored_balance_difference_count > 0
                THEN 'STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION' END,
            CASE WHEN d.invalid_term_count > 0
                THEN 'UNRECOGNIZED_TERM_CODE' END,
            CASE WHEN d.future_term_count > 0
                THEN 'FUTURE_TERM_ACTIVITY_EXCLUDED_FROM_ALLOCATION' END,
            CASE WHEN d.special_priority_mismatch_count > 0
                THEN 'ARTIFICIAL_PRIORITY_DETAIL_CODE_HAS_UNEXPECTED_BASE_PRIORITY' END,
            CASE WHEN d.negative_net_source_count > 0
                THEN 'NEGATIVE_NET_SOURCE_REQUIRES_REVIEW' END,
            CASE WHEN d.unpaid_charge_amount > 0
                THEN 'UNPAID_CHARGES_AFTER_POLICY_ALLOCATION' END,
            CASE WHEN d.balance_source_credit_total
                          <> GREATEST(-d.full_account_balance, 0)
                THEN 'POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT' END,
            CASE WHEN d.refund_hold_ind = 'Y' THEN 'REFUND_HOLD_RH' END,
            CASE WHEN UPPER(TRIM(COALESCE(d.deceased_ind, ''))) = 'Y'
                THEN 'DECEASED_PERSON' END,
            CASE WHEN d.third_party_review_required_ind = 'Y'
                THEN 'THIRD_PARTY_ACCOUNT_REVIEW_REQUIRED' END,
            CASE WHEN d.cwid IS NULL THEN 'CURRENT_SPRIDEN_MISSING' END,
            CASE WHEN d.account_control_row_count <> 1
                THEN CONCAT('TBBACCT_ROW_COUNT_', d.account_control_row_count) END,
            CASE WHEN d.active_ed_row_count > 1
                THEN CONCAT('MULTIPLE_ACTIVE_ED_ROWS_', d.active_ed_row_count) END,
            CASE WHEN d.plus_to_student_status = 'MISSING'
                THEN 'PLUS_AUTH_RECORD_MISSING' END,
            CASE WHEN d.plus_to_student_status = 'CONFLICT'
                THEN 'PLUS_AUTH_VALUES_CONFLICT' END,
            CASE WHEN d.original_payment_row_count > 0
                THEN 'REVIEW_ACH_CC_IN_TRANSACT' END,
            CASE WHEN d.achk_clearing_wait_amount > 0
                THEN 'ACHK_CLEARING_PERIOD_NOT_MET' END,
            CASE WHEN d.achk_too_old_amount > 0
                THEN 'ACHK_OVER_180_DAYS_MAY_BE_TOO_OLD_FOR_ORIGINAL_METHOD' END,
            CASE WHEN d.achk_date_review_amount > 0
                THEN 'ACHK_EFFECTIVE_DATE_MISSING_OR_FUTURE' END
        ) AS review_reasons
    FROM delivery d
)

SELECT
    f.cwid,
    f.last_name,
    f.first_name,
    f.full_account_balance,
    f.total_refund_amount,
    f.proposed_student_delivery,
    f.proposed_student_refund_amount AS student_refund_amount,
    f.proposed_parent_delivery,
    f.proposed_parent_refund_amount AS parent_refund_amount,
    f.balance_sources,
    f.plus_to_student_status,
    p.target_term AS parent_plus_target_term,
    CASE WHEN f.proposed_student_refund_amount IS NULL
               OR f.proposed_parent_refund_amount IS NULL
        THEN 'UNDETERMINED_SEE_REVIEW_REASONS'
        ELSE 'CALCULATED_SUBJECT_TO_REVIEW'
    END AS refund_split_status,
    f.third_party_review_required_ind,
    f.third_party_match_source,
    f.refund_hold_ind,
    f.raw_delinquency_code,
    f.active_ed_ind,
    f.raw_refund_account_ind,
    f.refund_account_selected_ind,
    f.fdpl_row_count,
    f.fdpl_credit_amount AS target_term_fdpl_amount,
    f.fdpl_aidy_code,
    'EFFECTIVE_PRIORITY_THEN_EARLIEST_TRAN_NUMBER' AS fdpl_priority_tie_rule,
    f.unused_fdpl_amount,
    f.unused_non_fdpl_amount,
    f.balance_source_credit_total AS total_unused_payment_amount,
    f.unpaid_charge_amount,
    f.allocation_review_required_ind,
    f.previous_term_balance AS previous_term_balance_before_current_payments,
    f.prior_terms_balance AS prior_terms_balance_before_current_payments,
    f.title_iv_to_older_fy AS title_iv_applied_to_older_fiscal_years,
    f.unrestricted_to_older_terms
        AS unrestricted_applied_to_older_terms,
    f.original_payment_row_count,
    f.original_payment_total,
    f.original_payment_detail,
    f.deceased_ind,
    f.deceased_date,
    f.confidential_ind,
    f.plus_auth_row_count,
    f.plus_auth_raw_values,
    f.negative_source_count,
    f.ambiguous_source_pool_count,
    CASE
        WHEN f.refund_hold_ind = 'Y' THEN 'HOLD'
        WHEN f.allocation_review_required_ind = 'Y' THEN 'MANUAL_REVIEW'
        WHEN UPPER(TRIM(COALESCE(f.deceased_ind, ''))) = 'Y' THEN 'MANUAL_REVIEW'
        WHEN f.third_party_review_required_ind = 'Y' THEN 'MANUAL_REVIEW'
        WHEN f.cwid IS NULL THEN 'MANUAL_REVIEW'
        WHEN f.account_control_row_count <> 1 THEN 'MANUAL_REVIEW'
        WHEN f.active_ed_row_count > 1 THEN 'MANUAL_REVIEW'
        WHEN f.plus_to_student_status IN ('MISSING', 'CONFLICT')
            THEN 'MANUAL_REVIEW'
        WHEN f.achk_date_review_amount > 0 THEN 'MANUAL_REVIEW'
        WHEN f.achk_clearing_wait_amount > 0 THEN 'WAIT_ACH_CLEARING'
        WHEN f.original_payment_row_count > 0 THEN 'TRANSACT_REVIEW'
        ELSE 'READY_FOR_STAFF_REVIEW'
    END AS review_status,
    f.review_reasons,
    f.last_ar_activity_date,
    f.account_control_activity_date,
    f.ed_activity_date,
    f.plus_auth_activity_date
FROM final_review f
CROSS JOIN params p
WHERE (p.cwid_filter IS NULL OR f.cwid = TRIM(p.cwid_filter))
  AND (p.last_name_filter IS NULL
       OR UPPER(f.last_name) LIKE UPPER(p.last_name_filter))
  AND (f.total_refund_amount > 0 OR f.full_account_balance < 0)
ORDER BY
    f.last_name,
    f.first_name,
    f.cwid;
