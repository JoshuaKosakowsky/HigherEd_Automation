/* Shared candidate selection for both exports. Render through extract.py.
   The two-year window selects accounts; it never truncates their history. */
WITH run_settings AS (
    SELECT
        __RUN_DATE__ AS run_date,
        CAST(__TARGET_TERM_OVERRIDE__ AS varchar(6)) AS target_term_override,
        CAST(__CWID_FILTER__ AS varchar(30)) AS cwid_filter
),
scope_dates AS (
    SELECT *, CAST(run_date - INTERVAL '2 years' AS date) AS lookback_date
    FROM run_settings
),
params AS (
    SELECT
        run_date,
        CAST(COALESCE(target_term_override, CONCAT(
            CAST(EXTRACT(YEAR FROM run_date) AS integer),
            CASE
                WHEN run_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM run_date) AS integer), 5, 15) THEN '10'
                WHEN run_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM run_date) AS integer), 7, 15) THEN '55'
                ELSE '80'
            END
        )) AS varchar(6)) AS target_term,
        CAST(CONCAT(
            CAST(EXTRACT(YEAR FROM lookback_date) AS integer),
            CASE
                WHEN lookback_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM lookback_date) AS integer), 5, 15) THEN '10'
                WHEN lookback_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM lookback_date) AS integer), 7, 15) THEN '55'
                ELSE '80'
            END
        ) AS varchar(6)) AS lookback_term,
        cwid_filter
    FROM scope_dates
),
candidate_pidms AS MATERIALIZED (
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_term_code = p.target_term
      AND MOD(ABS(t.tbraccd_pidm), __BATCH_COUNT__) = __BATCH_INDEX__

    UNION

    /* Conservative HOMP candidate check; Python nets reversals and decides review. */
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_detail_code = 'HOMP'
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
      AND t.tbraccd_amount > 0
      AND (t.tbraccd_term_code = p.target_term OR (
          t.tbraccd_effective_date >= p.run_date - INTERVAL '32 days'
          AND t.tbraccd_effective_date < p.run_date + INTERVAL '1 day'
      ))
      AND MOD(ABS(t.tbraccd_pidm), __BATCH_COUNT__) = __BATCH_INDEX__

    UNION

    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_term_code >= p.lookback_term
      AND t.tbraccd_term_code <= p.target_term
      AND t.tbraccd_balance < 0
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
      AND MOD(ABS(t.tbraccd_pidm), __BATCH_COUNT__) = __BATCH_INDEX__

    UNION

    SELECT i.spriden_pidm AS pidm
    FROM saturn.spriden i
    CROSS JOIN params p
    WHERE p.cwid_filter IS NOT NULL
      AND i.spriden_change_ind IS NULL
      AND i.spriden_id = TRIM(p.cwid_filter)
      AND MOD(ABS(i.spriden_pidm), __BATCH_COUNT__) = __BATCH_INDEX__
),
account_balances AS MATERIALIZED (
    /* Full history for selected accounts only. Positive balances are out of scope.
       Keep uncertain balances for Python's data-quality checks rather than
       silently inferring a credit from missing amounts or classifications. */
    SELECT
        c.pidm,
        SUM(CASE UPPER(TRIM(d.tbbdetc_type_ind))
            WHEN 'P' THEN -t.tbraccd_amount
            WHEN 'C' THEN t.tbraccd_amount
        END) AS full_account_balance,
        COUNT(*) FILTER (WHERE t.tbraccd_amount IS NULL
            OR d.tbbdetc_type_ind IS NULL
            OR UPPER(TRIM(d.tbbdetc_type_ind)) NOT IN ('C', 'P')) AS invalid_rows
    FROM candidate_pidms c
    INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = c.pidm
    LEFT JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY c.pidm
)
SELECT a.pidm, p.target_term
FROM account_balances a
CROSS JOIN params p
WHERE ROUND(a.full_account_balance, 2) <= 0 OR a.invalid_rows > 0
