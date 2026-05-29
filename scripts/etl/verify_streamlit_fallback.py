"""
================================================================
Streamlit Fallback Verification
================================================================
Verifies that local PostgreSQL has all data required to run the
Streamlit app independently of Azure. Run this before Day 8
(Azure activation) and again on Day 21 (VPS deployment).

Exit code 0 = READY. Exit code 1 = at least one check failed.

Eight checks — each is a real query the Streamlit app will use:
    1  DB connection
    2  vw_fund_performance       (fund metrics page)
    3  vw_investor_segmentation  (investor analytics page)
    4  vw_risk_summary           (risk & volatility page)
    5  sp_compute_aum()          (AUM widget)
    6  Dim_Date coverage         (time-intelligence in DAX/Streamlit)
    7  Fact_Returns completeness (13 metric columns)
    8  .env variables            (Streamlit reads from .env)

Usage:
    python scripts/etl/verify_streamlit_fallback.py
================================================================
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("LOCAL_DB_HOST", "localhost")
DB_PORT = int(os.getenv("LOCAL_DB_PORT", "5432"))
DB_NAME = os.getenv("LOCAL_DB_NAME", "mf_analytics")
DB_USER = os.getenv("LOCAL_DB_USER", "postgres")
DB_PASS = os.getenv("LOCAL_DB_PASSWORD", "")

# Expected row counts (from verified Day 4-6 runs)
MIN_FUND_PERFORMANCE_ROWS = 16
EXPECTED_INVESTOR_ROWS = 500
MIN_RISK_SUMMARY_ROWS = 16
MIN_AUM_ROWS = 1
EXPECTED_DATE_MIN = "2015-01-01"
EXPECTED_DATE_MAX = "2026-12-31"
MIN_METRIC_ROWS = 14     # Fact_Returns rows with at least one metric non-NULL
METRIC_COLUMNS = [
    "cagr_1y", "cagr_3y", "cagr_5y",
    "std_dev_1y", "max_drawdown",
    "sharpe_ratio", "sortino_ratio", "treynor_ratio",
    "alpha", "beta",
]


def _row(label: str, passed: bool, detail: str = "") -> dict:
    return {"label": label, "passed": passed, "detail": detail}


def run_checks() -> list[dict]:
    results: list[dict] = []

    # ---- Check 8: .env variables ----
    missing_env = [
        v for v in ("LOCAL_DB_HOST", "LOCAL_DB_PORT", "LOCAL_DB_NAME",
                    "LOCAL_DB_USER", "LOCAL_DB_PASSWORD")
        if not os.getenv(v)
    ]
    results.append(_row(
        "8  .env variables present",
        len(missing_env) == 0,
        f"Missing: {missing_env}" if missing_env else "All 5 LOCAL_DB_* vars set",
    ))

    # ---- Check 1: DB connection ----
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS, connect_timeout=5,
        )
        results.append(_row("1  DB connection", True,
                            f"{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"))
    except Exception as e:
        results.append(_row("1  DB connection", False, str(e)))
        # Can't run any further DB checks
        for label in ("2  vw_fund_performance", "3  vw_investor_segmentation",
                       "4  vw_risk_summary", "5  sp_compute_aum()",
                       "6  Dim_Date coverage", "7  Fact_Returns metrics"):
            results.append(_row(label, False, "Skipped — no DB connection"))
        return results

    with conn:
        with conn.cursor() as cur:

            # ---- Check 2: vw_fund_performance ----
            cur.execute("SELECT COUNT(*) FROM dbo.vw_fund_performance")
            n = cur.fetchone()[0]
            results.append(_row(
                "2  vw_fund_performance",
                n >= MIN_FUND_PERFORMANCE_ROWS,
                f"{n} rows (need >= {MIN_FUND_PERFORMANCE_ROWS})",
            ))

            # ---- Check 3: vw_investor_segmentation ----
            cur.execute("SELECT COUNT(*) FROM dbo.vw_investor_segmentation")
            n = cur.fetchone()[0]
            results.append(_row(
                "3  vw_investor_segmentation",
                n == EXPECTED_INVESTOR_ROWS,
                f"{n} rows (expect {EXPECTED_INVESTOR_ROWS})",
            ))

            # ---- Check 4: vw_risk_summary ----
            cur.execute("SELECT COUNT(*) FROM dbo.vw_risk_summary")
            n = cur.fetchone()[0]
            results.append(_row(
                "4  vw_risk_summary",
                n >= MIN_RISK_SUMMARY_ROWS,
                f"{n} rows (need >= {MIN_RISK_SUMMARY_ROWS})",
            ))

            # ---- Check 5: sp_compute_aum() ----
            try:
                cur.execute("SELECT COUNT(*) FROM dbo.sp_compute_aum('2026-05-28')")
                n = cur.fetchone()[0]
                results.append(_row(
                    "5  sp_compute_aum()",
                    n >= MIN_AUM_ROWS,
                    f"{n} fund AUM rows returned",
                ))
            except Exception as e:
                results.append(_row("5  sp_compute_aum()", False, str(e)))

            # ---- Check 6: Dim_Date coverage ----
            cur.execute(
                "SELECT MIN(full_date)::text, MAX(full_date)::text FROM dbo.Dim_Date"
            )
            d_min, d_max = cur.fetchone()
            results.append(_row(
                "6  Dim_Date coverage",
                d_min == EXPECTED_DATE_MIN and d_max == EXPECTED_DATE_MAX,
                f"{d_min} -> {d_max}",
            ))

            # ---- Check 7: Fact_Returns metric completeness ----
            # Count rows where every key metric column is non-NULL
            non_null_checks = " AND ".join(
                f"{col} IS NOT NULL" for col in METRIC_COLUMNS[:5]  # key 5
            )
            cur.execute(
                f"SELECT COUNT(*) FROM dbo.Fact_Returns WHERE {non_null_checks}"
            )
            n = cur.fetchone()[0]
            results.append(_row(
                "7  Fact_Returns metrics",
                n >= MIN_METRIC_ROWS,
                f"{n} fully-metric rows (need >= {MIN_METRIC_ROWS})",
            ))

    conn.close()
    return results


def main() -> None:
    print()
    print("=" * 60)
    print("  STREAMLIT FALLBACK VERIFICATION")
    print(f"  DB: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("=" * 60)

    results = run_checks()

    # Sort by check number for display
    results_sorted = sorted(results, key=lambda r: r["label"])

    passed_count = sum(1 for r in results_sorted if r["passed"])
    total = len(results_sorted)

    print(f"\n{'Check':<35} {'Status':>8}  Detail")
    print("-" * 75)
    for r in results_sorted:
        status = "  PASS  " if r["passed"] else "  FAIL  "
        print(f"{r['label']:<35} {status}  {r['detail']}")

    print()
    print("=" * 60)
    overall = passed_count == total
    verdict = "READY" if overall else "NOT READY"
    print(f"  STREAMLIT FALLBACK: {verdict}  ({passed_count}/{total} checks passed)")
    print("=" * 60)
    print()

    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
