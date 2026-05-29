-- ============================================================
-- 08_fact_transactions.sql
-- Individual investor transaction fact table.
-- Grain: one row per transaction.
-- 35,280 rows at initial load (synthetic SIP data).
-- Populated by scripts/etl/load_facts.py (Day 4).
--
-- Depends on: 02_dim_date.sql, 05_dim_fund.sql, 06_dim_investor.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Fact_Transactions (
    transaction_key     BIGSERIAL       NOT NULL,
    date_key            INTEGER         NOT NULL,
    fund_key            INTEGER         NOT NULL,
    investor_key        INTEGER         NOT NULL,
    transaction_type    VARCHAR(15)     NOT NULL,   -- 'SIP', 'Lumpsum', 'Redemption'
    amount              NUMERIC(18,2)   NOT NULL,
    units               NUMERIC(18,4),              -- units purchased or redeemed
    nav_at_transaction  NUMERIC(18,4),              -- NAV at time of transaction

    loaded_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fact_transactions         PRIMARY KEY (transaction_key),
    CONSTRAINT fk_fact_txn_date             FOREIGN KEY (date_key)
                                                REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_txn_fund             FOREIGN KEY (fund_key)
                                                REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT fk_fact_txn_investor         FOREIGN KEY (investor_key)
                                                REFERENCES dbo.Dim_Investor (investor_key),
    CONSTRAINT chk_fact_txn_type            CHECK (transaction_type IN ('SIP', 'Lumpsum', 'Redemption')),
    CONSTRAINT chk_fact_txn_amount_positive CHECK (amount > 0)
);

COMMENT ON TABLE dbo.Fact_Transactions IS
    'Investor transaction fact. Grain: one transaction. Supports SIP tracker, fund cashflow, and investor segmentation.';

-- Investor portfolio view: "all transactions for INV00042, sorted by date".
-- investor_key leads — most Streamlit and Power BI queries filter by investor first.
CREATE INDEX IF NOT EXISTS idx_fact_transactions_investor_date
    ON dbo.Fact_Transactions (investor_key, date_key);

COMMENT ON INDEX dbo.idx_fact_transactions_investor_date IS
    'Primary investor portfolio lookup — filters and sorts by investor then date.';

-- Fund flow analysis: "all SIP inflows for NIFTYBEES.NS".
-- Used by SQL view vw_fund_cashflow and sp_compute_aum stored procedure.
CREATE INDEX IF NOT EXISTS idx_fact_transactions_fund_type
    ON dbo.Fact_Transactions (fund_key, transaction_type);

COMMENT ON INDEX dbo.idx_fact_transactions_fund_type IS
    'Fund-level cashflow queries: net inflows, SIP volume, redemption pressure per fund.';
