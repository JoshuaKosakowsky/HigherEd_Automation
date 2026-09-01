/*
Student Refund Review
Colorado School of Mines | Banner Insights (PostgreSQL-flavored SQL)

PURPOSE
  Read-only decision-support report for student refund review.
  This query does not approve a refund or create a Transact/TSARFND file.

CONFIRMED CONTROLS
  * Candidate accounts come directly from TBRACCD. Every account whose fully
    classified, accounting-signed balance is negative is included.
  * The balance covers the full account, without a term restriction, because
    payments can be posted in one term for charges in another term.
  * Refund ownership uses each target-term transaction's current
    TBRACCD_BALANCE after Banner payment application. Other terms' transactions
    are not replayed. A mismatch with the full-account refund requires review.
  * TBRACCD_AMOUNT is converted to an accounting-signed amount using
    TBBDETC_TYPE_IND: payments are negative and charges are positive.
  * TBBACCT_DELI_CODE = 'RH' means Refund Hold and blocks processing.
  * TBBACCT_REFUND_IND checked means the account is selected for a TSARFND
    check; it is not a refund-eligibility indicator.
  * An active ED marker is SPRHOLD_HLDD_CODE = 'ED' with a to-date of
    9999-12-31; ED identifies the student eRefund route.
  * FDPL is the active Parent PLUS detail code.
  * RLRPAPP_PLUS_TO_STUDENT is matched by PIDM and the aid-year code carried
    on the target-term FDPL transaction.
  * Third-party accounts are identified by a TPS-prefixed CWID or the legacy
    CWID list below. They always require manual review.
  * ACH/card detail codes requiring a Transact review are:
      ACHK, CRDS, CRED, CRVC, CRAM, CRMC
  * ACHK clearing age is measured from TBRACCD_EFFECTIVE_DATE, consistent with
    the AR aging queries. An ACHK is eligible for AFRD through Transact only
    when it is more than 16 days old and less than 90 days old. Eligible ACHK
    activity is netted within that window so returns can reduce or eliminate
    the amount proposed for AFRD.
  * CRVC unapplied balances are proposed for immediate return through Transact.

BALANCE-SOURCE EXPLANATION
  BALANCE_SOURCES lists target-term payment transactions whose current stored
  balance is negative. The exact remaining transaction balance, not a replay of
  original transaction amounts, determines the source of the current refund.

PARENT PLUS REFUND SPLIT
  TBBDETC_PRIORITY remains visible as configuration context, but it does not
  reconstruct payment application. Local priorities can require correction and
  staff may manually apply payments to charges. TBRACCD_BALANCE reflects that
  resulting application state and therefore controls the current source split.

  A missing transaction balance, a balance with the wrong sign for its detail
  type, an unpaid charge balance, or a failure to reconcile target-term remaining
  payments to the full-account refund suppresses the proposed split. A missing
  or invalid priority remains a review reason but does not override a reconciled
  stored balance.
  For exactly one target-term FDPL row with a resolved source state, the parent
  portion is its unused amount, capped at the full-account refund. Existing
  PLUS-to-student authorization still controls the recipient.

FIRST-RUN VALIDATION
  1. Confirm FULL_ACCOUNT_BALANCE equals the TSAAREV full Query Balance.
  2. Confirm every active TBRACCD detail code has a C or P type in TBBDETC;
     accounts containing an unclassified type cannot be signed reliably.
  3. Validate TBBDETC_PRIORITY as configuration context. Correct application in
     Banner when configuration or prior application is wrong before using this report.
  4. Reconcile TBRACCD_BALANCE against actual Banner payment application for the
     target term. Its unused payments must equal the full-
     account TOTAL_REFUND_AMOUNT with no unpaid target-term charges before the
     proposed split is considered resolved. Settled prior terms must not alter it.
  5. Rerun immediately before any Transact/TSARFND action and remove accounts
     whose balance or controls changed.
*/

WITH
term_context AS (
    SELECT
        CURRENT_DATE AS run_date,
        /*
        Leave NULL to derive the Mines term containing RUN_DATE. Set a valid
        six-digit Banner term only for an intentional prior-term or work-ahead run.
        */
        CAST(NULL AS varchar(6)) AS target_term_override
),

params AS (
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
        /* Replace NULL with 'SMITH%' for an optional last-name validation run. */
        CAST(NULL AS varchar(60)) AS last_name_filter
    FROM term_context
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
Calculate an accounting-signed balance for every PIDM with AR activity. Detail
codes without a C/P type are counted so an indeterminate account is never
presented as a reliable refund amount.
*/
account_balance_rollup AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE 0
        END), 2) AS full_account_balance,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(d.tbbdetc_type_ind, '')))
                  NOT IN ('C', 'P')
        ) AS unclassified_detail_type_count,
        MAX(t.tbraccd_activity_date) AS last_ar_activity_date
    FROM taismgr.tbraccd t
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY t.tbraccd_pidm
),

/* Every fully classifiable account with a full-account credit balance. */
account_balances AS (
    SELECT
        r.pidm,
        r.full_account_balance,
        r.last_ar_activity_date
    FROM account_balance_rollup r
    WHERE r.unclassified_detail_type_count = 0
      AND r.full_account_balance < 0
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

person_controls AS (
    SELECT
        p.spbpers_pidm AS pidm,
        p.spbpers_dead_ind AS deceased_ind,
        p.spbpers_dead_date AS deceased_date,
        p.spbpers_confid_ind AS confidential_ind,
        p.spbpers_activity_date AS person_activity_date
    FROM saturn.spbpers p
),

account_controls AS (
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
    GROUP BY a.tbbacct_pidm
),

active_ed AS (
    SELECT
        h.sprhold_pidm AS pidm,
        COUNT(*) AS active_ed_row_count,
        MAX(h.sprhold_activity_date) AS ed_activity_date
    FROM saturn.sprhold h
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'ED'
      AND CAST(h.sprhold_to_date AS date) = DATE '9999-12-31'
    GROUP BY h.sprhold_pidm
),

/*
Allocate only target-term transactions on credit-balance accounts. Keeping this
filter before source netting excludes historical/future charges, payments, and
issued refunds from every allocation consumer, including ACH/card review.
The full-account balance/population above intentionally remains unrestricted.
*/
candidate_transactions AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        t.tbraccd_term_code AS term_code,
        t.tbraccd_aidy_code AS aidy_code,
        t.tbraccd_tran_number AS tran_number,
        t.tbraccd_detail_code AS detail_code,
        COALESCE(d.tbbdetc_desc, '[Description unavailable]') AS detail_desc,
        UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
        CASE
            WHEN TRIM(CAST(d.tbbdetc_priority AS text)) ~ '^[0-9]{1,3}$'
                THEN LPAD(TRIM(CAST(d.tbbdetc_priority AS text)), 3, '0')
            ELSE NULL
        END AS priority_code,
        COALESCE(t.tbraccd_amount, 0) AS raw_amount,
        CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_amount, 0)
            ELSE NULL
        END AS amount,
        t.tbraccd_balance AS raw_transaction_balance,
        CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
                THEN -COALESCE(t.tbraccd_balance, 0)
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
                THEN COALESCE(t.tbraccd_balance, 0)
            ELSE NULL
        END AS transaction_balance,
        t.tbraccd_effective_date AS effective_date,
        t.tbraccd_activity_date AS activity_date
    FROM taismgr.tbraccd t
    INNER JOIN account_balances b
        ON b.pidm = t.tbraccd_pidm
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE t.tbraccd_term_code = p.target_term
),

/*
The stored transaction balance is Banner's current application result. Priority
is retained for review, but original amounts are not replayed to reconstruct it.
*/
balance_input_checks AS (
    SELECT
        b.pidm,
        COUNT(*) FILTER (
            WHERE x.raw_transaction_balance <> 0 AND x.priority_code IS NULL
        ) AS invalid_priority_count,
        COUNT(*) FILTER (WHERE x.raw_amount < 0) AS negative_source_count,
        COUNT(*) FILTER (WHERE x.raw_transaction_balance IS NULL)
            AS missing_transaction_balance_count,
        COUNT(*) FILTER (
            WHERE (x.type_ind = 'P' AND x.raw_transaction_balance > 0)
               OR (x.type_ind = 'C' AND x.raw_transaction_balance < 0)
        ) AS unexpected_balance_sign_count
    FROM account_balances b
    LEFT JOIN candidate_transactions x ON x.pidm = b.pidm
    GROUP BY b.pidm
),

unpaid_charge_summary AS (
    SELECT
        x.pidm,
        ROUND(SUM(CASE
            WHEN x.type_ind = 'C' AND x.raw_transaction_balance > 0
                THEN x.raw_transaction_balance
            ELSE 0
        END), 2) AS unpaid_charge_amount
    FROM candidate_transactions x
    GROUP BY x.pidm
),

selected_balance_sources AS (
    SELECT
        x.pidm,
        x.term_code,
        x.aidy_code,
        x.tran_number,
        x.detail_code,
        x.detail_desc,
        x.priority_code,
        CASE WHEN UPPER(TRIM(x.detail_code)) = 'FDPL' THEN 1 ELSE 0 END
            AS is_fdpl,
        ROUND(-x.raw_transaction_balance, 2) AS source_credit_amount,
        x.effective_date,
        x.activity_date
    FROM candidate_transactions x
    WHERE x.type_ind = 'P'
      AND x.raw_transaction_balance < 0
),

balance_source_summary AS (
    SELECT
        r.pidm,
        COUNT(*) AS balance_source_group_count,
        ROUND(SUM(r.source_credit_amount), 2) AS balance_source_credit_total,
        ROUND(SUM(CASE WHEN r.is_fdpl = 1
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_fdpl_amount,
        ROUND(SUM(CASE WHEN r.is_fdpl = 0
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_non_fdpl_amount,
        CAST(0 AS bigint) AS ambiguous_source_pool_count,
        STRING_AGG(
            CONCAT(
                COALESCE(r.priority_code, '[invalid priority]'),
                ' / ', r.detail_code, ' (', TRIM(r.detail_desc), ')',
                ' / remaining ', TO_CHAR(r.source_credit_amount, 'FM999999990.00')
            ),
            ' | ' ORDER BY r.priority_code DESC NULLS LAST, r.tran_number
        ) AS balance_sources
    FROM selected_balance_sources r
    GROUP BY r.pidm
),

/* Target-term Parent PLUS transaction. Multiple rows are exceptions. */
fdpl_summary AS (
    SELECT
        x.pidm,
        COUNT(*) AS fdpl_row_count,
        MIN(x.tran_number) AS first_fdpl_tran_number,
        MAX(x.tran_number) AS last_fdpl_tran_number,
        ROUND(SUM(CASE
            WHEN x.amount < 0 THEN -x.amount
            ELSE 0
        END), 2) AS fdpl_credit_amount,
        ROUND(SUM(x.amount), 2) AS fdpl_net_amount,
        COUNT(DISTINCT x.aidy_code) AS fdpl_aidy_count,
        MIN(x.aidy_code) AS fdpl_aidy_code_min,
        MAX(x.aidy_code) AS fdpl_aidy_code
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.term_code = p.target_term
      AND UPPER(TRIM(x.detail_code)) = 'FDPL'
    GROUP BY x.pidm
),

/* Authorization is matched to the aid year stored on the target-term FDPL row. */
plus_authorization AS (
    SELECT
        f.pidm,
        f.fdpl_aidy_code,
        COUNT(r.rlrpapp_pidm) AS plus_auth_row_count,
        COUNT(*) FILTER (
            WHERE UPPER(TRIM(COALESCE(r.rlrpapp_plus_to_student, ''))) = 'Y'
        ) AS plus_auth_y_count,
        COUNT(*) FILTER (
            WHERE r.rlrpapp_pidm IS NOT NULL
              AND UPPER(TRIM(COALESCE(r.rlrpapp_plus_to_student, ''))) <> 'Y'
        ) AS plus_auth_not_y_count,
        STRING_AGG(
            DISTINCT COALESCE(
                NULLIF(TRIM(r.rlrpapp_plus_to_student), ''),
                '[blank]'
            ),
            ', '
        ) AS plus_auth_raw_values,
        MAX(r.rlrpapp_activity_date) AS plus_auth_activity_date
    FROM fdpl_summary f
    LEFT JOIN faismgr.rlrpapp r
        ON r.rlrpapp_pidm = f.pidm
       AND r.rlrpapp_aidy_code = f.fdpl_aidy_code
    GROUP BY f.pidm, f.fdpl_aidy_code
),

/*
An ACH/card source is relevant when that payment transaction has a negative
stored balance. The delivery rules below distinguish confirmed ACHK and CRVC
routes; other original-payment detail codes retain staff Transact review.
*/
original_payment_summary AS (
    SELECT
        s.pidm,
        COUNT(*) AS original_payment_row_count,
        ROUND(SUM(s.source_credit_amount), 2) AS original_payment_total,
        MAX(s.tran_number) AS latest_original_payment_tran,
        MAX(s.activity_date) AS latest_original_payment_activity_date,
        STRING_AGG(
            CONCAT(
                COALESCE(s.term_code, '[no term]'),
                ' / ', s.detail_code,
                ' / priority ', s.priority_code,
                ' / ', TO_CHAR(s.source_credit_amount, 'FM999999990.00')
            ),
            ' | ' ORDER BY s.term_code, s.tran_number
        ) AS original_payment_detail
    FROM selected_balance_sources s
    WHERE UPPER(TRIM(s.detail_code)) IN (
          'ACHK', 'CRDS', 'CRED', 'CRVC', 'CRAM', 'CRMC'
      )
    GROUP BY s.pidm
),

/*
Separate the student original-payment sources that have confirmed delivery
rules. ACHK uses strict age boundaries from policy: age > 16 and age < 90.
Transactions at 16 days remain in the clearing wait; transactions at 90 days
or older fall back to the normal student refund route.
*/
original_payment_source_amounts AS (
    SELECT
        s.pidm,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(s.detail_code)) = 'ACHK'
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_remaining_amount,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(s.detail_code)) = 'ACHK'
             AND s.effective_date IS NOT NULL
             AND (tc.run_date - CAST(s.effective_date AS date)) > 16
             AND (tc.run_date - CAST(s.effective_date AS date)) < 90
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_window_remaining_amount,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(s.detail_code)) = 'ACHK'
             AND s.effective_date IS NOT NULL
             AND (tc.run_date - CAST(s.effective_date AS date)) BETWEEN 0 AND 16
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_clearing_wait_amount,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(s.detail_code)) = 'ACHK'
             AND (s.effective_date IS NULL
               OR CAST(s.effective_date AS date) > tc.run_date)
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_date_review_amount,
        ROUND(SUM(CASE
            WHEN UPPER(TRIM(s.detail_code)) = 'CRVC'
                THEN s.source_credit_amount ELSE 0
        END), 2) AS crvc_transact_amount
    FROM selected_balance_sources s
    CROSS JOIN term_context tc
    GROUP BY s.pidm
),

/* Net original ACHK amounts in the eligible window, including reversals. */
achk_window_net AS (
    SELECT
        x.pidm,
        ROUND(GREATEST(SUM(x.raw_amount), 0), 2) AS achk_window_net_amount
    FROM candidate_transactions x
    CROSS JOIN term_context tc
    WHERE UPPER(TRIM(x.detail_code)) = 'ACHK'
      AND x.effective_date IS NOT NULL
      AND (tc.run_date - CAST(x.effective_date AS date)) > 16
      AND (tc.run_date - CAST(x.effective_date AS date)) < 90
    GROUP BY x.pidm
),

student_delivery_sources AS (
    SELECT
        b.pidm,
        COALESCE(o.achk_remaining_amount, 0) AS achk_remaining_amount,
        ROUND(LEAST(
            COALESCE(o.achk_window_remaining_amount, 0),
            COALESCE(n.achk_window_net_amount, 0)
        ), 2) AS achk_transact_eligible_amount,
        COALESCE(o.achk_clearing_wait_amount, 0) AS achk_clearing_wait_amount,
        ROUND(GREATEST(
            COALESCE(o.achk_window_remaining_amount, 0)
                - COALESCE(n.achk_window_net_amount, 0),
            0
        ), 2) AS achk_net_review_amount,
        COALESCE(o.achk_date_review_amount, 0) AS achk_date_review_amount,
        COALESCE(o.crvc_transact_amount, 0) AS crvc_transact_amount
    FROM account_balances b
    LEFT JOIN original_payment_source_amounts o ON o.pidm = b.pidm
    LEFT JOIN achk_window_net n ON n.pidm = b.pidm
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
        GREATEST(-b.full_account_balance, 0) AS total_refund_amount,
        bs.balance_sources,
        COALESCE(bs.balance_source_group_count, 0) AS balance_source_group_count,
        COALESCE(bs.balance_source_credit_total, 0) AS balance_source_credit_total,
        COALESCE(bs.unused_fdpl_amount, 0) AS unused_fdpl_amount,
        COALESCE(bs.unused_non_fdpl_amount, 0) AS unused_non_fdpl_amount,
        v.invalid_priority_count,
        v.negative_source_count,
        v.missing_transaction_balance_count,
        v.unexpected_balance_sign_count,
        COALESCE(uc.unpaid_charge_amount, 0) AS unpaid_charge_amount,
        COALESCE(bs.ambiguous_source_pool_count, 0) AS ambiguous_source_pool_count,
        CASE WHEN v.missing_transaction_balance_count > 0
               OR v.unexpected_balance_sign_count > 0
               OR COALESCE(uc.unpaid_charge_amount, 0) <> 0
               OR COALESCE(bs.balance_source_credit_total, 0) <> -b.full_account_balance
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
        pa.plus_auth_y_count,
        pa.plus_auth_not_y_count,
        pa.plus_auth_raw_values,
        pa.plus_auth_activity_date,
        CASE
            WHEN COALESCE(f.fdpl_row_count, 0) = 0 THEN 'NOT_APPLICABLE'
            WHEN COALESCE(pa.plus_auth_row_count, 0) = 0 THEN 'MISSING'
            WHEN pa.plus_auth_y_count > 0 AND pa.plus_auth_not_y_count > 0
                THEN 'CONFLICT'
            WHEN pa.plus_auth_y_count > 0 THEN 'Y'
            ELSE 'N'
        END AS plus_to_student_status,
        COALESCE(op.original_payment_row_count, 0) AS original_payment_row_count,
        CASE WHEN COALESCE(op.original_payment_row_count, 0) = 0 THEN 0
            ELSE op.original_payment_total END AS original_payment_total,
        op.latest_original_payment_tran,
        op.latest_original_payment_activity_date,
        op.original_payment_detail,
        ds.achk_remaining_amount,
        ds.achk_transact_eligible_amount,
        ds.achk_clearing_wait_amount,
        ds.achk_net_review_amount,
        ds.achk_date_review_amount,
        ds.crvc_transact_amount
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
        /* Source review is separate from whether the recipient totals are calculable. */
        CASE WHEN j.refund_split_blocked_ind = 'Y'
               OR j.invalid_priority_count > 0
               OR j.ambiguous_source_pool_count > 0
            THEN 'Y' ELSE 'N' END AS allocation_review_required_ind,
        CASE
            WHEN j.refund_split_blocked_ind = 'Y' THEN NULL
            WHEN j.fdpl_row_count = 0 THEN CAST(0 AS numeric)
            WHEN j.fdpl_row_count = 1 THEN ROUND(
                LEAST(
                    j.total_refund_amount,
                    COALESCE(j.fdpl_credit_amount, 0),
                    j.unused_fdpl_amount
                ),
                2
            )
            ELSE NULL
        END AS calculated_fdpl_created_credit
    FROM joined j
),

refund_split AS (
    SELECT
        c.*,
        CASE
            WHEN c.refund_split_blocked_ind = 'Y' THEN NULL
            WHEN c.fdpl_row_count = 0 THEN CAST(0 AS numeric)
            WHEN c.fdpl_row_count = 1
             AND c.plus_to_student_status = 'Y' THEN CAST(0 AS numeric)
            WHEN c.fdpl_row_count = 1 THEN c.calculated_fdpl_created_credit
            ELSE NULL
        END AS proposed_parent_refund_amount,
        CASE
            WHEN c.refund_split_blocked_ind = 'Y' THEN NULL
            WHEN c.fdpl_row_count = 0 THEN c.total_refund_amount
            WHEN c.fdpl_row_count = 1
             AND c.plus_to_student_status = 'Y' THEN c.total_refund_amount
            WHEN c.fdpl_row_count = 1
                THEN c.total_refund_amount - c.calculated_fdpl_created_credit
            ELSE NULL
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
                - s.achk_net_review_amount
                - s.achk_date_review_amount
                - s.crvc_transact_amount,
            0
        ), 2) AS standard_student_delivery_amount,
        (CASE WHEN s.achk_transact_eligible_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_clearing_wait_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_net_review_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_date_review_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.crvc_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN COALESCE(s.proposed_student_refund_amount, 0)
                    - s.achk_transact_eligible_amount
                    - s.achk_clearing_wait_amount
                    - s.achk_net_review_amount
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
             AND s.achk_clearing_wait_amount > 0 THEN 'ACHK Clearing Wait'
            WHEN s.student_delivery_component_count = 1
             AND s.achk_net_review_amount > 0 THEN 'ACHK Return/Net Review'
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
                    'ACHK Clearing Wait ',
                    TO_CHAR(s.achk_clearing_wait_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.achk_net_review_amount > 0 THEN CONCAT(
                    'ACHK Return/Net Review ',
                    TO_CHAR(s.achk_net_review_amount, 'FM999999990.00')
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
             AND s.plus_to_student_status = 'N' THEN 'RFDP'
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
            CASE WHEN d.missing_transaction_balance_count > 0
                THEN 'MISSING_TRANSACTION_BALANCE' END,
            CASE WHEN d.unexpected_balance_sign_count > 0
                THEN 'UNEXPECTED_TRANSACTION_BALANCE_SIGN' END,
            CASE WHEN d.unpaid_charge_amount > 0
                THEN 'UNPAID_CHARGES_IN_STORED_BALANCES' END,
            CASE WHEN d.balance_source_credit_total <> d.total_refund_amount
                THEN 'TARGET_TERM_STORED_BALANCES_DIFFER_FROM_FULL_ACCOUNT_REFUND' END,
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
            CASE WHEN d.fdpl_row_count > 1
                THEN CONCAT('MULTIPLE_TARGET_TERM_FDPL_ROWS_', d.fdpl_row_count) END,
            CASE WHEN d.fdpl_row_count = 1
                   AND COALESCE(d.fdpl_credit_amount, 0) <= 0
                THEN 'TARGET_TERM_FDPL_NOT_A_NEGATIVE_CREDIT' END,
            CASE WHEN d.fdpl_row_count = 1 AND d.fdpl_aidy_count <> 1
                THEN 'FDPL_AID_YEAR_MISSING_OR_CONFLICTING' END,
            CASE WHEN d.fdpl_row_count = 1 AND d.plus_to_student_status = 'MISSING'
                THEN 'PLUS_AUTH_RECORD_MISSING' END,
            CASE WHEN d.fdpl_row_count = 1 AND d.plus_to_student_status = 'CONFLICT'
                THEN 'PLUS_AUTH_VALUES_CONFLICT' END,
            CASE WHEN d.fdpl_row_count = 1 AND d.plus_auth_row_count > 1
                THEN CONCAT('MULTIPLE_PLUS_AUTH_ROWS_', d.plus_auth_row_count) END,
            CASE WHEN d.original_payment_row_count > 0
                THEN 'REVIEW_ACH_CC_IN_TRANSACT' END,
            CASE WHEN d.achk_clearing_wait_amount > 0
                THEN 'ACHK_CLEARING_PERIOD_NOT_MET' END,
            CASE WHEN d.achk_net_review_amount > 0
                THEN 'ACHK_ELIGIBLE_NET_LESS_THAN_REMAINING_BALANCE' END,
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
    'NOT_APPLICABLE_BALANCE_BASED_SOURCE' AS fdpl_priority_tie_rule,
    f.unused_fdpl_amount,
    f.unused_non_fdpl_amount,
    f.balance_source_credit_total AS total_unused_payment_amount,
    f.unpaid_charge_amount,
    f.allocation_review_required_ind,
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
        WHEN f.fdpl_row_count > 1 THEN 'MANUAL_REVIEW'
        WHEN f.fdpl_row_count = 1
         AND COALESCE(f.fdpl_credit_amount, 0) <= 0 THEN 'MANUAL_REVIEW'
        WHEN f.fdpl_row_count = 1
         AND f.fdpl_aidy_count <> 1 THEN 'MANUAL_REVIEW'
        WHEN f.fdpl_row_count = 1
         AND f.plus_to_student_status IN ('MISSING', 'CONFLICT')
            THEN 'MANUAL_REVIEW'
        WHEN f.fdpl_row_count = 1
         AND f.plus_auth_row_count > 1 THEN 'MANUAL_REVIEW'
        WHEN f.achk_net_review_amount > 0
          OR f.achk_date_review_amount > 0 THEN 'MANUAL_REVIEW'
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
WHERE p.last_name_filter IS NULL
   OR UPPER(f.last_name) LIKE UPPER(p.last_name_filter)
ORDER BY
    f.last_name,
    f.first_name,
    f.cwid;
