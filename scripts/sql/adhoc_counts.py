import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

queries = [
    ("1. DISTINCT fund_key in vw_fund_performance", "SELECT COUNT(DISTINCT fund_key) FROM dbo.vw_fund_performance"),
    ("2. DISTINCT fund_key in Dim_Fund",            "SELECT COUNT(DISTINCT fund_key) FROM dbo.Dim_Fund"),
    ("3. COUNT(*) Dim_Fund",                        "SELECT COUNT(*) FROM dbo.Dim_Fund"),
    ("4. DISTINCT base_fund_name in Dim_Fund",      "SELECT COUNT(DISTINCT base_fund_name) FROM dbo.Dim_Fund"),
]
for label, q in queries:
    cur.execute(q)
    print(f"{label:<48} = {cur.fetchone()[0]:,}")

conn.close()
