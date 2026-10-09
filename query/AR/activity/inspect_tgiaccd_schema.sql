/* Read-only discovery of the actual columns exposed to Insights.
   Use this when TGIACCD display labels do not match replicated Banner fields.
   Return the TBRACCD rows before choosing the feed-document mapping.
*/
SELECT
    table_schema AS "Schema",
    table_name AS "Table",
    column_name AS "Column",
    data_type AS "Data Type"
FROM information_schema.columns
WHERE (UPPER(table_schema) = 'TAISMGR' AND
       UPPER(table_name) IN ('TBRACCD', 'TBBDETC'))
   OR (UPPER(table_schema) = 'SATURN' AND UPPER(table_name) = 'SPRIDEN')
ORDER BY table_schema, table_name, ordinal_position;
