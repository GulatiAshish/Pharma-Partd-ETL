# Medicare Part D Prescription Analytics – ETL Pipeline

An end-to-end **Python + SQL ETL pipeline** that ingests public CMS Medicare Part D prescription data,
cleans and validates it, loads it into a **star-schema relational database**, and runs analytical SQL
to answer pharma commercial questions: which drugs drive spend, which added the most spend YoY,
how generic adoption varies by state, and how opioid prescribing is trending.

## Architecture

```
 data/raw/*.csv  ──►  extract.py  ──►  transform.py  ──►  load.py  ──►  SQLite / MySQL  ──►  analysis.sql  ──►  outputs/*.csv
 (CMS, 2 years)      schema check     clean, de-dupe,     star schema,                         CTEs + window
                     year detect      derive metrics,     idempotent                           functions
                                      data-quality checks per-year loads
```

**Star schema**

| Table | Grain | Key columns |
|---|---|---|
| `dim_drug` | one row per brand + generic name | `drug_id`, `brand_name`, `generic_name`, `is_generic`, `opioid_flag` |
| `dim_geo` | one row per geography (National + 50 states/territories) | `geo_id`, `geo_level`, `geo_code`, `geo_name` |
| `fact_prescription` | year × drug × geography | claims, 30-day fills, drug cost, beneficiaries, cost per claim |

## Data source

[CMS – Medicare Part D Prescribers by Geography and Drug](https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-geography-and-drug)
(public, U.S. government work). Data years 2023 and 2024 are used.

## Engineering highlights

- **Data quality:** only the needed columns are read and a missing one stops the run; negative counts or costs
  stop the run; duplicates on the business key are dropped. CMS-suppressed cells are stored as `NULL`, not 0.
- **Idempotent loads:** re-running a year replaces that year's facts in one transaction — no duplicates.
- **Portable SQL:** runs on SQLite (default, zero setup) and MySQL 8 by changing one connection string.
- **Analytical SQL:** CTEs, `LAG`, `RANK`, `DENSE_RANK`, conditional aggregation.
- **Tests:** `pytest` covers year detection, cleaning, de-duplication, quality rules, load idempotency and query correctness.

## Analyses (`sql/analysis.sql` → `outputs/`)

| # | Question | SQL technique |
|---|---|---|
| 01 | Top 10 drugs by national spend (latest year) | CTE, joins |
| 02 | Which drugs added the most spend YoY (new launch vs established) | `LAG` window, `CASE` |
| 03 | Top 3 drugs per state | `RANK() OVER (PARTITION BY …)` |
| 04 | Generic Dispensing Rate by state: share of claims vs cost, brand-heaviest first | conditional aggregation |
| 05 | Opioid share of claims by state, YoY change | `LAG` on aggregated CTE |
| 06 | States ranked by average cost per claim | `DENSE_RANK` |

## Key findings

- _Top drug by spend in 2024: … ($20.77 bn)_
- Generics are ~75% of prescriptions in every state but only ~10% of spend: brand drugs drive Medicare drug cost.

<!-- ## How to run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# put the CMS CSVs in data/raw/  (file name must contain the year, e.g. partd_2023.csv)
python -m etl.pipeline                     # SQLite -> partd.db, results -> outputs/
python -m pytest -v                        # run tests

# optional: MySQL instead of SQLite
pip install pymysql
python -m etl.pipeline --db "mysql+pymysql://user:password@localhost/partd"
``` -->

<!-- ## Project structure

```
etl/        extract.py, transform.py, load.py, analyze.py, pipeline.py (entry point)
sql/        analysis.sql
tests/      test_pipeline.py
data/raw/   input CSVs (git-ignored)
outputs/    query results (CSV)
``` -->