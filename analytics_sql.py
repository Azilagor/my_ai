"""Параметризованные запросы для Streamlit и внешних клиентов."""
ANOMALIES_SQL = """
WITH avg_price AS (
  SELECT COALESCE(ref_enstru_code, '__unknown__') AS ref_enstru_code,
         AVG(NULLIF(amount, 0) / NULLIF(count, 0)) AS avg_unit_price
  FROM fact_lots WHERE customer_bin = :bin AND export_year = :year
  GROUP BY COALESCE(ref_enstru_code, '__unknown__')
)
SELECT l.*, a.avg_unit_price,
       ROUND((l.amount / NULLIF(l.count, 0) / NULLIF(a.avg_unit_price, 0) - 1) * 100, 2) AS deviation_pct
FROM fact_lots l JOIN avg_price a ON a.ref_enstru_code = COALESCE(l.ref_enstru_code, '__unknown__')
WHERE l.customer_bin = :bin AND l.export_year = :year
  AND ABS(l.amount / NULLIF(l.count, 0) / NULLIF(a.avg_unit_price, 0) - 1) > 0.30
ORDER BY ABS(l.amount / NULLIF(l.count, 0) / NULLIF(a.avg_unit_price, 0) - 1) DESC
"""

FAIR_PRICE_SQL = """
SELECT kato_code, AVG(amount / NULLIF(count, 0)) AS avg_unit_price,
       MIN(amount / NULLIF(count, 0)) AS min_unit_price,
       MAX(amount / NULLIF(count, 0)) AS max_unit_price,
       COUNT(*) AS lots
FROM fact_lots
WHERE kato_code = :kato AND export_year = :year
GROUP BY kato_code
"""

VOLUME_SQL = """
SELECT pln_point_year AS year, ref_enstru_code, SUM(count) AS total_count, SUM(amount) AS total_amount
FROM fact_plans WHERE subject_biin = :bin AND pln_point_year BETWEEN 2024 AND 2026
GROUP BY pln_point_year, ref_enstru_code ORDER BY ref_enstru_code, pln_point_year
"""
