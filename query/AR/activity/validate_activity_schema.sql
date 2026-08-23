/* Read-only schema inventory for the AR activity reports. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('TAISMGR', 'TBRACCD', 'PIDM'),
        ('TAISMGR', 'TBRACCD', 'TERM_CODE'),
        ('TAISMGR', 'TBRACCD', 'DETAIL_CODE'),
        ('TAISMGR', 'TBRACCD', 'AMOUNT'),
        ('TAISMGR', 'TBRACCD', 'BALANCE'),
        ('TAISMGR', 'TBRACCD', 'FEED_DATE'),
        ('TAISMGR', 'TBRACCD', 'TRAN_NUMBER'),
        ('TAISMGR', 'TBBDETC', 'DETAIL_CODE'),
        ('TAISMGR', 'TBBDETC', 'DESC'),
        ('TAISMGR', 'TBBDETC', 'DCAT_CODE'),
        ('TAISMGR', 'TBBDETC', 'TYPE_IND'),
        ('TAISMGR', 'TBBDETC', 'PRIORITY'),
        ('SATURN', 'SPRIDEN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'ID'),
        ('SATURN', 'SPRIDEN', 'FIRST_NAME'),
        ('SATURN', 'SPRIDEN', 'LAST_NAME'),
        ('SATURN', 'SPRIDEN', 'CHANGE_IND')
)

SELECT
    r.table_schema AS "Expected Schema",
    r.table_name AS "Expected Table",
    CONCAT(LOWER(r.table_name), '_', LOWER(r.column_name))
        AS "Expected Banner Column",
    c.data_type AS "Data Type",
    CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'FOUND' END
        AS "Validation Status"
FROM required_columns r
LEFT JOIN information_schema.columns c
    ON UPPER(c.table_schema) = r.table_schema
   AND UPPER(c.table_name) = r.table_name
   AND UPPER(c.column_name) = CONCAT(r.table_name, '_', r.column_name)
ORDER BY
    r.table_name,
    r.column_name;
