import os; from pathlib import Path; import pyodbc; from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
cs = (f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};SERVER={os.getenv('AZURE_SQL_SERVER')};"
      f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};UID={os.getenv('AZURE_SQL_USER')};"
      f"PWD={os.getenv('AZURE_SQL_PASSWORD')};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;")
conn = pyodbc.connect(cs, autocommit=True)

# ── Query 1: benchmark flag check ────────────────────────────────────────────
print("=" * 70)
print("Query 1 — is_benchmark flag for all funds in Fact_Returns")
print("=" * 70)
with conn.cursor() as cur:
    cur.execute("""
        SELECT f.scheme_code, f.fund_name, f.is_benchmark, f.source
        FROM dbo.Dim_Fund f
        JOIN dbo.Fact_Returns r ON f.fund_key = r.fund_key
        ORDER BY f.is_benchmark DESC, f.source
    """)
    rows = cur.fetchall()
print(f"  {'scheme_code':<20}  {'fund_name':<35}  {'is_benchmark':>12}  source")
print("  " + "-"*85)
for r in rows:
    print(f"  {(r[0] or ''):<20}  {(r[1] or ''):<35}  {str(r[2]):>12}  {r[3]}")

# ── Query 2: MON100 CAGR check ───────────────────────────────────────────────
print(f"\n{'=' * 70}")
print("Query 2 — MON100 (Motilal NASDAQ) CAGR values")
print("=" * 70)
with conn.cursor() as cur:
    cur.execute("""
        SELECT f.scheme_code, f.fund_name, r.cagr_1y, r.cagr_3y, r.cagr_5y
        FROM dbo.Fact_Returns r
        JOIN dbo.Dim_Fund f ON r.fund_key = f.fund_key
        WHERE f.scheme_code LIKE '%MON100%'
           OR f.fund_name   LIKE '%NASDAQ%'
    """)
    rows = cur.fetchall()
for r in rows:
    def f(v): return f"{float(v):.2f}%" if v is not None else "NULL"
    print(f"  scheme_code : {r[0]}")
    print(f"  fund_name   : {r[1]}")
    print(f"  cagr_1y     : {f(r[2])}")
    print(f"  cagr_3y     : {f(r[3])}")
    print(f"  cagr_5y     : {f(r[4])}")

# ── Query 3: MON100 NAV date range ───────────────────────────────────────────
print(f"\n{'=' * 70}")
print("Query 3 — MON100 NAV date range in Fact_NAV")
print("=" * 70)
with conn.cursor() as cur:
    # Fact_NAV has no date column — dates are in Dim_Date.full_date
    cur.execute("""
        SELECT
            MIN(dd.full_date) AS min_date,
            MAX(dd.full_date) AS max_date,
            COUNT(*)          AS row_count
        FROM dbo.Fact_NAV n
        JOIN dbo.Dim_Fund f  ON f.fund_key  = n.fund_key
        JOIN dbo.Dim_Date dd ON dd.date_key = n.date_key
        WHERE f.scheme_code LIKE '%MON100%'
           OR f.fund_name   LIKE '%NASDAQ%'
    """)
    r = cur.fetchone()
    print(f"  min_date  : {r[0]}")
    print(f"  max_date  : {r[1]}")
    print(f"  row_count : {r[2]:,}")

conn.close()
