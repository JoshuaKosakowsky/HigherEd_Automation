/* Read-only RH delinquency review, using the refund workflow's TBBACCT source.
   Account activity is not an RH assignment date: do not use it to age the code.
   Include every RH student regardless of balance, enrollment, or other holds.
   Aggregate RH control rows before joining identity to preserve one row/student.
*/
WITH rh_accounts AS (
    SELECT
        a.tbbacct_pidm AS pidm,
        CAST(MAX(a.tbbacct_activity_date) AS date) AS account_activity_date
    FROM taismgr.tbbacct a
    WHERE UPPER(TRIM(a.tbbacct_deli_code)) = 'RH'
      AND EXISTS (
          SELECT 1 FROM saturn.sgbstdn student
          WHERE student.sgbstdn_pidm = a.tbbacct_pidm
      )
    GROUP BY a.tbbacct_pidm
)
SELECT
    s.spriden_id AS "CWID",
    s.spriden_first_name AS "First Name",
    s.spriden_last_name AS "Last Name",
    'RH' AS "Delinquency Code",
    a.account_activity_date AS "Account Activity Date",
    COUNT(*) OVER () AS "Report Row Count"
FROM rh_accounts a
JOIN saturn.spriden s
    ON s.spriden_pidm = a.pidm
   AND s.spriden_change_ind IS NULL
ORDER BY s.spriden_id;
