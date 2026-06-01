import pyodbc, os
from dotenv import load_dotenv
load_dotenv()

conn = pyodbc.connect(
    f"DRIVER={os.environ['AZURE_SQL_DRIVER']};SERVER={os.environ['AZURE_SQL_SERVER']};"
    f"DATABASE={os.environ['AZURE_SQL_DATABASE']};UID={os.environ['AZURE_SQL_USER']};"
    f"PWD={os.environ['AZURE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;"
)
cur = conn.cursor()

cur.execute("SELECT COUNT(*), SUM(aum_inr) FROM dbo.vw_aum_summary")
rows, total = cur.fetchone()
total = float(total)
print(f"vw_aum_summary rows : {rows:,}")
print(f"Total AUM           : Rs {total/1e7:,.2f} Cr  (Rs {total:,.0f})")

cur.execute("SELECT TOP 5 fund_name, amc_name, aum_inr FROM dbo.vw_aum_summary ORDER BY aum_inr DESC")
print("\nTop 5 funds by AUM:")
for r in cur.fetchall():
    print(f"  Rs {float(r[2])/1e7:>7,.2f} Cr  {r[1]:<22} {r[0][:45]}")

conn.close()
