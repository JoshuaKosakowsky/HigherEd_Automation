-- Safe proof of concept using Banner term reference data rather than student data.
SELECT
    stvterm_code,
    stvterm_desc,
    stvterm_start_date,
    stvterm_end_date
FROM stvterm
ORDER BY stvterm_code DESC
LIMIT 10;
