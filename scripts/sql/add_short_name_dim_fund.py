"""
Add short_name column to dbo.Dim_Fund in Azure SQL.

Logic:
  yahoo_etf / yahoo_benchmark  → fund_name  (already short: GOLDBEES, NIFTYBEES.NS)
  amfi                         → LEFT(base_fund_name, 15)

Note: source values are 'yahoo_etf', 'yahoo_benchmark', 'amfi'
      (not plain 'yahoo'), so CASE uses LIKE 'yahoo%'.
"""
from __future__ import annotations
import os
from pathlib import Path
import pyodbc
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

cs = (
    f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};"
    f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
    f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
    f"UID={os.getenv('AZURE_SQL_USER')};"
    f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)
conn = pyodbc.connect(cs, autocommit=True)

with conn.cursor() as cur:

    # Step 1: add column (idempotent check)
    cur.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'Dim_Fund' AND COLUMN_NAME = 'short_name'
        )
        ALTER TABLE dbo.Dim_Fund ADD short_name VARCHAR(50)
    """)
    print("short_name column: added (or already existed)")

    # Step 2: populate
    cur.execute("""
        UPDATE dbo.Dim_Fund
        SET short_name = CASE
            WHEN source LIKE 'yahoo%' THEN fund_name
            ELSE LEFT(base_fund_name, 15)
        END
    """)
    print(f"Rows updated: {cur.rowcount:,}")

    # Step 3: sample
    cur.execute("""
        SELECT TOP 10
            fund_key, scheme_code, source,
            fund_name, base_fund_name, short_name
        FROM dbo.Dim_Fund
        ORDER BY source, fund_key
    """)
    rows = cur.fetchall()

print("\nSample (10 rows):\n")
print(f"  {'fund_key':>8}  {'source':<18}  {'scheme_code':<20}  {'short_name':<18}  base_fund_name")
print("  " + "-" * 100)
for r in rows:
    fk, sc, src, fn, bfn, sn = r
    print(f"  {fk:>8}  {src:<18}  {sc:<20}  {(sn or ''):<18}  {bfn or fn}")

conn.close()
