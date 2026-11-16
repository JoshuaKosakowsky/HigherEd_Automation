/* Read-only diagnostic: stored _6 versus currently visible manual-source keys.
   Discover every visible _5/_6 application/definition-creator/run-user scope.
   Compare each scope separately: never combine different operators' stored
   results. _5/_6 creators can differ from a generated FINAL result's creator.
   The manual source deliberately spans applications, creators and run users,
   matching the scope of the displayed selection-name condition only. This is
   NOT a rerun of _6: identity joins and application rules are not reproduced.
   A missing source key does not prove that its waiver expired or was deleted.
*/
WITH scoped_rows AS (
    SELECT
        DENSE_RANK() OVER (ORDER BY e.glbextr_application, e.glbextr_creator_id,
            e.glbextr_user_id) AS scope_id,
        e.glbextr_application AS application,
        e.glbextr_creator_id AS definition_creator_id,
        e.glbextr_user_id AS run_user_id,
        e.glbextr_selection AS selection_id,
        CAST(e.glbextr_key AS text) AS population_key,
        e.glbextr_activity_date AS activity_date
    FROM general.glbextr e
    WHERE e.glbextr_selection IN ('AR_LATEFEES_5', 'AR_LATEFEES_6')
), scopes AS (
    SELECT DISTINCT scope_id, application, definition_creator_id, run_user_id
    FROM scoped_rows
    UNION ALL
    -- Keep source-only evidence visible even when no stored scope is available.
    SELECT 0, CAST(NULL AS text), CAST(NULL AS text), CAST(NULL AS text)
    WHERE NOT EXISTS (SELECT 1 FROM scoped_rows)
), stored_waivers AS (
    SELECT scope_id, population_key,
        COUNT(*) AS stored_rows, MIN(activity_date) AS oldest_activity,
        MAX(activity_date) AS latest_activity
    FROM scoped_rows
    WHERE selection_id = 'AR_LATEFEES_6'
    GROUP BY scope_id, population_key
), source_waivers AS (
    SELECT CAST(e.glbextr_key AS text) AS population_key,
        COUNT(*) AS source_rows,
        COUNT(DISTINCT e.glbextr_application) AS source_applications,
        COUNT(DISTINCT e.glbextr_creator_id) AS source_creators,
        COUNT(DISTINCT e.glbextr_user_id) AS source_run_users,
        MIN(e.glbextr_activity_date) AS oldest_activity,
        MAX(e.glbextr_activity_date) AS latest_activity
    FROM general.glbextr e
    WHERE e.glbextr_selection = 'AR_WAIVE_MANUAL_LATEFEES'
    GROUP BY e.glbextr_key
), pre_final AS (
    SELECT DISTINCT scope_id, population_key
    FROM scoped_rows
    WHERE selection_id = 'AR_LATEFEES_5'
), all_keys AS (
    SELECT scope_id, population_key FROM stored_waivers
    UNION
    SELECT p.scope_id, w.population_key
    FROM scopes p CROSS JOIN source_waivers w
), membership AS (
    SELECT k.scope_id, k.population_key,
        COALESCE(s.stored_rows, 0) AS stored_rows,
        COALESCE(w.source_rows, 0) AS source_rows,
        COALESCE(w.source_applications, 0) AS source_applications,
        COALESCE(w.source_creators, 0) AS source_creators,
        COALESCE(w.source_run_users, 0) AS source_run_users,
        s.oldest_activity AS stored_oldest_activity,
        s.latest_activity AS stored_latest_activity,
        w.oldest_activity AS source_oldest_activity,
        w.latest_activity AS source_latest_activity,
        CASE WHEN NOT EXISTS (SELECT 1 FROM pre_final f
                              WHERE f.scope_id = k.scope_id) THEN NULL
             WHEN EXISTS (SELECT 1 FROM pre_final f
                          WHERE f.scope_id = k.scope_id
                            AND f.population_key = k.population_key) THEN 'Y'
             ELSE 'N' END AS in_pre_final
    FROM all_keys k
    LEFT JOIN stored_waivers s
      ON s.scope_id = k.scope_id
     AND (s.population_key = k.population_key
          OR (s.population_key IS NULL AND k.population_key IS NULL))
    LEFT JOIN source_waivers w
      ON w.population_key = k.population_key
      OR (w.population_key IS NULL AND k.population_key IS NULL)
)
SELECT
    CASE WHEN m.stored_rows IS NULL THEN 'NO_VISIBLE_WAIVER_ROWS'
         WHEN m.population_key IS NULL OR m.population_key = ''
           OR TRANSLATE(m.population_key, '0123456789', '') <> '' THEN 'INVALID_KEY'
         WHEN p.scope_id = 0 THEN 'SOURCE_WITHOUT_STORED_SCOPE'
         WHEN m.source_rows = 0 THEN 'STORED_EXTRACT_ONLY'
         WHEN m.stored_rows = 0 THEN 'CURRENT_SOURCE_ONLY'
         ELSE 'BOTH' END AS "Membership Status",
    m.population_key AS "Population Key",
    m.in_pre_final AS "In Stored Pre-final",
    m.stored_rows AS "Stored Rows For Key", m.source_rows AS "Source Rows For Key",
    m.source_applications AS "Source Applications For Key",
    m.source_creators AS "Source Creators For Key",
    m.source_run_users AS "Source Run Users For Key",
    m.stored_oldest_activity AS "Stored Oldest Activity",
    m.stored_latest_activity AS "Stored Latest Activity",
    m.source_oldest_activity AS "Source Oldest Activity",
    m.source_latest_activity AS "Source Latest Activity",
    (SELECT COUNT(*) FROM stored_waivers s
     WHERE s.scope_id = p.scope_id) AS "Stored Waiver Key Groups",
    (SELECT COUNT(*) FROM source_waivers) AS "Source Waiver Key Groups",
    (SELECT COUNT(*) FROM pre_final f
     WHERE f.scope_id = p.scope_id) AS "Stored Pre-final Key Groups",
    p.application AS "Application", p.definition_creator_id AS "Definition Creator ID",
    p.run_user_id AS "Run User ID", CURRENT_TIMESTAMP AS "Extracted At",
    COUNT(*) OVER () AS "Report Row Count"
FROM scopes p
LEFT JOIN membership m ON m.scope_id = p.scope_id
ORDER BY p.application, p.definition_creator_id, p.run_user_id,
    CASE WHEN m.source_rows = 0 OR m.stored_rows = 0 THEN 0 ELSE 1 END,
    m.population_key;
