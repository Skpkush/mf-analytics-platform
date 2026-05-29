-- ============================================================
-- vw_risk_summary
-- Risk dashboard view — fund risk metrics with SEBI-aligned
-- risk tier classification and category context.
--
-- risk_tier thresholds mirror SEBI's Riskometer categories:
--   Very Low  : std_dev < 5%   (e.g. Liquid, Overnight funds)
--   Low       : std_dev < 10%  (e.g. Short Duration debt)
--   Medium    : std_dev < 18%  (e.g. Large Cap equity)
--   High      : std_dev < 30%  (e.g. Mid/Small Cap, Sectoral)
--   Very High : std_dev >= 30% (e.g. Gold ETFs, NASDAQ ETFs)
--
-- Only funds with std_dev_1y populated are included.
-- Used by Power BI Page 4 (Risk & Volatility) and Streamlit
-- risk comparison tool.
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT
        fr.fund_key,
        fr.std_dev_1y,
        fr.max_drawdown,
        fr.sharpe_ratio,
        fr.sortino_ratio,
        fr.beta,
        fr.alpha,
        fr.cagr_1y,
        fr.cagr_3y,
        fr.cagr_5y,
        dd.full_date AS as_of_date
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
    WHERE fr.std_dev_1y IS NOT NULL
)
SELECT
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.source,
    df.is_benchmark,

    -- Category context
    dc.asset_class,
    dc.sub_category,
    da.amc_name,

    -- Risk metrics
    rd.std_dev_1y,
    rd.max_drawdown,
    rd.sharpe_ratio,
    rd.sortino_ratio,
    rd.beta,
    rd.alpha,

    -- Return context for risk-return scatter plot
    rd.cagr_1y,
    rd.cagr_3y,
    rd.cagr_5y,

    -- SEBI Riskometer-aligned tier
    CASE
        WHEN rd.std_dev_1y < 5  THEN 'Very Low'
        WHEN rd.std_dev_1y < 10 THEN 'Low'
        WHEN rd.std_dev_1y < 18 THEN 'Medium'
        WHEN rd.std_dev_1y < 30 THEN 'High'
        ELSE                         'Very High'
    END AS risk_tier,

    rd.as_of_date
FROM risk_data rd
JOIN dbo.Dim_Fund df           ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc  ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da  ON da.amc_key      = df.amc_key;

COMMENT ON VIEW dbo.vw_risk_summary IS
    'Fund risk metrics with SEBI riskometer tier classification. Filtered to funds with std_dev_1y populated. Drives Power BI Risk & Volatility page.';
