/* Metadata only: discover the payment application table before defining an
   allocation extract. Absence can mean unavailable data or limited visibility. */
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE LOWER(table_name) = 'tbrappl'
ORDER BY table_schema, ordinal_position;
