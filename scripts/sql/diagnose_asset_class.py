import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

DRIVER   = os.environ["AZURE_SQL_DRIVER"]
SERVER   = os.environ["AZURE_SQL_SERVER"]
DATABASE = os.environ["AZURE_SQL_DATABASE"]
USER     = os.environ["AZURE_SQL_USER"]
PASSWORD = os.environ["AZURE_SQL_PASSWORD"]

conn = pyodbc.connect(
    f"DRIVER={DRIVER};SERVER={SERVER};DATABASE={DATABASE};"
    f"UID={USER};PWD={PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

# 1. Category mapping for the 16 funds actually in the view
cur.execute("""
    SELECT
        df.fund_key, df.scheme_code, df.is_benchmark,
        df.category_key,
        dc.asset_class, dc.sub_category
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Fund df     ON df.fund_key     = fr.fund_key
    LEFT JOIN dbo.Dim_Category dc ON dc.category_key = df.category_key
    GROUP BY df.fund_key, df.scheme_code, df.is_benchmark, df.category_key,
             dc.asset_class, dc.sub_category
    ORDER BY df.is_benchmark DESC, df.scheme_code
""")
print("Category mapping for the 16 funds in the view:")
print(f"  {'scheme_code':15} {'is_bench':8} {'cat_key':8} {'asset_class':25} {'sub_category'}")
for r in cur.fetchall():
    print(f"  {str(r[1]):15} {str(r[2]):8} {str(r[3]):8} {str(r[4]):25} {r[5]}")

# 2. Fact_Returns vs Fact_NAV — how many funds have NAV data?
cur.execute("SELECT COUNT(DISTINCT fund_key) FROM dbo.Fact_NAV")
print(f"\nFact_NAV distinct funds: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM dbo.Fact_NAV")
print(f"Fact_NAV total rows: {cur.fetchone()[0]}")

# 3. Fact_NAV date range
cur.execute("""
    SELECT MIN(date_key), MAX(date_key), COUNT(DISTINCT date_key)
    FROM dbo.Fact_NAV
""")
row = cur.fetchone()
print(f"Fact_NAV date_key range: min={row[0]}  max={row[1]}  distinct_dates={row[2]}")

# 4. How many AMFI funds (non-Yahoo) are in Fact_NAV?
cur.execute("""
    SELECT df.source, COUNT(DISTINCT fn.fund_key) AS distinct_funds, COUNT(*) AS nav_rows
    FROM dbo.Fact_NAV fn
    JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
    GROUP BY df.source
    ORDER BY nav_rows DESC
""")
print("\nFact_NAV breakdown by source:")
for r in cur.fetchall():
    print(f"  source={r[0]:10}  distinct_funds={r[1]}  nav_rows={r[2]}")

conn.close()
