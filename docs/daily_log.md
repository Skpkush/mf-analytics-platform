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
