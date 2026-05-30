-- ============================================================
-- 10_fact_returns.sql
-- Computed financial metrics fact table.
-- Grain: one row per fund × as-of date.
-- Starts EMPTY. Populated by metrics scripts on Days 5–6:
--   scripts/analytics/metrics_returns.py
--   scripts/analytics/metrics_risk.py
--   scripts/analytics/metrics_risk_adjusted.py
--   scripts/analytics/metrics_market.py
--
-- Depends on: 02_dim_date.sql, 05_dim_fund.sql
--
-- All ratio columns store percentages or dimensionless ratios
-- to 4 decimal places. NULL means not yet computed or
-- insufficient NAV history for the window (e.g. a fund with
-- less than 1 year of data has NULL return_1y).
--
-- Benchmark for alpha/beta: Nifty 50 (^NSEI in Dim_Fund).
-- Risk-free rate for Sharpe/Treynor: 6.5% (RBI repo rate).
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Fact_Returns (
    return_key      BIGSERIAL       NOT NULL,
    date_key        INTEGER         NOT NULL,   -- as-of date (last trading day of computation window)
    fund_key        INTEGER         NOT NULL,

    -- Absolute returns (%)
    return_1y       NUMERIC(10,4),   -- (NAV_today / NAV_1y_ago - 1) * 100
    return_3y       NUMERIC(10,4),
    return_5y       NUMERIC(10,4),

    -- Compound Annual Growth Rate (%)
    cagr_1y         NUMERIC(10,4),
    cagr_3y         NUMERIC(10,4),
    cagr_5y         NUMERIC(10,4),

    -- Risk metrics
    std_dev_1y      NUMERIC(10,4),   -- annualised daily volatility over trailing 1 year
    max_drawdown    NUMERIC(10,4),   -- maximum peak-to-trough decline (%) since inception

    -- Risk-adjusted returns (dimensionless ratios)
    sharpe_ratio    NUMERIC(10,4),   -- (CAGR - Rf) / std_dev; Rf = 6.5%
    sortino_ratio   NUMERIC(10,4),   -- (CAGR - Rf) / downside_deviation
    treynor_ratio   NUMERIC(10,4),   -- (CAGR - Rf) / beta

    -- Market-relative metrics (vs Nifty 50 benchmark)
    alpha           NUMERIC(10,4),   -- Jensen's Alpha (%)
    beta            NUMERIC(10,4),   -- systematic risk coefficient

    loaded_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fact_returns              PRIMARY KEY (return_key),
    CONSTRAINT uq_fact_returns_fund_date    UNIQUE (fund_key, date_key),
    CONSTRAINT fk_fact_returns_date         FOREIGN KEY (date_key)
                                                REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_returns_fund         FOREIGN KEY (fund_key)
                                                REFERENCES dbo.Dim_Fund (fund_key)
);

COMMENT ON TABLE dbo.Fact_Returns IS
    'Pre-computed financial metrics. Grain: fund x as-of date. Empty at schema creation; filled by Day 5-6 analytics scripts. UNIQUE(fund_key, date_key) prevents duplicate metric runs.';

-- The UNIQUE constraint on (fund_key, date_key) covers the primary metrics lookup:
-- "sharpe ratio for HDFCNIFTY.NS as of today / as of quarter-end".
-- fund_key leads so per-fund metric history queries are fully index-covered.

-- Cross-fund leaderboard queries: "rank all funds by sharpe_ratio as of 31-Dec-2025".
-- date_key is the leading column since all funds share the same as-of date in leaderboards.
CREATE INDEX IF NOT EXISTS idx_fact_returns_date_key
    ON dbo.Fact_Returns (date_key);

COMMENT ON INDEX dbo.idx_fact_returns_date_key IS
    'Cross-fund metric leaderboards: top funds by Sharpe, CAGR, alpha on a given as-of date.';
