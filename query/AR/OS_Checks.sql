SELECT	
		s.spriden_id             	AS "CWID",
	    s.spriden_first_name     	AS "First Name",
	    s.spriden_last_name      	AS "Last Name",

		g.goremal_emal_code			AS "email_type",
		g.goremal_email_address		AS "email_address",
		g.goremal_status_ind		AS "active_indicator",
		g.goremal_preferred_ind 	AS "preferred_indicator",
		g.goremal_activity_date		AS "activity_date",

        sp.sprtele_tele_code        AS "phone_type",
        sp.sprtele_phone_area       AS "area_code",
        sp.sprtele_phone_number     AS "phone_number",
        sp.sprtele_primary_ind      AS "primary_indicator"

FROM goremal g

JOIN spriden s
	ON g.goremal_pidm = s.spriden_pidm
	AND s.spriden_change_ind IS NULL
	
LEFT JOIN sprtele sp
    ON sp.sprtele_pidm = s.spriden_pidm
    AND sp.sprtele_primary_ind = 'Y'

WHERE goremal_emal_code = 'UNIV'
AND goremal_preferred_ind = 'Y'
AND goremal_status_ind = 'A'
AND g.goremal_activity_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '6 years'
