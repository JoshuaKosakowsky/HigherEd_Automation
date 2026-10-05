/* API template. CWID and year are validated before substitution. */
params AS (
    SELECT __CWID__::text AS cwid, __TAX_YEAR__::integer AS tax_year
),
identity AS (
    SELECT i.spriden_pidm AS pidm, i.spriden_id AS cwid,
           i.spriden_first_name AS first_name, i.spriden_last_name AS last_name
    FROM saturn.spriden i
    CROSS JOIN params p
    WHERE i.spriden_id = p.cwid AND i.spriden_change_ind IS NULL
),
year_terms AS (
    SELECT t.stvterm_code AS term_code, t.stvterm_desc AS term_description,
           t.stvterm_start_date AS term_start_date,
           t.stvterm_end_date AS term_end_date
    FROM saturn.stvterm t
    CROSS JOIN params p
    -- Keep code-year terms even if calendar dates are absent. These are
    -- candidates for review, not a final determination of course eligibility.
    WHERE t.stvterm_code LIKE p.tax_year::text || '%'
       OR (t.stvterm_start_date < MAKE_DATE(p.tax_year + 1, 1, 1)
           AND t.stvterm_end_date >= MAKE_DATE(p.tax_year, 1, 1))
)
