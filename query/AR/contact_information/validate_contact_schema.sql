/* Read-only schema inventory for the contact-information lookup. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('GENERAL', 'GOREMAL', 'PIDM'),
        ('GENERAL', 'GOREMAL', 'EMAL_CODE'),
        ('GENERAL', 'GOREMAL', 'EMAIL_ADDRESS'),
        ('GENERAL', 'GOREMAL', 'STATUS_IND'),
        ('GENERAL', 'GOREMAL', 'PREFERRED_IND'),
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
        ('SATURN', 'SPRTELE', 'PRIMARY_IND')
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
   AND (
       UPPER(c.table_schema) = r.table_schema
       OR r.table_name = 'GOREMAL'
   )
ORDER BY
    r.table_name,
    r.column_name;
