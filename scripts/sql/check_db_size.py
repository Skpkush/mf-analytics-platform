import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
import pyodbc

DRIVER   = os.environ["AZURE_SQL_DRIVER"]
SERVER   = os.environ["AZURE_SQL_SERVER"]
DATABASE = os.environ["AZURE_SQL_DATABASE"]
USER     = os.environ["AZURE_SQL_USER"]
PASSWORD = os.environ["AZURE_SQL_PASSWORD"]

cs = (f"DRIVER={DRIVER};SERVER={SERVER};DATABASE={DATABASE};"
      f"UID={USER};PWD={PASSWORD};"
      "Encrypt=yes;TrustServerCertificate=no;")
conn = pyodbc.connect(cs)
cur = conn.cursor()

cur.execute("SELECT SUM(reserved_page_count)*8.0/1024.0 FROM sys.dm_db_partition_stats")
used_mb = float(cur.fetchone()[0])
print(f"DB used   : {used_mb:.1f} MB / 2048 MB")
print(f"DB free   : {2048 - used_mb:.0f} MB")

cur.execute("SELECT COUNT(*) FROM dbo.Fact_NAV")
print(f"Fact_NAV  : {cur.fetchone()[0]:,} rows")
cur.execute("SELECT COUNT(*) FROM dbo.Fact_Returns")
print(f"Fact_Ret  : {cur.fetchone()[0]:,} rows")
conn.close()
