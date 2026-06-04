import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

def scalar(q):
    cur.execute(q)
    return cur.fetchone()

print("="*60)
print("  TABLE ROW COUNTS")
print("="*60)
tables = ["Dim_Date","Dim_AMC","Dim_Category","Dim_Fund","Dim_Investor",
          "Fact_NAV","Fact_Transactions","Fact_SIP","Fact_Returns"]
views  = ["vw_fund_performance","vw_risk_summary","vw_investor_segmentation","vw_aum_summary"]
total = 0
for t in tables:
    n = scalar(f"SELECT COUNT(*) FROM dbo.{t}")[0]; total += n
    print(f"  {t:<26}{n:>14,}")
print("  " + "-"*40)
print(f"  {'TABLE TOTAL':<26}{total:>14,}")
print()
for v in views:
    n = scalar(f"SELECT COUNT(*) FROM dbo.{v}")[0]
    print(f"  {v:<26}{n:>14,}  (view)")

print("\n" + "="*60)
print("  DIM_FUND breakdown")
print("="*60)
cur.execute("SELECT source, COUNT(*) FROM dbo.Dim_Fund GROUP BY source ORDER BY COUNT(*) DESC")
for r in cur.fetchall(): print(f"  source={r[0]:<18}{r[1]:>10,}")
print(f"  benchmarks (is_benchmark=1): {scalar('SELECT COUNT(*) FROM dbo.Dim_Fund WHERE is_benchmark=1')[0]:>6,}")

print("\n" + "="*60)
print("  FACT_NAV coverage")
print("="*60)
mn, mx, dd, fk = scalar("SELECT MIN(dd.full_date), MAX(dd.full_date), COUNT(DISTINCT fn.date_key), COUNT(DISTINCT fn.fund_key) FROM dbo.Fact_NAV fn JOIN dbo.Dim_Date dd ON dd.date_key=fn.date_key")
print(f"  Rows           : {scalar('SELECT COUNT(*) FROM dbo.Fact_NAV')[0]:>12,}")
print(f"  Date range     : {mn} -> {mx}")
print(f"  Distinct dates : {dd:>12,}")
print(f"  Distinct funds : {fk:>12,}")

print("\n" + "="*60)
print("  FACT_RETURNS metric coverage")
print("="*60)
for c in ["cagr_1y","cagr_3y","cagr_5y","std_dev_1y","sharpe_ratio","beta","alpha","treynor_ratio"]:
    n = scalar(f"SELECT COUNT(*) FROM dbo.Fact_Returns WHERE {c} IS NOT NULL")[0]
    print(f"  {c:<14} populated: {n:>8,}")

print("\n" + "="*60)
print("  vw_fund_performance by asset_class")
print("="*60)
cur.execute("SELECT asset_class, COUNT(*) FROM dbo.vw_fund_performance GROUP BY asset_class ORDER BY COUNT(*) DESC")
for r in cur.fetchall(): print(f"  {r[0]:<26}{r[1]:>8,}")

print("\n" + "="*60)
print("  INVESTOR / TRANSACTION summary")
print("="*60)
print(f"  Investors            : {scalar('SELECT COUNT(*) FROM dbo.Dim_Investor')[0]:>12,}")
print(f"  Transactions         : {scalar('SELECT COUNT(*) FROM dbo.Fact_Transactions')[0]:>12,}")
print(f"  SIP records          : {scalar('SELECT COUNT(*) FROM dbo.Fact_SIP')[0]:>12,}")
amt = float(scalar("SELECT SUM(amount) FROM dbo.Fact_Transactions WHERE transaction_type IN ('SIP','Lumpsum')")[0])
print(f"  Total invested       : Rs {amt/1e7:>10,.2f} Cr")
aum = float(scalar("SELECT SUM(aum_inr) FROM dbo.vw_aum_summary")[0])
print(f"  Current AUM          : Rs {aum/1e7:>10,.2f} Cr  ({scalar('SELECT COUNT(*) FROM dbo.vw_aum_summary')[0]} funds)")

print("\n" + "="*60)
print("  DATABASE SIZE")
print("="*60)
used = float(scalar("SELECT SUM(reserved_page_count)*8.0/1024.0 FROM sys.dm_db_partition_stats")[0])
print(f"  Used: {used:,.1f} MB / 2048 MB   ({2048-used:,.0f} MB free)")

conn.close()
