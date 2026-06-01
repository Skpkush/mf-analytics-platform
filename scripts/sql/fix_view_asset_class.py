"""
Fix blank columns in vw_fund_performance and vw_risk_summary.

Problems:
  1. Benchmark rows (^NSEI, ^NSEBANK etc.) show blank amc_name,
     asset_class, sub_category because they have no Dim_AMC /
     Dim_Category rows.
  2. All ETF funds show 'Other Scheme' as asset_class — Power BI
     asset-class slicer has no Equity or Hybrid option.

Fix: ALTER both views to add CASE expressions that:
  - Derive amc_name for benchmarks (NSE / BSE)
  - Map asset_class to simplified labels matching the dashboard
    slicer: Equity / Debt / Hybrid / Gold / Liquid / Index
  - Map sub_category for benchmark rows to the index name
"""

import os
import logging
import pyodbc
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def get_conn() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={os.environ['AZURE_SQL_DRIVER']};"
        f"SERVER={os.environ['AZURE_SQL_SERVER']};"
        f"DATABASE={os.environ['AZURE_SQL_DATABASE']};"
        f"UID={os.environ['AZURE_SQL_USER']};"
        f"PWD={os.environ['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


# ── Shared CASE blocks (T-SQL) ───────────────────────────────────────────────

AMC_NAME_CASE = """
    CASE
        WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
        WHEN df.is_benchmark = 1                                  THEN 'NSE'
        ELSE da.amc_name
    END"""

AMC_SHORT_CASE = """
    CASE
        WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
        WHEN df.is_benchmark = 1                                  THEN 'NSE'
        ELSE da.amc_short_name
    END"""

# Simplified asset_class labels for Power BI slicer
# Equity ETFs (index funds / other ETFs) → 'Equity'
# Gold ETF → 'Gold', Liquid → 'Liquid', Debt → 'Debt', Hybrid → 'Hybrid'
# Benchmarks (indices) → 'Index'
ASSET_CLASS_CASE = """
    CASE
        WHEN df.is_benchmark = 1                                   THEN 'Index'
        WHEN dc.asset_class  = 'Equity Scheme'                    THEN 'Equity'
        WHEN dc.sub_category = 'Gold ETF'                         THEN 'Gold'
        WHEN dc.sub_category = 'Liquid Fund'                      THEN 'Liquid'
        WHEN dc.asset_class  = 'Debt Scheme'                      THEN 'Debt'
        WHEN dc.asset_class  = 'Hybrid Scheme'                    THEN 'Hybrid'
        WHEN dc.sub_category IN ('Index Funds', 'Other  ETFs')    THEN 'Equity'
        ELSE ISNULL(dc.asset_class, 'Other')
    END"""

# Sub-category: use index name for benchmarks, else Dim_Category value
SUB_CATEGORY_CASE = """
    CASE
        WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
        WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
        WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
        WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
        WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
        ELSE dc.sub_category
    END"""

STRUCTURE_TYPE_CASE = "ISNULL(dc.structure_type, 'Open Ended Schemes')"


# ── Updated view definitions (T-SQL) ────────────────────────────────────────

VW_FUND_PERFORMANCE_SQL = f"""
ALTER VIEW dbo.vw_fund_performance AS
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

    {AMC_NAME_CASE}   AS amc_name,
    {AMC_SHORT_CASE}  AS amc_short_name,

    {ASSET_CLASS_CASE} AS asset_class,
    {SUB_CATEGORY_CASE} AS sub_category,
    {STRUCTURE_TYPE_CASE} AS structure_type,

    rd.as_of_date,
    rd.return_1y,  rd.return_3y,  rd.return_5y,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.treynor_ratio,
    rd.alpha,      rd.beta
FROM returns_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key;
"""

VW_RISK_SUMMARY_SQL = f"""
ALTER VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT
        fr.fund_key,
        fr.std_dev_1y, fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio,
        fr.beta,       fr.alpha,
        fr.cagr_1y,    fr.cagr_3y,    fr.cagr_5y,
        dd.full_date   AS as_of_date
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

    {ASSET_CLASS_CASE} AS asset_class,
    {SUB_CATEGORY_CASE} AS sub_category,
    {AMC_NAME_CASE}   AS amc_name,

    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio,
    rd.beta,       rd.alpha,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,

    CASE
        WHEN rd.std_dev_1y <  1  THEN 'Very Low'
        WHEN rd.std_dev_1y <  5  THEN 'Very Low'
        WHEN rd.std_dev_1y < 10  THEN 'Low'
        WHEN rd.std_dev_1y < 18  THEN 'Medium'
        WHEN rd.std_dev_1y < 30  THEN 'High'
        ELSE                          'Very High'
    END AS risk_tier,

    rd.as_of_date
FROM risk_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key;
"""

# ── Verification queries ─────────────────────────────────────────────────────

VERIFY_FP = """
SELECT
    base_fund_name,
    amc_name,
    amc_short_name,
    asset_class,
    sub_category,
    plan_type,
    option_type,
    is_benchmark
FROM dbo.vw_fund_performance
ORDER BY is_benchmark, cagr_5y DESC;
"""

VERIFY_RS = """
SELECT
    base_fund_name,
    amc_name,
    asset_class,
    sub_category,
    risk_tier,
    is_benchmark
FROM dbo.vw_risk_summary
ORDER BY is_benchmark, std_dev_1y DESC;
"""

# ── Updated SQL file content (PostgreSQL-compatible, for git history) ────────

VW_FP_FILE_SQL = """\
-- ============================================================
-- vw_fund_performance  (updated: fix asset_class + benchmark context)
-- One row per fund with at least one metric populated.
--
-- asset_class simplified for Power BI slicer:
--   Equity / Debt / Hybrid / Gold / Liquid / Index
-- Benchmark rows get NSE/BSE as amc_name and their index
-- name as sub_category.
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

    CASE
        WHEN df.is_benchmark                                   THEN 'Index'
        WHEN dc.asset_class  = 'Equity Scheme'                THEN 'Equity'
        WHEN dc.sub_category = 'Gold ETF'                     THEN 'Gold'
        WHEN dc.sub_category = 'Liquid Fund'                  THEN 'Liquid'
        WHEN dc.asset_class  = 'Debt Scheme'                  THEN 'Debt'
        WHEN dc.asset_class  = 'Hybrid Scheme'                THEN 'Hybrid'
        WHEN dc.sub_category IN ('Index Funds','Other  ETFs') THEN 'Equity'
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
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key;
"""

VW_RS_FILE_SQL = """\
-- ============================================================
-- vw_risk_summary  (updated: fix asset_class + benchmark context)
-- Risk metrics with SEBI-aligned tier + simplified asset_class.
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT
        fr.fund_key,
        fr.std_dev_1y, fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio,
        fr.beta,       fr.alpha,
        fr.cagr_1y,    fr.cagr_3y,    fr.cagr_5y,
        dd.full_date   AS as_of_date
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

    CASE
        WHEN df.is_benchmark                                   THEN 'Index'
        WHEN dc.asset_class  = 'Equity Scheme'                THEN 'Equity'
        WHEN dc.sub_category = 'Gold ETF'                     THEN 'Gold'
        WHEN dc.sub_category = 'Liquid Fund'                  THEN 'Liquid'
        WHEN dc.asset_class  = 'Debt Scheme'                  THEN 'Debt'
        WHEN dc.asset_class  = 'Hybrid Scheme'                THEN 'Hybrid'
        WHEN dc.sub_category IN ('Index Funds','Other  ETFs') THEN 'Equity'
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

    CASE
        WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
        WHEN df.is_benchmark                                  THEN 'NSE'
        ELSE da.amc_name
    END AS amc_name,

    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio,
    rd.beta,       rd.alpha,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,

    CASE
        WHEN rd.std_dev_1y <  5  THEN 'Very Low'
        WHEN rd.std_dev_1y < 10  THEN 'Low'
        WHEN rd.std_dev_1y < 18  THEN 'Medium'
        WHEN rd.std_dev_1y < 30  THEN 'High'
        ELSE                          'Very High'
    END AS risk_tier,

    rd.as_of_date
FROM risk_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key;
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Connecting to Azure SQL...")
    conn = get_conn()
    cur  = conn.cursor()

    # ALTER both views
    for name, sql in [
        ("vw_fund_performance", VW_FUND_PERFORMANCE_SQL),
        ("vw_risk_summary",     VW_RISK_SUMMARY_SQL),
    ]:
        log.info("Altering %s ...", name)
        cur.execute(sql)
        conn.commit()
        log.info("  %s updated OK", name)

    # Verify vw_fund_performance
    print("\n" + "="*110)
    print("vw_fund_performance — all rows")
    print("="*110)
    cur.execute(VERIFY_FP)
    rows = cur.fetchall()
    print(f"{'Fund':<42} {'AMC':<22} {'AMC Short':<14} {'Asset Class':<10} {'Sub-Category':<18} {'Plan':<5} {'Bench'}")
    print("-"*110)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:42]:<42} "
              f"{str(r.amc_name or 'NULL')[:22]:<22} "
              f"{str(r.amc_short_name or 'NULL')[:14]:<14} "
              f"{str(r.asset_class or 'NULL')[:10]:<10} "
              f"{str(r.sub_category or 'NULL')[:18]:<18} "
              f"{str(r.plan_type or '')[:5]:<5} "
              f"{str(r.is_benchmark)}")

    # Verify vw_risk_summary
    print("\n" + "="*110)
    print("vw_risk_summary — all rows")
    print("="*110)
    cur.execute(VERIFY_RS)
    rows = cur.fetchall()
    print(f"{'Fund':<42} {'AMC':<22} {'Asset Class':<10} {'Sub-Category':<18} {'Risk Tier':<12} {'Bench'}")
    print("-"*110)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:42]:<42} "
              f"{str(r.amc_name or 'NULL')[:22]:<22} "
              f"{str(r.asset_class or 'NULL')[:10]:<10} "
              f"{str(r.sub_category or 'NULL')[:18]:<18} "
              f"{str(r.risk_tier or 'NULL')[:12]:<12} "
              f"{str(r.is_benchmark)}")

    cur.close()
    conn.close()
    log.info("Done. Saving updated SQL files...")

    # Update SQL files on disk
    fp = Path("scripts/sql/views/vw_fund_performance.sql")
    rs = Path("scripts/sql/views/vw_risk_summary.sql")
    fp.write_text(VW_FP_FILE_SQL, encoding="utf-8")
    rs.write_text(VW_RS_FILE_SQL, encoding="utf-8")
    log.info("SQL files updated. Refresh Power BI Desktop to load changes.")


if __name__ == "__main__":
    main()
