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
