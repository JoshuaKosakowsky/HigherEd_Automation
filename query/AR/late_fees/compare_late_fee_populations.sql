/* Read-only exact membership comparison of TWO PRESERVED populations.
   Fill creator_id, run_user_id and baseline_selection below. Both populations must be
   visible in this same Insights database under the same application, creator
   and run user. This query cannot recover a FINAL overwritten by a later run.
   Preserve the seven-step result under a distinct TEST selection first.
   No automatic PASS: equal keys still require run logs, matching prompt values
   and confirmed replication. Source activity dates are not refresh timestamps.
*/
WITH parameters AS (
    SELECT
        'AR_STU' AS application,
        CAST(NULL AS varchar(30)) AS creator_id,
        CAST(NULL AS varchar(30)) AS run_user_id,
        CAST(NULL AS varchar(30)) AS baseline_selection,
        'AR_LATEFEES_FINAL' AS candidate_selection
), input_check AS (
    SELECT p.*,
        CASE
            WHEN NULLIF(BTRIM(application), '') IS NULL
              OR NULLIF(BTRIM(creator_id), '') IS NULL
              OR NULLIF(BTRIM(run_user_id), '') IS NULL
              OR NULLIF(BTRIM(baseline_selection), '') IS NULL
              OR NULLIF(BTRIM(candidate_selection), '') IS NULL
              OR application <> BTRIM(application)
              OR creator_id <> BTRIM(creator_id)
              OR run_user_id <> BTRIM(run_user_id)
              OR baseline_selection <> BTRIM(baseline_selection)
              OR candidate_selection <> BTRIM(candidate_selection)
                THEN 'INVALID_PARAMETERS'
            WHEN baseline_selection = candidate_selection THEN 'SAME_POPULATION'
            ELSE 'READY'
        END AS input_status
    FROM parameters p
), source_rows AS (
    SELECT
        CASE WHEN e.glbextr_selection = p.baseline_selection
             THEN 'BASELINE' ELSE 'CANDIDATE' END AS side,
        CAST(e.glbextr_key AS text) AS population_key,
        e.glbextr_activity_date AS activity_date
    FROM general.glbextr e
    CROSS JOIN input_check p
    WHERE p.input_status = 'READY'
      AND e.glbextr_application = p.application
      AND e.glbextr_creator_id = p.creator_id
      AND e.glbextr_user_id = p.run_user_id
      AND e.glbextr_selection IN (p.baseline_selection, p.candidate_selection)
), grouped AS (
    SELECT side, population_key, COUNT(*) AS row_count,
        MIN(activity_date) AS oldest_activity, MAX(activity_date) AS latest_activity,
        CASE WHEN population_key IS NULL OR population_key = ''
               OR TRANSLATE(population_key, '0123456789', '') <> ''
             THEN 1 ELSE 0 END AS invalid_key
    FROM source_rows
    GROUP BY side, population_key
), sides (side) AS (
    VALUES ('BASELINE'), ('CANDIDATE')
), scope_stats AS (
    SELECT s.side, COALESCE(SUM(g.row_count), 0) AS total_rows,
        COUNT(g.row_count) AS key_groups,
        COALESCE(SUM(g.row_count - 1), 0) AS duplicate_rows,
        COALESCE(SUM(g.invalid_key * g.row_count), 0) AS invalid_rows,
        MIN(g.oldest_activity) AS oldest_activity,
        MAX(g.latest_activity) AS latest_activity
    FROM sides s
    LEFT JOIN grouped g ON g.side = s.side
    GROUP BY s.side
), all_keys AS (
    SELECT population_key FROM grouped GROUP BY population_key
), membership AS (
    SELECT k.population_key,
        COALESCE(b.row_count, 0) AS baseline_rows,
        COALESCE(c.row_count, 0) AS candidate_rows,
        COALESCE(b.invalid_key, c.invalid_key, 0) AS invalid_key
    FROM all_keys k
    LEFT JOIN grouped b ON b.side = 'BASELINE'
      AND (b.population_key = k.population_key
           OR (b.population_key IS NULL AND k.population_key IS NULL))
    LEFT JOIN grouped c ON c.side = 'CANDIDATE'
      AND (c.population_key = k.population_key
           OR (c.population_key IS NULL AND k.population_key IS NULL))
), differences AS (
    SELECT
        COALESCE(SUM(CASE WHEN candidate_rows = 0 THEN 1 ELSE 0 END), 0)
            AS baseline_only_keys,
        COALESCE(SUM(CASE WHEN baseline_rows = 0 THEN 1 ELSE 0 END), 0)
            AS candidate_only_keys
    FROM membership
), summary AS (
    SELECT
        CASE
            WHEN p.input_status <> 'READY' THEN p.input_status
            WHEN b.invalid_rows + c.invalid_rows > 0 THEN 'INVALID_KEYS'
            WHEN b.total_rows = 0 OR c.total_rows = 0 THEN 'INCONCLUSIVE_EMPTY_SIDE'
            WHEN d.baseline_only_keys + d.candidate_only_keys > 0 THEN 'DIFFERENT'
            WHEN b.duplicate_rows + c.duplicate_rows > 0 THEN 'DUPLICATE_KEYS_REVIEW'
            ELSE 'MATCH_REQUIRES_RUN_EVIDENCE'
        END AS comparison_status,
        b.total_rows AS baseline_total_rows, c.total_rows AS candidate_total_rows,
        b.key_groups AS baseline_key_groups, c.key_groups AS candidate_key_groups,
        b.duplicate_rows AS baseline_duplicate_rows,
        c.duplicate_rows AS candidate_duplicate_rows,
        b.invalid_rows AS baseline_invalid_rows, c.invalid_rows AS candidate_invalid_rows,
        b.oldest_activity AS baseline_oldest_activity,
        b.latest_activity AS baseline_latest_activity,
        c.oldest_activity AS candidate_oldest_activity,
        c.latest_activity AS candidate_latest_activity,
        d.baseline_only_keys, d.candidate_only_keys
    FROM input_check p
    CROSS JOIN scope_stats b CROSS JOIN scope_stats c CROSS JOIN differences d
    WHERE b.side = 'BASELINE' AND c.side = 'CANDIDATE'
), report_rows AS (
    SELECT 'SUMMARY' AS row_type, CAST(NULL AS text) AS population_key,
        CAST(NULL AS text) AS membership_status,
        CAST(NULL AS bigint) AS baseline_rows, CAST(NULL AS bigint) AS candidate_rows
    UNION ALL
    SELECT 'EXCEPTION', population_key,
        CASE WHEN invalid_key = 1 THEN 'INVALID_KEY'
             WHEN candidate_rows = 0 THEN 'BASELINE_ONLY'
             WHEN baseline_rows = 0 THEN 'CANDIDATE_ONLY'
             ELSE 'DUPLICATE_KEY' END,
        baseline_rows, candidate_rows
    FROM membership
    WHERE baseline_rows = 0 OR candidate_rows = 0 OR invalid_key = 1
       OR baseline_rows > 1 OR candidate_rows > 1
)
SELECT
    r.row_type AS "Row Type", s.comparison_status AS "Comparison Status",
    r.population_key AS "Population Key", r.membership_status AS "Membership Status",
    r.baseline_rows AS "Baseline Rows For Key", r.candidate_rows AS "Candidate Rows For Key",
    s.baseline_total_rows AS "Baseline Total Rows",
    s.candidate_total_rows AS "Candidate Total Rows",
    s.baseline_key_groups AS "Baseline Key Groups",
    s.candidate_key_groups AS "Candidate Key Groups",
    s.baseline_only_keys AS "Baseline Only Keys", s.candidate_only_keys AS "Candidate Only Keys",
    s.baseline_duplicate_rows AS "Baseline Duplicate Rows",
    s.candidate_duplicate_rows AS "Candidate Duplicate Rows",
    s.baseline_invalid_rows AS "Baseline Invalid Rows",
    s.candidate_invalid_rows AS "Candidate Invalid Rows",
    s.baseline_oldest_activity AS "Baseline Oldest Activity",
    s.baseline_latest_activity AS "Baseline Latest Activity",
    s.candidate_oldest_activity AS "Candidate Oldest Activity",
    s.candidate_latest_activity AS "Candidate Latest Activity",
    p.application AS "Application", p.creator_id AS "Creator ID",
    p.run_user_id AS "Run User ID", p.baseline_selection AS "Baseline Selection",
    p.candidate_selection AS "Candidate Selection",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count"
FROM report_rows r CROSS JOIN summary s CROSS JOIN input_check p
ORDER BY CASE r.row_type WHEN 'SUMMARY' THEN 0 ELSE 1 END, r.population_key;
