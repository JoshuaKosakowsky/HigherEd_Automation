/* Term-effective program history, rather than today's program for all years.
   Retain ties at the latest effective term instead of choosing arbitrarily. */
WITH __TL11A_SCOPE_SQL__,
candidates AS (
    SELECT p.tax_year AS extract_tax_year, i.pidm,
           y.term_code, y.term_description,
           s.sgbstdn_term_code_eff AS program_effective_term,
           s.sgbstdn_program_1 AS program_code,
           s.sgbstdn_levl_code AS level_code,
           s.sgbstdn_degc_code_1 AS degree_code,
           DENSE_RANK() OVER (
               PARTITION BY i.pidm, y.term_code
               ORDER BY s.sgbstdn_term_code_eff DESC
           ) AS effective_rank
    FROM identity i CROSS JOIN year_terms y CROSS JOIN params p
    INNER JOIN saturn.sgbstdn s
        ON s.sgbstdn_pidm = i.pidm
       AND s.sgbstdn_term_code_eff <= y.term_code
)
SELECT COUNT(*) OVER () AS extract_row_count,
       extract_tax_year, pidm, term_code, term_description,
       program_effective_term, program_code, level_code, degree_code
FROM candidates WHERE effective_rank = 1
ORDER BY term_code;
