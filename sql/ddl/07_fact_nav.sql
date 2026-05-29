-- ============================================================
-- 07_fact_nav.sql
-- Daily NAV / price fact table.
-- Grain: one row per fund × date.
-- ~33,016 rows at initial load (18,648 Yahoo + 14,368 AMFI).
-- Populated by scripts/etl/load_facts.py (Day 4).
--
-- Depends on: 02_dim_date.sql, 05_dim_fund.sql
--
-- OHLCV columns (open_price, high_price, low_price, volume) are
-- NULL for AMFI records — AMFI publishes only end-of-day NAV.
-- is_outlier is set by the z-score flag in clean_nav.py and
-- carried through to support DAX measures that exclude anomalies.
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Fact_NAV (
    nav_key         BIGSERIAL       NOT NULL,
    date_key        INTEGER         NOT NULL,
    fund_key        INTEGER         NOT NULL,
    nav             NUMERIC(18,4)   NOT NULL,   -- closing NAV or adjusted close price
    open_price      NUMERIC(18,4),              -- NULL for AMFI records
    high_price      NUMERIC(18,4),              -- NULL for AMFI records
    low_price       NUMERIC(18,4),              -- NULL for AMFI records
    volume          BIGINT,                     -- NULL for AMFI records
    source          VARCHAR(20)     NOT NULL,   -- 'amfi', 'yahoo_etf', 'yahoo_benchmark'
    is_outlier      BOOLEAN         NOT NULL DEFAULT FALSE,
    loaded_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fact_nav              PRIMARY KEY (nav_key),
    CONSTRAINT uq_fact_nav_fund_date    UNIQUE (fund_key, date_key),
    CONSTRAINT fk_fact_nav_date         FOREIGN KEY (date_key)
                                            REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_nav_fund         FOREIGN KEY (fund_key)
                                            REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT chk_fact_nav_positive    CHECK (nav > 0),
    CONSTRAINT chk_fact_nav_source      CHECK (source IN ('amfi', 'yahoo_etf', 'yahoo_benchmark'))
);

COMMENT ON TABLE dbo.Fact_NAV IS
    'Daily NAV fact. Grain: fund x date. UNIQUE(fund_key, date_key) prevents duplicate daily entries.';

-- The UNIQUE constraint above creates an underlying unique index on (fund_key, date_key),
-- covering the primary analytics query: "NAV for fund X between dates A and B".
-- fund_key leads so per-fund range scans use the index efficiently.

-- Cross-fund date snapshots: "all fund NAVs on 31-Mar-2026".
-- Used by Power BI time-intelligence measures and sp_compute_aum.
CREATE INDEX IF NOT EXISTS idx_fact_nav_date_key
    ON dbo.Fact_NAV (date_key);

COMMENT ON INDEX dbo.idx_fact_nav_date_key IS
    'Supports cross-fund date queries: portfolio valuation snapshots and month-end NAV lookups.';
