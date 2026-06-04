import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

cur.execute("""
    SELECT
        asset_class,
        COUNT(*)        AS funds,
        AVG(cagr_1y)    AS avg_cagr_1y,
        AVG(cagr_3y)    AS avg_cagr_3y,
        AVG(std_dev_1y) AS avg_volatility
    FROM dbo.vw_fund_performance
    WHERE cagr_1y IS NOT NULL
        AND cagr_1y <= 100
        AND cagr_1y >= -50
    GROUP BY asset_class
    ORDER BY avg_cagr_1y DESC
""")
print(f"{'asset_class':<26}{'funds':>7}{'avg_cagr_1y':>13}{'avg_cagr_3y':>13}{'avg_vol':>10}")
print("-" * 70)
for r in cur.fetchall():
    c3 = f"{float(r[3]):.2f}" if r[3] is not None else "NULL"
    print(f"{r[0]:<26}{r[1]:>7,}{float(r[2]):>13.2f}{c3:>13}{float(r[4]):>10.2f}")

conn.close()
