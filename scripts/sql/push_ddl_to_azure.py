#!/usr/bin/env python3
"""
push_ddl_to_azure.py
Deploy the complete star schema DDL to Azure SQL Database.

Converts PostgreSQL DDL to T-SQL:
  - SERIAL / BIGSERIAL  → INT / BIGINT IDENTITY(1,1)
  - BOOLEAN             → BIT  (0/1 defaults)
  - TIMESTAMPTZ         → DATETIMEOFFSET  (DEFAULT SYSDATETIMEOFFSET())
  - CREATE TABLE IF NOT EXISTS → sys.tables existence check
  - CREATE INDEX  IF NOT EXISTS → sys.indexes existence check
  - CREATE OR REPLACE VIEW     → CREATE OR ALTER VIEW
  - PL/pgSQL FUNCTION          → T-SQL PROCEDURE  (CREATE OR ALTER)

Run order:
  1. Dimension tables (Date → AMC → Category → Fund → Investor)
  2. Fact tables      (NAV → Transactions → SIP → Returns)
  3. Indexes
  4. Views
  5. Stored procedures
  6. Row-count verification
"""

from __future__ import annotations

import logging
import os
import sys

import pyodbc
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ── Connection ────────────────────────────────────────────────────────────────

def _conn() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};"
        f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
        f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
        f"UID={os.getenv('AZURE_SQL_USER')};"
        f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, autocommit=True)


# ── DDL — Tables ─────────────────────────────────────────────────────────────

TABLES: list[tuple[str, str]] = [

    ("Dim_Date", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Dim_Date' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Dim_Date (
    date_key            INT          NOT NULL,
    full_date           DATE         NOT NULL,
    day_of_week         SMALLINT     NOT NULL,
    day_name            VARCHAR(10)  NOT NULL,
    day_of_month        SMALLINT     NOT NULL,
    day_of_year         SMALLINT     NOT NULL,
    week_of_year        SMALLINT     NOT NULL,
    month_num           SMALLINT     NOT NULL,
    month_name          VARCHAR(10)  NOT NULL,
    quarter             SMALLINT     NOT NULL,
    year                SMALLINT     NOT NULL,
    is_weekday          BIT          NOT NULL,
    is_month_end        BIT          NOT NULL,
    is_quarter_end      BIT          NOT NULL,
    is_year_end         BIT          NOT NULL,
    financial_year      VARCHAR(10)  NOT NULL,
    financial_quarter   VARCHAR(8)   NOT NULL,
    CONSTRAINT pk_dim_date          PRIMARY KEY (date_key),
    CONSTRAINT uq_dim_date_fulldate UNIQUE      (full_date),
    CONSTRAINT chk_dim_date_dow     CHECK (day_of_week BETWEEN 1 AND 7),
    CONSTRAINT chk_dim_date_month   CHECK (month_num   BETWEEN 1 AND 12),
    CONSTRAINT chk_dim_date_quarter CHECK (quarter     BETWEEN 1 AND 4)
)
"""),

    ("Dim_AMC", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Dim_AMC' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Dim_AMC (
    amc_key         INT IDENTITY(1,1) NOT NULL,
    amc_name        VARCHAR(200)      NOT NULL,
    amc_short_name  VARCHAR(50)       NULL,
    CONSTRAINT pk_dim_amc      PRIMARY KEY (amc_key),
    CONSTRAINT uq_dim_amc_name UNIQUE      (amc_name)
)
"""),

    ("Dim_Category", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Dim_Category' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Dim_Category (
    category_key    INT IDENTITY(1,1) NOT NULL,
    raw_category    VARCHAR(300)      NOT NULL,
    structure_type  VARCHAR(50)       NOT NULL,
    asset_class     VARCHAR(50)       NOT NULL,
    sub_category    VARCHAR(100)      NOT NULL,
    CONSTRAINT pk_dim_category     PRIMARY KEY (category_key),
    CONSTRAINT uq_dim_category_raw UNIQUE      (raw_category)
)
"""),

    ("Dim_Fund", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Dim_Fund' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Dim_Fund (
    fund_key        INT IDENTITY(1,1) NOT NULL,
    scheme_code     VARCHAR(20)       NOT NULL,
    fund_name       VARCHAR(400)      NOT NULL,
    base_fund_name  VARCHAR(300)      NULL,
    plan_type       VARCHAR(20)       NULL,
    option_type     VARCHAR(30)       NULL,
    amc_key         INT               NULL,
    category_key    INT               NULL,
    isin_growth     VARCHAR(12)       NULL,
    isin_idcw       VARCHAR(12)       NULL,
    source          VARCHAR(20)       NOT NULL,
    is_benchmark    BIT               NOT NULL DEFAULT 0,
    is_active       BIT               NOT NULL DEFAULT 1,
    inception_date  DATE              NULL,
    CONSTRAINT pk_dim_fund             PRIMARY KEY (fund_key),
    CONSTRAINT uq_dim_fund_scheme_code UNIQUE (scheme_code),
    CONSTRAINT fk_dim_fund_amc         FOREIGN KEY (amc_key)
                                           REFERENCES dbo.Dim_AMC (amc_key),
    CONSTRAINT fk_dim_fund_category    FOREIGN KEY (category_key)
                                           REFERENCES dbo.Dim_Category (category_key),
    CONSTRAINT chk_dim_fund_source     CHECK (source IN ('amfi', 'yahoo_etf', 'yahoo_benchmark'))
)
"""),

    ("Dim_Investor", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Dim_Investor' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Dim_Investor (
    investor_key        INT IDENTITY(1,1) NOT NULL,
    investor_id         VARCHAR(20)       NOT NULL,
    age_group           VARCHAR(10)       NULL,
    city                VARCHAR(50)       NULL,
    state               VARCHAR(50)       NULL,
    risk_profile        VARCHAR(20)       NULL,
    investor_segment    VARCHAR(20)       NULL,
    kyc_status          BIT               NOT NULL DEFAULT 1,
    CONSTRAINT pk_dim_investor          PRIMARY KEY (investor_key),
    CONSTRAINT uq_dim_investor_id       UNIQUE      (investor_id),
    CONSTRAINT chk_dim_investor_segment CHECK (investor_segment IN ('Retail', 'HNI', 'Institutional')),
    CONSTRAINT chk_dim_investor_risk    CHECK (risk_profile     IN ('Conservative', 'Moderate', 'Aggressive'))
)
"""),

    ("Fact_NAV", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Fact_NAV' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Fact_NAV (
    nav_key         BIGINT IDENTITY(1,1) NOT NULL,
    date_key        INT             NOT NULL,
    fund_key        INT             NOT NULL,
    nav             NUMERIC(18,4)   NOT NULL,
    open_price      NUMERIC(18,4)   NULL,
    high_price      NUMERIC(18,4)   NULL,
    low_price       NUMERIC(18,4)   NULL,
    volume          BIGINT          NULL,
    source          VARCHAR(20)     NOT NULL,
    is_outlier      BIT             NOT NULL DEFAULT 0,
    loaded_at       DATETIMEOFFSET  NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT pk_fact_nav           PRIMARY KEY (nav_key),
    CONSTRAINT uq_fact_nav_fund_date UNIQUE (fund_key, date_key),
    CONSTRAINT fk_fact_nav_date      FOREIGN KEY (date_key) REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_nav_fund      FOREIGN KEY (fund_key) REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT chk_fact_nav_positive CHECK (nav > 0),
    CONSTRAINT chk_fact_nav_source   CHECK (source IN ('amfi', 'yahoo_etf', 'yahoo_benchmark'))
)
"""),

    ("Fact_Transactions", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Fact_Transactions' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Fact_Transactions (
    transaction_key     BIGINT IDENTITY(1,1) NOT NULL,
    date_key            INT             NOT NULL,
    fund_key            INT             NOT NULL,
    investor_key        INT             NOT NULL,
    transaction_type    VARCHAR(15)     NOT NULL,
    amount              NUMERIC(18,2)   NOT NULL,
    units               NUMERIC(18,4)   NULL,
    nav_at_transaction  NUMERIC(18,4)   NULL,
    transaction_hash    CHAR(64)        NULL,
    loaded_at           DATETIMEOFFSET  NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT pk_fact_transactions         PRIMARY KEY (transaction_key),
    CONSTRAINT fk_fact_txn_date             FOREIGN KEY (date_key)
                                                REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_txn_fund             FOREIGN KEY (fund_key)
                                                REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT fk_fact_txn_investor         FOREIGN KEY (investor_key)
                                                REFERENCES dbo.Dim_Investor (investor_key),
    CONSTRAINT chk_fact_txn_type            CHECK (transaction_type IN ('SIP', 'Lumpsum', 'Redemption')),
    CONSTRAINT chk_fact_txn_amount_positive CHECK (amount > 0)
)
"""),

    ("Fact_SIP", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Fact_SIP' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Fact_SIP (
    sip_key                 BIGINT IDENTITY(1,1) NOT NULL,
    date_key                INT             NOT NULL,
    fund_key                INT             NOT NULL,
    investor_key            INT             NOT NULL,
    monthly_sip_amount      NUMERIC(18,2)   NULL,
    cumulative_invested     NUMERIC(18,2)   NULL,
    units_purchased         NUMERIC(18,4)   NULL,
    current_units_held      NUMERIC(18,4)   NULL,
    loaded_at               DATETIMEOFFSET  NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT pk_fact_sip                  PRIMARY KEY (sip_key),
    CONSTRAINT uq_fact_sip_investor_fund_dt UNIQUE (investor_key, fund_key, date_key),
    CONSTRAINT fk_fact_sip_date             FOREIGN KEY (date_key)
                                                REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_sip_fund             FOREIGN KEY (fund_key)
                                                REFERENCES dbo.Dim_Fund (fund_key),
    CONSTRAINT fk_fact_sip_investor         FOREIGN KEY (investor_key)
                                                REFERENCES dbo.Dim_Investor (investor_key)
)
"""),

    ("Fact_Returns", """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'Fact_Returns' AND SCHEMA_NAME(schema_id) = 'dbo'
)
CREATE TABLE dbo.Fact_Returns (
    return_key      BIGINT IDENTITY(1,1) NOT NULL,
    date_key        INT             NOT NULL,
    fund_key        INT             NOT NULL,
    return_1y       NUMERIC(10,4)   NULL,
    return_3y       NUMERIC(10,4)   NULL,
    return_5y       NUMERIC(10,4)   NULL,
    cagr_1y         NUMERIC(10,4)   NULL,
    cagr_3y         NUMERIC(10,4)   NULL,
    cagr_5y         NUMERIC(10,4)   NULL,
    std_dev_1y      NUMERIC(10,4)   NULL,
    max_drawdown    NUMERIC(10,4)   NULL,
    sharpe_ratio    NUMERIC(10,4)   NULL,
    sortino_ratio   NUMERIC(10,4)   NULL,
    treynor_ratio   NUMERIC(10,4)   NULL,
    alpha           NUMERIC(10,4)   NULL,
    beta            NUMERIC(10,4)   NULL,
    loaded_at       DATETIMEOFFSET  NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT pk_fact_returns           PRIMARY KEY (return_key),
    CONSTRAINT uq_fact_returns_fund_date UNIQUE (fund_key, date_key),
    CONSTRAINT fk_fact_returns_date      FOREIGN KEY (date_key)
                                             REFERENCES dbo.Dim_Date (date_key),
    CONSTRAINT fk_fact_returns_fund      FOREIGN KEY (fund_key)
                                             REFERENCES dbo.Dim_Fund (fund_key)
)
"""),
]


# ── DDL — Indexes ─────────────────────────────────────────────────────────────

INDEXES: list[tuple[str, str]] = [

    ("idx_dim_date_year_month", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_dim_date_year_month'
               AND object_id = OBJECT_ID('dbo.Dim_Date'))
CREATE INDEX idx_dim_date_year_month ON dbo.Dim_Date (year, month_num)
"""),

    ("idx_dim_fund_amc", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_dim_fund_amc'
               AND object_id = OBJECT_ID('dbo.Dim_Fund'))
CREATE INDEX idx_dim_fund_amc ON dbo.Dim_Fund (amc_key)
"""),

    ("idx_dim_fund_category", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_dim_fund_category'
               AND object_id = OBJECT_ID('dbo.Dim_Fund'))
CREATE INDEX idx_dim_fund_category ON dbo.Dim_Fund (category_key)
"""),

    ("idx_dim_fund_source_benchmark", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_dim_fund_source_benchmark'
               AND object_id = OBJECT_ID('dbo.Dim_Fund'))
CREATE INDEX idx_dim_fund_source_benchmark ON dbo.Dim_Fund (source, is_benchmark)
"""),

    ("idx_fact_nav_date_key", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_nav_date_key'
               AND object_id = OBJECT_ID('dbo.Fact_NAV'))
CREATE INDEX idx_fact_nav_date_key ON dbo.Fact_NAV (date_key)
"""),

    # Filtered unique index — allows multiple NULLs (pre-insert records),
    # enforces dedup only on populated hashes.
    ("idx_fact_txn_hash", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_txn_hash'
               AND object_id = OBJECT_ID('dbo.Fact_Transactions'))
CREATE UNIQUE INDEX idx_fact_txn_hash
    ON dbo.Fact_Transactions (transaction_hash)
    WHERE transaction_hash IS NOT NULL
"""),

    ("idx_fact_transactions_investor_date", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_transactions_investor_date'
               AND object_id = OBJECT_ID('dbo.Fact_Transactions'))
CREATE INDEX idx_fact_transactions_investor_date
    ON dbo.Fact_Transactions (investor_key, date_key)
"""),

    ("idx_fact_transactions_fund_type", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_transactions_fund_type'
               AND object_id = OBJECT_ID('dbo.Fact_Transactions'))
CREATE INDEX idx_fact_transactions_fund_type
    ON dbo.Fact_Transactions (fund_key, transaction_type)
"""),

    ("idx_fact_sip_investor", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_sip_investor'
               AND object_id = OBJECT_ID('dbo.Fact_SIP'))
CREATE INDEX idx_fact_sip_investor ON dbo.Fact_SIP (investor_key)
"""),

    ("idx_fact_returns_date_key", """
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'idx_fact_returns_date_key'
               AND object_id = OBJECT_ID('dbo.Fact_Returns'))
CREATE INDEX idx_fact_returns_date_key ON dbo.Fact_Returns (date_key)
"""),
]


# ── DDL — Views ───────────────────────────────────────────────────────────────

VIEWS: list[tuple[str, str]] = [

    ("vw_fund_performance", """
CREATE OR ALTER VIEW dbo.vw_fund_performance AS
WITH returns_data AS (
    SELECT
        fr.fund_key,
        fr.date_key,
        dd.full_date     AS as_of_date,
        fr.return_1y,    fr.return_3y,    fr.return_5y,
        fr.cagr_1y,      fr.cagr_3y,      fr.cagr_5y,
        fr.std_dev_1y,   fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio, fr.treynor_ratio,
        fr.alpha,        fr.beta
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
    WHERE fr.cagr_1y IS NOT NULL OR fr.std_dev_1y IS NOT NULL
)
SELECT
    df.scheme_code,    df.fund_name,    df.base_fund_name,
    df.plan_type,      df.option_type,  df.source,         df.is_benchmark,
    da.amc_name,       da.amc_short_name,
    dc.asset_class,    dc.sub_category, dc.structure_type,
    rd.as_of_date,
    rd.return_1y,      rd.return_3y,    rd.return_5y,
    rd.cagr_1y,        rd.cagr_3y,      rd.cagr_5y,
    rd.std_dev_1y,     rd.max_drawdown,
    rd.sharpe_ratio,   rd.sortino_ratio, rd.treynor_ratio,
    rd.alpha,          rd.beta
FROM returns_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
"""),

    ("vw_investor_segmentation", """
CREATE OR ALTER VIEW dbo.vw_investor_segmentation AS
WITH txn_summary AS (
    SELECT
        investor_key,
        fund_key,
        SUM(CASE WHEN transaction_type IN ('SIP','Lumpsum') THEN amount ELSE 0 END) AS invested,
        SUM(CASE WHEN transaction_type = 'Redemption'       THEN amount ELSE 0 END) AS redeemed,
        SUM(CASE WHEN transaction_type = 'SIP'              THEN 1      ELSE 0 END) AS sip_count,
        SUM(CASE WHEN transaction_type = 'Lumpsum'          THEN 1      ELSE 0 END) AS lumpsum_count,
        SUM(CASE WHEN transaction_type = 'Redemption'       THEN 1      ELSE 0 END) AS redemption_count,
        COUNT(*)                                                                      AS total_txn_count
    FROM dbo.Fact_Transactions
    GROUP BY investor_key, fund_key
),
investor_summary AS (
    SELECT
        investor_key,
        SUM(invested)             AS total_invested,
        SUM(redeemed)             AS total_redeemed,
        COUNT(DISTINCT fund_key)  AS active_funds,
        SUM(sip_count)            AS sip_count,
        SUM(lumpsum_count)        AS lumpsum_count,
        SUM(redemption_count)     AS redemption_count,
        SUM(total_txn_count)      AS total_txn_count
    FROM txn_summary
    GROUP BY investor_key
)
SELECT
    di.investor_id,  di.age_group,  di.city,
    di.state,        di.risk_profile, di.investor_segment, di.kyc_status,
    COALESCE(s.total_invested, 0)                                AS total_invested,
    COALESCE(s.total_redeemed, 0)                                AS total_redeemed,
    COALESCE(s.total_invested, 0) - COALESCE(s.total_redeemed,0) AS net_invested,
    COALESCE(s.active_funds,     0)                              AS active_funds,
    COALESCE(s.sip_count,        0)                              AS sip_count,
    COALESCE(s.lumpsum_count,    0)                              AS lumpsum_count,
    COALESCE(s.redemption_count, 0)                              AS redemption_count,
    COALESCE(s.total_txn_count,  0)                              AS total_txn_count
FROM dbo.Dim_Investor di
LEFT JOIN investor_summary s ON s.investor_key = di.investor_key
"""),

    ("vw_risk_summary", """
CREATE OR ALTER VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT
        fr.fund_key,
        fr.std_dev_1y, fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio,
        fr.beta, fr.alpha,
        fr.cagr_1y, fr.cagr_3y, fr.cagr_5y,
        dd.full_date AS as_of_date
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
    WHERE fr.std_dev_1y IS NOT NULL
)
SELECT
    df.scheme_code, df.fund_name, df.base_fund_name,
    df.source,      df.is_benchmark,
    dc.asset_class, dc.sub_category,
    da.amc_name,
    rd.std_dev_1y,  rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio,
    rd.beta,        rd.alpha,
    rd.cagr_1y,     rd.cagr_3y,     rd.cagr_5y,
    CASE
        WHEN rd.std_dev_1y < 5  THEN 'Very Low'
        WHEN rd.std_dev_1y < 10 THEN 'Low'
        WHEN rd.std_dev_1y < 18 THEN 'Medium'
        WHEN rd.std_dev_1y < 30 THEN 'High'
        ELSE                         'Very High'
    END AS risk_tier,
    rd.as_of_date
FROM risk_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
"""),
]


# ── DDL — Stored Procedures ───────────────────────────────────────────────────

PROCS: list[tuple[str, str]] = [

    ("sp_compute_aum", """
CREATE OR ALTER PROCEDURE dbo.sp_compute_aum
    @p_as_of_date DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @p_as_of_date IS NULL SET @p_as_of_date = CAST(GETDATE() AS DATE);

    WITH latest_sip AS (
        SELECT
            fs.fund_key,
            fs.investor_key,
            fs.current_units_held,
            ROW_NUMBER() OVER (
                PARTITION BY fs.fund_key, fs.investor_key
                ORDER BY dd.full_date DESC
            ) AS rn
        FROM dbo.Fact_SIP fs
        JOIN dbo.Dim_Date dd ON dd.date_key = fs.date_key
        WHERE dd.full_date <= @p_as_of_date
    ),
    fund_units AS (
        SELECT fund_key, SUM(current_units_held) AS total_units
        FROM latest_sip WHERE rn = 1
        GROUP BY fund_key
    ),
    latest_nav AS (
        SELECT
            fn.fund_key,
            fn.nav,
            ROW_NUMBER() OVER (
                PARTITION BY fn.fund_key
                ORDER BY dd.full_date DESC
            ) AS rn
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
        WHERE dd.full_date <= @p_as_of_date
    )
    SELECT
        df.scheme_code,
        df.fund_name,
        da.amc_name,
        fu.total_units,
        ln.nav                  AS nav_price,
        fu.total_units * ln.nav AS aum_inr
    FROM fund_units fu
    JOIN       latest_nav   ln ON ln.fund_key = fu.fund_key AND ln.rn = 1
    JOIN       dbo.Dim_Fund df ON df.fund_key = fu.fund_key
    LEFT JOIN  dbo.Dim_AMC  da ON da.amc_key  = df.amc_key
    WHERE fu.total_units > 0
    ORDER BY (fu.total_units * ln.nav) DESC;
END
"""),

    ("sp_top_funds_by_category", """
CREATE OR ALTER PROCEDURE dbo.sp_top_funds_by_category
    @p_category VARCHAR(100),
    @p_metric   VARCHAR(30) = 'cagr_3y',
    @p_top_n    INT         = 10
AS
BEGIN
    SET NOCOUNT ON;

    -- Whitelist: prevents SQL injection via dynamic column name
    IF @p_metric NOT IN (
        'cagr_1y','cagr_3y','cagr_5y',
        'return_1y','return_3y','return_5y',
        'sharpe_ratio','sortino_ratio','treynor_ratio',
        'alpha','beta','std_dev_1y','max_drawdown'
    )
    BEGIN
        RAISERROR('Invalid metric "%s". See sp_top_funds_by_category for allowed values.', 16, 1, @p_metric);
        RETURN;
    END

    DECLARE @sql NVARCHAR(2000) = N'
        SELECT TOP (@top_n)
            ROW_NUMBER() OVER (ORDER BY fr.' + QUOTENAME(@p_metric) + N' DESC) AS rank_pos,
            df.scheme_code,
            df.fund_name,
            dc.sub_category,
            da.amc_name,
            fr.' + QUOTENAME(@p_metric) + N' AS metric_value
        FROM dbo.Fact_Returns fr
        JOIN       dbo.Dim_Fund     df ON df.fund_key     = fr.fund_key
        JOIN       dbo.Dim_Category dc ON dc.category_key = df.category_key
        LEFT JOIN  dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
        WHERE dc.sub_category = @category
          AND fr.' + QUOTENAME(@p_metric) + N' IS NOT NULL
        ORDER BY fr.' + QUOTENAME(@p_metric) + N' DESC';

    EXEC sp_executesql @sql,
        N'@top_n INT, @category VARCHAR(100)',
        @top_n    = @p_top_n,
        @category = @p_category;
END
"""),
]


ALL_TABLES = [
    "Dim_Date", "Dim_AMC", "Dim_Category", "Dim_Fund", "Dim_Investor",
    "Fact_NAV", "Fact_Transactions", "Fact_SIP", "Fact_Returns",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _exec(label: str, cur: pyodbc.Cursor, sql: str) -> bool:
    try:
        cur.execute(sql)
        log.info("PASS  %s", label)
        return True
    except Exception as exc:
        log.error("FAIL  %s — %s", label, exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    conn = _conn()
    cur  = conn.cursor()
    results: dict[str, bool] = {}

    log.info("=== Tables (%d) ===", len(TABLES))
    for name, sql in TABLES:
        results[f"Table  {name}"] = _exec(name, cur, sql)

    log.info("=== Indexes (%d) ===", len(INDEXES))
    for name, sql in INDEXES:
        results[f"Index  {name}"] = _exec(name, cur, sql)

    log.info("=== Views (%d) ===", len(VIEWS))
    for name, sql in VIEWS:
        results[f"View   {name}"] = _exec(name, cur, sql)

    log.info("=== Stored Procedures (%d) ===", len(PROCS))
    for name, sql in PROCS:
        results[f"Proc   {name}"] = _exec(name, cur, sql)

    log.info("=== Row Counts ===")
    for table in ALL_TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) FROM dbo.{table}")
            count = cur.fetchone()[0]
            log.info("PASS  %-25s %d rows", table, count)
            results[f"Rows   {table}"] = True
        except Exception as exc:
            log.error("FAIL  %s — %s", table, exc)
            results[f"Rows   {table}"] = False

    conn.close()

    passed = sum(results.values())
    total  = len(results)
    print(f"\n{'='*55}")
    print(f"  Result: {passed}/{total} passed")
    if passed < total:
        print("  Failed:")
        for k, ok in results.items():
            if not ok:
                print(f"    FAIL  {k}")
    else:
        print("  All checks passed — Azure SQL schema is live.")
    print("=" * 55)


if __name__ == "__main__":
    main()
