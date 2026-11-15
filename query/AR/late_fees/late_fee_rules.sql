/* Read-only definition evidence, not an eligibility query or SQL executor.
   Run validate_late_fee_schema.sql first in the chosen Insights database.
   Include every visible application/creator for the named selections; ownership
   of the shared waiver lists must not be restricted to one staff member.
   Preserve parentheses, key/line order, joins and application-level rules.
   A generated set-operation result can legitimately have no selection rules.
*/
WITH target_selections (selection_id) AS (
    VALUES
        ('AR_TERM_BALANCE'),
        ('AR_PP,CO,TO,WO_HOLDS'),
        ('AR_LATEFEES_1'), ('AR_LATEFEES_2'), ('AR_LATEFEES_3'),
        ('AR_LATEFEES_4'), ('AR_LATEFEES_5'), ('AR_LATEFEES_6'),
        ('AR_LATEFEES_FINAL'), ('AR_WAIVE_MANUAL_LATEFEES')
), target_applications AS (
    SELECT h.glbslct_application AS application
    FROM general.glbslct h
    JOIN target_selections t ON t.selection_id = h.glbslct_selection
    UNION
    SELECT f.glrsfrm_application
    FROM general.glrsfrm f
    JOIN target_selections t ON t.selection_id = f.glrsfrm_selection
    UNION
    SELECT r.glrslct_application
    FROM general.glrslct r
    JOIN target_selections t ON t.selection_id = r.glrslct_selection
), evidence AS (
    SELECT
        CASE WHEN h.glbslct_selection IS NULL THEN 'MISSING_HEADER'
             ELSE 'SELECTION_HEADER' END AS evidence_type,
        h.glbslct_application AS application, t.selection_id,
        h.glbslct_creator_id AS creator_id,
        h.glbslct_desc AS description,
        h.glbslct_type_ind AS type_indicator,
        CAST(NULL AS text) AS select_clause, CAST(NULL AS text) AS from_clause,
        CAST(NULL AS text) AS group_by_clause, CAST(NULL AS text) AS order_by_clause,
        CAST(NULL AS numeric) AS key_no, CAST(NULL AS numeric) AS line_no,
        CAST(NULL AS text) AS open_paren, CAST(NULL AS text) AS data_element,
        CAST(NULL AS text) AS operator, CAST(NULL AS text) AS rule_value,
        CAST(NULL AS text) AS close_paren, CAST(NULL AS text) AS separator,
        h.glbslct_activity_date AS activity_date
    FROM target_selections t
    LEFT JOIN general.glbslct h ON h.glbslct_selection = t.selection_id

    UNION ALL
    SELECT
        'SELECT_FROM', f.glrsfrm_application, f.glrsfrm_selection, f.glrsfrm_creator_id,
        NULL, NULL, f.glrsfrm_select_clause, f.glrsfrm_from_clause,
        f.glrsfrm_group_by, f.glrsfrm_order_by,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        f.glrsfrm_activity_date
    FROM general.glrsfrm f
    JOIN target_selections t ON t.selection_id = f.glrsfrm_selection

    UNION ALL
    SELECT
        'SELECTION_RULE', r.glrslct_application, r.glrslct_selection, r.glrslct_creator_id,
        NULL, NULL, NULL, NULL, NULL, NULL,
        r.glrslct_key_no, r.glrslct_line_no, r.glrslct_open_paren,
        r.glrslct_data_element, r.glrslct_operator, r.glrslct_value,
        r.glrslct_close_paren, r.glrslct_separator, r.glrslct_activity_date
    FROM general.glrslct r
    JOIN target_selections t ON t.selection_id = r.glrslct_selection

    UNION ALL
    SELECT
        CASE WHEN a.glrappl_application IS NULL THEN 'NO_VISIBLE_APPLICATION_RULES'
             ELSE 'APPLICATION_RULE' END,
        p.application, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        a.glrappl_key_no, a.glrappl_line_no, a.glrappl_open_paren,
        a.glrappl_data_element, a.glrappl_operator, a.glrappl_value,
        a.glrappl_close_paren, a.glrappl_separator, a.glrappl_activity_date
    FROM target_applications p
    LEFT JOIN general.glrappl a ON a.glrappl_application = p.application
)
SELECT
    evidence_type AS "Evidence Type", application AS "Application",
    selection_id AS "Selection ID", creator_id AS "Creator ID",
    description AS "Description", type_indicator AS "Raw Type Indicator",
    select_clause AS "Select Clause", from_clause AS "From Clause",
    group_by_clause AS "Group By Clause", order_by_clause AS "Order By Clause",
    key_no AS "Key No", line_no AS "Line No", open_paren AS "Open Paren",
    data_element AS "Data Element", operator AS "Operator", rule_value AS "Value",
    close_paren AS "Close Paren", separator AS "And/Or",
    activity_date AS "Source Activity Date",
    CURRENT_TIMESTAMP AS "Extracted At", COUNT(*) OVER () AS "Report Row Count"
FROM evidence
ORDER BY application, selection_id, creator_id,
    CASE evidence_type WHEN 'SELECTION_HEADER' THEN 1 WHEN 'MISSING_HEADER' THEN 1
         WHEN 'SELECT_FROM' THEN 2 ELSE 3 END,
    key_no, line_no;
