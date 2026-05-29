# Daily Log — Mutual Fund Analytics Platform

---

## Day 1 — 2026-05-29

**Completed:**
- Virtual environment verified (Python 3.14.3, all deps importable)
- AMFI ingestion working: 14,368 schemes, 51 AMCs, 0 null NAVs, date range 2008-10-02 → 2026-05-28 (544 KB parquet)
- Yahoo Finance ingestion working: 11/16 ETF tickers (12,489 rows) + 5/5 benchmarks (6,165 rows), date range 2021-05-31 → 2026-05-28
- Fixed Windows cp1252 UnicodeEncodeError in logging setup for both ingestion scripts (UTF-8 reconfigure on StreamHandler)
- All 3 parquet files saved to `data/raw/`

**Known issues / Day 2 action items:**
- 5 ETF tickers returned empty (possibly delisted): ICICINIFTY.NS, KOTAKNV20.NS, UTINIFTETF.NS, ICICIPRAMC.NS, ICICIBANKN.NS — verify replacement tickers during Day 2 cleaning
- 1 null close value in ETF data, 5 null close values in benchmark data — handle in `clean_nav.py`

**Applications submitted:** 0/10 — pending (evening session)

**Blockers:** None

**Tomorrow (Day 2):**
- Build `scripts/transformation/clean_nav.py` — handle missing dates, outliers, null NAVs
- Build `scripts/transformation/clean_transactions.py` — investor data cleanup
- Build `scripts/transformation/data_quality.py` — schema enforcement, anomaly detection
- Write unit tests for data quality checks
- Fix the 5 failed Yahoo Finance ETF tickers
- Commit: `feat: data cleaning + quality framework`

---

## Day 2 — 2026-05-29

**Completed:**
- Built `scripts/transformation/data_quality.py` — reusable quality checks: completeness, schema, freshness, duplicates, anomaly detection, quality report
- Built `scripts/transformation/clean_nav.py` — cleans Yahoo ETF + benchmark + AMFI parquets into unified schema; drops 6 trailing null rows (2026-05-28 unsettled market data); flagged 1 outlier in ETF data
- Built `scripts/transformation/clean_transactions.py` — generates reproducible synthetic SIP dataset (35,280 transactions, 500 investors, 30 real AMFI scheme codes, 36 months); framework ready for real Kaggle data via --input flag
- Built `tests/test_data_quality.py` — 28 unit tests, all passing
- Fixed pandas 3.x `str` vs `object` dtype issue in `check_schema`
- Fixed `.str.title()` corrupting "SIP" → "Sip" in transaction type normalisation
- Added `tests/conftest.py` for sys.path resolution in pytest
- Installed pytest into venv

**Processed outputs saved:**
- `data/processed/nav_yahoo_clean_20260529.parquet` — 18,648 rows (ETFs + benchmarks), 593 KB
- `data/processed/nav_amfi_clean_20260529.parquet` — 14,368 rows, 400 KB
- `data/processed/transactions_clean_20260529.parquet` — 35,280 rows, 599 KB

**Applications submitted:** 0/10 — pending (evening session)

**Blockers:** None

**Tomorrow (Day 3):**
- Design star schema: Dim_Fund, Dim_Date, Dim_Investor, Dim_AMC, Dim_Category
- Write DDL scripts in `sql/ddl/`
- Set up local PostgreSQL, create database `mf_analytics`
- Run DDL, verify schema
- Commit: `feat: star schema DDL`

---

## Day 3 — 2026-05-29

**Completed:**
- Designed full star schema from real data (inspected processed parquets before designing)
- Wrote 10 DDL files in `sql/ddl/` (PostgreSQL 18, dbo schema)
  - 5 dimension tables: Dim_Date (17 cols), Dim_AMC (3), Dim_Category (5), Dim_Fund (14), Dim_Investor (8)
  - 4 fact tables: Fact_NAV (11), Fact_Transactions (9), Fact_SIP (9), Fact_Returns (17)
  - 26 total indexes/constraints: 9 PKs, 8 UNIQUEs, 9 non-unique indexes, business-logic CHECKs
- Wrote `scripts/etl/run_ddl.py` — creates DB if absent, runs all DDL files in order, idempotent
- Created `mf_analytics` database on local PostgreSQL 18
- Verified: 9 tables, 95 constraints, 26 indexes — all in `dbo` schema
- Fixed `COMMENT ON INDEX` to require `dbo.` schema prefix (PostgreSQL indexes inherit table schema)
- Fixed all `CREATE INDEX` to `IF NOT EXISTS` for idempotent re-runs

**Schema state:** All 9 tables empty, ready for Day 4 ETL load.

**Applications submitted:** 0/10 — pending (evening session)

**Blockers:** None

**Tomorrow (Day 4):**
- Build `scripts/etl/load_dimensions.py` — populate all 5 Dim tables from processed parquets
- Build `scripts/etl/load_facts.py` — populate Fact_NAV, Fact_Transactions, Fact_SIP
- Build `scripts/etl/generate_dim_date.py` — generate 2015–2026 date spine
- Verify row counts and referential integrity
- Commit: `feat: ETL pipeline to star schema`

---

## Day 4 — 2026-05-29

**Completed:**
- Built `scripts/etl/load_dimensions.py` — loads all 5 Dim tables with UPSERT, bulk execute_values
  - Dim_Date: 4,383-row Indian FY date spine (2015–2026), vectorised pandas, no loops
  - Dim_AMC: 51 rows, amc_short_name derived from name
  - Dim_Category: 50 rows, dual-regex parser (42 primary + 8 secondary pattern)
  - Dim_Fund: 14,368 AMFI + 16 Yahoo = 14,384 rows; plan/option/base_name parsed from scheme names; ISINs joined from raw parquet
  - Dim_Investor: 500 synthetic investors, seed=42, realistic Indian city/state/age/risk distribution
- Built `scripts/etl/load_facts.py` — loads 3 fact tables with UPSERT + referential integrity check
  - Fact_NAV: 32,607 rows (409 dropped: 29 pre-2015 dates + 380 zero-NAV newly-registered schemes)
  - Fact_Transactions: 35,280 rows, 0 dropped; SHA-256 dedup hash (transaction_hash CHAR(64))
  - Fact_SIP: 28,224 monthly records derived in-memory from txn data (no DB round-trip)
- Added `transaction_hash` column via idempotent migration in load_facts.py (ADD COLUMN IF NOT EXISTS + CREATE UNIQUE INDEX IF NOT EXISTS)
- Fixed: ADD CONSTRAINT IF NOT EXISTS not supported in PostgreSQL — switched to CREATE UNIQUE INDEX IF NOT EXISTS
- Fixed: 380 zero-NAV AMFI rows (newly-registered schemes) filtered at ETL boundary before CHECK constraint
- **Referential integrity: PASSED** — 0 orphan rows in Fact_NAV, 0 orphan rows in Fact_Transactions

**Schema state:** All 8 tables loaded (Fact_Returns remains empty — populated Day 5-6).

**Applications submitted:** 0/10 — pending

**Blockers:** None

**Tomorrow (Day 5):**
- Build `scripts/analytics/metrics_returns.py` — CAGR, rolling returns (1Y/3Y/5Y)
- Build `scripts/analytics/metrics_risk.py` — std dev, volatility, max drawdown
- Validate against known benchmark values (e.g. Nifty 50 published CAGR)
- Commit: `feat: returns + risk metrics`

---

## Day 5 — 2026-05-29

**Completed:**
- Built `scripts/analytics/metrics_returns.py` — return_1y/3y/5y, cagr_1y/3y/5y for 16 Yahoo funds
- Built `scripts/analytics/metrics_risk.py` — std_dev_1y, max_drawdown for 16 Yahoo funds
- Both scripts write to Fact_Returns via column-targeted UPSERT (each script only touches its own columns; Day 6 Sharpe/alpha/beta will safely merge into same rows)
- Fixed bidirectional date gap: data starts 2021-05-31, 5Y target is 2021-05-28 — forward-gap lookup resolved this; NIFTYBEES.NS cagr_5y = 10.19%
- **Validation PASSED**: NIFTYBEES.NS cagr_5y = 10.19% (expected 8–14%), std_dev_1y = 12.09% (expected 8–20%), max_drawdown = -16.11% (non-positive)
- Key metric results: NIFTYBEES.NS CAGR5Y 10.19% | Gold ETF CAGR5Y 24.82% | Nifty IT index CAGR5Y 1.29% (tech correction) | Nifty 50 CAGR5Y 8.94%
- Note: AMFI schemes have only one NAV snapshot — time-series metrics only apply to 16 Yahoo ETF/benchmark funds. Historical AMFI data (fetch_amfi_nav.py --historical) needed for AMFI scheme metrics.
- Note: MON100.NS max_drawdown = -90.13% — data artifact from Yahoo Finance unadjusted corporate action (the is_outlier flag was set for this fund in Day 2 cleaning). Formula is correct.

**Fact_Returns state:** 16 rows (return/CAGR + risk columns populated; Sharpe/Sortino/alpha/beta NULL until Day 6)

**Applications submitted:** 0/10 — pending

**Blockers:** None

**Tomorrow (Day 6):**
- Build `scripts/analytics/metrics_risk_adjusted.py` — Sharpe, Sortino, Treynor (risk-free rate = 6.5% RBI repo)
- Build `scripts/analytics/metrics_market.py` — Alpha, Beta vs Nifty 50 (^NSEI)
- Write SQL views: `vw_fund_performance`, `vw_investor_segmentation`, `vw_risk_summary`
- Write stored procs: `sp_compute_aum`, `sp_top_funds_by_category`
- Commit: `feat: risk-adjusted metrics + SQL analytical layer`

---

## Day 6 — 2026-05-29

**Completed:**
- Built `scripts/analytics/metrics_market.py` — Beta (OLS regression vs ^NSEI, 1,232 common days) + Jensen's Alpha (CAPM-based, longest available CAGR window)
  - Validation PASSED: NIFTYBEES.NS beta=0.8938 (expected 0.85–1.05); ^NSEI self-check beta=1.0, alpha=0.0 ✓
  - LIQUIDBEES.NS beta=-0.0001 (warning fired but economically correct: essentially zero correlation with equity market)
  - Notable: GOLDBEES.NS alpha=18.12% (gold significantly outperformed CAPM prediction); ^CNXIT alpha=-7.53% (IT underperformed)
- Built `scripts/analytics/metrics_risk_adjusted.py` — Sharpe, Sortino, Treynor (Rf=6.5% RBI repo)
  - Validation PASSED: GOLDBEES.NS sharpe=1.50 (positive, cagr_1y=61% >> Rf); NIFTYBEES.NS sharpe=-0.68 (negative, cagr_1y=-2.43% < Rf) ✓
  - Fixed: numpy.float64 passed raw to psycopg2 — added explicit float() cast in upsert
  - LIQUIDBEES.NS extreme values (sharpe=-578, treynor=65,000) are mathematically correct for near-zero-vol cash-equivalent fund
- All SQL objects created via `run_sql_layer.py`:
  - `vw_fund_performance` — 16 rows, all 13 metrics populated, Power BI primary source
  - `vw_investor_segmentation` — 500 investors with invested/redeemed/net/fund-count aggregates
  - `vw_risk_summary` — 16 rows with SEBI riskometer tier (Very Low → Very High) classification
  - `dbo.sp_compute_aum()` — live AUM: units × latest NAV, top fund ~INR 35.9L (synthetic data)
  - `dbo.sp_top_funds_by_category()` — returns 0 rows for AMFI categories (expected: Yahoo ETFs have NULL category; will work once historical AMFI time-series loaded)

**Fact_Returns state:** 16 rows, all 13 metric columns populated (NULL only for HDFCNIFTY/MONIFTY500 cagr_5y due to <3Y history, and LIQUIDBEES extreme ratio values are populated)

**Applications submitted:** 0/10 — pending

**Blockers:** None

**Tomorrow (Day 7):**
- Run end-to-end local pipeline (ingest → clean → ETL → metrics)
- Generate exploratory notebook with key visualizations
- Document data dictionary (`docs/data_dictionary.md`)
- Streamlit fallback test: ensure local Postgres + metrics work standalone
- Commit: `docs: data dictionary + week 1 wrap-up`
