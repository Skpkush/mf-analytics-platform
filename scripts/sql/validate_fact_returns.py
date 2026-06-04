import os; from pathlib import Path; import pyodbc; from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
cs = (f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};SERVER={os.getenv('AZURE_SQL_SERVER')};"
      f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};UID={os.getenv('AZURE_SQL_USER')};"
      f"PWD={os.getenv('AZURE_SQL_PASSWORD')};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
conn = pyodbc.connect(cs, autocommit=True)

# Query 1
with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM dbo.Fact_Returns")
    print(f"Query 1 — total_funds in Fact_Returns: {cur.fetchone()[0]}\n")

# Query 2
with conn.cursor() as cur:
    cur.execute("""
        SELECT fund_key, cagr_1y, cagr_3y, cagr_5y,
               sharpe_ratio, beta, alpha, max_drawdown
        FROM dbo.Fact_Returns
        ORDER BY cagr_5y DESC
    """)
    rows = cur.fetchall()
print("Query 2 — Fact_Returns ordered by cagr_5y DESC:")
print(f"  {'fund_key':>8}  {'cagr_1y':>8}  {'cagr_3y':>8}  {'cagr_5y':>8}  {'sharpe':>7}  {'beta':>7}  {'alpha':>8}  max_drawdown")
print("  " + "-"*82)
for r in rows:
    def f(v): return f"{float(v):>8.2f}" if v is not None else "    NULL"
    print(f"  {r[0]:>8}  {f(r[1])}  {f(r[2])}  {f(r[3])}  {f(r[4])}  {f(r[5])}  {f(r[6])}  {f(r[7])}")

# Query 3
with conn.cursor() as cur:
    cur.execute("""
        SELECT f.short_name, r.cagr_1y, r.cagr_3y, r.cagr_5y,
               r.sharpe_ratio, r.beta, r.alpha, r.max_drawdown
        FROM dbo.Fact_Returns r
        JOIN dbo.Dim_Fund f ON r.fund_key = f.fund_key
        ORDER BY r.cagr_5y DESC
    """)
    rows = cur.fetchall()
print(f"\nQuery 3 — with fund names, ordered by cagr_5y DESC:")
print(f"  {'fund_name':<22}  {'cagr_1y':>8}  {'cagr_3y':>8}  {'cagr_5y':>8}  {'sharpe':>7}  {'beta':>7}  {'alpha':>8}  max_drawdown")
print("  " + "-"*100)
for r in rows:
    def f(v): return f"{float(v):>8.2f}" if v is not None else "    NULL"
    print(f"  {(r[0] or ''):<22}  {f(r[1])}  {f(r[2])}  {f(r[3])}  {f(r[4])}  {f(r[5])}  {f(r[6])}  {f(r[7])}")

conn.close()
