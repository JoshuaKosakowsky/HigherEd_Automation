SELECT
    -- Student ID Information
    s.spriden_id             AS "CWID",
    s.spriden_first_name     AS "First Name",
    s.spriden_last_name      AS "Last Name",

    -- Student Charge Information
    t.tbraccd_term_code      AS "Term",
    t.tbraccd_detail_code    AS "Detail Code",
    d.tbbdetc_desc           AS "Detail Code Description",
    t.tbraccd_amount         AS "Amount",
    t.tbraccd_balance        AS "Balance",

    -- Charge Feed Information
    d.tbbdetc_type_ind       AS "Charge or Payment",
    t.tbraccd_feed_date      AS "Feed Date",
    t.tbraccd_tran_number    AS "Transaction Number",
    d.tbbdetc_priority       AS "Priority"

FROM tbraccd t

-- Student's current name and CWID.
JOIN spriden s
    ON t.tbraccd_pidm = s.spriden_pidm
   AND s.spriden_change_ind IS NULL

-- Description, type, and priority assigned to the detail code.
LEFT JOIN tbbdetc d
    ON t.tbraccd_detail_code = d.tbbdetc_detail_code

-- Every transaction since the beginning of the current month.
WHERE t.tbraccd_feed_date >= date_trunc('month', CURRENT_DATE)

-- List by CWID, Feed Date, Tran Number (Midnight Feed Date)
ORDER BY
    s.spriden_id,
    t.tbraccd_feed_date DESC,
    t.tbraccd_tran_number DESC;