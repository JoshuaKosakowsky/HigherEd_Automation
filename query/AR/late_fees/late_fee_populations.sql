/* Read-only inventory AND member export for the named populations.
   Deliberately shows every visible application/creator/run-user combination:
   _6's displayed manual-waiver rule does not restrict these fields. This does
   not broaden eligibility; it exposes stored rows for scope review.
   A zero-row marker is NOT evidence that a job ran and selected zero people.
   Keys are internal population keys (expected PIDMs), not CWIDs. No identity
   join: missing identities must not silently remove comparison evidence.
*/
WITH target_selections (selection_id) AS (
    VALUES
        ('AR_TERM_BALANCE'), ('AR_PP,CO,TO,WO_HOLDS'),
        ('AR_LATEFEES_1'), ('AR_LATEFEES_2'), ('AR_LATEFEES_3'),
        ('AR_LATEFEES_4'), ('AR_LATEFEES_5'), ('AR_LATEFEES_6'),
        ('AR_LATEFEES_FINAL'), ('AR_WAIVE_MANUAL_LATEFEES')
)
SELECT
    CASE WHEN e.glbextr_selection IS NULL THEN 'NO_VISIBLE_ROWS'
         ELSE 'STORED_ROW' END AS "Evidence Type",
    t.selection_id AS "Selection ID", e.glbextr_application AS "Application",
    e.glbextr_creator_id AS "Creator ID", e.glbextr_user_id AS "Run User ID",
    CAST(e.glbextr_key AS text) AS "Population Key",
    e.glbextr_sys_ind AS "Raw System Indicator",
    e.glbextr_slct_ind AS "Raw Selection Indicator",
    e.glbextr_activity_date AS "Source Activity Date",
    COUNT(e.glbextr_selection) OVER (
        PARTITION BY t.selection_id, e.glbextr_application,
            e.glbextr_creator_id, e.glbextr_user_id
    ) AS "Stored Rows In Scope",
    COUNT(e.glbextr_selection) OVER (
        PARTITION BY t.selection_id, e.glbextr_application,
            e.glbextr_creator_id, e.glbextr_user_id, e.glbextr_key
    ) AS "Rows For Key In Scope",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count"
FROM target_selections t
LEFT JOIN general.glbextr e ON e.glbextr_selection = t.selection_id
ORDER BY t.selection_id, e.glbextr_application, e.glbextr_creator_id,
    e.glbextr_user_id, e.glbextr_key, e.glbextr_activity_date;
