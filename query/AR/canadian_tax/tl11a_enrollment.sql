/* One raw registration per term/CRN, including dropped registrations.
   Part-of-term schedules are reference dates, not proof of actual attendance.
   Keep section dates and part-of-term dates separate for reconciliation. */
WITH __TL11A_SCOPE_SQL__
SELECT COUNT(*) OVER () AS extract_row_count,
       p.tax_year AS extract_tax_year, i.pidm,
       r.sfrstcr_term_code AS term_code, y.term_description,
       r.sfrstcr_crn AS crn, r.sfrstcr_rsts_code AS registration_status,
       status.stvrsts_incl_sect_enrl AS counts_in_enrollment,
       r.sfrstcr_credit_hr AS credit_hours, r.sfrstcr_bill_hr AS billable_hours,
       section.ssbsect_subj_code AS subject_code,
       section.ssbsect_crse_numb AS course_number,
       section.ssbsect_ptrm_code AS part_of_term,
       section.ssbsect_ptrm_start_date AS section_start_date,
       section.ssbsect_ptrm_end_date AS section_end_date,
       part.sobptrm_desc AS part_of_term_description,
       part.sobptrm_start_date AS part_of_term_start_date,
       part.sobptrm_end_date AS part_of_term_end_date
FROM identity i
INNER JOIN saturn.sfrstcr r ON r.sfrstcr_pidm = i.pidm
INNER JOIN year_terms y ON y.term_code = r.sfrstcr_term_code
CROSS JOIN params p
LEFT JOIN saturn.stvrsts status ON status.stvrsts_code = r.sfrstcr_rsts_code
LEFT JOIN saturn.ssbsect section
    ON section.ssbsect_term_code = r.sfrstcr_term_code
   AND section.ssbsect_crn = r.sfrstcr_crn
LEFT JOIN saturn.sobptrm part
    ON part.sobptrm_term_code = section.ssbsect_term_code
   AND part.sobptrm_ptrm_code = section.ssbsect_ptrm_code
ORDER BY r.sfrstcr_term_code, r.sfrstcr_crn;
