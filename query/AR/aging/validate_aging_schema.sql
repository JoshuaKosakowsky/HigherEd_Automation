/* Read-only schema inventory for the receivable aging dashboard. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'ACCOUNT_UID'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'ID'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'BALANCE'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'BILL_DATE'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'DUE_DATE'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT_DETAIL', 'EFFECTIVE_DATE'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT', 'ACCOUNT_UID'),
        ('ODSMGR', 'RECEIVABLE_ACCOUNT', 'ID')
)

SELECT
    r.table_schema AS "Expected Schema",
    r.table_name AS "Expected Table",
    r.column_name AS "Expected Column",
    c.data_type AS "Data Type",
    CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'FOUND' END
        AS "Validation Status"
FROM required_columns r
LEFT JOIN information_schema.columns c
    ON UPPER(c.table_schema) = r.table_schema
   AND UPPER(c.table_name) = r.table_name
   AND UPPER(c.column_name) = r.column_name
ORDER BY
    r.table_name,
    r.column_name;
