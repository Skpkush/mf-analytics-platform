import os; from pathlib import Path; import pyodbc; from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
cs = (f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};SERVER={os.getenv('AZURE_SQL_SERVER')};"
      f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};UID={os.getenv('AZURE_SQL_USER')};"
      f"PWD={os.getenv('AZURE_SQL_PASSWORD')};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
conn = pyodbc.connect(cs, autocommit=True)

with conn.cursor() as cur:
    cur.execute("UPDATE dbo.Fact_Returns SET sharpe_ratio = -10.0 WHERE sharpe_ratio < -10")
    print(f"Rows updated: {cur.rowcount}")

with conn.cursor() as cur:
    cur.execute("""
        SELECT f.short_name, r.cagr_5y, r.sharpe_ratio, r.max_drawdown
        FROM dbo.Fact_Returns r
        JOIN dbo.Dim_Fund f ON r.fund_key = f.fund_key
        ORDER BY r.sharpe_ratio DESC
    """)
    rows = cur.fetchall()

print(f"\n  {'fund':<22}  {'cagr_5y':>8}  {'sharpe':>8}  max_drawdown")
print("  " + "-"*55)
for r in rows:
    def f(v): return f"{float(v):>8.2f}" if v is not None else "    NULL"
    print(f"  {(r[0] or ''):<22}  {f(r[1])}  {f(r[2])}  {f(r[3])}")

conn.close()
