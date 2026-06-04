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
    SELECT ORDINAL_POSITION, COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'vw_fund_performance'
    ORDER BY ORDINAL_POSITION
""")
print(f"{'#':>3}  {'COLUMN_NAME':<22}{'DATA_TYPE'}")
print("-" * 45)
for r in cur.fetchall():
    print(f"{r[0]:>3}  {r[1]:<22}{r[2]}")

conn.close()
