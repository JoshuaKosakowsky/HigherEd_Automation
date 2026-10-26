/*
W&F - Banner Recon; read-only Banner Insights (PostgreSQL-flavored SQL).
CO with TO_DATE strictly after today defines the population. No FROM_DATE,
enrollment, term, or positive-balance restriction is applied.
One row per current identity/PIDM: latest qualifying FROM_DATE (NULL last),
then latest TO_DATE. Hold dates are calendar dates in the output.
Balance is all-term charges minus payments/credits, preserving reversal signs.
Unknown amounts/types or absent transactions leave balance NULL for review;
they never remove a qualifying account. Latest Feed Date is account-wide,
not the collection referral date or a collections-only payment date.
TO uses the same strictly-after-today end-date rule; it never expands the CO
population or creates extra rows. WOFF/BDRC are all-history signed Amount sums.
Absent code activity is zero when transactions exist; unknown amounts are NULL.
Total Balance = Current Account Balance + WOFF + BDRC (owner rule, issue #15).
*/
WITH ranked_holds AS (
    SELECT
        h.sprhold_pidm AS pidm,
        h.sprhold_from_date AS from_date,
        h.sprhold_to_date AS to_date,
        ROW_NUMBER() OVER (
            PARTITION BY h.sprhold_pidm
            ORDER BY h.sprhold_from_date DESC NULLS LAST,
                     h.sprhold_to_date DESC
        ) AS hold_rank
    FROM saturn.sprhold h
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'CO'
      AND CAST(h.sprhold_to_date AS date) > CURRENT_DATE
),
to_holds AS (
    SELECT DISTINCT h.sprhold_pidm AS pidm
    FROM saturn.sprhold h
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'TO'
      AND CAST(h.sprhold_to_date AS date) > CURRENT_DATE
),
account_totals AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        CASE WHEN SUM(CASE
            WHEN t.tbraccd_amount IS NULL
              OR d.tbbdetc_type_ind IS NULL
              OR UPPER(TRIM(d.tbbdetc_type_ind)) NOT IN ('C', 'P')
            THEN 1 ELSE 0
        END) > 0 THEN NULL
        ELSE ROUND(SUM(CASE UPPER(TRIM(d.tbbdetc_type_ind))
            WHEN 'C' THEN t.tbraccd_amount
            WHEN 'P' THEN -t.tbraccd_amount
        END), 2) END AS total_balance,
        MAX(t.tbraccd_feed_date) AS latest_feed_date,
        -- Signed posted Amount totals, not remaining transaction balances.
        CASE WHEN SUM(CASE WHEN t.tbraccd_detail_code = 'WOFF'
                          AND t.tbraccd_amount IS NULL THEN 1 ELSE 0 END) > 0
             THEN NULL ELSE ROUND(SUM(CASE WHEN t.tbraccd_detail_code = 'WOFF'
                          THEN t.tbraccd_amount ELSE 0 END), 2) END AS woff,
        CASE WHEN SUM(CASE WHEN t.tbraccd_detail_code = 'BDRC'
                          AND t.tbraccd_amount IS NULL THEN 1 ELSE 0 END) > 0
             THEN NULL ELSE ROUND(SUM(CASE WHEN t.tbraccd_detail_code = 'BDRC'
                          THEN t.tbraccd_amount ELSE 0 END), 2) END AS bdrc
    FROM taismgr.tbraccd t
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    WHERE EXISTS (
        SELECT 1 FROM ranked_holds h WHERE h.pidm = t.tbraccd_pidm
    )
    GROUP BY t.tbraccd_pidm
)
SELECT
    s.spriden_id AS "CWID",
    s.spriden_first_name AS "First Name",
    s.spriden_last_name AS "Last Name",
    a.total_balance AS "Current Account Balance",
    a.latest_feed_date AS "Latest Feed Date",
    'CO' AS "CO Hold",
    CASE WHEN th.pidm IS NOT NULL THEN 'TO' END AS "TO Hold",
    CAST(h.from_date AS date) AS "From Date",
    CAST(h.to_date AS date) AS "To Date",
    a.woff AS "WOFF",
    a.bdrc AS "BDRC",
    a.total_balance + a.woff + a.bdrc AS "Total Balance",
    COUNT(*) OVER () AS "Report Row Count"
FROM ranked_holds h
INNER JOIN saturn.spriden s
    ON s.spriden_pidm = h.pidm
   AND s.spriden_change_ind IS NULL
LEFT JOIN account_totals a ON a.pidm = h.pidm
LEFT JOIN to_holds th ON th.pidm = h.pidm
WHERE h.hold_rank = 1
ORDER BY s.spriden_last_name, s.spriden_first_name, s.spriden_id;
