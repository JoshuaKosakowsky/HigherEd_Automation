/* Read-only schema inventory for the institutional-loan enrollment report. */

WITH required_columns (table_schema, table_name, column_name) AS (
    VALUES
        ('SATURN', 'SFRSTCR', 'PIDM'),
        ('SATURN', 'SFRSTCR', 'TERM_CODE'),
        ('SATURN', 'SFRSTCR', 'RSTS_CODE'),
        ('SATURN', 'SFRSTCR', 'CREDIT_HR'),
        ('SATURN', 'SFRSTCR', 'BILL_HR'),
        ('SATURN', 'STVRSTS', 'CODE'),
        ('SATURN', 'STVRSTS', 'INCL_SECT_ENRL'),
        ('SATURN', 'SGBSTDN', 'PIDM'),
        ('SATURN', 'SGBSTDN', 'TERM_CODE_EFF'),
        ('SATURN', 'SGBSTDN', 'LEVL_CODE'),
        ('SATURN', 'SGBSTDN', 'STYP_CODE'),
        ('SATURN', 'SGBSTDN', 'EXP_GRAD_DATE'),
        ('SATURN', 'SHRLGPA', 'PIDM'),
        ('SATURN', 'SHRLGPA', 'LEVL_CODE'),
        ('SATURN', 'SHRLGPA', 'GPA_TYPE_IND'),
        ('SATURN', 'SHRLGPA', 'HOURS_EARNED'),
        ('SATURN', 'STVSTYP', 'CODE'),
        ('SATURN', 'STVSTYP', 'DESC'),
        ('SATURN', 'SPRIDEN', 'PIDM'),
        ('SATURN', 'SPRIDEN', 'ID'),
        ('SATURN', 'SPRIDEN', 'LAST_NAME'),
        ('SATURN', 'SPRIDEN', 'FIRST_NAME'),
        ('SATURN', 'SPRIDEN', 'CHANGE_IND'),
        ('SATURN', 'SPRADDR', 'PIDM'),
        ('SATURN', 'SPRADDR', 'ATYP_CODE'),
        ('SATURN', 'SPRADDR', 'SEQNO'),
        ('SATURN', 'SPRADDR', 'STREET_LINE1'),
        ('SATURN', 'SPRADDR', 'STREET_LINE2'),
        ('SATURN', 'SPRADDR', 'STREET_LINE3'),
        ('SATURN', 'SPRADDR', 'CITY'),
        ('SATURN', 'SPRADDR', 'STAT_CODE'),
        ('SATURN', 'SPRADDR', 'ZIP'),
        ('SATURN', 'SPRADDR', 'STATUS_IND'),
        ('SATURN', 'SPRADDR', 'FROM_DATE'),
        ('SATURN', 'SPRADDR', 'TO_DATE'),
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
        ('SATURN', 'SPRTELE', 'STATUS_IND'),
        ('TAISMGR', 'TBRACCD', 'PIDM'),
        ('TAISMGR', 'TBRACCD', 'TERM_CODE'),
        ('TAISMGR', 'TBRACCD', 'DETAIL_CODE'),
        ('TAISMGR', 'TBRACCD', 'AMOUNT'),
        ('TAISMGR', 'TBRACCD', 'ACTIVITY_DATE'),
        ('TAISMGR', 'TBBDETC', 'DETAIL_CODE'),
        ('TAISMGR', 'TBBDETC', 'DESC'),
        ('TAISMGR', 'TBBDETC', 'TYPE_IND')
)

SELECT
    required.table_schema AS "Expected Schema",
    required.table_name AS "Expected Table",
    CONCAT(LOWER(required.table_name), '_', LOWER(required.column_name))
        AS "Expected Banner Column",
    available.table_schema AS "Available Schema",
    available.data_type AS "Data Type",
    CASE
        WHEN available.column_name IS NULL THEN 'MISSING'
        ELSE 'FOUND'
    END AS "Validation Status"
FROM required_columns required
LEFT JOIN information_schema.columns available
    ON UPPER(available.table_schema) = required.table_schema
   AND UPPER(available.table_name) = required.table_name
   AND UPPER(available.column_name) = CONCAT(
       required.table_name,
       '_',
       required.column_name
   )
ORDER BY
    required.table_schema,
    required.table_name,
    required.column_name;
