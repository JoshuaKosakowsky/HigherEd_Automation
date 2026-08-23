/*
Sponsor Report Schema Inventory

Run this first in Insights. It is read-only and returns no student/account data.
Compare the result with the required columns documented in README.md before
running sponsored_student_summary.sql.
*/

SELECT
    c.table_schema AS "Schema",
    c.table_name AS "Table",
    c.ordinal_position AS "Column Position",
    c.column_name AS "Column",
    c.data_type AS "Data Type"
FROM information_schema.columns c
WHERE UPPER(c.table_name) IN (
    'TBBCSTU',
    'TBBCONT',
    'TBRACCD',
    'TBBDETC',
    'SPRIDEN',
    'STVTERM'
)
ORDER BY
    UPPER(c.table_name),
    c.ordinal_position;
