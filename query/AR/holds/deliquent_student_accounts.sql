/*
Deliquent student accounts: net balance owed without an active PP hold.
Banner Insights (PostgreSQL-flavored SQL); read-only.

Amt = all-term charges minus payments/credits, rounded to cents. Credits in
other terms offset charges. Past Due Amt sums positive remaining charge
balances with due dates before today; it relies on Banner payment application.
Missing charge balances or unpaid-charge due dates make Past Due Amt NULL.
Student = any SGBSTDN record, including former students. No enrollment filter.
PP is active when FROM_DATE <= today and TO_DATE > today (date-only).
A NULL start is treated as already started. A NULL end does not meet the
requested strict end-date condition; validate local NULL-date conventions.
Accounts with unknown detail types or missing amounts are excluded because
their net balance cannot be calculated reliably. Review data quality first.
*/

WITH account_balances AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        ROUND(SUM(CASE UPPER(TRIM(d.tbbdetc_type_ind))
            WHEN 'C' THEN t.tbraccd_amount
            WHEN 'P' THEN -t.tbraccd_amount
        END), 2) AS amount_owed,
        CASE WHEN SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
             AND (t.tbraccd_balance IS NULL
                  OR (t.tbraccd_balance > 0 AND t.tbraccd_due_date IS NULL))
            THEN 1 ELSE 0
        END) > 0 THEN NULL
        ELSE ROUND(SUM(CASE
            WHEN UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
             AND t.tbraccd_balance > 0
             AND CAST(t.tbraccd_due_date AS date) < CURRENT_DATE
            THEN t.tbraccd_balance ELSE 0
        END), 2) END AS past_due_amount
    FROM taismgr.tbraccd t
    LEFT JOIN taismgr.tbbdetc d
        ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    WHERE EXISTS (
        SELECT 1
        FROM saturn.sgbstdn student
        WHERE student.sgbstdn_pidm = t.tbraccd_pidm
    )
    GROUP BY t.tbraccd_pidm
    HAVING SUM(CASE
        WHEN d.tbbdetc_type_ind IS NULL
          OR UPPER(TRIM(d.tbbdetc_type_ind)) NOT IN ('C', 'P')
          OR t.tbraccd_amount IS NULL THEN 1
        ELSE 0
    END) = 0
),

/* Rank contacts before joining so duplicate preference flags cannot fan out. */
preferred_email AS (
    SELECT
        e.goremal_pidm AS pidm,
        TRIM(e.goremal_email_address) AS email_address,
        ROW_NUMBER() OVER (
            PARTITION BY e.goremal_pidm
            ORDER BY
                CASE WHEN e.goremal_emal_code = 'UNIV' THEN 1 ELSE 2 END,
                e.goremal_activity_date DESC NULLS LAST,
                e.goremal_email_address,
                e.goremal_emal_code
        ) AS contact_rank
    FROM general.goremal e
    INNER JOIN account_balances b ON b.pidm = e.goremal_pidm
    WHERE e.goremal_preferred_ind = 'Y'
      AND e.goremal_status_ind = 'A'
      AND NULLIF(TRIM(e.goremal_email_address), '') IS NOT NULL
),

primary_phone AS (
    SELECT
        phone.sprtele_pidm AS pidm,
        CASE WHEN NULLIF(TRIM(phone.sprtele_phone_area), '') IS NOT NULL
            THEN '(' || TRIM(phone.sprtele_phone_area) || ') ' ELSE '' END
        || TRIM(phone.sprtele_phone_number)
        || CASE WHEN NULLIF(TRIM(phone.sprtele_phone_ext), '') IS NOT NULL
            THEN ' x' || TRIM(phone.sprtele_phone_ext) ELSE '' END AS phone_number,
        ROW_NUMBER() OVER (
            PARTITION BY phone.sprtele_pidm
            ORDER BY phone.sprtele_seqno DESC NULLS LAST,
                phone.sprtele_phone_number,
                phone.sprtele_phone_area,
                phone.sprtele_phone_ext
        ) AS contact_rank
    FROM saturn.sprtele phone
    INNER JOIN account_balances b ON b.pidm = phone.sprtele_pidm
    WHERE phone.sprtele_primary_ind = 'Y'
      AND COALESCE(UPPER(TRIM(phone.sprtele_status_ind)), 'A') <> 'I'
      AND NULLIF(TRIM(phone.sprtele_phone_number), '') IS NOT NULL
)

SELECT
    s.spriden_id AS "CWID",
    s.spriden_first_name AS "First Name",
    s.spriden_last_name AS "Last Name",
    b.amount_owed AS "Amt",
    b.past_due_amount AS "Past Due Amt",
    email.email_address AS "Preferred Email",
    phone.phone_number AS "Preferred Phone"
FROM account_balances b
INNER JOIN saturn.spriden s
    ON s.spriden_pidm = b.pidm
   AND s.spriden_change_ind IS NULL
LEFT JOIN preferred_email email
    ON email.pidm = b.pidm AND email.contact_rank = 1
LEFT JOIN primary_phone phone
    ON phone.pidm = b.pidm AND phone.contact_rank = 1
WHERE b.amount_owed > 0
  AND NOT EXISTS (
      SELECT 1
      FROM saturn.sprhold h
      WHERE h.sprhold_pidm = b.pidm
        AND UPPER(TRIM(h.sprhold_hldd_code)) = 'PP'
        AND (
            h.sprhold_from_date IS NULL
            OR CAST(h.sprhold_from_date AS date) <= CURRENT_DATE
        )
        AND CAST(h.sprhold_to_date AS date) > CURRENT_DATE
  )
ORDER BY b.amount_owed DESC, s.spriden_id;
