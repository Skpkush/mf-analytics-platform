-- ============================================================
-- sp_compute_aum(p_as_of_date DATE)
-- Compute total AUM per fund as of a given date.
--
-- Logic:
--   1. latest_sip  — for each investor-fund pair, take the row from
--                    Fact_SIP with the most recent month ≤ p_as_of_date.
--                    current_units_held is cumulative (already net of
--                    redemptions), so the last row gives live holdings.
--   2. fund_units  — sum current_units_held across all investors per fund.
--   3. latest_nav  — most recent NAV per fund ≤ p_as_of_date.
--   4. aum_inr     = total_units × nav_price
--
-- Implemented as a FUNCTION (not PROCEDURE) because PostgreSQL
-- functions can return TABLE result sets.
--
-- Usage:
--   SELECT * FROM dbo.sp_compute_aum('2026-05-28');
--   SELECT * FROM dbo.sp_compute_aum();          -- defaults to today
-- ============================================================

CREATE OR REPLACE FUNCTION dbo.sp_compute_aum(
    p_as_of_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    scheme_code  TEXT,
    fund_name    TEXT,
    amc_name     TEXT,
    total_units  NUMERIC,
    nav_price    NUMERIC,
    aum_inr      NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH latest_sip AS (
        -- Most recent Fact_SIP row per investor-fund on or before p_as_of_date.
        -- current_units_held is already cumulative (SIP units minus redemptions),
        -- so the last row gives live net units for that investor-fund pair.
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
        WHERE dd.full_date <= p_as_of_date
    ),
    fund_units AS (
        -- Total units held across all investors per fund
        SELECT
            fund_key,
            SUM(current_units_held) AS total_units
        FROM latest_sip
        WHERE rn = 1
        GROUP BY fund_key
    ),
    latest_nav AS (
        -- Most recent NAV per fund on or before p_as_of_date
        SELECT
            fn.fund_key,
            fn.nav,
            ROW_NUMBER() OVER (
                PARTITION BY fn.fund_key
                ORDER BY dd.full_date DESC
            ) AS rn
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
        WHERE dd.full_date <= p_as_of_date
    )
    SELECT
        df.scheme_code::TEXT,
        df.fund_name::TEXT,
        da.amc_name::TEXT,
        fu.total_units                 AS total_units,
        ln.nav                         AS nav_price,
        fu.total_units * ln.nav        AS aum_inr
    FROM fund_units fu
    JOIN latest_nav ln  ON ln.fund_key  = fu.fund_key AND ln.rn = 1
    JOIN dbo.Dim_Fund df ON df.fund_key = fu.fund_key
    LEFT JOIN dbo.Dim_AMC da ON da.amc_key = df.amc_key
    WHERE fu.total_units > 0
    ORDER BY (fu.total_units * ln.nav) DESC NULLS LAST
$$;

COMMENT ON FUNCTION dbo.sp_compute_aum(DATE) IS
    'Compute AUM per fund as of a given date: sum of investor net units × latest NAV. Ordered by AUM descending.';
