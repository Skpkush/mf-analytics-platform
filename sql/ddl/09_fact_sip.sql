-- ============================================================
-- 09_fact_sip.sql
-- Monthly SIP aggregation fact table.
-- Grain: one row per investor × fund × month.
-- Populated by scripts/etl/load_facts.py (Day 4) by aggregating
-- Fact_Transactions where transaction_type = 'SIP'.
--
-- Depends on: 02_dim_date.sql, 05_dim_fund.sql, 06_dim_investor.sql
--
-- date_key references the first calendar day of each month
-- (month-start convention, matching clean_transactions.py date spine).
--
-- cumulative_invested = running sum of monthly_sip_amount from
-- the investor's first SIP in this fund to the current month.
-- current_units_held = units_purchased – units redeemed (from
-- Fact_Transactions), updated by sp_compute_aum each cycle.
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Fact_SIP (
    sip_key                 BIGSERIAL       NOT NULL,
    date_key                INTEGER         NOT NULL,   -- month-start date_key
    fund_key                INTEGER         NOT NULL,
    investor_key            INTEGER         NOT NULL,
    monthly_sip_amount      NUMERIC(18,2),              -- total SIP inflow this month
    cumulative_invested     NUMERIC(18,2),              -- running total invested to date
    units_purchased         NUMERIC(18,4),              -- units bought this month
    current_units_held      NUMERIC(18,4),              -- net units after all redemptions

    loaded_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fact_sip                  PRIMARY KEY (sip_key),
    CONSTRAINT uq_fact_sip_investor_fund_dt UNIQUE (investor_key, fund_key, date_key),
    CONSTRAINT fk_fact_sip_date             FOREIGN KEY (date_key)
                                                REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_sip_fund             FOREIGN KEY (fund_key)
                                                REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT fk_fact_sip_investor         FOREIGN KEY (investor_key)
                                                REFERENCES dbo.Dim_Investor (investor_key)
);

COMMENT ON TABLE dbo.Fact_SIP IS
    'Monthly SIP aggregation. Grain: investor x fund x month. UNIQUE constraint prevents double-loading. Drives SIP Planner in Streamlit.';

-- The UNIQUE constraint on (investor_key, fund_key, date_key) creates an underlying
-- unique index that covers the primary SIP timeline query:
-- "monthly SIP history for investor X in fund Y, sorted by date".

-- Investor-level SIP dashboard: total SIP across all funds for one investor.
-- Secondary to the unique index but needed when fund_key is not in the filter.
CREATE INDEX IF NOT EXISTS idx_fact_sip_investor
    ON dbo.Fact_SIP (investor_key);

COMMENT ON INDEX dbo.idx_fact_sip_investor IS
    'Investor-level SIP summary queries: total invested, fund count, tenure for Streamlit Risk Profiler.';
