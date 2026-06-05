-- ============================================================
-- vw_fund_performance  (v6 — fix asset_class via Dim_Category join)
--
-- Dialect: PostgreSQL (local is the primary post-Azure-trial DB).
--
-- asset_class fix (2026-06-05):
--   All funds in this view are ETFs / index benchmarks. Their
--   dim_fund.category_key was NULL, so the Dim_Category LEFT JOIN
--   produced NULL asset_class. Fixed in two parts:
--     1) Backfilled dim_fund.category_key for the 11 ETFs
--        (see scripts/sql/fix_asset_class_local.py) so the join
--        resolves. Benchmarks intentionally keep category_key NULL.
--     2) Dashboard-friendly asset_class CASE below, keyed off the
--        now-populated Dim_Category columns:
--          Index / Equity / Gold / Liquid / Debt / Hybrid
--
-- IDCW plans excluded: dividend payouts reset NAV, making CAGR
-- meaningless for performance comparison. Growth/Bonus/benchmarks
-- are the industry standard.
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_fund_performance AS
WITH returns_data AS (
    SELECT
        fr.fund_key,
        fr.date_key,
        dd.full_date   AS as_of_date,
        fr.return_1y,  fr.return_3y,  fr.return_5y,
        fr.cagr_1y,    fr.cagr_3y,    fr.cagr_5y,
        fr.std_dev_1y, fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio, fr.treynor_ratio,
        fr.alpha,      fr.beta
    FROM dbo.fact_returns fr
    JOIN dbo.dim_date dd ON dd.date_key = fr.date_key
    WHERE fr.cagr_1y IS NOT NULL
       OR fr.std_dev_1y IS NOT NULL
)
SELECT
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.plan_type,
    df.option_type,
    df.source,
    df.is_benchmark,

    CASE
        WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
        WHEN df.is_benchmark                                  THEN 'NSE'
        ELSE da.amc_name
    END AS amc_name,
    CASE
        WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
        WHEN df.is_benchmark                                  THEN 'NSE'
        ELSE da.amc_short_name
    END AS amc_short_name,

    -- Dashboard-friendly asset_class, sourced from the Dim_Category join.
    CASE
        WHEN df.is_benchmark                                   THEN 'Index'
        WHEN dc.asset_class  = 'Equity Scheme'                THEN 'Equity'
        WHEN dc.sub_category = 'Gold ETF'                     THEN 'Gold'
        WHEN dc.sub_category = 'Liquid Fund'                  THEN 'Liquid'
        WHEN dc.asset_class  = 'Debt Scheme'                  THEN 'Debt'
        WHEN dc.asset_class  = 'Hybrid Scheme'                THEN 'Hybrid'
        WHEN dc.sub_category IN ('Index Funds', 'Other  ETFs') THEN 'Equity'
        ELSE COALESCE(dc.asset_class, 'Other')
    END AS asset_class,

    CASE
        WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
        WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
        WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
        WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
        WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
        ELSE dc.sub_category
    END AS sub_category,

    COALESCE(dc.structure_type, 'Open Ended Schemes') AS structure_type,

    rd.as_of_date,
    rd.return_1y,  rd.return_3y,  rd.return_5y,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.treynor_ratio,
    rd.alpha,      rd.beta
FROM returns_data rd
JOIN      dbo.dim_fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.dim_amc      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.dim_category dc ON dc.category_key = df.category_key
WHERE df.is_benchmark
   OR df.option_type IN ('Growth', 'Bonus')
   OR df.option_type IS NULL;
