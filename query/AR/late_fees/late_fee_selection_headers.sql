/* Read-only header inventory using only the GLBSLCT fields confirmed visible
   in the 2026-11-15 TEST schema export. Headers/descriptions do not establish
   eligibility criteria. This query does not need the unavailable rule tables.
   Keep all visible applications/creators for ownership review. Run user is
   attached to extracted populations, not to these definition headers.
*/
WITH target_selections (selection_id) AS (
    VALUES
        ('AR_TERM_BALANCE'), ('AR_PP,CO,TO,WO_HOLDS'),
        ('AR_LATEFEES_1'), ('AR_LATEFEES_2'), ('AR_LATEFEES_3'),
        ('AR_LATEFEES_4'), ('AR_LATEFEES_5'), ('AR_LATEFEES_6'),
        ('AR_LATEFEES_FINAL'), ('AR_WAIVE_MANUAL_LATEFEES')
)
SELECT
    CASE WHEN h.glbslct_selection IS NULL THEN 'NO_VISIBLE_HEADER'
         ELSE 'SELECTION_HEADER' END AS "Evidence Type",
    t.selection_id AS "Selection ID", h.glbslct_application AS "Application",
    h.glbslct_creator_id AS "Creator ID", h.glbslct_desc AS "Description",
    h.glbslct_type_ind AS "Raw Type Indicator",
    h.glbslct_activity_date AS "Source Activity Date",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count"
FROM target_selections t
LEFT JOIN general.glbslct h ON h.glbslct_selection = t.selection_id
ORDER BY t.selection_id, h.glbslct_application, h.glbslct_creator_id;
