-- ============================================================
-- 05_dim_fund.sql
-- Fund dimension — one row per scheme_code.
-- Sources: 14,368 AMFI schemes + 16 Yahoo ETF/benchmark tickers.
-- Populated by scripts/etl/load_dimensions.py (Day 4).
--
-- Depends on: 03_dim_amc.sql, 04_dim_category.sql
--
-- scheme_code is the natural business key:
--   AMFI records  → numeric scheme code (e.g. '119551')
--   Yahoo ETFs    → Yahoo ticker (e.g. 'NIFTYBEES.NS')
--   Yahoo indices → Yahoo ticker (e.g. '^NSEI')
--
-- base_fund_name strips plan/option suffixes from AMFI names so
-- variants of the same fund (Direct-Growth, Regular-IDCW, etc.)
-- can be grouped in Power BI without additional logic.
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Dim_Fund (
    fund_key        SERIAL          NOT NULL,
    scheme_code     VARCHAR(20)     NOT NULL,
    fund_name       VARCHAR(400)    NOT NULL,
    base_fund_name  VARCHAR(300),               -- stripped of '- Direct - Growth' suffix
    plan_type       VARCHAR(20),                -- 'Direct', 'Regular', 'Retail', 'Institutional'
                                                -- NULL for Yahoo ETFs and benchmarks
    option_type     VARCHAR(30),                -- 'Growth', 'IDCW', 'Dividend', 'Bonus'
                                                -- NULL for Yahoo ETFs and benchmarks
    amc_key         INTEGER,                    -- NULL for Yahoo benchmarks (no AMC mapping)
    category_key    INTEGER,                    -- NULL for Yahoo tickers
    isin_growth     VARCHAR(12),                -- AMFI isin_div_reinvestment (growth option ISIN)
    isin_idcw       VARCHAR(12),                -- AMFI isin_div_payout (dividend option ISIN)
    source          VARCHAR(20)     NOT NULL,   -- 'amfi', 'yahoo_etf', 'yahoo_benchmark'
    is_benchmark    BOOLEAN         NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    inception_date  DATE,                       -- first NAV date; populated by ETL

    CONSTRAINT pk_dim_fund              PRIMARY KEY (fund_key),
    CONSTRAINT uq_dim_fund_scheme_code  UNIQUE (scheme_code),
    CONSTRAINT fk_dim_fund_amc          FOREIGN KEY (amc_key)
                                            REFERENCES dbo.Dim_AMC (amc_key),
    CONSTRAINT fk_dim_fund_category     FOREIGN KEY (category_key)
                                            REFERENCES dbo.Dim_Category (category_key),
    CONSTRAINT chk_dim_fund_source      CHECK (source IN ('amfi', 'yahoo_etf', 'yahoo_benchmark'))
);

COMMENT ON TABLE dbo.Dim_Fund IS
    '14,384 fund/benchmark records. Natural key is scheme_code. base_fund_name enables variant grouping in Power BI.';

-- "All funds from Axis AMC" — without this, every AMC filter full-scans 14k+ rows.
CREATE INDEX IF NOT EXISTS idx_dim_fund_amc
    ON dbo.Dim_Fund (amc_key);

COMMENT ON INDEX dbo.idx_dim_fund_amc IS
    'Supports Power BI slicers and Streamlit dropdowns filtered by AMC.';

-- "All large cap equity funds" — same reasoning as above.
CREATE INDEX IF NOT EXISTS idx_dim_fund_category
    ON dbo.Dim_Fund (category_key);

COMMENT ON INDEX dbo.idx_dim_fund_category IS
    'Supports fund comparison filtered by SEBI category (e.g. all Liquid Funds).';

-- "Show only benchmarks" / "Exclude benchmarks from fund selector" —
-- Streamlit fund comparison dropdown and Power BI benchmark toggle.
CREATE INDEX IF NOT EXISTS idx_dim_fund_source_benchmark
    ON dbo.Dim_Fund (source, is_benchmark);

COMMENT ON INDEX dbo.idx_dim_fund_source_benchmark IS
    'Separates benchmark tickers from investable funds in UI filters.';
