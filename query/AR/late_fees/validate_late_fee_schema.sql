/* Read-only schema check. Safe to run before referencing any Banner table.
   FOUND means the column is visible in metadata, not that data is current.
   Resolve MISSING fields for the query you intend to use. GLRCMPL is optional.
   Other schemas with the same table/column are shown for mapping review;
   neither their permissions nor their equivalence is assumed.
*/
WITH required_columns (used_by, table_schema, table_name, column_name) AS (
    VALUES
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_APPLICATION'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_SELECTION'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_CREATOR_ID'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_USER_ID'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_KEY'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_ACTIVITY_DATE'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_SYS_IND'),
        ('Populations and comparison', 'GENERAL', 'GLBEXTR', 'GLBEXTR_SLCT_IND'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_APPLICATION'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_SELECTION'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_CREATOR_ID'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_DESC'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_TYPE_IND'),
        ('Rules', 'GENERAL', 'GLBSLCT', 'GLBSLCT_ACTIVITY_DATE'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_APPLICATION'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_SELECTION'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_CREATOR_ID'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_SELECT_CLAUSE'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_FROM_CLAUSE'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_ORDER_BY'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_GROUP_BY'),
        ('Rules', 'GENERAL', 'GLRSFRM', 'GLRSFRM_ACTIVITY_DATE'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_APPLICATION'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_SELECTION'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_CREATOR_ID'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_KEY_NO'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_LINE_NO'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_DATA_ELEMENT'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_OPERATOR'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_VALUE'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_OPEN_PAREN'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_CLOSE_PAREN'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_SEPARATOR'),
        ('Rules', 'GENERAL', 'GLRSLCT', 'GLRSLCT_ACTIVITY_DATE'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_APPLICATION'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_KEY_NO'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_LINE_NO'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_DATA_ELEMENT'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_OPERATOR'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_VALUE'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_OPEN_PAREN'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_CLOSE_PAREN'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_SEPARATOR'),
        ('Rules', 'GENERAL', 'GLRAPPL', 'GLRAPPL_ACTIVITY_DATE'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_APPLICATION'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_VRBL_OR_SLCT'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_CREATOR_ID'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_SEQ_NO'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_SUB_SEQ_NO'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_SQL_LENGTH'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_SQL_STATEMENT'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_SQL_PARMS'),
        ('Optional compiled SQL', 'GENERAL', 'GLRCMPL', 'GLRCMPL_ACTIVITY_DATE'),
        ('Student review', 'SATURN', 'SPRIDEN', 'SPRIDEN_PIDM'),
        ('Student review', 'SATURN', 'SPRIDEN', 'SPRIDEN_ID'),
        ('Student review', 'SATURN', 'SPRIDEN', 'SPRIDEN_FIRST_NAME'),
        ('Student review', 'SATURN', 'SPRIDEN', 'SPRIDEN_LAST_NAME'),
        ('Student review', 'SATURN', 'SPRIDEN', 'SPRIDEN_CHANGE_IND'),
        ('Student review', 'GENERAL', 'GOREMAL', 'GOREMAL_PIDM'),
        ('Student review', 'GENERAL', 'GOREMAL', 'GOREMAL_EMAL_CODE'),
        ('Student review', 'GENERAL', 'GOREMAL', 'GOREMAL_EMAIL_ADDRESS'),
        ('Student review', 'GENERAL', 'GOREMAL', 'GOREMAL_STATUS_IND'),
        ('Student review', 'GENERAL', 'GOREMAL', 'GOREMAL_ACTIVITY_DATE'),
        ('Student review', 'TAISMGR', 'TBRACCD', 'TBRACCD_PIDM'),
        ('Student review', 'TAISMGR', 'TBRACCD', 'TBRACCD_TERM_CODE'),
        ('Student review', 'TAISMGR', 'TBRACCD', 'TBRACCD_DETAIL_CODE'),
        ('Student review', 'TAISMGR', 'TBRACCD', 'TBRACCD_AMOUNT'),
        ('Student review', 'TAISMGR', 'TBRACCD', 'TBRACCD_BALANCE'),
        ('Student review', 'TAISMGR', 'TBBDETC', 'TBBDETC_DETAIL_CODE'),
        ('Student review', 'TAISMGR', 'TBBDETC', 'TBBDETC_TYPE_IND'),
        ('Student review', 'SATURN', 'SPRHOLD', 'SPRHOLD_PIDM'),
        ('Student review', 'SATURN', 'SPRHOLD', 'SPRHOLD_HLDD_CODE'),
        ('Student review', 'SATURN', 'SPRHOLD', 'SPRHOLD_FROM_DATE'),
        ('Student review', 'SATURN', 'SPRHOLD', 'SPRHOLD_TO_DATE')
)
SELECT
    r.used_by AS "Used By", r.table_schema AS "Expected Schema",
    r.table_name AS "Expected Table", LOWER(r.column_name) AS "Expected Column",
    CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'FOUND' END AS "Validation Status",
    c.data_type AS "Data Type",
    (SELECT STRING_AGG(DISTINCT a.table_schema, ', ' ORDER BY a.table_schema)
     FROM information_schema.columns a
     WHERE UPPER(a.table_name) = r.table_name
       AND UPPER(a.column_name) = r.column_name
    ) AS "Schemas With This Column"
FROM required_columns r
LEFT JOIN information_schema.columns c
  ON UPPER(c.table_schema) = r.table_schema
 AND UPPER(c.table_name) = r.table_name
 AND UPPER(c.column_name) = r.column_name
ORDER BY r.used_by, r.table_name, r.column_name;
