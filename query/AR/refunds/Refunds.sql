/*
Student Refund Review | Colorado School of Mines | Banner Insights / PostgreSQL

One read-only statement: daily candidate selection, complete-history allocation,
Parent PLUS ownership by aid year, and source-specific delivery. No database
functions, temp tables, schema changes, or Python execution are required.

CURRENT POLICY
- Candidates: target-term activity OR HOMP effective in the past 32 days OR a
  stored payment credit from the whole term containing run_date minus two years
  through the target term. Validation CWID/name filters bypass activity criteria.
- Full-account positive balances are excluded. Zero balances can have restricted
  refunds with equal unpaid charges. Final rows require unused payment principal.
- Keep every term and charge priority. Oldest charge terms apply first, then
  descending charge priority. Payment zero digits are positional wildcards;
  899/869 only pay their exact priorities in any term. Payments apply by descending
  priority, then earliest transaction number. TPDT/TPPY retain 800A; COFP retains
  000A. ACH/cards use their normal stored priority; there is no 000Z.
- A completed historical prefix is settled only when its cumulative raw total
  and every stored transaction balance are known zero. Other history is replayed.
- Reversals reduce newest positive payment rows within term/aid year/detail and
  charge rows within term/priority. Payments retain source ownership and dates.
- TBBDETC_TIV_IND=Y overrides category. FA% without Y, CSH, and other non-Title-IV
  funds are unrestricted. Within one FY Title IV has no cap. Between different
  FYs, each source FY gives at most 200 and each destination FY receives at most
  200, using independent ledgers, including older funds paying newer charges.
  Fiscal years run Fall 80 through Summer 55 (historical 50/60 supported).
- Each unused FDPL aid year uses its own PLUS authorization: N parent/RFDP,
  Y student. Missing/conflicting authorization blocks a reliable recipient split.
- Only unused ACH/card principal goes to Transact; ordinary student funds use
  ARFD (System) with ED, otherwise RFND (CHECK). RH holds override student delivery.
  ACHK clears on effective date +16 days; after 180 days it carries an age warning.
  CRAM, CRDS, CRMC, CRVC are immediately available via their respective codes.
- Unused target-term C529/Z0LE/TPPY sources flag Possible Third Party refund,
  along with existing TPS/legacy account controls. Third-party delivery is blocked.
- Surviving HOMP charges in the target term OR effective 0..32 days ago trigger
  Mines Park Charge - Review, including paid charges in settled history.

PERFORMANCE
Normalize selected account history once. Net reversals and pool charges before
building one matching-payment list per charge priority. Each account walks its
charges independently and selects the earliest still-eligible source. Recursion
emits only actual transfers or completed charges, never empty source-pair steps.
All money uses exact numeric cents.
Runtime still depends on Insights hardware, indexes, and candidate/history volume;
validate a representative population against the ten-minute server limit.

OUTPUT
One row per account, same calculation columns as the Python allocator. SQL returns
a single result set; separate Excel tabs remain a workbook-export feature.
This report proposes amounts/routes for staff review and does not issue refunds.
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
Select the daily population before loading history: target-term activity, recent
HOMP activity, or a stored payment credit in the last two years of whole terms.
The lookback selects accounts, never cuts their history. Validation filters
override activity requirements, but known positive account balances stay out.
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
scope_dates AS (
    SELECT p.*, CAST(p.run_date - INTERVAL '2 years' AS date) AS lookback_date
    FROM params p
),
scope_terms AS (
    SELECT d.*, CONCAT(EXTRACT(YEAR FROM lookback_date)::integer,
        CASE
            WHEN lookback_date <= MAKE_DATE(EXTRACT(YEAR FROM lookback_date)::integer, 5, 15) THEN '10'
            WHEN lookback_date <= MAKE_DATE(EXTRACT(YEAR FROM lookback_date)::integer, 7, 15) THEN '55'
            ELSE '80'
        END) AS lookback_term
    FROM scope_dates d
),
report_scope_pidms AS MATERIALIZED (
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL AND p.last_name_filter IS NULL
      AND t.tbraccd_term_code = p.target_term

    UNION

    SELECT t.tbraccd_pidm
    FROM taismgr.tbraccd t
    JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL AND p.last_name_filter IS NULL
      AND t.tbraccd_detail_code = 'HOMP'
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
      AND t.tbraccd_amount > 0
      AND t.tbraccd_effective_date >= p.run_date - INTERVAL '32 days'
      AND t.tbraccd_effective_date < p.run_date + INTERVAL '1 day'

    UNION

    SELECT t.tbraccd_pidm
    FROM taismgr.tbraccd t
    JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN scope_terms p
    WHERE p.cwid_filter IS NULL AND p.last_name_filter IS NULL
      AND t.tbraccd_term_code >= p.lookback_term
      AND t.tbraccd_term_code <= p.target_term
      AND t.tbraccd_balance < 0
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'

    UNION

    SELECT pidm FROM validation_scope_pidms
),

/*
Load and normalize each selected account's history once for all consumers.
Carry boolean classifications through materialized CTEs: on PostgreSQL 16,
string-equality predicates on those outputs can severely underestimate rows
and cause repeated nested-loop scans instead of population-scale hash joins.
*/
screening_transactions AS MATERIALIZED (
    SELECT
        t.tbraccd_pidm AS pidm,
        TRIM(t.tbraccd_term_code) AS term_code,
        NULLIF(TRIM(t.tbraccd_aidy_code), '') AS aidy_code,
        t.tbraccd_tran_number AS tran_number,
        UPPER(TRIM(t.tbraccd_detail_code)) AS detail_code,
        COALESCE(NULLIF(TRIM(d.tbbdetc_desc), ''), '[Description unavailable]') AS detail_desc,
        UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
        UPPER(TRIM(d.tbbdetc_type_ind)) = 'P' AS is_payment,
        UPPER(TRIM(d.tbbdetc_type_ind)) = 'C' AS is_charge,
        UPPER(TRIM(COALESCE(d.tbbdetc_dcat_code, ''))) AS category_code,
        CASE WHEN UPPER(TRIM(COALESCE(d.tbbdetc_tiv_ind, ''))) = 'Y'
            THEN 1 ELSE 0 END AS is_title_iv,
        CASE WHEN TRIM(CAST(d.tbbdetc_priority AS text)) ~ '^[0-9]{1,3}$'
            THEN LPAD(TRIM(CAST(d.tbbdetc_priority AS text)), 3, '0') END AS priority_code,
        CASE WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60|80)$'
            THEN CAST(TRIM(t.tbraccd_term_code) AS integer) END AS term_sort,
        CASE
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}80$'
                THEN SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4)::integer
            WHEN TRIM(t.tbraccd_term_code) ~ '^[0-9]{4}(10|50|55|60)$'
                THEN SUBSTRING(TRIM(t.tbraccd_term_code) FROM 1 FOR 4)::integer - 1
        END AS fiscal_year_start,
        CASE WHEN t.tbraccd_amount IS NULL THEN 1 ELSE 0 END AS amount_missing_ind,
        COALESCE(t.tbraccd_amount, 0) AS raw_amount,
        CASE UPPER(TRIM(d.tbbdetc_type_ind))
            WHEN 'P' THEN -COALESCE(t.tbraccd_amount, 0)
            WHEN 'C' THEN COALESCE(t.tbraccd_amount, 0)
        END AS accounting_amount,
        t.tbraccd_balance AS raw_transaction_balance,
        CAST(t.tbraccd_effective_date AS date) AS effective_date,
        t.tbraccd_activity_date AS activity_date
    FROM report_scope_pidms v
    JOIN taismgr.tbraccd t ON t.tbraccd_pidm = v.pidm
    LEFT JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
),
account_balance_rollup AS (
    SELECT pidm, ROUND(SUM(accounting_amount), 2) AS full_account_balance,
        BOOL_OR(type_ind IS NULL OR type_ind NOT IN ('C', 'P')) AS has_unclassified_detail_type,
        MAX(activity_date) AS last_ar_activity_date
    FROM screening_transactions
    GROUP BY pidm
),
account_balances AS MATERIALIZED (
    SELECT pidm, full_account_balance, last_ar_activity_date
    FROM account_balance_rollup
    WHERE NOT has_unclassified_detail_type AND full_account_balance <= 0
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
candidate_transactions AS MATERIALIZED (
    SELECT x.*
    FROM screening_transactions x
    JOIN account_balances b ON b.pidm = x.pidm
),

/*
A zero account total alone is not settlement. Cut only the latest completed
prefix whose raw cumulative total is zero AND every stored row balance is
known zero. Preserve unresolved strict-priority offsets even in old terms.
*/
open_term_balances AS (
    SELECT x.pidm, x.term_sort, SUM(x.accounting_amount) AS term_balance,
        COUNT(*) FILTER (WHERE x.raw_transaction_balance IS DISTINCT FROM 0
                            OR x.amount_missing_ind = 1) AS unresolved_rows
    FROM candidate_transactions x
    CROSS JOIN params p
    WHERE x.term_sort <= p.target_term::integer
    GROUP BY x.pidm, x.term_sort
),
running_term_balances AS (
    SELECT t.*,
        ROUND(SUM(term_balance) OVER (PARTITION BY pidm ORDER BY term_sort), 2) AS cumulative_balance,
        SUM(unresolved_rows) OVER (PARTITION BY pidm ORDER BY term_sort) AS unresolved_prefix
    FROM open_term_balances t
),
settled_history AS (
    SELECT pidm, MAX(term_sort) AS settled_through
    FROM running_term_balances
    CROSS JOIN params p
    WHERE term_sort < p.target_term::integer
      AND cumulative_balance = 0 AND unresolved_prefix = 0
    GROUP BY pidm
),
allocation_transactions AS MATERIALIZED (
    SELECT x.*
    FROM candidate_transactions x
    LEFT JOIN settled_history h ON h.pidm = x.pidm
    CROSS JOIN params p
    WHERE x.term_sort <= p.target_term::integer
      AND (h.settled_through IS NULL OR x.term_sort > h.settled_through)
),
allocation_ledger AS (
    SELECT pidm, ROUND(SUM(accounting_amount), 2) AS included_balance
    FROM allocation_transactions
    GROUP BY pidm
),

/* Housing review uses surviving charges, including paid/settled history. */
housing_rows AS (
    SELECT x.*,
        SUM(raw_amount) OVER (PARTITION BY pidm, term_code) AS group_net,
        COALESCE(SUM(GREATEST(raw_amount, 0)) OVER (
            PARTITION BY pidm, term_code ORDER BY tran_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ), 0) AS prior_positive
    FROM candidate_transactions x
    WHERE is_charge AND detail_code = 'HOMP'
),
housing_review AS MATERIALIZED (
    SELECT x.pidm
    FROM housing_rows x
    CROSS JOIN params p
    WHERE LEAST(x.raw_amount, GREATEST(x.group_net - x.prior_positive, 0)) > 0
      AND (x.term_code = p.target_term OR p.run_date - x.effective_date BETWEEN 0 AND 32)
    GROUP BY x.pidm
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
                (x.detail_code IN ('TPDT', 'TPPY') AND x.priority_code IS DISTINCT FROM '800')
                OR (x.detail_code = 'COFP' AND x.priority_code IS DISTINCT FROM '000')
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
    FROM allocation_transactions x
    CROSS JOIN params p
    WHERE x.is_payment
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
        r.detail_code = 'FDPL' AS is_fdpl,
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
            ELSE r.priority_code
        END AS effective_priority_code,
        CASE
            WHEN r.detail_code IN ('TPDT', 'TPPY') AND r.priority_code = '800'
                THEN 8002
            WHEN r.priority_code = '800' THEN 8001
            WHEN r.detail_code = 'COFP' AND r.priority_code = '000' THEN 2
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
    FROM allocation_transactions x
    CROSS JOIN params p
    WHERE x.is_charge
      AND x.term_sort IS NOT NULL
      AND x.term_sort <= CAST(p.target_term AS integer)
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
Number actual sources and term/priority charge pools once. Historical charges
retain their eligibility; no synthetic unrestricted fiscal-year deficit exists.
*/
numbered_payment_sources AS MATERIALIZED (
    SELECT s.*, s.source_amount AS stage_source_amount,
        CAST(ROW_NUMBER() OVER (
            PARTITION BY s.pidm ORDER BY s.payment_priority_sort DESC NULLS LAST,
                s.tran_number, s.term_sort, s.detail_code
        ) AS integer) AS payment_sequence,
        CONCAT('P', ROW_NUMBER() OVER (
            PARTITION BY s.pidm ORDER BY s.payment_priority_sort DESC NULLS LAST,
                s.tran_number, s.term_sort, s.detail_code
        )) AS payment_key
    FROM payment_sources s
),
numbered_charges AS MATERIALIZED (
    SELECT c.*,
        CAST(ROW_NUMBER() OVER (
            PARTITION BY c.pidm ORDER BY c.term_sort, c.priority_code DESC NULLS LAST,
                c.tran_number, c.detail_code
        ) AS integer) AS charge_sequence
    FROM charge_sources c
),
/*
Matching depends on priority digits, not term. Compute each priority's ordered
payment indexes once per account; repeating this list for every charge term
would multiply the intermediate rows on long histories.
*/
charge_priority_types AS (
    SELECT DISTINCT pidm, priority_code
    FROM numbered_charges
    WHERE priority_code IS NOT NULL
),
priority_matches AS (
    SELECT c.pidm, c.priority_code,
        ARRAY_AGG(s.payment_sequence ORDER BY s.payment_sequence) AS payment_indexes
    FROM charge_priority_types c
    JOIN numbered_payment_sources s ON s.pidm = c.pidm
    WHERE c.priority_code LIKE REPLACE(s.priority_code, '0', '_')
    GROUP BY c.pidm, c.priority_code
),
priority_vectors AS MATERIALIZED (
    SELECT pidm, JSONB_OBJECT_AGG(priority_code, TO_JSONB(payment_indexes)) AS matches
    FROM priority_matches
    GROUP BY pidm
),
payment_vectors AS MATERIALIZED (
    SELECT pidm,
        ARRAY_AGG(source_amount ORDER BY payment_sequence) AS amounts,
        ARRAY_AGG(fiscal_year_start ORDER BY payment_sequence) AS fiscal_years,
        ARRAY_AGG(term_sort ORDER BY payment_sequence) AS terms,
        ARRAY_AGG(is_title_iv = 1 ORDER BY payment_sequence) AS title_iv_flags
    FROM numbered_payment_sources
    GROUP BY pidm
),
charge_vectors AS MATERIALIZED (
    SELECT pidm,
        ARRAY_AGG(charge_amount ORDER BY charge_sequence) AS amounts,
        ARRAY_AGG(priority_code ORDER BY charge_sequence) AS priorities,
        ARRAY_AGG(fiscal_year_start ORDER BY charge_sequence) AS fiscal_years,
        ARRAY_AGG(term_sort ORDER BY charge_sequence) AS terms
    FROM numbered_charges
    GROUP BY pidm
),
allocation_inputs AS MATERIALIZED (
    SELECT b.pidm,
        COALESCE(v.matches, '{}'::jsonb) AS priority_matches,
        COALESCE(p.amounts, ARRAY[]::numeric[]) AS initial_payments,
        p.fiscal_years AS payment_years, p.terms AS payment_terms,
        p.title_iv_flags AS payment_title_iv,
        COALESCE(c.amounts, ARRAY[]::numeric[]) AS initial_charges,
        c.priorities AS charge_priorities, c.fiscal_years AS charge_years,
        c.terms AS charge_terms
    FROM account_balances b
    LEFT JOIN priority_vectors v USING (pidm)
    LEFT JOIN payment_vectors p USING (pidm)
    LEFT JOIN charge_vectors c USING (pidm)
),

/*
Run one independent greedy allocation per account. For the current charge,
MIN(payment index) selects the first still-eligible source in the exact Python
order. Exhausted principal or FY caps are skipped without emitting recursion
rows. Each iteration either transfers money or finishes an unpayable charge.
No population relation is joined inside recursion, and completed charge
balances need not be copied into every recursive state.
*/
allocation_final AS MATERIALIZED (
    SELECT i.pidm, a.*
    FROM allocation_inputs i
    CROSS JOIN params p
    CROSS JOIN LATERAL (
        WITH RECURSIVE priority_allocation AS (
            SELECT 0 AS allocation_step,
                1 AS charge_index,
                COALESCE(i.initial_charges[1], 0) AS current_charge_remaining,
                0::numeric AS unpaid_charge_amount,
                i.initial_payments AS payment_remaining,
                '{}'::jsonb AS title_iv_given_by_fy,
                '{}'::jsonb AS title_iv_received_by_fy,
                0::numeric AS title_iv_to_older_fy,
                0::numeric AS unrestricted_to_older_terms

            UNION ALL

            SELECT
                a.allocation_step + 1,
                CASE WHEN e.s IS NULL OR a.current_charge_remaining = applied.amount
                    THEN a.charge_index + 1 ELSE a.charge_index END,
                CASE WHEN e.s IS NULL OR a.current_charge_remaining = applied.amount
                    THEN COALESCE(i.initial_charges[a.charge_index + 1], 0)
                    ELSE a.current_charge_remaining - applied.amount END,
                a.unpaid_charge_amount + CASE WHEN e.s IS NULL
                    THEN a.current_charge_remaining ELSE 0 END,
                CASE WHEN applied.amount > 0 THEN
                    a.payment_remaining[:e.s - 1]
                    || ARRAY[a.payment_remaining[e.s] - applied.amount]
                    || a.payment_remaining[e.s + 1:]
                    ELSE a.payment_remaining END,
                CASE WHEN applied.amount > 0 AND limits.cross_fy_title_iv THEN
                    JSONB_SET(a.title_iv_given_by_fy, ARRAY[i.payment_years[e.s]::text],
                        TO_JSONB(limits.given_so_far + applied.amount), TRUE)
                    ELSE a.title_iv_given_by_fy END,
                CASE WHEN applied.amount > 0 AND limits.cross_fy_title_iv THEN
                    JSONB_SET(a.title_iv_received_by_fy, ARRAY[i.charge_years[a.charge_index]::text],
                        TO_JSONB(limits.received_so_far + applied.amount), TRUE)
                    ELSE a.title_iv_received_by_fy END,
                a.title_iv_to_older_fy + CASE WHEN i.payment_title_iv[e.s]
                    AND i.payment_years[e.s] > i.charge_years[a.charge_index]
                    THEN applied.amount ELSE 0 END,
                a.unrestricted_to_older_terms + CASE WHEN NOT i.payment_title_iv[e.s]
                    AND i.payment_terms[e.s] > i.charge_terms[a.charge_index]
                    THEN applied.amount ELSE 0 END
            FROM priority_allocation a
            CROSS JOIN LATERAL (
                SELECT MIN(k.value::integer) AS s
                FROM JSONB_ARRAY_ELEMENTS_TEXT(COALESCE(
                    i.priority_matches -> i.charge_priorities[a.charge_index], '[]'::jsonb
                )) k
                WHERE a.payment_remaining[k.value::integer] > 0
                  AND (
                    NOT i.payment_title_iv[k.value::integer]
                    OR i.payment_years[k.value::integer] = i.charge_years[a.charge_index]
                    OR (
                        COALESCE((a.title_iv_given_by_fy
                            ->> i.payment_years[k.value::integer]::text)::numeric, 0) < p.title_iv_cross_fy_cap
                        AND COALESCE((a.title_iv_received_by_fy
                            ->> i.charge_years[a.charge_index]::text)::numeric, 0) < p.title_iv_cross_fy_cap
                    )
                  )
            ) e
            CROSS JOIN LATERAL (
                SELECT i.payment_title_iv[e.s]
                    AND i.payment_years[e.s] <> i.charge_years[a.charge_index] AS cross_fy_title_iv,
                    COALESCE((a.title_iv_given_by_fy
                        ->> i.payment_years[e.s]::text)::numeric, 0) AS given_so_far,
                    COALESCE((a.title_iv_received_by_fy
                        ->> i.charge_years[a.charge_index]::text)::numeric, 0) AS received_so_far
            ) limits
            CROSS JOIN LATERAL (
                SELECT CASE WHEN e.s IS NULL THEN 0::numeric ELSE ROUND(LEAST(
                    a.current_charge_remaining, a.payment_remaining[e.s],
                    CASE WHEN limits.cross_fy_title_iv THEN GREATEST(LEAST(
                        p.title_iv_cross_fy_cap - limits.given_so_far,
                        p.title_iv_cross_fy_cap - limits.received_so_far
                    ), 0) ELSE a.payment_remaining[e.s] END
                ), 2) END AS amount
            ) applied
            WHERE a.charge_index <= CARDINALITY(i.initial_charges)
        )
        SELECT * FROM priority_allocation
        WHERE charge_index > CARDINALITY(i.initial_charges)
    ) a
),
allocation_transfer_summary AS MATERIALIZED (
    SELECT pidm, title_iv_to_older_fy, unrestricted_to_older_terms
    FROM allocation_final
),

selected_balance_sources AS (
    SELECT
        s.*,
        ROUND(COALESCE(
            a.payment_remaining[s.payment_sequence],
            s.stage_source_amount
        ), 2) AS source_credit_amount
    FROM numbered_payment_sources s
    INNER JOIN allocation_final a ON a.pidm = s.pidm
    WHERE COALESCE(
        a.payment_remaining[s.payment_sequence],
        s.stage_source_amount
    ) > 0
),

unpaid_charge_summary AS MATERIALIZED (
    SELECT pidm, unpaid_charge_amount
    FROM allocation_final
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
      AND s.is_fdpl
    GROUP BY s.pidm
),

unused_fdpl_aid_years AS (
    SELECT DISTINCT s.pidm, s.aidy_code
    FROM selected_balance_sources s
    WHERE s.is_fdpl
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
        CASE WHEN COUNT(r.rlrpapp_pidm) = 0 THEN NULL ELSE
            STRING_AGG(DISTINCT COALESCE(
                NULLIF(UPPER(TRIM(r.rlrpapp_plus_to_student)), ''), '[blank]'
            ), ', ' ORDER BY COALESCE(
                NULLIF(UPPER(TRIM(r.rlrpapp_plus_to_student)), ''), '[blank]'
            )) END AS plus_auth_raw_values,
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
    WHERE s.is_fdpl
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

third_party_sources AS MATERIALIZED (
    SELECT s.pidm, STRING_AGG(DISTINCT s.detail_code, ', ' ORDER BY s.detail_code) AS detail_codes
    FROM selected_balance_sources s
    CROSS JOIN params p
    WHERE s.term_code = p.target_term AND s.detail_code IN ('C529', 'Z0LE', 'TPPY')
    GROUP BY s.pidm
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
             AND s.effective_date <= p.run_date
             AND p.run_date < CAST(s.effective_date AS date) + 16
                THEN s.source_credit_amount ELSE 0
        END), 2) AS achk_clearing_wait_amount,
        MIN(CAST(s.effective_date AS date) + 16) FILTER (
            WHERE s.detail_code = 'ACHK'
              AND s.effective_date IS NOT NULL
              AND s.effective_date <= p.run_date
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
            THEN s.source_credit_amount ELSE 0 END), 2) AS crvc_transact_amount,
        ROUND(SUM(CASE WHEN s.detail_code = 'CRAM'
            THEN s.source_credit_amount ELSE 0 END), 2) AS cram_transact_amount,
        ROUND(SUM(CASE WHEN s.detail_code = 'CRDS'
            THEN s.source_credit_amount ELSE 0 END), 2) AS crds_transact_amount,
        ROUND(SUM(CASE WHEN s.detail_code = 'CRMC'
            THEN s.source_credit_amount ELSE 0 END), 2) AS crmc_transact_amount
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
              OR legacy_tps.cwid IS NOT NULL OR tp.pidm IS NOT NULL
                THEN 'Y'
            ELSE 'N'
        END AS third_party_review_required_ind,
        NULLIF(CONCAT_WS(', ',
            CASE WHEN UPPER(TRIM(COALESCE(i.cwid, ''))) LIKE 'TPS%' THEN 'TPS_CWID_PREFIX' END,
            CASE WHEN legacy_tps.cwid IS NOT NULL THEN 'LEGACY_CWID_LIST' END,
            tp.detail_codes
        ), '') AS third_party_match_source,
        tp.detail_codes AS third_party_detail_codes,
        hr.pidm IS NOT NULL AS mines_park_review,
        COALESCE(al.included_balance, 0)
            - (COALESCE(uc.unpaid_charge_amount, 0) - COALESCE(bs.balance_source_credit_total, 0))
            AS ledger_residual,
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
               OR COALESCE(al.included_balance, 0)
                    <> COALESCE(uc.unpaid_charge_amount, 0) - COALESCE(bs.balance_source_credit_total, 0)
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
        COALESCE(ds.crvc_transact_amount, 0) AS crvc_transact_amount,
        COALESCE(ds.cram_transact_amount, 0) AS cram_transact_amount,
        COALESCE(ds.crds_transact_amount, 0) AS crds_transact_amount,
        COALESCE(ds.crmc_transact_amount, 0) AS crmc_transact_amount
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
    LEFT JOIN allocation_ledger al ON al.pidm = b.pidm
    LEFT JOIN housing_review hr ON hr.pidm = b.pidm
    LEFT JOIN third_party_sources tp ON tp.pidm = b.pidm
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
                - s.crvc_transact_amount - s.cram_transact_amount - s.crds_transact_amount - s.crmc_transact_amount,
            0
        ), 2) AS standard_student_delivery_amount,
        (CASE WHEN s.achk_transact_eligible_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_clearing_wait_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_too_old_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.achk_date_review_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.crvc_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.cram_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.crds_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN s.crmc_transact_amount > 0 THEN 1 ELSE 0 END
         + CASE WHEN COALESCE(s.proposed_student_refund_amount, 0)
                    - s.achk_transact_eligible_amount
                    - s.achk_clearing_wait_amount
                    - s.achk_too_old_amount
                    - s.achk_date_review_amount
                    - s.crvc_transact_amount - s.cram_transact_amount - s.crds_transact_amount - s.crmc_transact_amount > 0
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
             AND s.cram_transact_amount > 0 THEN 'CRAM (Transact)'
            WHEN s.student_delivery_component_count = 1
             AND s.crds_transact_amount > 0 THEN 'CRDS (Transact)'
            WHEN s.student_delivery_component_count = 1
             AND s.crmc_transact_amount > 0 THEN 'CRMC (Transact)'
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
                CASE WHEN s.cram_transact_amount > 0 THEN CONCAT(
                    'CRAM (Transact) ', TO_CHAR(s.cram_transact_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.crds_transact_amount > 0 THEN CONCAT(
                    'CRDS (Transact) ', TO_CHAR(s.crds_transact_amount, 'FM999999990.00')
                ) END,
                CASE WHEN s.crmc_transact_amount > 0 THEN CONCAT(
                    'CRMC (Transact) ', TO_CHAR(s.crmc_transact_amount, 'FM999999990.00')
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
             AND s.third_party_review_required_ind = 'Y' THEN 'THIRD_PARTY_REVIEW'
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
        NULLIF(CONCAT_WS(
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
            CASE WHEN d.unpaid_charge_amount > 0 AND d.refund_split_blocked_ind = 'N'
                THEN 'RESTRICTED_PAYMENT_REFUND_WITH_UNPAID_CHARGE' END,
            CASE WHEN d.ledger_residual <> 0
                THEN 'ALLOCATION_LEDGER_DOES_NOT_RECONCILE_TO_INCLUDED_TRANSACTIONS' END,
            CASE WHEN d.balance_source_credit_total
                          <> GREATEST(-d.full_account_balance, 0)
                THEN 'POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT' END,
            CASE WHEN d.refund_hold_ind = 'Y' THEN 'REFUND_HOLD_RH' END,
            CASE WHEN UPPER(TRIM(COALESCE(d.deceased_ind, ''))) = 'Y'
                THEN 'DECEASED_PERSON' END,
            CASE WHEN d.third_party_review_required_ind = 'Y'
                THEN 'THIRD_PARTY_ACCOUNT_REVIEW_REQUIRED' END,
            CASE WHEN d.third_party_detail_codes IS NOT NULL THEN 'Possible Third Party refund' END,
            CASE WHEN d.mines_park_review THEN 'Mines Park Charge - Review' END,
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
        ), '') AS review_reasons
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
        WHEN f.mines_park_review THEN 'MANUAL_REVIEW'
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
  AND f.total_refund_amount > 0
ORDER BY
    f.last_name,
    f.first_name,
    f.cwid;
