"""Check row counts on all 9 tables in Azure SQL and report empty ones."""
import os
import sys
from dotenv import load_dotenv
import pyodbc

load_dotenv()

EXPECTED = {
    "Dim_Date":          4383,
    "Dim_AMC":           51,
    "Dim_Category":      50,
    "Dim_Fund":          14384,
    "Dim_Investor":      500,
    "Fact_NAV":          32607,
    "Fact_Transactions": 35280,
    "Fact_SIP":          28224,
    "Fact_Returns":      16,
}

SQL = """
SELECT 'Dim_AMC'          AS tbl, COUNT(*) AS rows FROM dbo.Dim_AMC          UNION ALL
SELECT 'Dim_Category',             COUNT(*)         FROM dbo.Dim_Category     UNION ALL
SELECT 'Dim_Date',                 COUNT(*)         FROM dbo.Dim_Date         UNION ALL
SELECT 'Dim_Fund',                 COUNT(*)         FROM dbo.Dim_Fund         UNION ALL
SELECT 'Dim_Investor',             COUNT(*)         FROM dbo.Dim_Investor     UNION ALL
SELECT 'Fact_NAV',                 COUNT(*)         FROM dbo.Fact_NAV         UNION ALL
SELECT 'Fact_Returns',             COUNT(*)         FROM dbo.Fact_Returns     UNION ALL
SELECT 'Fact_SIP',                 COUNT(*)         FROM dbo.Fact_SIP         UNION ALL
SELECT 'Fact_Transactions',        COUNT(*)         FROM dbo.Fact_Transactions
"""

conn = pyodbc.connect(
    f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};"
    f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
    f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
    f"UID={os.getenv('AZURE_SQL_USER')};"
    f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;",
    autocommit=True,
)

cur = conn.cursor()
cur.execute(SQL)
results = {r[0]: r[1] for r in cur.fetchall()}
conn.close()

print(f"\n{'Table':<25} {'Azure SQL':>10}  {'Expected':>10}  Status")
print("-" * 60)

empty = []
mismatch = []
for table, exp in EXPECTED.items():
    actual = results.get(table, -1)
    if actual == 0:
        status = "EMPTY"
        empty.append(table)
    elif actual != exp:
        status = f"MISMATCH (exp {exp:,})"
        mismatch.append(table)
    else:
        status = "OK"
    print(f"{table:<25} {actual:>10,}  {exp:>10,}  {status}")

print("-" * 60)
print(f"\nEmpty tables   : {empty if empty else 'none'}")
print(f"Mismatched     : {mismatch if mismatch else 'none'}")
print(f"Fully loaded   : {9 - len(empty) - len(mismatch)}/9")
