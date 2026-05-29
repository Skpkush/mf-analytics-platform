-- ============================================================
-- 03_dim_amc.sql
-- Asset Management Company dimension.
-- 51 rows sourced from AMFI NAV data (all registered Indian AMCs).
-- Populated by scripts/etl/load_dimensions.py (Day 4).
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Dim_AMC (
    amc_key         SERIAL          NOT NULL,
    amc_name        VARCHAR(200)    NOT NULL,   -- e.g. 'HDFC Mutual Fund'
    amc_short_name  VARCHAR(50),                -- e.g. 'HDFC', 'ICICI Pru'

    CONSTRAINT pk_dim_amc       PRIMARY KEY (amc_key),
    CONSTRAINT uq_dim_amc_name  UNIQUE (amc_name)
);

COMMENT ON TABLE dbo.Dim_AMC IS
    '51 SEBI-registered AMCs sourced from AMFI daily NAV file. Referenced by Dim_Fund.amc_key.';
