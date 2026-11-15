/* Read-only student detail for the stored late-fee populations, all operators.
   {{review_term}} selects CURRENT financial context, not historical eligibility.
   Keep raw keys and every stored scope, even without a usable current identity.
   Each row is one application/selection/creator/run-user/raw-key membership.
   Monetary values repeat across memberships: do not sum across selections/users.
   LPPF values are posted transactions, not a proposed fee or an assumed rate.
   Hold activity below is context (from <= today, to > today), not a replacement
   for the unobserved Banner application/hold selection rules.
*/
WITH parameters AS (
    SELECT CAST({{review_term}} AS varchar(6)) AS review_term,
        CURRENT_DATE AS context_date
), target_selections (selection_id) AS (
    VALUES ('AR_TERM_BALANCE'), ('AR_PP,CO,TO,WO_HOLDS'),
        ('AR_LATEFEES_1'), ('AR_LATEFEES_2'), ('AR_LATEFEES_3'),
        ('AR_LATEFEES_4'), ('AR_LATEFEES_5'), ('AR_LATEFEES_6'),
        ('AR_LATEFEES_FINAL'), ('AR_WAIVE_MANUAL_LATEFEES')
), members AS (
    SELECT e.glbextr_application AS application, e.glbextr_selection AS selection_id,
        e.glbextr_creator_id AS creator_id, e.glbextr_user_id AS run_user_id,
        CAST(e.glbextr_key AS text) AS population_key, COUNT(*) AS stored_rows,
        MIN(e.glbextr_activity_date) AS oldest_activity,
        MAX(e.glbextr_activity_date) AS latest_activity
    FROM general.glbextr e
    JOIN target_selections t ON t.selection_id = e.glbextr_selection
    GROUP BY e.glbextr_application, e.glbextr_selection, e.glbextr_creator_id,
        e.glbextr_user_id, e.glbextr_key
), keyed_members AS (
    SELECT m.*,
        CASE WHEN LENGTH(population_key) BETWEEN 1 AND 18
                  AND TRANSLATE(population_key, '0123456789', '') = ''
             THEN CAST(population_key AS bigint) END AS pidm
    FROM members m
), subjects AS (
    SELECT DISTINCT pidm FROM keyed_members WHERE pidm IS NOT NULL
), identities AS (
    SELECT s.spriden_pidm AS pidm, COUNT(*) AS identity_count,
        CASE WHEN COUNT(*) = 1 THEN MAX(s.spriden_id) END AS cwid,
        CASE WHEN COUNT(*) = 1 THEN MAX(s.spriden_first_name) END AS first_name,
        CASE WHEN COUNT(*) = 1 THEN MAX(s.spriden_last_name) END AS last_name
    FROM saturn.spriden s JOIN subjects p ON p.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
    GROUP BY s.spriden_pidm
), email_ranked AS (
    SELECT e.goremal_pidm AS pidm, TRIM(e.goremal_email_address) AS email,
        ROW_NUMBER() OVER (PARTITION BY e.goremal_pidm
            ORDER BY e.goremal_activity_date DESC NULLS LAST,
                e.goremal_email_address) AS email_rank
    FROM general.goremal e JOIN subjects p ON p.pidm = e.goremal_pidm
    WHERE e.goremal_emal_code = 'UNIV' AND e.goremal_status_ind = 'A'
      AND NULLIF(TRIM(e.goremal_email_address), '') IS NOT NULL
), descriptions AS (
    SELECT h.glbslct_application AS application, h.glbslct_selection AS selection_id,
        h.glbslct_creator_id AS creator_id,
        CASE WHEN COUNT(*) = 1 THEN MAX(h.glbslct_desc) END AS description
    FROM general.glbslct h
    JOIN target_selections t ON t.selection_id = h.glbslct_selection
    GROUP BY h.glbslct_application, h.glbslct_selection, h.glbslct_creator_id
), detail_types AS (
    -- Duplicate classifications must not multiply student transactions.
    SELECT d.tbbdetc_detail_code AS detail_code,
        CASE WHEN COUNT(*) = 1 THEN MAX(UPPER(TRIM(d.tbbdetc_type_ind))) END AS detail_type
    FROM taismgr.tbbdetc d GROUP BY d.tbbdetc_detail_code
), term_financials AS (
    SELECT t.tbraccd_pidm AS pidm, t.tbraccd_term_code AS term_code,
        COUNT(*) AS transaction_count,
        SUM(CASE WHEN t.tbraccd_amount IS NULL
                       OR d.detail_type IS NULL OR d.detail_type NOT IN ('C', 'P')
            THEN 1 ELSE 0 END) AS invalid_rows,
        SUM(CASE WHEN d.detail_type = 'C' THEN t.tbraccd_amount ELSE 0 END) AS charges,
        SUM(CASE WHEN d.detail_type = 'P' THEN t.tbraccd_amount ELSE 0 END) AS payments,
        SUM(CASE d.detail_type WHEN 'C' THEN t.tbraccd_amount
            WHEN 'P' THEN -t.tbraccd_amount END) AS net_amount,
        SUM(CASE WHEN t.tbraccd_detail_code = 'LPPF' THEN 1 ELSE 0 END) AS lppf_rows,
        SUM(CASE WHEN t.tbraccd_detail_code = 'LPPF' AND t.tbraccd_amount IS NULL
            THEN 1 ELSE 0 END) AS lppf_missing_amounts,
        SUM(CASE WHEN t.tbraccd_detail_code = 'LPPF' AND t.tbraccd_balance IS NULL
            THEN 1 ELSE 0 END) AS lppf_missing_balances,
        SUM(CASE WHEN t.tbraccd_detail_code = 'LPPF' THEN t.tbraccd_amount ELSE 0 END) AS lppf_amount,
        SUM(CASE WHEN t.tbraccd_detail_code = 'LPPF' THEN t.tbraccd_balance ELSE 0 END) AS lppf_balance
    FROM taismgr.tbraccd t JOIN subjects p ON p.pidm = t.tbraccd_pidm
    LEFT JOIN detail_types d ON d.detail_code = t.tbraccd_detail_code
    GROUP BY t.tbraccd_pidm, t.tbraccd_term_code
), accounts AS (
    SELECT f.pidm, SUM(f.transaction_count) AS transaction_count,
        SUM(f.invalid_rows) AS invalid_rows,
        CASE WHEN SUM(f.invalid_rows) = 0 THEN ROUND(SUM(f.net_amount), 2) END AS balance,
        MAX(CASE WHEN f.term_code <> p.review_term AND f.net_amount < 0
                       AND f.invalid_rows = 0 THEN 1 ELSE 0 END) AS other_term_credit
    FROM term_financials f CROSS JOIN parameters p GROUP BY f.pidm
), hold_records AS (
    SELECT h.sprhold_pidm AS pidm, h.sprhold_hldd_code AS hold_code,
        CASE WHEN (h.sprhold_from_date IS NULL OR CAST(h.sprhold_from_date AS date) <= p.context_date)
                   AND CAST(h.sprhold_to_date AS date) > p.context_date THEN 1 ELSE 0 END AS active,
        COALESCE(h.sprhold_hldd_code, '(missing code)') || ' ['
            || COALESCE(CAST(CAST(h.sprhold_from_date AS date) AS text), 'unknown') || ' to '
            || COALESCE(CAST(CAST(h.sprhold_to_date AS date) AS text), 'unknown') || ']' AS hold_detail
    FROM saturn.sprhold h JOIN subjects s ON s.pidm = h.sprhold_pidm
    CROSS JOIN parameters p
), holds AS (
    SELECT pidm,
        STRING_AGG(DISTINCT CASE WHEN active = 1 THEN hold_code END, ', ') AS active_codes,
        STRING_AGG(DISTINCT hold_detail, '; ') AS history,
        COUNT(*) AS hold_count
    FROM hold_records GROUP BY pidm
), manual_waivers AS (
    -- Every staff list contributes. Creator and run-user restrictions are absent.
    SELECT population_key, SUM(stored_rows) AS source_rows,
        COUNT(DISTINCT run_user_id) AS source_users,
        STRING_AGG(DISTINCT application, ', ') AS applications,
        STRING_AGG(DISTINCT creator_id, ', ') AS creators,
        STRING_AGG(DISTINCT run_user_id, ', ') AS run_users,
        MIN(oldest_activity) AS oldest_activity, MAX(latest_activity) AS latest_activity
    FROM members WHERE selection_id = 'AR_WAIVE_MANUAL_LATEFEES'
    GROUP BY population_key
), run_memberships AS (
    SELECT application, run_user_id, population_key,
        STRING_AGG(DISTINCT selection_id || ' (creator '
            || COALESCE(creator_id, 'unknown') || ')', '; ') AS selections
    FROM members WHERE selection_id <> 'AR_WAIVE_MANUAL_LATEFEES'
    GROUP BY application, run_user_id, population_key
)
SELECT
    i.cwid AS "CWID", i.last_name AS "Last Name", i.first_name AS "First Name",
    e.email AS "Mines Email", m.population_key AS "Population Key", CAST(m.pidm AS text) AS "PIDM",
    CASE WHEN m.pidm IS NULL THEN 'INVALID_KEY'
         WHEN i.pidm IS NULL THEN 'MISSING_IDENTITY'
         WHEN i.identity_count <> 1 THEN 'MULTIPLE_CURRENT_IDENTITIES'
         WHEN NULLIF(TRIM(i.cwid), '') IS NULL THEN 'MISSING_CWID'
         ELSE 'MATCHED' END AS "Identity Status",
    m.application AS "Application", m.selection_id AS "Selection ID",
    d.description AS "Selection Description", m.creator_id AS "Creator ID",
    m.run_user_id AS "Run User ID", m.stored_rows AS "Stored Rows For Key",
    m.oldest_activity AS "Population Oldest Activity",
    m.latest_activity AS "Population Latest Activity",
    r.selections AS "Stored Selections For This Run User",
    p.review_term AS "Financial Context Term", p.context_date AS "Financial Context Date",
    CASE WHEN a.pidm IS NULL OR COALESCE(f.invalid_rows, 0) > 0 THEN NULL
         ELSE ROUND(COALESCE(f.charges, 0), 2) END AS "Current Term Charges",
    CASE WHEN a.pidm IS NULL OR COALESCE(f.invalid_rows, 0) > 0 THEN NULL
         ELSE ROUND(COALESCE(f.payments, 0), 2) END AS "Current Term Payments",
    CASE WHEN a.pidm IS NULL OR COALESCE(f.invalid_rows, 0) > 0 THEN NULL
         ELSE ROUND(COALESCE(f.net_amount, 0), 2) END AS "Current Term Net Balance",
    a.balance AS "Current All-Term Account Balance",
    CASE WHEN a.pidm IS NULL OR a.invalid_rows > 0 THEN 'Unknown'
         WHEN a.other_term_credit = 1 THEN 'Yes' ELSE 'No' END AS "Other Term Credit",
    COALESCE(f.transaction_count, 0) AS "Term Transaction Rows",
    COALESCE(a.transaction_count, 0) AS "Account Transaction Rows",
    COALESCE(a.invalid_rows, 0) AS "Invalid Financial Rows",
    CASE WHEN a.pidm IS NULL OR COALESCE(f.lppf_missing_amounts, 0) > 0 THEN NULL
         ELSE ROUND(COALESCE(f.lppf_amount, 0), 2) END AS "Posted LPPF Amount - Selected Term",
    CASE WHEN a.pidm IS NULL OR COALESCE(f.lppf_missing_balances, 0) > 0 THEN NULL
         ELSE ROUND(COALESCE(f.lppf_balance, 0), 2) END AS "Remaining LPPF Balance - Selected Term",
    COALESCE(f.lppf_rows, 0) AS "LPPF Transaction Rows - Selected Term",
    h.active_codes AS "Active Hold Codes", h.history AS "Hold History",
    COALESCE(h.hold_count, 0) AS "Hold Record Count",
    CASE WHEN w.source_rows IS NULL THEN 'N' ELSE 'Y' END AS "In Current Shared Manual Waivers",
    COALESCE(w.source_rows, 0) AS "Manual Waiver Source Rows",
    COALESCE(w.source_users, 0) AS "Manual Waiver Staff Count",
    w.applications AS "Manual Waiver Applications", w.creators AS "Manual Waiver Creators",
    w.run_users AS "Manual Waiver Staff Users",
    w.oldest_activity AS "Manual Waiver Oldest Activity",
    w.latest_activity AS "Manual Waiver Latest Activity",
    NULLIF(
        CASE WHEN m.pidm IS NULL THEN 'Invalid population key; identity and account unavailable. ' ELSE '' END
        || CASE WHEN COALESCE(i.identity_count, 0) <> 1 THEN 'Missing or ambiguous current identity. ' ELSE '' END
        || CASE WHEN i.identity_count = 1 AND NULLIF(TRIM(i.cwid), '') IS NULL THEN 'Current identity has no CWID. ' ELSE '' END
        || CASE WHEN m.stored_rows > 1 THEN 'Duplicate stored membership rows. ' ELSE '' END
        || CASE WHEN a.pidm IS NULL THEN 'No visible account transactions. ' ELSE '' END
        || CASE WHEN a.invalid_rows > 0 THEN 'Unknown amount or missing/duplicate detail classification. ' ELSE '' END
        || CASE WHEN f.lppf_missing_balances > 0 THEN 'Missing remaining balance on a posted LPPF transaction. ' ELSE '' END
        || CASE WHEN a.other_term_credit = 1 THEN 'Credit in another term; review payment application. ' ELSE '' END
        || CASE WHEN m.selection_id = 'AR_LATEFEES_FINAL' AND w.source_rows > 0
            THEN 'Stored FINAL overlaps current manual waivers; compare source/run dates. ' ELSE '' END,
        '') AS "Review Notes",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count",
    ROW_NUMBER() OVER (ORDER BY m.application, m.selection_id, m.creator_id,
        m.run_user_id, m.population_key) AS "__Report Row Number"
FROM keyed_members m CROSS JOIN parameters p
LEFT JOIN identities i ON i.pidm = m.pidm
LEFT JOIN email_ranked e ON e.pidm = m.pidm AND e.email_rank = 1
LEFT JOIN descriptions d ON d.application = m.application AND d.selection_id = m.selection_id
    AND d.creator_id = m.creator_id
LEFT JOIN term_financials f ON f.pidm = m.pidm AND f.term_code = p.review_term
LEFT JOIN accounts a ON a.pidm = m.pidm
LEFT JOIN holds h ON h.pidm = m.pidm
LEFT JOIN manual_waivers w ON w.population_key = m.population_key
    OR (w.population_key IS NULL AND m.population_key IS NULL)
LEFT JOIN run_memberships r ON r.application = m.application AND r.run_user_id = m.run_user_id
    AND (r.population_key = m.population_key OR (r.population_key IS NULL AND m.population_key IS NULL))
ORDER BY "__Report Row Number";
