/* Complete Banner detail-code reference, including inactive/historical codes.
   Normalized code pages and server-side remaining counts guard API truncation.
   These fields match the metadata consumed by Historical Trends.
*/
SELECT
    UPPER(TRIM(d.tbbdetc_detail_code)) AS detail_code,
    UPPER(TRIM(d.tbbdetc_type_ind)) AS type,
    UPPER(TRIM(d.tbbdetc_dcat_code)) AS category,
    d.tbbdetc_desc AS detail_code_description,
    COUNT(*) OVER () AS extract_remaining_count
FROM taismgr.tbbdetc d
WHERE __CURSOR_FILTER__
ORDER BY UPPER(TRIM(d.tbbdetc_detail_code))
LIMIT __PAGE_SIZE__;
