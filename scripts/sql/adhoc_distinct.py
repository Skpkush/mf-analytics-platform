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
        COUNT(DISTINCT scheme_code)    AS scheme_codes,
        COUNT(DISTINCT base_fund_name) AS base_names,
        COUNT(DISTINCT fund_key)       AS fund_keys,
        COUNT(*)                       AS total_rows
    FROM dbo.vw_fund_performance
""")
r = cur.fetchone()
print(f"scheme_codes : {r[0]:,}")
print(f"base_names   : {r[1]:,}")
print(f"fund_keys    : {r[2]:,}")
print(f"total_rows   : {r[3]:,}")

conn.close()
