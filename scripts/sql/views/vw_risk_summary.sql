-- vw_risk_summary  (v4 - Azure SQL T-SQL syntax)
-- asset_class_label is intentionally omitted: it is a DAX calculated column
-- in the Power BI model. Returning it from SQL causes a duplicate-name conflict.
CREATE OR ALTER VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT fr.fund_key, fr.std_dev_1y, fr.max_drawdown,
           fr.sharpe_ratio, fr.sortino_ratio, fr.beta, fr.alpha,
           fr.cagr_1y, fr.cagr_3y, fr.cagr_5y, dd.full_date AS as_of_date
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
    WHERE fr.std_dev_1y IS NOT NULL
)
SELECT
    df.fund_key,
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.source,
    df.is_benchmark,
    CASE WHEN df.is_benchmark = 1 THEN 'Other Scheme'
         ELSE COALESCE(dc.asset_class, 'Other Scheme') END             AS asset_class,
    CASE WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
         WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
         WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
         WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
         WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
         ELSE dc.sub_category END                                      AS sub_category,
    CASE WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark = 1 THEN 'NSE' ELSE da.amc_name END     AS amc_name,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.beta, rd.alpha,
    rd.cagr_1y, rd.cagr_3y, rd.cagr_5y,
    CASE WHEN rd.std_dev_1y <  5 THEN 'Very Low'
         WHEN rd.std_dev_1y < 10 THEN 'Low'
         WHEN rd.std_dev_1y < 18 THEN 'Medium'
         WHEN rd.std_dev_1y < 30 THEN 'High'
         ELSE 'Very High' END                                          AS risk_tier,
    rd.as_of_date
FROM risk_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key;
