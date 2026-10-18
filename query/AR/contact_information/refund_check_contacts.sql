/* Read-only refund-check contacts for manual matching to AP's outstanding list.
   RFND/RFDP feed dates: 200 days ago through today, inclusive.
   This report does not establish whether a check is uncashed, voided, or replaced.
   One student row per RFND account; one RFDP row per distinct borrower suffix.
   Borrower suffixes are preserved as stored, without padding or separators.
   No transaction-level matching, amount totals, or automatic communications.
*/
WITH refund_accounts AS MATERIALIZED (
    SELECT t.tbraccd_pidm AS pidm, t.tbraccd_detail_code AS detail_code,
           MIN(t.tbraccd_feed_date) AS first_feed_date,
           MAX(t.tbraccd_feed_date) AS latest_feed_date
    FROM taismgr.tbraccd t
    WHERE t.tbraccd_detail_code IN ('RFND', 'RFDP')
      AND t.tbraccd_feed_date >= CURRENT_DATE - INTERVAL '200 days'
      AND t.tbraccd_feed_date < CURRENT_DATE + INTERVAL '1 day'
    GROUP BY t.tbraccd_pidm, t.tbraccd_detail_code
),
student_identity AS (
    SELECT s.spriden_pidm AS pidm, s.spriden_id AS cwid,
           s.spriden_first_name AS first_name, s.spriden_last_name AS last_name,
           ROW_NUMBER() OVER (
               PARTITION BY s.spriden_pidm
               ORDER BY s.spriden_id, s.spriden_last_name, s.spriden_first_name
           ) AS identity_rank
    FROM saturn.spriden s
    WHERE s.spriden_change_ind IS NULL
      AND EXISTS (SELECT 1 FROM refund_accounts a WHERE a.pidm = s.spriden_pidm)
),
students AS MATERIALIZED (
    SELECT pidm, cwid, first_name, last_name
    FROM student_identity WHERE identity_rank = 1
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
),
/* Pull all borrower IDs for RFDP accounts; AP identifies the actual payee.
   Do not restrict to the refund's aid year or PLUS-to-student authorization. */
borrower_records AS MATERIALIZED (
    SELECT r.rlrpapp_pidm AS pidm,
           NULLIF(TRIM(CAST(r.rlrpapp_borrower_id_no AS text)), '') AS suffix,
           NULLIF(TRIM(r.rlrpapp_borr_first_name), '') AS first_name,
           NULLIF(TRIM(r.rlrpapp_borr_last_name), '') AS last_name,
           NULLIF(TRIM(r.rlrpapp_borr_phone_no), '') AS phone_number,
           NULLIF(TRIM(r.rlrpapp_borr_email), '') AS email_address,
           r.rlrpapp_activity_date AS activity_date,
           r.rlrpapp_aidy_code AS aid_year
    FROM faismgr.rlrpapp r
    INNER JOIN refund_accounts a ON a.pidm = r.rlrpapp_pidm AND a.detail_code = 'RFDP'
),
borrower_profiles AS (
    SELECT DISTINCT pidm, suffix, first_name, last_name, phone_number, email_address
    FROM borrower_records
),
borrower_versions AS (
    SELECT pidm, suffix, COUNT(*) AS profile_count
    FROM borrower_profiles GROUP BY pidm, suffix
),
ranked_borrowers AS (
    SELECT b.*,
           ROW_NUMBER() OVER (
               PARTITION BY b.pidm, b.suffix
               ORDER BY b.activity_date DESC NULLS LAST, b.aid_year DESC NULLS LAST,
                        b.last_name NULLS LAST, b.first_name NULLS LAST,
                        b.email_address NULLS LAST, b.phone_number NULLS LAST
           ) AS borrower_rank
    FROM borrower_records b
),
recipients AS (
    SELECT a.pidm, s.cwid, a.detail_code, 'Student' AS recipient_type,
           CAST(NULL AS text) AS suffix, CAST(NULL AS text) AS borrower_cwid,
           s.first_name, s.last_name, e.email_address, e.email_type,
           p.phone_number, p.phone_type, 0 AS profile_count,
           a.first_feed_date, a.latest_feed_date
    FROM refund_accounts a
    LEFT JOIN students s ON s.pidm = a.pidm
    LEFT JOIN mines_email e ON e.pidm = a.pidm AND e.contact_rank = 1
    LEFT JOIN contact_phone p ON p.pidm = a.pidm AND p.contact_rank = 1
    WHERE a.detail_code = 'RFND'
    UNION ALL
    SELECT a.pidm, s.cwid, a.detail_code, 'Parent' AS recipient_type,
           b.suffix,
           CASE WHEN NULLIF(TRIM(s.cwid), '') IS NOT NULL AND b.suffix IS NOT NULL
                THEN s.cwid || b.suffix END AS borrower_cwid,
           b.first_name, b.last_name, b.email_address,
           CASE WHEN b.email_address IS NOT NULL THEN 'RLRPAPP' END AS email_type,
           b.phone_number,
           CASE WHEN b.phone_number IS NOT NULL THEN 'RLRPAPP' END AS phone_type,
           COALESCE(v.profile_count, 0) AS profile_count,
           a.first_feed_date, a.latest_feed_date
    FROM refund_accounts a
    LEFT JOIN students s ON s.pidm = a.pidm
    LEFT JOIN ranked_borrowers b ON b.pidm = a.pidm AND b.borrower_rank = 1
    LEFT JOIN borrower_versions v ON v.pidm = b.pidm
        AND (v.suffix = b.suffix OR (v.suffix IS NULL AND b.suffix IS NULL))
    WHERE a.detail_code = 'RFDP'
),
review AS (
    SELECT r.*,
           CASE WHEN NULLIF(TRIM(cwid), '') IS NULL THEN 'Missing student CWID; ' ELSE '' END
           || CASE WHEN recipient_type = 'Parent' AND suffix IS NULL
                   THEN 'Missing borrower suffix; ' ELSE '' END
           || CASE WHEN NULLIF(TRIM(first_name), '') IS NULL
                     OR NULLIF(TRIM(last_name), '') IS NULL
                   THEN 'Missing recipient name; ' ELSE '' END
           || CASE WHEN email_address IS NULL THEN 'Missing email; ' ELSE '' END
           || CASE WHEN phone_number IS NULL THEN 'Missing phone; ' ELSE '' END
           || CASE WHEN profile_count > 1
                   THEN 'Borrower contact records differ; verify selected record; ' ELSE '' END
           AS review_reasons
    FROM recipients r
)
SELECT cwid AS "Student CWID", detail_code AS "Detail Code",
       recipient_type AS "Recipient Type", suffix AS "Borrower Suffix",
       borrower_cwid AS "Borrower CWID", first_name AS "First Name",
       last_name AS "Last Name", email_address AS "Email",
       email_type AS "Email Source", phone_number AS "Phone Number",
       phone_type AS "Phone Source", first_feed_date AS "First Feed Date",
       latest_feed_date AS "Latest Feed Date",
       CASE WHEN review_reasons = '' THEN 'Contacts available'
            ELSE review_reasons END AS "Contact Review",
       COUNT(*) OVER () AS "Report Row Count"
FROM review
ORDER BY cwid NULLS LAST, detail_code, suffix NULLS LAST, pidm;
