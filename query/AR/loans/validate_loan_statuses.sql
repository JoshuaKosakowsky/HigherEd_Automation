/* Read-only configuration inventory; no student records. Run after schema validation. */
SELECT
    'Degree award status' AS "Configuration",
    stvdegs_code AS "Code",
    stvdegs_desc AS "Description",
    stvdegs_award_status_ind AS "Indicator"
FROM saturn.stvdegs
UNION ALL
SELECT
    'Third-party withdrawal status',
    stvests_code,
    stvests_desc,
    stvests_third_party_wd_ind
FROM saturn.stvests
ORDER BY "Configuration", "Code";
