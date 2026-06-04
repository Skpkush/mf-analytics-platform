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
        MIN(std_dev_1y) AS min_vol,
        MAX(std_dev_1y) AS max_vol,
        AVG(std_dev_1y) AS avg_vol,
        COUNT(*)        AS total,
        COUNT(CASE WHEN std_dev_1y > 50 THEN 1 END) AS outliers_above_50
    FROM dbo.vw_fund_performance
    WHERE std_dev_1y IS NOT NULL
""")
r = cur.fetchone()
print(f"min_vol           : {float(r[0]):,.4f}")
print(f"max_vol           : {float(r[1]):,.4f}")
print(f"avg_vol           : {float(r[2]):,.4f}")
print(f"total             : {r[3]:,}")
print(f"outliers_above_50 : {r[4]:,}")

conn.close()
