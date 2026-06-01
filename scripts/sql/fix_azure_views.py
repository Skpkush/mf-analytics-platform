"""Deploy SQL views to Azure SQL.

Reads the canonical view definitions from scripts/sql/views/*.sql and
applies them with CREATE OR ALTER VIEW. Safe to re-run (idempotent).

Views deployed:
    dbo.vw_fund_performance
    dbo.vw_risk_summary
"""
import os
import re
import sys
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VIEWS_DIR    = PROJECT_ROOT / "scripts" / "sql" / "views"

SERVER   = os.environ["AZURE_SQL_SERVER"]
DATABASE = os.environ["AZURE_SQL_DATABASE"]
USER     = os.environ["AZURE_SQL_USER"]
PASSWORD = os.environ["AZURE_SQL_PASSWORD"]
DRIVER   = os.environ.get("AZURE_SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")

CONN_STR = (
    f"DRIVER={DRIVER};SERVER={SERVER};DATABASE={DATABASE};"
    f"UID={USER};PWD={PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)

VIEWS = ["vw_fund_performance", "vw_risk_summary"]

VERIFY_SQL = """
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = ? AND TABLE_SCHEMA = 'dbo'
    ORDER BY ORDINAL_POSITION
"""


def load_ddl(view_name: str) -> str:
    """
    Load view DDL from the SQL file, stripping PostgreSQL-only syntax
    (COMMENT ON VIEW, trailing semicolons after the body) so it runs on T-SQL.
    """
    path = VIEWS_DIR / f"{view_name}.sql"
    raw = path.read_text(encoding="utf-8")

    # Remove COMMENT ON VIEW ... ; blocks (PostgreSQL-only)
    raw = re.sub(r"COMMENT\s+ON\s+VIEW\s+.*?;", "", raw, flags=re.DOTALL | re.IGNORECASE)

    # Strip leading/trailing whitespace
    ddl = raw.strip()

    # Remove trailing semicolon if present (T-SQL doesn't need it for DDL)
    if ddl.endswith(";"):
        ddl = ddl[:-1].rstrip()

    return ddl


def main() -> None:
    print(f"Connecting to {SERVER}/{DATABASE} ...")
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
    except Exception as exc:
        print(f"  CONNECTION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    cursor = conn.cursor()

    for view_name in VIEWS:
        ddl = load_ddl(view_name)
        print(f"\n-- Deploying dbo.{view_name} ...")
        try:
            cursor.execute(ddl)
            print(f"   OK")
        except Exception as exc:
            print(f"   FAILED: {exc}", file=sys.stderr)
            conn.close()
            sys.exit(1)

        cursor.execute(VERIFY_SQL, view_name)
        col_names = [r[0] for r in cursor.fetchall()]
        dupes = [c for c in col_names if col_names.count(c) > 1]
        print(f"   Columns ({len(col_names)}): {', '.join(col_names)}")
        if dupes:
            print(f"   WARNING -- duplicate columns: {set(dupes)}", file=sys.stderr)
        else:
            print(f"   No duplicate columns. View is clean.")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
