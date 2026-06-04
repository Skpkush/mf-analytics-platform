import os; from pathlib import Path; import pyodbc; from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
cs = (f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};SERVER={os.getenv('AZURE_SQL_SERVER')};"
      f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};UID={os.getenv('AZURE_SQL_USER')};"
      f"PWD={os.getenv('AZURE_SQL_PASSWORD')};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
conn = pyodbc.connect(cs, autocommit=True)
with conn.cursor() as cur:
    cur.execute("SELECT fund_key, source, scheme_code, fund_name, short_name FROM dbo.Dim_Fund WHERE source LIKE 'yahoo%' ORDER BY fund_key")
    rows = cur.fetchall()
print(f"Yahoo funds ({len(rows)} rows):")
print(f"  {'fund_key':>8}  {'source':<20}  {'scheme_code':<20}  short_name")
print("  " + "-"*70)
for r in rows:
    print(f"  {r[0]:>8}  {r[1]:<20}  {r[2]:<20}  {r[4]}")
conn.close()
