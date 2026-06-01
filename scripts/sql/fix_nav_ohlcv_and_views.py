"""
Fix 3 data issues:
  1. Fact_NAV: AMFI rows have NULL open_price/high_price/low_price/volume
     Fix: fill with nav (open=high=low=nav) and volume=0
  2. vw_fund_performance / vw_risk_summary: asset_class uses simplified
     labels ('Equity') that don't match Dim_Category ('Equity Scheme')
     Fix: restore asset_class = SEBI names, add asset_class_label = simplified
  3. vw_fund_performance needs scheme_code exposed so PBI can create
     the many-to-one relationship to Dim_Fund
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
    return pyodbc.connect(
        f"DRIVER={os.environ['AZURE_SQL_DRIVER']};"
        f"SERVER={os.environ['AZURE_SQL_SERVER']};"
        f"DATABASE={os.environ['AZURE_SQL_DATABASE']};"
        f"UID={os.environ['AZURE_SQL_USER']};"
        f"PWD={os.environ['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


# ── Fix 1: Fill AMFI Fact_NAV OHLCV blanks ──────────────────────────────────
FIX_NAV_OHLCV_SQL = """
UPDATE dbo.Fact_NAV
SET
    open_price = nav,
    high_price = nav,
    low_price  = nav,
    volume     = 0
WHERE source = 'amfi'
  AND open_price IS NULL;
"""

VERIFY_NAV_SQL = """
SELECT
    source,
    COUNT(*)                                       AS total_rows,
    SUM(CASE WHEN open_price IS NULL THEN 1 END)   AS open_blanks,
    SUM(CASE WHEN high_price IS NULL THEN 1 END)   AS high_blanks,
    SUM(CASE WHEN low_price  IS NULL THEN 1 END)   AS low_blanks,
    SUM(CASE WHEN volume     IS NULL THEN 1 END)   AS vol_blanks
FROM dbo.Fact_NAV
GROUP BY source
ORDER BY source;
"""


# ── Shared CASE blocks (T-SQL) ───────────────────────────────────────────────

# Restore original SEBI names — matches Dim_Category[asset_class]
ASSET_CLASS_SEBI = """
    CASE
        WHEN df.is_benchmark = 1 THEN 'Other Scheme'
        ELSE ISNULL(dc.asset_class, 'Other Scheme')
    END"""

# Simplified slicer label for Power BI (separate column)
ASSET_CLASS_LABEL = """
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

SUB_CATEGORY_CASE = """
    CASE
        WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
        WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
        WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
        WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
        WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
        ELSE dc.sub_category
    END"""


# ── Fix 2: ALTER vw_fund_performance ────────────────────────────────────────
ALTER_VW_FP = f"""
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
    df.fund_key,
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.plan_type,
    df.option_type,
    df.source,
    df.is_benchmark,

    -- AMC (NSE/BSE for benchmarks)
    {AMC_NAME_CASE}   AS amc_name,
    {AMC_SHORT_CASE}  AS amc_short_name,

    -- SEBI asset_class (matches Dim_Category for cross-filter relationships)
    {ASSET_CLASS_SEBI} AS asset_class,

    -- Simplified label for Power BI slicer (Equity / Gold / Liquid / Index etc.)
    {ASSET_CLASS_LABEL} AS asset_class_label,

    -- Sub-category (index name for benchmarks)
    {SUB_CATEGORY_CASE} AS sub_category,

    ISNULL(dc.structure_type, 'Open Ended Schemes') AS structure_type,

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


# ── Fix 2: ALTER vw_risk_summary ────────────────────────────────────────────
ALTER_VW_RS = f"""
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
    df.fund_key,
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.source,
    df.is_benchmark,

    -- SEBI asset_class
    {ASSET_CLASS_SEBI} AS asset_class,

    -- Simplified slicer label
    {ASSET_CLASS_LABEL} AS asset_class_label,

    {SUB_CATEGORY_CASE} AS sub_category,

    {AMC_NAME_CASE}   AS amc_name,

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


# ── Verify views after alter ─────────────────────────────────────────────────
VERIFY_FP_SQL = """
SELECT base_fund_name, asset_class, asset_class_label, sub_category,
       amc_name, is_benchmark
FROM dbo.vw_fund_performance
ORDER BY is_benchmark, cagr_5y DESC;
"""

VERIFY_RS_SQL = """
SELECT base_fund_name, asset_class, asset_class_label, sub_category,
       amc_name, risk_tier, is_benchmark
FROM dbo.vw_risk_summary
ORDER BY is_benchmark, std_dev_1y DESC;
"""


# ── Update SQL files on disk ─────────────────────────────────────────────────

VW_FP_FILE = """\
-- vw_fund_performance  (v3 - asset_class=SEBI, asset_class_label=simplified, fund_key+scheme_code exposed)
CREATE OR REPLACE VIEW dbo.vw_fund_performance AS
WITH returns_data AS (
    SELECT fr.fund_key, fr.date_key, dd.full_date AS as_of_date,
           fr.return_1y, fr.return_3y, fr.return_5y,
           fr.cagr_1y, fr.cagr_3y, fr.cagr_5y,
           fr.std_dev_1y, fr.max_drawdown,
           fr.sharpe_ratio, fr.sortino_ratio, fr.treynor_ratio,
           fr.alpha, fr.beta
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Date dd ON dd.date_key = fr.date_key
    WHERE fr.cagr_1y IS NOT NULL OR fr.std_dev_1y IS NOT NULL
)
SELECT
    df.fund_key,
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.plan_type,
    df.option_type,
    df.source,
    df.is_benchmark,
    CASE WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark THEN 'NSE' ELSE da.amc_name END     AS amc_name,
    CASE WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark THEN 'NSE' ELSE da.amc_short_name END AS amc_short_name,
    -- SEBI name (matches Dim_Category for PBI relationship chain)
    CASE WHEN df.is_benchmark THEN 'Other Scheme'
         ELSE COALESCE(dc.asset_class, 'Other Scheme') END         AS asset_class,
    -- Simplified label for slicer (Equity / Debt / Hybrid / Gold / Liquid / Index)
    CASE WHEN df.is_benchmark THEN 'Index'
         WHEN dc.asset_class  = 'Equity Scheme' THEN 'Equity'
         WHEN dc.sub_category = 'Gold ETF'       THEN 'Gold'
         WHEN dc.sub_category = 'Liquid Fund'    THEN 'Liquid'
         WHEN dc.asset_class  = 'Debt Scheme'    THEN 'Debt'
         WHEN dc.asset_class  = 'Hybrid Scheme'  THEN 'Hybrid'
         WHEN dc.sub_category IN ('Index Funds','Other  ETFs') THEN 'Equity'
         ELSE COALESCE(dc.asset_class, 'Other') END                AS asset_class_label,
    CASE WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
         WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
         WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
         WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
         WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
         ELSE dc.sub_category END                                  AS sub_category,
    COALESCE(dc.structure_type, 'Open Ended Schemes')              AS structure_type,
    rd.as_of_date,
    rd.return_1y, rd.return_3y, rd.return_5y,
    rd.cagr_1y, rd.cagr_3y, rd.cagr_5y,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.treynor_ratio,
    rd.alpha, rd.beta
FROM returns_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key;
"""

VW_RS_FILE = """\
-- vw_risk_summary  (v3 - asset_class=SEBI, asset_class_label=simplified, scheme_code exposed)
CREATE OR REPLACE VIEW dbo.vw_risk_summary AS
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
    CASE WHEN df.is_benchmark THEN 'Other Scheme'
         ELSE COALESCE(dc.asset_class, 'Other Scheme') END         AS asset_class,
    CASE WHEN df.is_benchmark THEN 'Index'
         WHEN dc.asset_class  = 'Equity Scheme' THEN 'Equity'
         WHEN dc.sub_category = 'Gold ETF'       THEN 'Gold'
         WHEN dc.sub_category = 'Liquid Fund'    THEN 'Liquid'
         WHEN dc.asset_class  = 'Debt Scheme'    THEN 'Debt'
         WHEN dc.asset_class  = 'Hybrid Scheme'  THEN 'Hybrid'
         WHEN dc.sub_category IN ('Index Funds','Other  ETFs') THEN 'Equity'
         ELSE COALESCE(dc.asset_class, 'Other') END                AS asset_class_label,
    CASE WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
         WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
         WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
         WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
         WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
         ELSE dc.sub_category END                                  AS sub_category,
    CASE WHEN df.is_benchmark AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark THEN 'NSE' ELSE da.amc_name END      AS amc_name,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.beta, rd.alpha,
    rd.cagr_1y, rd.cagr_3y, rd.cagr_5y,
    CASE WHEN rd.std_dev_1y <  5 THEN 'Very Low'
         WHEN rd.std_dev_1y < 10 THEN 'Low'
         WHEN rd.std_dev_1y < 18 THEN 'Medium'
         WHEN rd.std_dev_1y < 30 THEN 'High'
         ELSE 'Very High' END                                      AS risk_tier,
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

    # ── Fix 1: Fact_NAV OHLCV ───────────────────────────────────────────────
    log.info("Fix 1: Filling Fact_NAV OHLCV blanks for AMFI rows...")
    cur.execute(FIX_NAV_OHLCV_SQL)
    conn.commit()
    log.info("  Updated %d rows", cur.rowcount)

    print("\n=== Fact_NAV blank check after fix ===")
    cur.execute(VERIFY_NAV_SQL)
    rows = cur.fetchall()
    print(f"{'source':<15} {'total':>8} {'open_blanks':>12} {'high_blanks':>12} {'low_blanks':>11} {'vol_blanks':>11}")
    print("-" * 72)
    for r in rows:
        print(f"{str(r.source or ''):<15} {r.total_rows:>8} "
              f"{str(r.open_blanks or 0):>12} {str(r.high_blanks or 0):>12} "
              f"{str(r.low_blanks or 0):>11} {str(r.vol_blanks or 0):>11}")

    # ── Fix 2: ALTER views ───────────────────────────────────────────────────
    for name, sql in [
        ("vw_fund_performance", ALTER_VW_FP),
        ("vw_risk_summary",     ALTER_VW_RS),
    ]:
        log.info("Fix 2: Altering %s...", name)
        cur.execute(sql)
        conn.commit()
        log.info("  %s OK", name)

    # Verify views
    print("\n=== vw_fund_performance after fix ===")
    cur.execute(VERIFY_FP_SQL)
    rows = cur.fetchall()
    print(f"{'Fund':<40} {'asset_class':<18} {'asset_class_label':<10} {'sub_cat':<18} {'bench'}")
    print("-" * 100)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:40]:<40} "
              f"{str(r.asset_class or '')[:18]:<18} "
              f"{str(r.asset_class_label or ''):<10} "
              f"{str(r.sub_category or '')[:18]:<18} "
              f"{r.is_benchmark}")

    print("\n=== vw_risk_summary after fix ===")
    cur.execute(VERIFY_RS_SQL)
    rows = cur.fetchall()
    print(f"{'Fund':<40} {'asset_class':<18} {'label':<10} {'risk_tier':<12} {'bench'}")
    print("-" * 90)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:40]:<40} "
              f"{str(r.asset_class or '')[:18]:<18} "
              f"{str(r.asset_class_label or ''):<10} "
              f"{str(r.risk_tier or ''):<12} "
              f"{r.is_benchmark}")

    cur.close()
    conn.close()

    # Save updated SQL files
    Path("scripts/sql/views/vw_fund_performance.sql").write_text(VW_FP_FILE, encoding="utf-8")
    Path("scripts/sql/views/vw_risk_summary.sql").write_text(VW_RS_FILE, encoding="utf-8")
    log.info("SQL files updated on disk.")
    log.info("Done. Refresh Power BI and create relationship vw_fund_performance[scheme_code] -> Dim_Fund[scheme_code]")


if __name__ == "__main__":
    main()
