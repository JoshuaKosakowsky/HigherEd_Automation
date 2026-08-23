SELECT
    spriden_id         AS "CWID",
    spriden_first_name AS "First Name",
    spriden_last_name  AS "Last Name"
FROM spriden
    JOIN tbraccd ON spriden_pidm = tbraccd_pidm
WHERE tbraccd_detail_code = 'HLTH'
  AND tbraccd_term_code = {{v_fall_term_code}}
AND spriden_change_ind IS NULL
AND NOT EXISTS 
(
	SELECT 1
	FROM sfrstcr
		JOIN sgbstdn ON sfrstcr_pidm = sgbstdn_pidm
		JOIN ssbsect ON sfrstcr_term_code = ssbsect_term_code
			AND sfrstcr_crn = ssbsect_crn
		LEFT JOIN gorvisa ON sfrstcr_pidm = gorvisa_pidm
	WHERE sfrstcr_pidm = tbraccd_pidm
	  AND sfrstcr_term_code = {{v_fall_term_code}}
	  AND 
		(sfrstcr_camp_code != 'O'
		AND sfrstcr_bill_hr > 0
		AND sgbstdn_styp_code NOT IN ('E','N')
		AND sgbstdn_stst_code = 'AS'
		AND sgbstdn_term_code_eff =
		   (SELECT MAX(sgbstdn_term_code_eff)
			FROM sgbstdn
			WHERE sgbstdn_pidm = sfrstcr_pidm
			AND   sgbstdn_term_code_eff <= {{v_fall_term_code}}
		   )
		AND
			(
				(ssbsect_subj_code = 'CSM'
				 AND ssbsect_crse_numb = '999'
				 AND ssbsect_seq_numb != 'SA'
				)
				OR
				(ssbsect_subj_code != 'CSM')
			)
		OR
			(sgbstdn_stst_code = 'AS'
			 AND sgbstdn_term_code_eff = 
			   (SELECT MAX(sgbstdn_term_code_eff)
				FROM sgbstdn 
				WHERE sgbstdn_pidm = sfrstcr_pidm
				AND   sgbstdn_term_code_eff <= {{v_fall_term_code}}
			   )
			 AND gorvisa_vtyp_code IN ('F1','F2','J1','J2')
			)
		)
)
GROUP BY spriden_id, spriden_first_name, spriden_last_name
HAVING COALESCE(SUM(tbraccd_amount), 0) > 0
ORDER BY 1;