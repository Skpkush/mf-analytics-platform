import os
import psycopg2
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(
    host=os.environ["LOCAL_DB_HOST"],
    port=os.environ["LOCAL_DB_PORT"],
    dbname=os.environ["LOCAL_DB_NAME"],
    user=os.environ["LOCAL_DB_USER"],
    password=os.environ["LOCAL_DB_PASSWORD"],
)
cur = conn.cursor()

cur.execute("""
    SELECT asset_class, COUNT(*) AS funds
    FROM dbo.vw_fund_performance
    WHERE max_drawdown IS NOT NULL
    GROUP BY asset_class
    ORDER BY asset_class
""")
print(f"{'asset_class':<28}{'funds':>7}")
print("-" * 35)
total = 0
for r in cur.fetchall():
    total += r[1]
    print(f"{str(r[0]):<28}{r[1]:>7,}")
print("-" * 35)
print(f"{'TOTAL':<28}{total:>7,}")

conn.close()
