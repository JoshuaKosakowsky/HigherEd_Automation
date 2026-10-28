/* First-generation discovery only. Description matches are candidates, not
   approved definitions. Counts disclose no student-level records. A code not
   stored in SGRSATT will need its actual source confirmed with the data owner. */
WITH co_population AS (
    SELECT DISTINCT sprhold_pidm AS pidm FROM saturn.sprhold
    WHERE UPPER(TRIM(sprhold_hldd_code)) = 'CO'
),
attribute_usage AS (
    SELECT a.sgrsatt_atts_code AS code, COUNT(DISTINCT a.sgrsatt_pidm) AS co_students
    FROM saturn.sgrsatt a
    INNER JOIN co_population p ON p.pidm = a.sgrsatt_pidm
    GROUP BY a.sgrsatt_atts_code
)
SELECT d.stvatts_code AS "Attribute Code", d.stvatts_desc AS "Attribute Description",
    COALESCE(u.co_students, 0) AS "Historical CO Students Ever With Attribute",
    CASE WHEN LOWER(d.stvatts_desc) LIKE '%first%gen%'
           OR LOWER(d.stvatts_desc) LIKE '%1st%gen%'
           OR UPPER(d.stvatts_code) LIKE '%FGEN%'
         THEN 'Candidate - owner must verify definition and history'
         ELSE 'Other attribute used by CO population' END AS "Mapping Review"
FROM saturn.stvatts d
LEFT JOIN attribute_usage u ON u.code = d.stvatts_code
WHERE u.code IS NOT NULL OR LOWER(d.stvatts_desc) LIKE '%first%gen%'
    OR LOWER(d.stvatts_desc) LIKE '%1st%gen%' OR UPPER(d.stvatts_code) LIKE '%FGEN%'
ORDER BY "Mapping Review", d.stvatts_code;
