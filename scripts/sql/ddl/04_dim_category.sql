-- ============================================================
-- 04_dim_category.sql
-- Fund category dimension, parsed from AMFI scheme_type strings.
-- 50 unique categories covering all SEBI-mandated fund buckets.
-- Populated by scripts/etl/load_dimensions.py (Day 4).
--
-- Source string example:
--   'Open Ended Schemes(Equity Scheme - Large Cap Fund)'
-- Parsed into:
--   structure_type = 'Open Ended Schemes'
--   asset_class    = 'Equity Scheme'
--   sub_category   = 'Large Cap Fund'
-- ============================================================

CREATE TABLE IF NOT EXISTS dbo.Dim_Category (
    category_key    SERIAL          NOT NULL,
    raw_category    VARCHAR(300)    NOT NULL,   -- original AMFI string, kept for auditability
    structure_type  VARCHAR(50)     NOT NULL,   -- 'Open Ended Schemes', 'Close Ended Schemes', 'Interval Fund Schemes'
    asset_class     VARCHAR(50)     NOT NULL,   -- 'Equity Scheme', 'Debt Scheme', 'Hybrid Scheme',
                                                -- 'Other Scheme', 'Solution Oriented Scheme'
    sub_category    VARCHAR(100)    NOT NULL,   -- 'Large Cap Fund', 'Liquid Fund', 'Gilt Fund' …

    CONSTRAINT pk_dim_category          PRIMARY KEY (category_key),
    CONSTRAINT uq_dim_category_raw      UNIQUE (raw_category)
);

COMMENT ON TABLE dbo.Dim_Category IS
    '50 SEBI fund categories parsed from AMFI scheme_type. Enables asset_class and sub_category slicing in Power BI.';
