-- ============================================================
-- vw_aum_summary
-- Current AUM per fund — mirrors sp_compute_aum() logic as a
-- plain view (no date parameter; always returns latest state).
--
-- Grain: one row per fund with positive units outstanding.
-- AUM (INR) = total_current_units_held × latest_nav
--
-- Data sources:
--   current_units_held → Fact_SIP (latest month per investor×fund)
--   nav               → Fact_NAV (latest date per fund)
--
-- Power BI usage:
--   SUM(vw_aum_summary[aum_inr]) gives total portfolio AUM.
--   DAX: "₹" & FORMAT(SUM(vw_aum_summary[aum_inr]) / 10000000, "0.00") & " Cr"
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_aum_summary AS
WITH latest_sip AS (
    -- Most recent Fact_SIP row per investor-fund.
    -- current_units_held is cumulative net units (purchased minus redeemed),
    -- so the last row gives live holdings without summing history.
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
),
fund_units AS (
    SELECT
        fund_key,
        SUM(current_units_held) AS total_units
    FROM latest_sip
    WHERE rn = 1
    GROUP BY fund_key
),
latest_nav AS (
    -- Most recent NAV per fund across the entire Fact_NAV history.
    SELECT
        fn.fund_key,
        fn.nav,
        ROW_NUMBER() OVER (
            PARTITION BY fn.fund_key
            ORDER BY dd.full_date DESC
        ) AS rn
    FROM dbo.Fact_NAV fn
    JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
)
SELECT
    df.scheme_code,
    df.fund_name,
    da.amc_name,
    fu.total_units,
    ln.nav                      AS nav_price,
    fu.total_units * ln.nav     AS aum_inr
FROM fund_units fu
JOIN  latest_nav    ln  ON ln.fund_key  = fu.fund_key AND ln.rn = 1
JOIN  dbo.Dim_Fund  df  ON df.fund_key  = fu.fund_key
LEFT JOIN dbo.Dim_AMC da ON da.amc_key  = df.amc_key
WHERE fu.total_units > 0;

COMMENT ON VIEW dbo.vw_aum_summary IS
    'Current AUM per fund: latest net units from Fact_SIP × latest NAV from Fact_NAV. One row per fund. Sum aum_inr for total portfolio AUM.';
