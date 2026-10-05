/* Read-only inventory. Resolve every MISSING column before extraction. */
WITH required_columns (table_schema, table_name, column_suffix) AS (
    VALUES
        ('saturn', 'spriden', 'pidm'),
        ('saturn', 'spriden', 'id'),
        ('saturn', 'spriden', 'first_name'),
        ('saturn', 'spriden', 'last_name'),
        ('saturn', 'spriden', 'change_ind'),
        ('saturn', 'stvterm', 'code'),
        ('saturn', 'stvterm', 'desc'),
        ('saturn', 'stvterm', 'start_date'),
        ('saturn', 'stvterm', 'end_date'),
        ('taismgr', 'tbraccd', 'pidm'),
        ('taismgr', 'tbraccd', 'tran_number'),
        ('taismgr', 'tbraccd', 'term_code'),
        ('taismgr', 'tbraccd', 'detail_code'),
        ('taismgr', 'tbraccd', 'amount'),
        ('taismgr', 'tbraccd', 'balance'),
        ('taismgr', 'tbraccd', 'effective_date'),
        ('taismgr', 'tbraccd', 'activity_date'),
        ('taismgr', 'tbraccd', 'entry_date'),
        ('taismgr', 'tbraccd', 'feed_date'),
        ('taismgr', 'tbbdetc', 'detail_code'),
        ('taismgr', 'tbbdetc', 'desc'),
        ('taismgr', 'tbbdetc', 'type_ind'),
        ('taismgr', 'tbbdetc', 'dcat_code'),
        ('saturn', 'sfrstcr', 'pidm'),
        ('saturn', 'sfrstcr', 'term_code'),
        ('saturn', 'sfrstcr', 'crn'),
        ('saturn', 'sfrstcr', 'rsts_code'),
        ('saturn', 'sfrstcr', 'credit_hr'),
        ('saturn', 'sfrstcr', 'bill_hr'),
        ('saturn', 'stvrsts', 'code'),
        ('saturn', 'stvrsts', 'incl_sect_enrl'),
        ('saturn', 'ssbsect', 'term_code'),
        ('saturn', 'ssbsect', 'crn'),
        ('saturn', 'ssbsect', 'subj_code'),
        ('saturn', 'ssbsect', 'crse_numb'),
        ('saturn', 'ssbsect', 'ptrm_code'),
        ('saturn', 'ssbsect', 'ptrm_start_date'),
        ('saturn', 'ssbsect', 'ptrm_end_date'),
        ('saturn', 'sobptrm', 'term_code'),
        ('saturn', 'sobptrm', 'ptrm_code'),
        ('saturn', 'sobptrm', 'desc'),
        ('saturn', 'sobptrm', 'start_date'),
        ('saturn', 'sobptrm', 'end_date'),
        ('saturn', 'sgbstdn', 'pidm'),
        ('saturn', 'sgbstdn', 'term_code_eff'),
        ('saturn', 'sgbstdn', 'program_1'),
        ('saturn', 'sgbstdn', 'levl_code'),
        ('saturn', 'sgbstdn', 'degc_code_1')
)
SELECT required.table_schema AS expected_schema,
       required.table_name AS expected_table,
       required.table_name || '_' || required.column_suffix AS expected_column,
       available.data_type,
       CASE WHEN available.column_name IS NULL THEN 'MISSING' ELSE 'FOUND' END
           AS validation_status
FROM required_columns required
LEFT JOIN information_schema.columns available
    ON LOWER(available.table_schema) = required.table_schema
   AND LOWER(available.table_name) = required.table_name
   AND LOWER(available.column_name) = required.table_name || '_' || required.column_suffix
ORDER BY expected_schema, expected_table, expected_column;
