/* Optional, read-only compiled-definition evidence. Requires GLRCMPL to be
   exposed in this Insights database (see schema inventory). Returned SQL is
   evidence ONLY: do not execute it here. Oracle syntax and dynamic parameters
   may need translation; compilation does not prove a successful job run.
   Include all visible applications/creators, keeping each definition's chunks
   together. A missing-row marker has no assumed application or creator.
*/
WITH target_selections (selection_id) AS (
    VALUES
        ('AR_TERM_BALANCE'), ('AR_PP,CO,TO,WO_HOLDS'),
        ('AR_LATEFEES_1'), ('AR_LATEFEES_2'), ('AR_LATEFEES_3'),
        ('AR_LATEFEES_4'), ('AR_LATEFEES_5'), ('AR_LATEFEES_6'),
        ('AR_LATEFEES_FINAL'), ('AR_WAIVE_MANUAL_LATEFEES')
)
SELECT
    CASE WHEN c.glrcmpl_vrbl_or_slct IS NULL THEN 'NO_VISIBLE_COMPILED_ROWS'
         ELSE 'COMPILED_ROW' END AS "Evidence Type",
    c.glrcmpl_application AS "Application", t.selection_id AS "Selection ID",
    c.glrcmpl_creator_id AS "Creator ID", c.glrcmpl_seq_no AS "Sequence No",
    c.glrcmpl_sub_seq_no AS "Subsequence No",
    c.glrcmpl_sql_length AS "SQL Length",
    CAST(c.glrcmpl_sql_statement AS text) AS "SQL Statement",
    c.glrcmpl_sql_parms AS "SQL Parameters",
    c.glrcmpl_activity_date AS "Source Activity Date",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count"
FROM target_selections t
LEFT JOIN general.glrcmpl c ON c.glrcmpl_vrbl_or_slct = t.selection_id
ORDER BY c.glrcmpl_application, t.selection_id, c.glrcmpl_creator_id,
    c.glrcmpl_seq_no, c.glrcmpl_sub_seq_no;
