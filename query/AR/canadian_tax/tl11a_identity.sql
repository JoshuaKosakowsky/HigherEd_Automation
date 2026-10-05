WITH __TL11A_SCOPE_SQL__
SELECT COUNT(*) OVER () AS extract_row_count,
       p.tax_year AS extract_tax_year, i.*
FROM identity i CROSS JOIN params p;
