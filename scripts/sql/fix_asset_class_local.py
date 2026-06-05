"""
Fix asset_class NULL issue in dbo.vw_fund_performance / vw_risk_summary
(local PostgreSQL).

Root cause (diagnosed 2026-06-05):
  Every fund surfaced by these views is an ETF or index benchmark, and ALL
  of them had dim_fund.category_key = NULL. The views LEFT JOIN Dim_Category
  on category_key, so dc.asset_class came back NULL for every row -> the
  deployed (stale) views exposed that NULL directly.

  The upstream cause is now fixed at source in scripts/etl/load_dimensions.py
  (Yahoo ETFs are classified to a category_key); this script also backfills
  the existing rows so the live DB is correct without a full reload.

Three-part fix:
  1. Backfill dim_fund.category_key for the 11 ETFs so the Dim_Category
     join actually resolves (benchmarks intentionally stay NULL and are
     classified as 'Index' in the views).
  2. Redeploy vw_fund_performance with the dashboard-friendly asset_class
     CASE (Index / Equity / Gold / Liquid / Debt / Hybrid) keyed off the
     now-populated Dim_Category columns.
  3. Redeploy vw_risk_summary with the same asset_class CASE.

Run:  ./venv/Scripts/python.exe scripts/sql/fix_asset_class_local.py
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Dim_Category target keys (see dbo.dim_category) ──────────────────────────
CAT_GOLD_ETF = 46  # asset_class 'Other Scheme', sub_category 'Gold ETF'
CAT_OTHER_ETF = 48  # asset_class 'Other Scheme', sub_category 'Other  ETFs'
CAT_LIQUID = 12  # asset_class 'Debt Scheme',  sub_category 'Liquid Fund'

# base_fund_name -> category_key. Benchmarks deliberately excluded (stay NULL).
ETF_CATEGORY_MAP: dict[str, int] = {
    "HDFC Nifty 50 ETF": CAT_OTHER_ETF,
    "ICICI Prudential Bharat 22 ETF": CAT_OTHER_ETF,
    "Motilal Oswal NASDAQ 100 ETF": CAT_OTHER_ETF,
    "Motilal Oswal Nifty 500 ETF": CAT_OTHER_ETF,
    "Nippon India ETF Bank BeES": CAT_OTHER_ETF,
    "Nippon India ETF Gold BeES": CAT_GOLD_ETF,
    "Nippon India ETF Junior BeES": CAT_OTHER_ETF,
    "Nippon India ETF Liquid BeES": CAT_LIQUID,
    "Nippon India ETF Nifty BeES": CAT_OTHER_ETF,
    "SBI ETF Nifty 50": CAT_OTHER_ETF,
    "SBI ETF Nifty Bank": CAT_OTHER_ETF,
}

# ── Corrected view definition (PostgreSQL) ───────────────────────────────────
# DROP + CREATE (not CREATE OR REPLACE) because the column set/order changes.
DROP_VIEW = "DROP VIEW IF EXISTS dbo.vw_fund_performance;"

CREATE_VIEW = """
CREATE VIEW dbo.vw_fund_performance AS
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
"""

# ── vw_risk_summary: same asset_class CASE, deployed column order kept ───────
DROP_RISK_VIEW = "DROP VIEW IF EXISTS dbo.vw_risk_summary;"

CREATE_RISK_VIEW = """
CREATE VIEW dbo.vw_risk_summary AS
WITH risk_data AS (
    SELECT
        fr.fund_key,
        fr.std_dev_1y, fr.max_drawdown,
        fr.sharpe_ratio, fr.sortino_ratio,
        fr.beta,       fr.alpha,
        fr.cagr_1y,    fr.cagr_3y,    fr.cagr_5y,
        dd.full_date   AS as_of_date
    FROM dbo.fact_returns fr
    JOIN dbo.dim_date dd ON dd.date_key = fr.date_key
    WHERE fr.std_dev_1y IS NOT NULL
)
SELECT
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.source,
    df.is_benchmark,

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
JOIN      dbo.dim_fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.dim_category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.dim_amc      da ON da.amc_key      = df.amc_key;
"""


def get_conn() -> "psycopg2.extensions.connection":
    """Open a connection to the local PostgreSQL primary DB."""
    return psycopg2.connect(
        host=os.environ["LOCAL_DB_HOST"],
        port=os.environ["LOCAL_DB_PORT"],
        dbname=os.environ["LOCAL_DB_NAME"],
        user=os.environ["LOCAL_DB_USER"],
        password=os.environ["LOCAL_DB_PASSWORD"],
    )


def backfill_category_keys(cur: "psycopg2.extensions.cursor") -> int:
    """Set dim_fund.category_key for the ETF funds. Returns rows updated."""
    total = 0
    for fund_name, cat_key in ETF_CATEGORY_MAP.items():
        cur.execute(
            """
            UPDATE dbo.dim_fund
               SET category_key = %s
             WHERE base_fund_name = %s
               AND is_benchmark = FALSE
               AND category_key IS NULL
            """,
            (cat_key, fund_name),
        )
        if cur.rowcount:
            log.info("  category_key=%-2s -> %s (%d row/s)", cat_key, fund_name, cur.rowcount)
        total += cur.rowcount
    return total


def main() -> None:
    conn = get_conn()
    conn.autocommit = False
    cur = conn.cursor()

    log.info("Step 1/3: backfilling dim_fund.category_key for ETFs ...")
    updated = backfill_category_keys(cur)
    log.info("  %d dim_fund row(s) updated", updated)

    log.info("Step 2/3: redeploying dbo.vw_fund_performance ...")
    cur.execute(DROP_VIEW)
    cur.execute(CREATE_VIEW)
    conn.commit()
    log.info("  view recreated OK")

    log.info("Step 3/3: redeploying dbo.vw_risk_summary ...")
    cur.execute(DROP_RISK_VIEW)
    cur.execute(CREATE_RISK_VIEW)
    conn.commit()
    log.info("  view recreated OK")

    # Verify: asset_class distribution (the original symptom)
    print("\n" + "=" * 48)
    print("asset_class distribution after fix")
    print("=" * 48)
    cur.execute(
        """
        SELECT COALESCE(asset_class, '<NULL>') AS asset_class, COUNT(*) AS funds
        FROM dbo.vw_fund_performance
        GROUP BY asset_class
        ORDER BY funds DESC, asset_class
        """
    )
    print(f"{'asset_class':<16}{'funds':>7}")
    print("-" * 23)
    for ac, n in cur.fetchall():
        print(f"{ac:<16}{n:>7,}")

    # Verify: per-fund detail (the user's diagnostic intent)
    print("\n" + "=" * 70)
    print("per-fund: base_fund_name -> asset_class / sub_category")
    print("=" * 70)
    cur.execute(
        """
        SELECT base_fund_name, is_benchmark, asset_class, sub_category
        FROM dbo.vw_fund_performance
        ORDER BY asset_class, base_fund_name
        """
    )
    print(f"{'fund':<34}{'bench':<7}{'asset_class':<12}{'sub_category'}")
    print("-" * 70)
    for name, bench, ac, sub in cur.fetchall():
        print(f"{str(name)[:33]:<34}{str(bench):<7}{str(ac):<12}{sub}")

    # Verify: vw_risk_summary asset_class distribution
    print("\n" + "=" * 48)
    print("vw_risk_summary asset_class distribution")
    print("=" * 48)
    cur.execute(
        """
        SELECT COALESCE(asset_class, '<NULL>') AS asset_class, COUNT(*) AS funds
        FROM dbo.vw_risk_summary
        GROUP BY asset_class
        ORDER BY funds DESC, asset_class
        """
    )
    print(f"{'asset_class':<16}{'funds':>7}")
    print("-" * 23)
    for ac, n in cur.fetchall():
        print(f"{ac:<16}{n:>7,}")

    cur.close()
    conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
