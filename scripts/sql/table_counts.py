import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

# Tables and views Power BI imports
objects = [
    ("Dim_Date",                 "table"),
    ("Dim_AMC",                  "table"),
    ("Dim_Category",             "table"),
    ("Dim_Fund",                 "table"),
    ("Dim_Investor",             "table"),
    ("Fact_NAV",                 "table"),
    ("Fact_Transactions",        "table"),
    ("Fact_SIP",                 "table"),
    ("Fact_Returns",             "table"),
    ("vw_fund_performance",      "view"),
    ("vw_risk_summary",          "view"),
    ("vw_investor_segmentation", "view"),
    ("vw_aum_summary",           "view"),
]

print(f"{'OBJECT':<28}{'TYPE':<8}{'ROWS':>14}")
print("-" * 50)
total = 0
for name, kind in objects:
    try:
        cur.execute(f"SELECT COUNT(*) FROM dbo.{name}")
        n = cur.fetchone()[0]
        total += n
        print(f"{name:<28}{kind:<8}{n:>14,}")
    except Exception as e:
        print(f"{name:<28}{kind:<8}{'N/A (' + str(e)[:20] + ')':>14}")

print("-" * 50)
print(f"{'TOTAL':<36}{total:>14,}")

conn.close()
