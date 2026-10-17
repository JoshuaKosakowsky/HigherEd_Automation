/* Read-only student contact information lookup; does not identify outstanding checks.
   Shared by the app (TEST/PROD) and staff saved Insights questions.
   Student accounts must have TBBACCT activity in the last eight years.
   Account updates indicate recency, not enrollment or formal active status.
   Include only students whose selected email/phone and contact types are populated.
   Use active UNIV email and usable PR phone, falling back to CELL.
   Email preferred and phone primary indicators do not affect selection.
   Rank identity too so duplicate current records cannot multiply the output.
*/
/* Restrict accounts before ranking identity/contacts. Keep date columns bare
   so the database can use available date indexes; deduplicate control rows. */
WITH recent_accounts AS MATERIALIZED (
    SELECT DISTINCT a.tbbacct_pidm AS pidm
    FROM taismgr.tbbacct a
    WHERE a.tbbacct_activity_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '8 years'
      AND a.tbbacct_activity_date < CURRENT_DATE + INTERVAL '1 day'
),
student_identity AS (
    SELECT
        s.spriden_pidm AS pidm,
        s.spriden_id AS cwid,
        s.spriden_first_name AS first_name,
        s.spriden_last_name AS last_name,
        ROW_NUMBER() OVER (
            PARTITION BY s.spriden_pidm
            ORDER BY s.spriden_id, s.spriden_last_name, s.spriden_first_name
        ) AS identity_rank
    FROM saturn.spriden s
    INNER JOIN recent_accounts a ON a.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
      AND EXISTS (
          SELECT 1 FROM saturn.sgbstdn student
          WHERE student.sgbstdn_pidm = s.spriden_pidm
      )
),
students AS MATERIALIZED (
    SELECT pidm, cwid, first_name, last_name
    FROM student_identity
    WHERE identity_rank = 1
),

/* Rank usable contacts before joining so multiple records cannot fan out. */
mines_email AS (
    SELECT
        e.goremal_pidm AS pidm,
        TRIM(e.goremal_email_address) AS email_address,
        e.goremal_emal_code AS email_type,
        ROW_NUMBER() OVER (
            PARTITION BY e.goremal_pidm
            ORDER BY
                e.goremal_activity_date DESC NULLS LAST,
                e.goremal_email_address,
                e.goremal_emal_code
        ) AS contact_rank
    FROM general.goremal e
    INNER JOIN students s ON s.pidm = e.goremal_pidm
    WHERE e.goremal_emal_code = 'UNIV'
      AND e.goremal_status_ind = 'A'
      AND NULLIF(TRIM(e.goremal_email_address), '') IS NOT NULL
),

contact_phone AS (
    SELECT
        phone.sprtele_pidm AS pidm,
        phone.sprtele_tele_code AS phone_type,
        CASE WHEN NULLIF(TRIM(phone.sprtele_phone_area), '') IS NOT NULL
            THEN '(' || TRIM(phone.sprtele_phone_area) || ') ' ELSE '' END
        || TRIM(phone.sprtele_phone_number)
        || CASE WHEN NULLIF(TRIM(phone.sprtele_phone_ext), '') IS NOT NULL
            THEN ' x' || TRIM(phone.sprtele_phone_ext) ELSE '' END AS phone_number,
        ROW_NUMBER() OVER (
            PARTITION BY phone.sprtele_pidm
            ORDER BY
                CASE WHEN phone.sprtele_tele_code = 'PR' THEN 1 ELSE 2 END,
                phone.sprtele_seqno DESC NULLS LAST,
                phone.sprtele_phone_number,
                phone.sprtele_phone_area,
                phone.sprtele_phone_ext,
                phone.sprtele_tele_code
        ) AS contact_rank
    FROM saturn.sprtele phone
    INNER JOIN students s ON s.pidm = phone.sprtele_pidm
    WHERE phone.sprtele_tele_code IN ('PR', 'CELL')
      AND COALESCE(UPPER(TRIM(phone.sprtele_status_ind)), 'A') <> 'I'
      AND NULLIF(TRIM(phone.sprtele_phone_number), '') IS NOT NULL
)


SELECT
    s.cwid AS "CWID",
    s.first_name AS "First Name",
    s.last_name AS "Last Name",
    email.email_address AS "Mines Email",
    email.email_type AS "Email Type",
    phone.phone_number AS "Phone Number",
    phone.phone_type AS "Phone Type"
FROM students s
INNER JOIN mines_email email
    ON email.pidm = s.pidm AND email.contact_rank = 1
INNER JOIN contact_phone phone
    ON phone.pidm = s.pidm AND phone.contact_rank = 1
WHERE NULLIF(TRIM(email.email_type), '') IS NOT NULL
  AND NULLIF(TRIM(phone.phone_type), '') IS NOT NULL
ORDER BY s.cwid;
