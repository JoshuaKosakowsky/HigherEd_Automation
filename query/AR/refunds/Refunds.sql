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

BALANCE-SOURCE EXPLANATION
  BALANCE_SOURCES is a review aid. Starting with the highest transaction number,
  it accumulates payment-type credits until they meet or exceed the full-account
  credit balance, then lists the selected detail codes and descriptions.
  This explains which newest credits cover the balance; it does not independently
  determine legal ownership of the refund.

PARENT PLUS REFUND SPLIT
  For exactly one target-term FDPL transaction when PLUS-to-student is not Y:
    Later student credits = negative payment transactions with a transaction
      number greater than the FDPL transaction number, across the full account.
    Parent amount = least of:
      (a) full refund amount,
      (b) FDPL amount, and
      (c) full refund amount less later student credits.
    Proposed student amount = full refund amount less parent amount.

FIRST-RUN VALIDATION
  1. Confirm FULL_ACCOUNT_BALANCE equals the TSAAREV full Query Balance.
  2. Confirm every active TBRACCD detail code has a C or P type in TBBDETC;
     accounts containing an unclassified type cannot be signed reliably.
  3. Confirm the known example returns $6,583 total, $5,105 student,
     and $1,478 parent.
  4. Spot-check BALANCE_SOURCES against TSAAREV: the newest selected credits
     should reach or slightly exceed TOTAL_REFUND_AMOUNT.
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
            (CAST(NULL AS varchar(30))),
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

/* Limit detailed transaction work to accounts with a credit balance. */
candidate_transactions AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        t.tbraccd_term_code AS term_code,
        t.tbraccd_aidy_code AS aidy_code,
        t.tbraccd_tran_number AS tran_number,
        t.tbraccd_detail_code AS detail_code,
        COALESCE(d.tbbdetc_desc, '[Description unavailable]') AS detail_desc,
        UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
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
),

/*
Allocate the full-account credit balance to the newest payment-type credits.
The transaction that crosses the refund amount is retained, which is why the
selected source credits can be greater than the exact balance.
*/
balance_source_ranked AS (
    SELECT
        x.pidm,
        x.term_code,
        x.tran_number,
        x.detail_code,
        x.detail_desc,
        x.activity_date,
        -x.amount AS source_credit_amount,
        -b.full_account_balance AS refund_amount,
        SUM(-x.amount) OVER (
            PARTITION BY x.pidm
            ORDER BY
                x.tran_number DESC,
                x.activity_date DESC,
                x.detail_code DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_source_credit_total,
        COALESCE(
            SUM(-x.amount) OVER (
                PARTITION BY x.pidm
                ORDER BY
                    x.tran_number DESC,
                    x.activity_date DESC,
                    x.detail_code DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ),
            0
        ) AS prior_source_credit_total
    FROM candidate_transactions x
    INNER JOIN account_balances b
        ON b.pidm = x.pidm
       AND b.full_account_balance < 0
    WHERE x.type_ind = 'P'
      AND x.amount < 0
),

selected_balance_sources AS (
    SELECT r.*
    FROM balance_source_ranked r
    WHERE r.prior_source_credit_total < r.refund_amount
),

balance_source_summary AS (
    SELECT
        r.pidm,
        COUNT(*) AS balance_source_transaction_count,
        ROUND(SUM(r.source_credit_amount), 2) AS balance_source_credit_total,
        STRING_AGG(
            DISTINCT CONCAT(
                UPPER(TRIM(r.detail_code)),
                ' (', TRIM(r.detail_desc), ')'
            ),
            ', ' ORDER BY CONCAT(
                UPPER(TRIM(r.detail_code)),
                ' (', TRIM(r.detail_desc), ')'
            )
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

/*
For the Parent PLUS allocation, student credits are payment-type
credits posted after the one target-term FDPL transaction. The later credits
are intentionally not restricted by term: the refund amount and TSAAREV Query
Balance cover the full account.
*/
later_payment_summary AS (
    SELECT
        x.pidm,
        COUNT(*) FILTER (
            WHERE x.amount < 0
              AND x.type_ind = 'P'
              AND UPPER(TRIM(x.detail_code)) <> 'FDPL'
        ) AS later_payment_count,
        ROUND(SUM(CASE
            WHEN x.amount < 0
             AND x.type_ind = 'P'
             AND UPPER(TRIM(x.detail_code)) <> 'FDPL'
                THEN -x.amount
            ELSE 0
        END), 2) AS later_non_fdpl_payment_total,
        STRING_AGG(
            CASE
                WHEN x.amount < 0
                 AND x.type_ind = 'P'
                 AND UPPER(TRIM(x.detail_code)) <> 'FDPL'
                THEN CONCAT(
                    COALESCE(x.term_code, '[no term]'),
                    ' / #', x.tran_number,
                    ' / ', x.detail_code,
                    ' / ', TO_CHAR(-x.amount, 'FM999999990.00')
                )
            END,
            ' | ' ORDER BY x.tran_number
        ) AS later_payment_detail
    FROM candidate_transactions x
    INNER JOIN fdpl_summary f
        ON f.pidm = x.pidm
       AND f.fdpl_row_count = 1
       AND x.tran_number > f.last_fdpl_tran_number
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
An ACH/card payment is relevant when it is one of the newest credits funding
the current full-account credit balance. Its term is intentionally unrestricted.
Presence cannot prove that Transact can return it to the original account, so
it creates a manual Transact review flag.
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
                ' / #', s.tran_number,
                ' / ', s.detail_code,
                ' / ', TO_CHAR(s.source_credit_amount, 'FM999999990.00')
            ),
            ' | ' ORDER BY s.tran_number
        ) AS original_payment_detail
    FROM selected_balance_sources s
    WHERE UPPER(TRIM(s.detail_code)) IN (
          'ACHK', 'CRDS', 'CRED', 'CRVC', 'CRAM', 'CRMC'
      )
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
        GREATEST(-b.full_account_balance, 0) AS total_refund_amount,
        bs.balance_sources,
        COALESCE(bs.balance_source_transaction_count, 0)
            AS balance_source_transaction_count,
        COALESCE(bs.balance_source_credit_total, 0) AS balance_source_credit_total,
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
        COALESCE(lp.later_payment_count, 0) AS later_payment_count,
        COALESCE(lp.later_non_fdpl_payment_total, 0) AS later_non_fdpl_payment_total,
        lp.later_payment_detail,
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
        COALESCE(op.original_payment_total, 0) AS original_payment_total,
        op.latest_original_payment_tran,
        op.latest_original_payment_activity_date,
        op.original_payment_detail
    FROM account_balances b
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
    LEFT JOIN later_payment_summary lp
        ON lp.pidm = b.pidm
    LEFT JOIN plus_authorization pa
        ON pa.pidm = b.pidm
    LEFT JOIN original_payment_summary op
        ON op.pidm = b.pidm
),

parent_plus_calculation AS (
    SELECT
        j.*,
        CASE
            WHEN j.fdpl_row_count = 0 THEN CAST(0 AS numeric)
            WHEN j.fdpl_row_count = 1 THEN ROUND(
                LEAST(
                    j.total_refund_amount,
                    COALESCE(j.fdpl_credit_amount, 0),
                    GREATEST(
                        j.total_refund_amount
                            - j.later_non_fdpl_payment_total,
                        0
                    )
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
            WHEN c.fdpl_row_count = 0 THEN CAST(0 AS numeric)
            WHEN c.fdpl_row_count = 1
             AND c.plus_to_student_status = 'Y' THEN CAST(0 AS numeric)
            WHEN c.fdpl_row_count = 1 THEN c.calculated_fdpl_created_credit
            ELSE NULL
        END AS proposed_parent_refund_amount,
        CASE
            WHEN c.fdpl_row_count = 0 THEN c.total_refund_amount
            WHEN c.fdpl_row_count = 1
             AND c.plus_to_student_status = 'Y' THEN c.total_refund_amount
            WHEN c.fdpl_row_count = 1
                THEN c.total_refund_amount - c.calculated_fdpl_created_credit
            ELSE NULL
        END AS proposed_student_refund_amount
    FROM parent_plus_calculation c
),

delivery AS (
    SELECT
        s.*,
        CASE
            WHEN COALESCE(s.proposed_student_refund_amount, 0) <= 0 THEN 'NONE'
            WHEN s.third_party_review_required_ind = 'Y'
                THEN 'THIRD_PARTY_REVIEW'
            WHEN s.active_ed_ind = 'Y'
             AND s.refund_account_selected_ind = 'Y'
                THEN 'CONFLICT_ED_AND_TSARFND'
            WHEN s.active_ed_ind = 'Y' THEN 'EREFUND'
            WHEN s.refund_account_selected_ind = 'Y' THEN 'TSARFND_CHECK'
            WHEN s.refund_account_selected_ind = 'UNKNOWN'
                THEN 'UNKNOWN_REFUND_IND_VALUE'
            ELSE 'DELIVERY_NOT_SELECTED'
        END AS proposed_student_delivery,
        CASE
            WHEN COALESCE(s.proposed_parent_refund_amount, 0) > 0
                THEN 'PARENT_CHECK_REVIEW'
            ELSE 'NONE'
        END AS proposed_parent_delivery
    FROM refund_split s
),

final_review AS (
    SELECT
        d.*,
        CONCAT_WS(
            '; ',
            CASE WHEN d.full_account_balance < 0
                   AND d.balance_source_credit_total < d.total_refund_amount
                THEN 'BALANCE_SOURCE_CREDITS_BELOW_REFUND' END,
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
            CASE WHEN d.proposed_student_delivery = 'CONFLICT_ED_AND_TSARFND'
                THEN 'ED_AND_REFUND_ACCOUNT_BOTH_SELECTED' END,
            CASE WHEN d.proposed_student_delivery = 'UNKNOWN_REFUND_IND_VALUE'
                THEN 'UNKNOWN_REFUND_ACCOUNT_VALUE' END,
            CASE WHEN d.proposed_student_delivery = 'DELIVERY_NOT_SELECTED'
                THEN 'STUDENT_DELIVERY_NOT_SELECTED' END
        ) AS review_reasons
    FROM delivery d
)

SELECT
    f.last_name,
    f.first_name,
    f.cwid,
    f.pidm AS banner_pidm,
    p.target_term AS parent_plus_target_term,
    f.third_party_review_required_ind,
    f.third_party_match_source,
    f.full_account_balance,
    f.total_refund_amount,
    f.balance_sources,
    f.refund_hold_ind,
    f.raw_delinquency_code,
    f.active_ed_ind,
    f.raw_refund_account_ind,
    f.refund_account_selected_ind,
    f.fdpl_row_count,
    f.last_fdpl_tran_number AS target_term_fdpl_tran_number,
    f.fdpl_credit_amount AS target_term_fdpl_amount,
    f.fdpl_aidy_code,
    f.plus_to_student_status,
    f.later_non_fdpl_payment_total AS credits_after_target_term_fdpl,
    f.later_payment_detail AS credits_after_target_term_fdpl_detail,
    f.calculated_fdpl_created_credit AS calculated_parent_plus_credit,
    f.proposed_student_refund_amount AS student_refund_amount,
    f.proposed_parent_refund_amount AS parent_refund_amount,
    f.original_payment_row_count,
    f.original_payment_total,
    f.original_payment_detail,
    f.proposed_student_delivery,
    f.proposed_parent_delivery,
    f.deceased_ind,
    f.deceased_date,
    f.confidential_ind,
    f.plus_auth_row_count,
    f.plus_auth_raw_values,
    f.later_payment_count,
    CASE
        WHEN f.full_account_balance < 0
         AND f.balance_source_credit_total < f.total_refund_amount
            THEN 'MANUAL_REVIEW'
        WHEN f.refund_hold_ind = 'Y' THEN 'HOLD'
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
        WHEN f.original_payment_row_count > 0 THEN 'TRANSACT_REVIEW'
        WHEN f.proposed_student_delivery IN (
            'CONFLICT_ED_AND_TSARFND',
            'UNKNOWN_REFUND_IND_VALUE'
        ) THEN 'MANUAL_REVIEW'
        WHEN f.proposed_student_delivery = 'DELIVERY_NOT_SELECTED'
            THEN 'ACTION_REQUIRED'
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
