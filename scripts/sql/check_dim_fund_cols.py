"""Query Dim_Fund column names from Azure SQL."""
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
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'Dim_Fund'
        ORDER BY ORDINAL_POSITION
    """)
    rows = cur.fetchall()

print(f"\nDim_Fund — {len(rows)} columns:\n")
for r in rows:
    print(f"  {r[0]:<25} {r[1]:<20} nullable={r[2]}")
conn.close()
