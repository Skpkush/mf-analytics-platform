-- ============================================================
-- 02_dim_date.sql
-- Date dimension covering 2015-01-01 to 2026-12-31.
-- Populated by scripts/etl/load_dimensions.py (Day 4).
--
-- date_key uses YYYYMMDD integer format (e.g. 20260529).
-- Integer PKs are ~20% faster to join than DATE PKs in PostgreSQL
-- and remain human-readable in query results.
--
-- Indian financial year: April 1 – March 31.
-- financial_year format: 'FY2025-26'
-- financial_quarter format: 'Q1FY26'  (Q1 = Apr–Jun)
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Dim_Date (
    date_key            INTEGER         NOT NULL,
    full_date           DATE            NOT NULL,
    day_of_week         SMALLINT        NOT NULL,   -- 1=Monday … 7=Sunday (ISO 8601)
    day_name            VARCHAR(10)     NOT NULL,   -- 'Monday', 'Tuesday' …
    day_of_month        SMALLINT        NOT NULL,   -- 1–31
    day_of_year         SMALLINT        NOT NULL,   -- 1–366
    week_of_year        SMALLINT        NOT NULL,   -- ISO week number
    month_num           SMALLINT        NOT NULL,   -- 1–12
    month_name          VARCHAR(10)     NOT NULL,   -- 'January' …
    quarter             SMALLINT        NOT NULL,   -- 1–4 (calendar)
    year                SMALLINT        NOT NULL,
    is_weekday          BOOLEAN         NOT NULL,   -- FALSE for Saturday and Sunday
    is_month_end        BOOLEAN         NOT NULL,   -- last calendar day of month
    is_quarter_end      BOOLEAN         NOT NULL,   -- last day of Mar, Jun, Sep, Dec
    is_year_end         BOOLEAN         NOT NULL,   -- December 31
    financial_year      VARCHAR(10)     NOT NULL,   -- 'FY2025-26'
    financial_quarter   VARCHAR(8)      NOT NULL,   -- 'Q1FY26'

    CONSTRAINT pk_dim_date          PRIMARY KEY (date_key),
    CONSTRAINT uq_dim_date_fulldate UNIQUE (full_date),
    CONSTRAINT chk_dim_date_dow     CHECK (day_of_week BETWEEN 1 AND 7),
    CONSTRAINT chk_dim_date_month   CHECK (month_num   BETWEEN 1 AND 12),
    CONSTRAINT chk_dim_date_quarter CHECK (quarter     BETWEEN 1 AND 4)
);

COMMENT ON TABLE dbo.Dim_Date IS
    'Date dimension 2015-01-01 – 2026-12-31. Includes Indian financial year columns for SEBI-aligned reporting.';

-- Supports monthly aggregations in rolling return calculations:
-- "all trading days in Apr-2025" filters on both columns.
CREATE INDEX IF NOT EXISTS idx_dim_date_year_month
    ON dbo.Dim_Date (year, month_num);

COMMENT ON INDEX dbo.idx_dim_date_year_month IS
    'Composite index for monthly grouping queries and financial quarter roll-ups.';
