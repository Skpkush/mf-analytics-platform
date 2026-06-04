import os; from pathlib import Path; import pyodbc; from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
cs = (f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};SERVER={os.getenv('AZURE_SQL_SERVER')};"
      f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};UID={os.getenv('AZURE_SQL_USER')};"
      f"PWD={os.getenv('AZURE_SQL_PASSWORD')};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
conn = pyodbc.connect(cs, autocommit=True)
with conn.cursor() as cur:
    cur.execute("UPDATE dbo.Dim_Fund SET short_name = scheme_code WHERE source LIKE 'yahoo%'")
    print(f"Rows updated: {cur.rowcount}")
    cur.execute("SELECT fund_key, source, scheme_code, short_name FROM dbo.Dim_Fund WHERE source LIKE 'yahoo%' ORDER BY fund_key")
    rows = cur.fetchall()
print(f"\n{'fund_key':>8}  {'source':<20}  {'scheme_code':<20}  short_name")
print("-"*70)
for r in rows:
    print(f"{r[0]:>8}  {r[1]:<20}  {r[2]:<20}  {r[3]}")
conn.close()
