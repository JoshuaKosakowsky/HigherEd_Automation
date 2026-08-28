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
  * Priority allocation uses ONLY params.target_term (the current term unless
    explicitly overridden). Other terms' charges, payments, and issued refunds
    are not reapplied. A mismatch with the full-account refund requires review.
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
  BALANCE_SOURCES lists target-term payment pools remaining after allocation.
  A pool contains payments with the same priority and FDPL/non-FDPL ownership.
  If a partially used pool has multiple sources, all possible sources are listed
  and the account requires manual review; no posting-order tie rule is invented.

PARENT PLUS REFUND SPLIT
  Read charge AND payment priorities from TBBDETC_PRIORITY for the target term.
  Process charges
  from highest priority to lowest. For each charge, apply eligible payment
  priorities from highest to lowest. Each zero in a payment priority is a
  wildcard for the corresponding charge-priority digit; 000 matches any charge.
  Track remaining amounts so a payment cannot be spent twice. Transaction
  numbers and disbursement dates do not determine application or refund ownership.

  TEMPORARY BUSINESS ASSUMPTION -- CONFIRM WITH BANNER OPERATIONS:
    FDPL applies LAST among payments with the SAME priority (currently 800).
    This is not a confirmed Banner rule. The single setting
    params.fdpl_last_at_same_priority controls this assumption; TRUE = last,
    FALSE = first. No priority value is hard-coded. The active assumption is
    also returned in FDPL_PRIORITY_TIE_RULE. Change the setting and rerun the
    allocation tests if operations confirms the opposite rule.

  Reversals are netted only within the same detail code, term, and aid year.
  A negative net source, missing/invalid priority, unpaid charge, or unreconciled
  allocation requires manual review and suppresses the proposed split.
  Ambiguity among non-FDPL payment sources still requires source/delivery review,
  but does NOT suppress a calculable FDPL/non-FDPL refund split. Target-term
  unused payments must equal the full-account refund; otherwise leave the split
  unresolved rather than assigning other terms' credits or charges to a recipient.
  For exactly one target-term FDPL row with a resolved allocation, the parent
  portion is its unused amount, capped at the full-account refund. Existing
  PLUS-to-student authorization still controls the recipient.

FIRST-RUN VALIDATION
  1. Confirm FULL_ACCOUNT_BALANCE equals the TSAAREV full Query Balance.
  2. Confirm every active TBRACCD detail code has a C or P type in TBBDETC;
     accounts containing an unclassified type cannot be signed reliably.
  3. Validate TBBDETC_PRIORITY on both sides and confirm the temporary FDPL tie
     assumption above. Do not use the former posting-order example as proof.
  4. Reconcile the applied and remaining amounts against actual Banner payment
     application for the target term. Its unused payments must equal the full-
     account TOTAL_REFUND_AMOUNT with no unpaid target-term charges before the
     proposed split is considered resolved. Settled prior terms must not alter it.
  5. Rerun immediately before any Transact/TSARFND action and remove accounts
     whose balance or controls changed.
*/

WITH RECURSIVE
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
        CAST(NULL AS varchar(60)) AS last_name_filter,
        /* TEMPORARY ASSUMPTION: FDPL is LAST within its actual payment priority. */
        TRUE AS fdpl_last_at_same_priority
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

/* Net reversals within a source, without treating charge reductions as payments. */
allocation_sources AS (
    SELECT
        x.pidm,
        x.term_code,
        x.aidy_code,
        x.detail_code,
        x.detail_desc,
        x.type_ind,
        x.priority_code,
        CASE WHEN UPPER(TRIM(x.detail_code)) = 'FDPL' THEN 1 ELSE 0 END
            AS is_fdpl,
        SUM(x.raw_amount) AS source_amount,
        MAX(x.tran_number) AS latest_tran_number,
        MAX(x.activity_date) AS latest_activity_date
    FROM candidate_transactions x
    GROUP BY x.pidm, x.term_code, x.aidy_code, x.detail_code, x.detail_desc,
             x.type_ind, x.priority_code
    HAVING SUM(x.raw_amount) <> 0
),

allocation_input_checks AS (
    SELECT
        b.pidm,
        COUNT(*) FILTER (
            WHERE s.source_amount <> 0 AND s.priority_code IS NULL
        ) AS invalid_priority_count,
        COUNT(*) FILTER (WHERE s.source_amount < 0) AS negative_source_count
    FROM account_balances b
    LEFT JOIN allocation_sources s ON s.pidm = b.pidm
    GROUP BY b.pidm
),

charge_priorities AS (
    SELECT s.pidm, s.priority_code, SUM(s.source_amount) AS charge_amount
    FROM allocation_sources s
    INNER JOIN allocation_input_checks v ON v.pidm = s.pidm
    WHERE s.type_ind = 'C'
      AND v.invalid_priority_count = 0 AND v.negative_source_count = 0
    GROUP BY s.pidm, s.priority_code
),

/*
Only FDPL versus non-FDPL has a specified same-priority ordering. Pool other
ties instead of inventing a transaction/date/detail-code application rule.
*/
payment_pools AS (
    SELECT
        s.pidm,
        s.priority_code,
        s.is_fdpl,
        CONCAT(s.priority_code, '/', s.is_fdpl) AS payment_key,
        SUM(s.source_amount) AS payment_amount,
        COUNT(*) AS source_count,
        STRING_AGG(
            DISTINCT CONCAT(s.detail_code, ' (', TRIM(s.detail_desc), ')'),
            ', ' ORDER BY CONCAT(s.detail_code, ' (', TRIM(s.detail_desc), ')')
        ) AS source_details
    FROM allocation_sources s
    INNER JOIN allocation_input_checks v ON v.pidm = s.pidm
    WHERE s.type_ind = 'P'
      AND v.invalid_priority_count = 0 AND v.negative_source_count = 0
    GROUP BY s.pidm, s.priority_code, s.is_fdpl
),

/* Every eligible pair is visited once: charge priority first, then payment. */
allocation_pairs AS (
    SELECT
        c.pidm,
        c.priority_code AS charge_priority,
        c.charge_amount,
        pay.payment_key,
        pay.payment_amount,
        ROW_NUMBER() OVER (
            PARTITION BY c.pidm
            ORDER BY c.priority_code DESC, pay.priority_code DESC,
                /* TEMPORARY FDPL TIE ASSUMPTION; controlled only in params. */
                CASE WHEN p.fdpl_last_at_same_priority
                    THEN pay.is_fdpl ELSE -pay.is_fdpl END
        ) AS allocation_step
    FROM charge_priorities c
    INNER JOIN payment_pools pay
        ON pay.pidm = c.pidm
       AND c.priority_code LIKE REPLACE(pay.priority_code, '0', '_')
    CROSS JOIN params p
),

allocation_pair_counts AS (
    SELECT pidm, COUNT(*) AS pair_count
    FROM allocation_pairs
    GROUP BY pidm
),

/*
Each recursive step spends MIN(charge remaining, payment remaining). JSONB maps
carry only the updated balances, keyed by charge priority and payment pool.
Amounts stay NUMERIC; neither map nor step ordering uses transaction chronology.
The recursion is bounded by the number of eligible priority/pool pairs.
*/
priority_allocation AS (
    SELECT
        b.pidm,
        CAST(0 AS bigint) AS allocation_step,
        CAST('{}' AS jsonb) AS charge_remaining,
        CAST('{}' AS jsonb) AS payment_remaining
    FROM account_balances b

    UNION ALL

    SELECT
        a.pidm,
        e.allocation_step,
        JSONB_SET(a.charge_remaining, ARRAY[e.charge_priority],
            TO_JSONB(r.charge_available - applied.amount)),
        JSONB_SET(a.payment_remaining, ARRAY[e.payment_key],
            TO_JSONB(r.payment_available - applied.amount))
    FROM priority_allocation a
    INNER JOIN allocation_pairs e
        ON e.pidm = a.pidm AND e.allocation_step = a.allocation_step + 1
    CROSS JOIN LATERAL (
        SELECT
            COALESCE(CAST(a.charge_remaining ->> e.charge_priority AS numeric),
                e.charge_amount) AS charge_available,
            COALESCE(CAST(a.payment_remaining ->> e.payment_key AS numeric),
                e.payment_amount) AS payment_available
    ) r
    CROSS JOIN LATERAL (
        SELECT LEAST(r.charge_available, r.payment_available) AS amount
    ) applied
),

allocation_final AS (
    SELECT a.*
    FROM priority_allocation a
    LEFT JOIN allocation_pair_counts n ON n.pidm = a.pidm
    WHERE a.allocation_step = COALESCE(n.pair_count, 0)
),

payment_remaining AS (
    SELECT
        pay.*,
        COALESCE(CAST(a.payment_remaining ->> pay.payment_key AS numeric),
            pay.payment_amount) AS source_credit_amount
    FROM payment_pools pay
    INNER JOIN allocation_final a ON a.pidm = pay.pidm
),

unpaid_charge_summary AS (
    SELECT
        c.pidm,
        SUM(COALESCE(CAST(a.charge_remaining ->> c.priority_code AS numeric),
            c.charge_amount)) AS unpaid_charge_amount
    FROM charge_priorities c
    INNER JOIN allocation_final a ON a.pidm = c.pidm
    GROUP BY c.pidm
),

selected_balance_sources AS (
    SELECT r.*
    FROM payment_remaining r
    WHERE r.source_credit_amount > 0
),

balance_source_summary AS (
    SELECT
        r.pidm,
        SUM(r.source_count) AS balance_source_group_count,
        ROUND(SUM(r.source_credit_amount), 2) AS balance_source_credit_total,
        ROUND(SUM(CASE WHEN r.is_fdpl = 1
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_fdpl_amount,
        ROUND(SUM(CASE WHEN r.is_fdpl = 0
            THEN r.source_credit_amount ELSE 0 END), 2) AS unused_non_fdpl_amount,
        COUNT(*) FILTER (
            WHERE r.source_count > 1 AND r.source_credit_amount < r.payment_amount
        ) AS ambiguous_source_pool_count,
        STRING_AGG(
            CONCAT(
                r.priority_code, ' / ', r.source_details, ' / remaining ',
                TO_CHAR(r.source_credit_amount, 'FM999999990.00'),
                CASE WHEN r.source_count > 1
                      AND r.source_credit_amount < r.payment_amount
                    THEN ' [SOURCE SPLIT UNRESOLVED]' ELSE '' END
            ),
            ' | ' ORDER BY r.priority_code DESC, r.is_fdpl
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
An ACH/card source is relevant when its target-term priority pool has unused
funds. Partially used pools with multiple sources do
not establish individual amounts: list possible ACH/card sources, leave their
total NULL, and require manual review. Presence alone cannot prove that Transact
can return funds to the original account.
*/
original_payment_summary AS (
    SELECT
        s.pidm,
        COUNT(*) AS original_payment_row_count,
        CASE WHEN MAX(CASE WHEN s.source_count > 1
                               AND s.source_credit_amount < s.payment_amount
                          THEN 1 ELSE 0 END) = 1 THEN NULL
            ELSE ROUND(SUM(CASE WHEN s.source_count = 1
                THEN s.source_credit_amount ELSE x.source_amount END), 2)
        END AS original_payment_total,
        MAX(x.latest_tran_number) AS latest_original_payment_tran,
        MAX(x.latest_activity_date) AS latest_original_payment_activity_date,
        STRING_AGG(
            CONCAT(
                COALESCE(x.term_code, '[no term]'),
                ' / ', x.detail_code,
                ' / priority ', s.priority_code,
                ' / ', CASE WHEN s.source_count > 1
                             AND s.source_credit_amount < s.payment_amount
                    THEN 'AMOUNT UNRESOLVED'
                    ELSE TO_CHAR(CASE WHEN s.source_count = 1
                        THEN s.source_credit_amount ELSE x.source_amount END,
                        'FM999999990.00') END
            ),
            ' | ' ORDER BY x.term_code, x.detail_code, x.aidy_code
        ) AS original_payment_detail
    FROM selected_balance_sources s
    INNER JOIN allocation_sources x
        ON x.pidm = s.pidm AND x.priority_code = s.priority_code
       AND x.is_fdpl = s.is_fdpl AND x.type_ind = 'P'
    WHERE UPPER(TRIM(x.detail_code)) IN (
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
        COALESCE(bs.balance_source_group_count, 0) AS balance_source_group_count,
        COALESCE(bs.balance_source_credit_total, 0) AS balance_source_credit_total,
        COALESCE(bs.unused_fdpl_amount, 0) AS unused_fdpl_amount,
        COALESCE(bs.unused_non_fdpl_amount, 0) AS unused_non_fdpl_amount,
        v.invalid_priority_count,
        v.negative_source_count,
        COALESCE(uc.unpaid_charge_amount, 0) AS unpaid_charge_amount,
        COALESCE(bs.ambiguous_source_pool_count, 0) AS ambiguous_source_pool_count,
        CASE WHEN v.invalid_priority_count > 0
               OR v.negative_source_count > 0
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
        op.original_payment_detail
    FROM account_balances b
    INNER JOIN allocation_input_checks v ON v.pidm = b.pidm
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
),

parent_plus_calculation AS (
    SELECT
        j.*,
        /* Source review is separate from whether the recipient totals are calculable. */
        CASE WHEN j.refund_split_blocked_ind = 'Y'
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
            CASE WHEN d.invalid_priority_count > 0
                THEN 'MISSING_OR_INVALID_DETAIL_PRIORITY' END,
            CASE WHEN d.negative_source_count > 0
                THEN 'NEGATIVE_NET_SOURCE_REQUIRES_REVIEW' END,
            CASE WHEN d.unpaid_charge_amount > 0
                THEN 'UNPAID_CHARGES_AFTER_PRIORITY_ALLOCATION' END,
            CASE WHEN d.balance_source_credit_total <> d.total_refund_amount
                THEN 'TARGET_TERM_ALLOCATION_DIFFERS_FROM_FULL_ACCOUNT_REFUND' END,
            CASE WHEN d.ambiguous_source_pool_count > 0
                THEN 'SAME_PRIORITY_SOURCE_SPLIT_UNRESOLVED' END,
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
    f.cwid,
    f.last_name,
    f.first_name,
    f.full_account_balance,
    f.total_refund_amount,
    f.proposed_student_refund_amount AS student_refund_amount,
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
    CASE WHEN p.fdpl_last_at_same_priority
        THEN 'ASSUMPTION_FDPL_LAST_WITHIN_SAME_PRIORITY'
        ELSE 'ASSUMPTION_FDPL_FIRST_WITHIN_SAME_PRIORITY'
    END AS fdpl_priority_tie_rule,
    f.unused_fdpl_amount,
    f.unused_non_fdpl_amount,
    f.balance_source_credit_total AS total_unused_payment_amount,
    f.unpaid_charge_amount,
    f.allocation_review_required_ind,
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
