import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM dbo.vw_fund_performance")
print(f"vw_fund_performance rows : {cur.fetchone()[0]:,}")

cur.execute("SELECT COUNT(*) FROM dbo.vw_fund_performance WHERE option_type = 'IDCW'")
print(f"IDCW rows remaining      : {cur.fetchone()[0]:,}")

cur.execute("SELECT option_type, COUNT(*) AS cnt FROM dbo.vw_fund_performance GROUP BY option_type ORDER BY cnt DESC")
print("\nBreakdown by option_type:")
for r in cur.fetchall():
    print(f"  {str(r[0]):15}  {r[1]:,}")

conn.close()
