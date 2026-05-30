-- ============================================================
-- sp_top_funds_by_category(p_category, p_metric, p_top_n)
-- Return the top N funds in a given SEBI sub_category, ranked
-- by a specified Fact_Returns metric column.
--
-- Parameters:
--   p_category  VARCHAR(100)  — Dim_Category.sub_category value
--                               e.g. 'Large Cap Fund', 'Liquid Fund'
--   p_metric    VARCHAR(30)   — Any Fact_Returns metric column name
--                               Default: 'cagr_3y'
--   p_top_n     INT           — Number of rows to return. Default: 10
--
-- Metric ordering is always DESC NULLS LAST.
-- For most metrics (CAGR, Sharpe, Alpha) this returns the best-
-- performing funds first. For max_drawdown (negative values),
-- DESC returns the fund with the smallest drawdown first (best).
-- For std_dev_1y, DESC returns highest-volatility first (caller
-- should sort ASC for "most stable" funds).
--
-- Security: p_metric is validated against an explicit whitelist
-- before EXECUTE to prevent SQL injection via identifier injection.
--
-- Usage:
--   SELECT * FROM dbo.sp_top_funds_by_category('Large Cap Fund', 'cagr_3y', 5);
--   SELECT * FROM dbo.sp_top_funds_by_category('Liquid Fund', 'sharpe_ratio');
-- ============================================================

CREATE OR REPLACE FUNCTION dbo.sp_top_funds_by_category(
    p_category  VARCHAR(100),
    p_metric    VARCHAR(30) DEFAULT 'cagr_3y',
    p_top_n     INT         DEFAULT 10
)
RETURNS TABLE (
    rank_pos     INT,
    scheme_code  TEXT,
    fund_name    TEXT,
    sub_category TEXT,
    amc_name     TEXT,
    metric_value NUMERIC
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    -- Explicit whitelist prevents SQL injection via dynamic column name.
    -- Add new Fact_Returns columns here as metrics are added.
    v_allowed TEXT[] := ARRAY[
        'cagr_1y', 'cagr_3y', 'cagr_5y',
        'return_1y', 'return_3y', 'return_5y',
        'sharpe_ratio', 'sortino_ratio', 'treynor_ratio',
        'alpha', 'beta',
        'std_dev_1y', 'max_drawdown'
    ];
BEGIN
    -- Guard: reject any metric not in the whitelist
    IF p_metric != ALL(v_allowed) THEN
        RAISE EXCEPTION
            'Invalid metric "%". Allowed values: %',
            p_metric,
            array_to_string(v_allowed, ', ');
    END IF;

    -- Dynamic query: %I quotes identifier safely, %L quotes literal safely
    RETURN QUERY EXECUTE format(
        $sql$
            SELECT
                ROW_NUMBER() OVER (
                    ORDER BY fr.%I DESC NULLS LAST
                )::INT                      AS rank_pos,
                df.scheme_code::TEXT,
                df.fund_name::TEXT,
                dc.sub_category::TEXT,
                da.amc_name::TEXT,
                fr.%I::NUMERIC              AS metric_value
            FROM dbo.Fact_Returns fr
            JOIN dbo.Dim_Fund     df ON df.fund_key     = fr.fund_key
            JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
            LEFT JOIN dbo.Dim_AMC da ON da.amc_key      = df.amc_key
            WHERE dc.sub_category = %L
              AND fr.%I IS NOT NULL
            ORDER BY fr.%I DESC NULLS LAST
            LIMIT %s
        $sql$,
        p_metric,    -- %I — ORDER BY in ROW_NUMBER window
        p_metric,    -- %I — SELECT column
        p_category,  -- %L — WHERE literal value
        p_metric,    -- %I — WHERE IS NOT NULL
        p_metric,    -- %I — ORDER BY
        p_top_n      -- %s — LIMIT
    );
END;
$$;

COMMENT ON FUNCTION dbo.sp_top_funds_by_category(VARCHAR, VARCHAR, INT) IS
    'Return top N funds in a SEBI sub_category ranked by any Fact_Returns metric. Metric column validated against whitelist to prevent injection.';
