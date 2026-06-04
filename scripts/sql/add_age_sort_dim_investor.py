"""
Add age_sort column to dbo.Dim_Investor and populate it for correct
age_group ordering in Power BI (Sort-By-Column on age_group -> age_sort).

Idempotent: re-running only re-applies the UPDATE; the column add is guarded.

Targets:
  --target local   (default) PostgreSQL via LOCAL_DB_* env vars
  --target azure   Azure SQL via AZURE_SQL_* env vars (needs IP whitelisted)
  --target both

Run: python scripts/sql/add_age_sort_dim_investor.py --target both
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# age_group -> sort order. Matches the 5 distinct values in Dim_Investor.
AGE_ORDER = [("18-25", 1), ("26-35", 2), ("36-45", 3), ("46-55", 4), ("55+", 5)]

UPDATE_CASE = (
    "UPDATE dbo.Dim_Investor SET age_sort = CASE age_group "
    + " ".join(f"WHEN '{g}' THEN {n}" for g, n in AGE_ORDER)
    + " ELSE 6 END"
)


def apply_postgres() -> None:
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ["LOCAL_DB_HOST"], port=os.environ["LOCAL_DB_PORT"],
        dbname=os.environ["LOCAL_DB_NAME"], user=os.environ["LOCAL_DB_USER"],
        password=os.environ["LOCAL_DB_PASSWORD"],
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE dbo.Dim_Investor ADD COLUMN IF NOT EXISTS age_sort INTEGER")
            cur.execute(UPDATE_CASE)
            cur.execute("SELECT age_group, age_sort, COUNT(*) FROM dbo.Dim_Investor "
                        "GROUP BY age_group, age_sort ORDER BY age_sort")
            print("[local Postgres] age_sort applied:")
            for g, s, c in cur.fetchall():
                print(f"   {s}  {g:<8} ({c})")
    finally:
        conn.close()


def apply_azure() -> None:
    import pyodbc
    cs = (f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
          f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
          f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=15;")
    conn = pyodbc.connect(cs, autocommit=True)
    try:
        cur = conn.cursor()
        # T-SQL guard: add column only if absent
        cur.execute(
            "IF COL_LENGTH('dbo.Dim_Investor', 'age_sort') IS NULL "
            "ALTER TABLE dbo.Dim_Investor ADD age_sort INT"
        )
        cur.execute(UPDATE_CASE)
        cur.execute("SELECT age_group, age_sort, COUNT(*) FROM dbo.Dim_Investor "
                    "GROUP BY age_group, age_sort ORDER BY age_sort")
        print("[Azure SQL] age_sort applied:")
        for g, s, c in cur.fetchall():
            print(f"   {s}  {g:<8} ({c})")
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["local", "azure", "both"], default="local")
    args = ap.parse_args()

    if args.target in ("local", "both"):
        try:
            apply_postgres()
        except Exception as e:  # noqa: BLE001
            print(f"[local Postgres] FAILED: {str(e)[:160]}")

    if args.target in ("azure", "both"):
        try:
            apply_azure()
        except Exception as e:  # noqa: BLE001
            print(f"[Azure SQL] FAILED (whitelist IP in Azure Portal firewall): {str(e)[:160]}")


if __name__ == "__main__":
    main()
