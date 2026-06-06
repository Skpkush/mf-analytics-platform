"""
Fix corrupted MON100 (Motilal Oswal NASDAQ 100 ETF) NAV + drawdown.

Root cause (diagnosed 2026-06-05):
  Two NAV points are a 10x decimal glitch (price /10, volume ~x15) for
  fund_key 14375:
      2021-06-17  nav 10.09  (neighbours ~101.56 / 103.41)
      2021-06-18  nav 10.42
  These were NOT flagged is_outlier (the global z-score detector misses a
  transient 2-day dip on a 10 -> 332 trending series). The fake -90% drop
  produced max_drawdown = -90.13; the true full-history drawdown is the
  2022-11-10 bear-market trough at -28.51%.

  cagr_1y (84.44%) is left untouched: it reconciles exactly with the NAV
  (178.24 -> 328.74) and shows no discrete glitch in the last 12 months.

Fix (local PostgreSQL):
  1. Correct the 2 NAV rows: x10 on nav/open/high/low, /10 on volume,
     is_outlier = TRUE. Idempotent (guarded on nav < 50).
  2. Recompute max_drawdown from the corrected full-history NAV and write
     it back to Fact_Returns.

The upstream detector is hardened separately in
scripts/transformation/clean_nav.py so future loads flag this class of
spike automatically.

Run:  ./venv/Scripts/python.exe scripts/sql/fix_mon100_nav_drawdown.py
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

MON100_FUND_KEY = 14375
GLITCH_DATES = ("2021-06-17", "2021-06-18")
GLITCH_FACTOR = 10  # price is 1/10th of true; volume is ~10x


def get_conn() -> "psycopg2.extensions.connection":
    return psycopg2.connect(
        host=os.environ["LOCAL_DB_HOST"],
        port=os.environ["LOCAL_DB_PORT"],
        dbname=os.environ["LOCAL_DB_NAME"],
        user=os.environ["LOCAL_DB_USER"],
        password=os.environ["LOCAL_DB_PASSWORD"],
    )


def fix_nav_points(cur: "psycopg2.extensions.cursor") -> int:
    """Correct the 10x decimal glitch on the 2 bad NAV rows. Returns rows fixed."""
    cur.execute(
        """
        UPDATE dbo.Fact_NAV n
           SET nav        = nav        * %(f)s,
               open_price = open_price * %(f)s,
               high_price = high_price * %(f)s,
               low_price  = low_price  * %(f)s,
               volume     = ROUND(volume / %(f)s),
               is_outlier = TRUE
          FROM dbo.Dim_Date dd
         WHERE dd.date_key = n.date_key
           AND n.fund_key  = %(fk)s
           AND dd.full_date IN (DATE %(d1)s, DATE %(d2)s)
           AND n.nav < 50          -- idempotency guard: skip if already fixed
        """,
        {"f": GLITCH_FACTOR, "fk": MON100_FUND_KEY, "d1": GLITCH_DATES[0], "d2": GLITCH_DATES[1]},
    )
    return cur.rowcount


def recompute_max_drawdown(cur: "psycopg2.extensions.cursor") -> float:
    """Recompute max_drawdown from the corrected full-history NAV series."""
    cur.execute(
        """
        WITH series AS (
            SELECT dd.full_date AS d, n.nav,
                   MAX(n.nav) OVER (ORDER BY dd.full_date
                                    ROWS UNBOUNDED PRECEDING) AS peak
            FROM dbo.Fact_NAV n
            JOIN dbo.Dim_Date dd ON dd.date_key = n.date_key
            WHERE n.fund_key = %s
        )
        SELECT ROUND(MIN(100.0 * (nav - peak) / peak), 4) FROM series
        """,
        (MON100_FUND_KEY,),
    )
    return float(cur.fetchone()[0])


def main() -> None:
    conn = get_conn()
    cur = conn.cursor()

    log.info("Step 1/2: correcting the 2 corrupt NAV rows ...")
    fixed = fix_nav_points(cur)
    log.info("  %d NAV row(s) corrected", fixed)

    log.info("Step 2/2: recomputing max_drawdown ...")
    true_dd = recompute_max_drawdown(cur)
    cur.execute(
        "UPDATE dbo.Fact_Returns SET max_drawdown = %s WHERE fund_key = %s",
        (true_dd, MON100_FUND_KEY),
    )
    log.info("  max_drawdown -> %.2f%% (%d row updated)", true_dd, cur.rowcount)
    conn.commit()

    # Verify NAV rows
    print("\n" + "=" * 60)
    print("corrected NAV rows")
    print("=" * 60)
    cur.execute(
        """
        SELECT dd.full_date, n.nav, n.open_price, n.high_price, n.low_price, n.is_outlier
        FROM dbo.Fact_NAV n JOIN dbo.Dim_Date dd ON dd.date_key = n.date_key
        WHERE n.fund_key = %s AND dd.full_date BETWEEN DATE '2021-06-16' AND DATE '2021-06-21'
        ORDER BY dd.full_date
        """,
        (MON100_FUND_KEY,),
    )
    print(f"{'date':<12}{'nav':>9}{'open':>9}{'high':>9}{'low':>9}  outlier")
    for r in cur.fetchall():
        print(f"{str(r[0]):<12}{float(r[1]):>9.2f}{float(r[2]):>9.2f}{float(r[3]):>9.2f}{float(r[4]):>9.2f}  {r[5]}")

    # Verify view now reflects the corrected drawdown
    print("\n" + "=" * 60)
    print("vw_fund_performance — MON100 after fix")
    print("=" * 60)
    cur.execute(
        """
        SELECT base_fund_name, asset_class, max_drawdown, cagr_1y, sharpe_ratio, std_dev_1y
        FROM dbo.vw_fund_performance WHERE base_fund_name LIKE %s
        """,
        ("%NASDAQ%",),
    )
    r = cur.fetchone()
    print(f"  {r[0]}")
    print(f"  asset_class={r[1]}  max_drawdown={float(r[2]):.2f}  "
          f"cagr_1y={float(r[3]):.2f}  sharpe={float(r[4]):.2f}  std_1y={float(r[5]):.2f}")

    cur.close()
    conn.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
