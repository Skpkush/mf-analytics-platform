-- ============================================================
-- vw_fund_performance
-- One-stop view for the Power BI Fund Performance page.
-- Joins all computed metrics with fund, AMC, and category context.
--
-- Grain: one row per fund with at least one metric populated.
-- LEFT JOINs on Dim_AMC and Dim_Category because Yahoo ETF/benchmark
-- funds have NULL amc_key and category_key.
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_fund_performance AS
WITH returns_data AS (
    SELECT
        fr.fund_key,
        fr.date_key,
        dd.full_date                AS as_of_date,
        fr.return_1y,
        fr.return_3y,
        fr.return_5y,
        fr.cagr_1y,
        fr.cagr_3y,
        fr.cagr_5y,
        fr.std_dev_1y,
        fr.max_drawdown,
        fr.sharpe_ratio,
        fr.sortino_ratio,
        fr.treynor_ratio,
        fr.alpha,
        fr.beta
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
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

    -- AMC context (NULL for Yahoo ETFs)
    da.amc_name,
    da.amc_short_name,

    -- Category context (NULL for Yahoo ETFs)
    dc.asset_class,
    dc.sub_category,
    dc.structure_type,

    -- Metric as-of date
    rd.as_of_date,

    -- Absolute returns (%)
    rd.return_1y,
    rd.return_3y,
    rd.return_5y,

    -- CAGR (%)
    rd.cagr_1y,
    rd.cagr_3y,
    rd.cagr_5y,

    -- Risk metrics
    rd.std_dev_1y,
    rd.max_drawdown,

    -- Risk-adjusted returns
    rd.sharpe_ratio,
    rd.sortino_ratio,
    rd.treynor_ratio,

    -- Market metrics
    rd.alpha,
    rd.beta
FROM returns_data rd
JOIN  dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC  da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key;

COMMENT ON VIEW dbo.vw_fund_performance IS
    'Complete fund metrics with AMC and category context. One row per fund with ≥1 metric. Primary source for Power BI Fund Performance page.';
