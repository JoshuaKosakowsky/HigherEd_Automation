/* Read-only required-column check for the PP hold review report. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('TAISMGR', 'TBRACCD', 'PIDM'),
        ('TAISMGR', 'TBRACCD', 'AMOUNT'),
        ('TAISMGR', 'TBRACCD', 'DETAIL_CODE'),
        ('TAISMGR', 'TBRACCD', 'BALANCE'),
        ('TAISMGR', 'TBRACCD', 'DUE_DATE'),
        ('TAISMGR', 'TBBDETC', 'DETAIL_CODE'),
        ('TAISMGR', 'TBBDETC', 'TYPE_IND'),
        ('SATURN', 'SGBSTDN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'ID'),
        ('SATURN', 'SPRIDEN', 'FIRST_NAME'),
        ('SATURN', 'SPRIDEN', 'LAST_NAME'),
        ('SATURN', 'SPRIDEN', 'CHANGE_IND'),
        ('SATURN', 'SPRHOLD', 'PIDM'),
        ('SATURN', 'SPRHOLD', 'HLDD_CODE'),
        ('SATURN', 'SPRHOLD', 'FROM_DATE'),
        ('SATURN', 'SPRHOLD', 'TO_DATE'),
        ('GENERAL', 'GOREMAL', 'PIDM'),
        ('GENERAL', 'GOREMAL', 'EMAL_CODE'),
        ('GENERAL', 'GOREMAL', 'EMAIL_ADDRESS'),
        ('GENERAL', 'GOREMAL', 'STATUS_IND'),
        ('GENERAL', 'GOREMAL', 'PREFERRED_IND'),
        ('GENERAL', 'GOREMAL', 'ACTIVITY_DATE'),
        ('SATURN', 'SPRTELE', 'PIDM'),
        ('SATURN', 'SPRTELE', 'SEQNO'),
        ('SATURN', 'SPRTELE', 'PHONE_AREA'),
        ('SATURN', 'SPRTELE', 'PHONE_NUMBER'),
        ('SATURN', 'SPRTELE', 'PHONE_EXT'),
        ('SATURN', 'SPRTELE', 'PRIMARY_IND'),
        ('SATURN', 'SPRTELE', 'STATUS_IND')
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
