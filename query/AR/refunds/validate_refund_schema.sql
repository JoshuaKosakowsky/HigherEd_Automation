/* Read-only schema inventory for refund review and refund-hold diagnostics. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('TAISMGR', 'TBRACCD', 'PIDM'),
        ('TAISMGR', 'TBRACCD', 'TERM_CODE'),
        ('TAISMGR', 'TBRACCD', 'AIDY_CODE'),
        ('TAISMGR', 'TBRACCD', 'TRAN_NUMBER'),
        ('TAISMGR', 'TBRACCD', 'DETAIL_CODE'),
        ('TAISMGR', 'TBRACCD', 'AMOUNT'),
        ('TAISMGR', 'TBRACCD', 'BALANCE'),
        ('TAISMGR', 'TBRACCD', 'EFFECTIVE_DATE'),
        ('TAISMGR', 'TBRACCD', 'ACTIVITY_DATE'),
        ('TAISMGR', 'TBBDETC', 'DETAIL_CODE'),
        ('TAISMGR', 'TBBDETC', 'DESC'),
        ('TAISMGR', 'TBBDETC', 'TYPE_IND'),
        ('TAISMGR', 'TBBDETC', 'PRIORITY'),
        ('TAISMGR', 'TBBACCT', 'PIDM'),
        ('TAISMGR', 'TBBACCT', 'DELI_CODE'),
        ('TAISMGR', 'TBBACCT', 'REFUND_IND'),
        ('TAISMGR', 'TBBACCT', 'ACTIVITY_DATE'),
        ('SATURN', 'SPRIDEN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'ID'),
        ('SATURN', 'SPRIDEN', 'LAST_NAME'),
        ('SATURN', 'SPRIDEN', 'FIRST_NAME'),
        ('SATURN', 'SPRIDEN', 'CHANGE_IND'),
        ('SATURN', 'SPBPERS', 'PIDM'),
        ('SATURN', 'SPBPERS', 'DEAD_IND'),
        ('SATURN', 'SPBPERS', 'DEAD_DATE'),
        ('SATURN', 'SPBPERS', 'CONFID_IND'),
        ('SATURN', 'SPBPERS', 'ACTIVITY_DATE'),
        ('SATURN', 'SPRHOLD', 'PIDM'),
        ('SATURN', 'SPRHOLD', 'HLDD_CODE'),
        ('SATURN', 'SPRHOLD', 'TO_DATE'),
        ('SATURN', 'SPRHOLD', 'ACTIVITY_DATE'),
        ('FAISMGR', 'RLRPAPP', 'PIDM'),
        ('FAISMGR', 'RLRPAPP', 'AIDY_CODE'),
        ('FAISMGR', 'RLRPAPP', 'PLUS_TO_STUDENT'),
        ('FAISMGR', 'RLRPAPP', 'ACTIVITY_DATE')
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
    r.table_schema,
    r.table_name,
    r.column_name;
