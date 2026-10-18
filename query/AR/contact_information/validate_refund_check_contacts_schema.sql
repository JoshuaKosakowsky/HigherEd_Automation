/* Read-only schema inventory for refund-check contacts (including RLRPAPP borrower fields). */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('TAISMGR', 'TBRACCD', 'PIDM'),
        ('TAISMGR', 'TBRACCD', 'DETAIL_CODE'),
        ('TAISMGR', 'TBRACCD', 'FEED_DATE'),
        ('FAISMGR', 'RLRPAPP', 'PIDM'),
        ('FAISMGR', 'RLRPAPP', 'BORROWER_ID_NO'),
        ('FAISMGR', 'RLRPAPP', 'BORR_FIRST_NAME'),
        ('FAISMGR', 'RLRPAPP', 'BORR_LAST_NAME'),
        ('FAISMGR', 'RLRPAPP', 'BORR_PHONE_NO'),
        ('FAISMGR', 'RLRPAPP', 'BORR_EMAIL'),
        ('FAISMGR', 'RLRPAPP', 'ACTIVITY_DATE'),
        ('FAISMGR', 'RLRPAPP', 'AIDY_CODE'),
        ('GENERAL', 'GOREMAL', 'PIDM'),
        ('GENERAL', 'GOREMAL', 'EMAL_CODE'),
        ('GENERAL', 'GOREMAL', 'EMAIL_ADDRESS'),
        ('GENERAL', 'GOREMAL', 'STATUS_IND'),
        ('GENERAL', 'GOREMAL', 'ACTIVITY_DATE'),
        ('SATURN', 'SPRIDEN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'ID'),
        ('SATURN', 'SPRIDEN', 'FIRST_NAME'),
        ('SATURN', 'SPRIDEN', 'LAST_NAME'),
        ('SATURN', 'SPRIDEN', 'CHANGE_IND'),
        ('SATURN', 'SPRTELE', 'PIDM'),
        ('SATURN', 'SPRTELE', 'TELE_CODE'),
        ('SATURN', 'SPRTELE', 'PHONE_AREA'),
        ('SATURN', 'SPRTELE', 'PHONE_NUMBER'),
        ('SATURN', 'SPRTELE', 'STATUS_IND'),
        ('SATURN', 'SPRTELE', 'SEQNO'),
        ('SATURN', 'SPRTELE', 'PHONE_EXT')
)

SELECT
    r.table_schema AS "Expected Schema",
    r.table_name AS "Expected Table",
    CONCAT(LOWER(r.table_name), '_', LOWER(r.column_name))
        AS "Expected Banner Column",
    c.table_schema AS "Available Schema",
    c.data_type AS "Data Type",
    CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'FOUND' END
        AS "Validation Status"
FROM required_columns r
LEFT JOIN information_schema.columns c
    ON UPPER(c.table_name) = r.table_name
   AND UPPER(c.column_name) = CONCAT(r.table_name, '_', r.column_name)
   AND UPPER(c.table_schema) = r.table_schema
ORDER BY
    r.table_name,
    r.column_name;
