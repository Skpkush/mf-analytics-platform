"""Push vw_aum_summary view to Azure SQL and verify row count + total AUM."""
from __future__ import annotations

import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

VIEW_SQL = ROOT / "scripts" / "sql" / "views" / "vw_aum_summary.sql"


def _conn() -> pyodbc.Connection:
    cs = (
        f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};"
        f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
        f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
        f"UID={os.getenv('AZURE_SQL_USER')};"
        f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(cs, autocommit=True)


def main() -> None:
    sql = VIEW_SQL.read_text(encoding="utf-8")
    # Convert PostgreSQL syntax → T-SQL (same as push_ddl_to_azure.py)
    sql = sql.replace("CREATE OR REPLACE VIEW", "CREATE OR ALTER VIEW")
    # Strip COMMENT ON VIEW (not supported in Azure SQL)
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("COMMENT ON VIEW")]
    sql = "\n".join(lines)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print("vw_aum_summary created/updated on Azure SQL.")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), SUM(aum_inr), MAX(aum_inr) FROM dbo.vw_aum_summary")
            row = cur.fetchone()
            total = float(row[1]) if row[1] else 0.0
            top = float(row[2]) if row[2] else 0.0
            print(f"  Funds:      {row[0]}")
            print(f"  Total AUM:  INR {total:>14,.2f}  =  {total / 10_000_000:.2f} Cr")
            print(f"  Top fund:   INR {top:>14,.2f}  =  {top / 100_000:.2f} L")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
