"""Fix duplicate asset_class_label column in Azure SQL views.

Replaces PostgreSQL-syntax views with correct T-SQL CREATE OR ALTER VIEW.
Run once; safe to re-run (idempotent).
"""
import pyodbc
import os
import sys
from dotenv import load_dotenv

load_dotenv()

SERVER   = os.environ["AZURE_SQL_SERVER"]
DATABASE = os.environ["AZURE_SQL_DATABASE"]
USER     = os.environ["AZURE_SQL_USER"]
PASSWORD = os.environ["AZURE_SQL_PASSWORD"]
DRIVER   = os.environ.get("AZURE_SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")

CONN_STR = (
    f"DRIVER={DRIVER};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={USER};"
    f"PWD={PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)

# ── vw_fund_performance ───────────────────────────────────────────────────────
# NOTE: asset_class_label is intentionally excluded — it is a DAX calculated
# column in the Power BI model (SWITCH on asset_class/sub_category). Returning
# it from SQL as well causes a "name already used" conflict on refresh.
VW_FUND_PERFORMANCE = """
CREATE OR ALTER VIEW dbo.vw_fund_performance AS
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
    CASE WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark = 1 THEN 'NSE' ELSE da.amc_name END     AS amc_name,
    CASE WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark = 1 THEN 'NSE' ELSE da.amc_short_name END AS amc_short_name,
    CASE WHEN df.is_benchmark = 1 THEN 'Other Scheme'
         ELSE COALESCE(dc.asset_class, 'Other Scheme') END              AS asset_class,
    CASE WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
         WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
         WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
         WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
         WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
         ELSE dc.sub_category END                                       AS sub_category,
    COALESCE(dc.structure_type, 'Open Ended Schemes')                   AS structure_type,
    rd.as_of_date,
    rd.return_1y,  rd.return_3y,  rd.return_5y,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,
    rd.std_dev_1y, rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.treynor_ratio,
    rd.alpha, rd.beta
FROM returns_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
"""

# ── vw_risk_summary ───────────────────────────────────────────────────────────
# NOTE: asset_class_label excluded for same reason as vw_fund_performance.
VW_RISK_SUMMARY = """
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
         ELSE COALESCE(dc.asset_class, 'Other Scheme') END              AS asset_class,
    CASE WHEN df.scheme_code = '^NSEI'    THEN 'Nifty 50'
         WHEN df.scheme_code = '^NSEBANK' THEN 'Nifty Bank'
         WHEN df.scheme_code = '^CNXIT'   THEN 'Nifty IT'
         WHEN df.scheme_code = '^CRSLDX'  THEN 'Nifty 500'
         WHEN df.scheme_code = '^BSESN'   THEN 'Sensex'
         ELSE dc.sub_category END                                       AS sub_category,
    CASE WHEN df.is_benchmark = 1 AND df.scheme_code LIKE '^BSE%' THEN 'BSE'
         WHEN df.is_benchmark = 1 THEN 'NSE' ELSE da.amc_name END      AS amc_name,
    rd.std_dev_1y,  rd.max_drawdown,
    rd.sharpe_ratio, rd.sortino_ratio, rd.beta, rd.alpha,
    rd.cagr_1y,    rd.cagr_3y,    rd.cagr_5y,
    CASE WHEN rd.std_dev_1y <  5 THEN 'Very Low'
         WHEN rd.std_dev_1y < 10 THEN 'Low'
         WHEN rd.std_dev_1y < 18 THEN 'Medium'
         WHEN rd.std_dev_1y < 30 THEN 'High'
         ELSE 'Very High' END                                           AS risk_tier,
    rd.as_of_date
FROM risk_data rd
JOIN      dbo.Dim_Fund     df ON df.fund_key     = rd.fund_key
LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
LEFT JOIN dbo.Dim_AMC      da ON da.amc_key      = df.amc_key
"""

VIEWS = [
    ("vw_fund_performance", VW_FUND_PERFORMANCE),
    ("vw_risk_summary",     VW_RISK_SUMMARY),
]

VERIFY_SQL = """
SELECT COLUMN_NAME
FROM INFORMATION_SCHEMA.VIEW_COLUMN_USAGE
WHERE VIEW_NAME = ?
ORDER BY ORDINAL_POSITION
"""

VERIFY_COLS_SQL = """
SELECT COLUMN_NAME, ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = ? AND TABLE_SCHEMA = 'dbo'
ORDER BY ORDINAL_POSITION
"""


def main() -> None:
    print(f"Connecting to {SERVER}/{DATABASE} ...")
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
    except Exception as exc:
        print(f"  CONNECTION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    cursor = conn.cursor()

    for view_name, ddl in VIEWS:
        print(f"\n-- Applying CREATE OR ALTER VIEW dbo.{view_name} ...")
        try:
            cursor.execute(ddl)
            print(f"   OK")
        except Exception as exc:
            print(f"   FAILED: {exc}", file=sys.stderr)
            conn.close()
            sys.exit(1)

        # Verify: count columns and check for duplicates
        cursor.execute(VERIFY_COLS_SQL, view_name)
        rows = cursor.fetchall()
        col_names = [r[0] for r in rows]
        dupes = [c for c in col_names if col_names.count(c) > 1]

        print(f"   Columns ({len(col_names)}): {', '.join(col_names)}")
        if dupes:
            print(f"   WARNING — duplicate columns still present: {set(dupes)}", file=sys.stderr)
        else:
            print(f"   No duplicate columns. View is clean.")

    conn.close()
    print("\nDone. Both views fixed on Azure SQL.")


if __name__ == "__main__":
    main()
