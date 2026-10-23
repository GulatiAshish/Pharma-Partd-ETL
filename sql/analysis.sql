-- Analytical queries on the Part D star schema.
-- Portable across SQLite 3.25+ and MySQL 8 (CTEs + window functions).
-- Each query starts with "-- name: <output_file>"; run_analysis.py saves each to outputs/<name>.csv

-- name: 01_top10_drugs_by_spend_latest_year
-- Which 10 drugs drive the most national Medicare Part D spend in the latest year?
WITH latest AS (SELECT MAX(year) AS yr FROM fact_prescription)
SELECT d.brand_name,
       d.generic_name,
       ROUND(f.total_drug_cost / 1e9, 2)  AS spend_usd_bn,
       f.total_claims,
       f.cost_per_claim
FROM fact_prescription f
JOIN dim_drug d ON d.drug_id = f.drug_id
JOIN dim_geo  g ON g.geo_id  = f.geo_id
JOIN latest   l ON f.year    = l.yr
WHERE g.geo_level = 'National'
ORDER BY f.total_drug_cost DESC
LIMIT 10;

-- name: 02_biggest_spend_increase_yoy
-- Which drugs added the most Medicare spend vs last year? (LAG window function)
-- Ranked by absolute $ increase, because % growth alone is dominated by new launches
-- with a tiny base (e.g. $0.2M -> $300M = +150,000%). growth_type separates the two stories.
WITH national AS (
    SELECT f.year, d.brand_name, d.generic_name, f.total_drug_cost
    FROM fact_prescription f
    JOIN dim_drug d ON d.drug_id = f.drug_id
    JOIN dim_geo  g ON g.geo_id  = f.geo_id
    WHERE g.geo_level = 'National'
),
with_prev AS (
    SELECT *,
           LAG(total_drug_cost) OVER (PARTITION BY brand_name, generic_name ORDER BY year) AS prev_cost
    FROM national
)
SELECT year,
       brand_name,
       generic_name,
       ROUND(prev_cost / 1e6, 1)                       AS prev_spend_usd_mn,
       ROUND(total_drug_cost / 1e6, 1)                 AS spend_usd_mn,
       ROUND((total_drug_cost - prev_cost) / 1e6, 1)   AS spend_increase_usd_mn,
       ROUND(100.0 * (total_drug_cost - prev_cost) / prev_cost, 1) AS yoy_growth_pct,
       CASE WHEN prev_cost < 10000000 THEN 'New launch / new coverage'
            ELSE 'Established drug' END                AS growth_type
FROM with_prev
WHERE prev_cost IS NOT NULL
ORDER BY total_drug_cost - prev_cost DESC
LIMIT 15;

-- name: 03_top3_drugs_per_state
-- Top 3 drugs by spend in every state for the latest year (RANK window function).
WITH latest AS (SELECT MAX(year) AS yr FROM fact_prescription),
ranked AS (
    SELECT g.geo_name AS state,
           d.brand_name,
           ROUND(f.total_drug_cost / 1e6, 1) AS spend_usd_mn,
           RANK() OVER (PARTITION BY g.geo_id ORDER BY f.total_drug_cost DESC) AS rnk
    FROM fact_prescription f
    JOIN dim_drug d ON d.drug_id = f.drug_id
    JOIN dim_geo  g ON g.geo_id  = f.geo_id
    JOIN latest   l ON f.year    = l.yr
    WHERE g.geo_level = 'State'
      AND g.geo_code BETWEEN '01' AND '56'   -- 50 states + DC only (drops territories, Armed Forces, Unknown)
)
SELECT state, rnk, brand_name, spend_usd_mn
FROM ranked
WHERE rnk <= 3
ORDER BY state, rnk;

-- name: 04_generic_dispensing_rate_by_state
-- Generic Dispensing Rate (GDR) per state: generics' share of prescriptions vs share of cost.
-- Nationally generics are ~3/4 of claims but ~1/10 of cost, so brands drive spend.
-- Sorted lowest GDR first = most brand-heavy states (where brand $ is concentrated).
WITH latest AS (SELECT MAX(year) AS yr FROM fact_prescription)
SELECT g.geo_name AS state,
       ROUND(100.0 * SUM(CASE WHEN d.is_generic = 1 THEN f.total_claims ELSE 0 END)
             / SUM(f.total_claims), 1)     AS generic_claim_share_pct,
       ROUND(100.0 * SUM(CASE WHEN d.is_generic = 1 THEN f.total_drug_cost ELSE 0 END)
             / SUM(f.total_drug_cost), 1)  AS generic_cost_share_pct,
       ROUND(SUM(CASE WHEN d.is_generic = 0 THEN f.total_drug_cost ELSE 0 END) / 1e9, 2)
                                           AS brand_spend_usd_bn
FROM fact_prescription f
JOIN dim_drug d ON d.drug_id = f.drug_id
JOIN dim_geo  g ON g.geo_id  = f.geo_id
JOIN latest   l ON f.year    = l.yr
WHERE g.geo_level = 'State'
      AND g.geo_code BETWEEN '01' AND '56'   -- 50 states + DC only (drops territories, Armed Forces, Unknown)
GROUP BY g.geo_name
ORDER BY generic_claim_share_pct ASC;

-- name: 05_opioid_claim_share_trend_by_state
-- Opioid share of all claims per state per year, with change vs previous year.
WITH state_year AS (
    SELECT g.geo_name AS state,
           f.year,
           100.0 * SUM(CASE WHEN d.opioid_flag = 1 THEN f.total_claims ELSE 0 END)
                 / SUM(f.total_claims) AS opioid_share_pct
    FROM fact_prescription f
    JOIN dim_drug d ON d.drug_id = f.drug_id
    JOIN dim_geo  g ON g.geo_id  = f.geo_id
    WHERE g.geo_level = 'State'
      AND g.geo_code BETWEEN '01' AND '56'   -- 50 states + DC only (drops territories, Armed Forces, Unknown)
    GROUP BY g.geo_name, f.year
)
SELECT state,
       year,
       ROUND(opioid_share_pct, 2) AS opioid_share_pct,
       ROUND(opioid_share_pct - LAG(opioid_share_pct) OVER (PARTITION BY state ORDER BY year), 2)
           AS change_pct_points
FROM state_year
ORDER BY state, year;

-- name: 06_state_avg_cost_per_claim
-- States ranked by average cost per claim (latest year) - a simple cost-efficiency KPI.
WITH latest AS (SELECT MAX(year) AS yr FROM fact_prescription)
SELECT g.geo_name AS state,
       ROUND(SUM(f.total_drug_cost) / 1e9, 2)                AS spend_usd_bn,
       ROUND(SUM(f.total_drug_cost) / SUM(f.total_claims), 2) AS avg_cost_per_claim,
       DENSE_RANK() OVER (ORDER BY SUM(f.total_drug_cost) / SUM(f.total_claims) DESC)
           AS cost_rank
FROM fact_prescription f
JOIN dim_geo g ON g.geo_id = f.geo_id
JOIN latest  l ON f.year   = l.yr
WHERE g.geo_level = 'State'
      AND g.geo_code BETWEEN '01' AND '56'   -- 50 states + DC only (drops territories, Armed Forces, Unknown)
GROUP BY g.geo_name
ORDER BY cost_rank;