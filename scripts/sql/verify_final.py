import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM dbo.Fact_Returns")
print(f"Fact_Returns rows : {cur.fetchone()[0]:,}")

cur.execute("SELECT COUNT(*) FROM dbo.Fact_NAV")
print(f"Fact_NAV rows     : {cur.fetchone()[0]:,}")

cur.execute("""
    SELECT asset_class, COUNT(*) AS cnt
    FROM dbo.vw_fund_performance
    GROUP BY asset_class ORDER BY cnt DESC
""")
print("\nvw_fund_performance asset_class breakdown:")
for r in cur.fetchall():
    print(f"  {str(r[0]):35s}  {r[1]:,}")

cur.execute("""
    SELECT TOP 5 fund_name, asset_class, cagr_1y, cagr_3y, sharpe_ratio
    FROM dbo.vw_fund_performance
    WHERE asset_class = 'Equity Scheme'
    ORDER BY cagr_1y DESC
""")
print("\nTop 5 Equity funds by 1Y CAGR:")
for r in cur.fetchall():
    print(f"  {str(r[1]):15} cagr_1y={str(r[2]):8} cagr_3y={str(r[3]):8} sharpe={r[4]}  {r[0][:50]}")

conn.close()
