"""
================================================================
Financial Metrics: Market Metrics (Beta, Jensen's Alpha)
================================================================
Computes Beta and Jensen's Alpha for all Yahoo ETF/benchmark funds
relative to the Nifty 50 (^NSEI) benchmark.

    Beta  — OLS regression slope of fund daily returns on ^NSEI
             daily returns, computed over full available history.
    Alpha — Jensen's Alpha (annualised, CAPM-based):
             Alpha = CAGR_fund − [Rf + Beta × (CAGR_bench − Rf)]
             Uses the longest available CAGR window (5Y > 3Y > 1Y).

UPSERT targets existing (fund_key, date_key) rows in Fact_Returns
created by metrics_returns.py — only alpha and beta columns are
written. All other columns are untouched.

RUN THIS BEFORE metrics_risk_adjusted.py — Treynor needs Beta.

Validation:
    NIFTYBEES.NS Beta expected within [0.85, 1.05]
    LIQUIDBEES.NS Beta expected within [0.00, 0.10]

Usage:
    python scripts/analytics/metrics_market.py
    python scripts/analytics/metrics_market.py --fund-code NIFTYBEES.NS
================================================================
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from scipy.stats import linregress

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

RISK_FREE_ANNUAL = 0.065      # 6.5% RBI repo rate
BENCHMARK_CODE = "^NSEI"      # Nifty 50 index — alpha/beta reference
MIN_REGRESSION_DAYS = 100     # minimum common trading days for valid Beta

# Validation bounds
NIFTYBEES_BETA_MIN = 0.85
NIFTYBEES_BETA_MAX = 1.05
LIQUIDBEES_BETA_MAX = 0.10

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
)
if hasattr(_stream_handler.stream, "reconfigure"):
    try:
        _stream_handler.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "metrics_market.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("metrics_market")


# ----------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------
def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("LOCAL_DB_HOST", "localhost"),
        port=int(os.getenv("LOCAL_DB_PORT", "5432")),
        dbname=os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        user=os.getenv("LOCAL_DB_USER", "postgres"),
        password=os.getenv("LOCAL_DB_PASSWORD", ""),
    )


def _to_float(v) -> float | None:
    """Convert psycopg2 Decimal / None to Python float / None."""
    return float(v) if v is not None else None


def load_nav_timeseries(
    conn: psycopg2.extensions.connection,
    fund_code: str | None = None,
) -> dict[int, tuple[str, pd.Series]]:
    """
    Load NAV time series for all Yahoo ETF and benchmark funds.

    Returns {fund_key: (scheme_code, nav_series)}.
    """
    where = "AND df.scheme_code = %s" if fund_code else ""
    params = (fund_code,) if fund_code else ()
    query = f"""
        SELECT fn.fund_key, df.scheme_code, dd.full_date, fn.nav
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
        JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
        WHERE df.source IN ('yahoo_etf', 'yahoo_benchmark')
          {where}
        ORDER BY fn.fund_key, dd.full_date
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    fund_data: dict = {}
    for fund_key, scheme_code, full_date, nav in rows:
        if fund_key not in fund_data:
            fund_data[fund_key] = {"scheme_code": scheme_code, "dates": [], "navs": []}
        fund_data[fund_key]["dates"].append(pd.Timestamp(full_date))
        fund_data[fund_key]["navs"].append(float(nav))

    result: dict[int, tuple[str, pd.Series]] = {}
    for fund_key, d in fund_data.items():
        series = pd.Series(
            d["navs"],
            index=pd.DatetimeIndex(d["dates"]),
            dtype=float,
        ).sort_index()
        result[fund_key] = (d["scheme_code"], series)

    logger.info(f"Loaded NAV time series for {len(result)} funds ({len(rows):,} rows total)")
    return result


def load_existing_metrics(
    conn: psycopg2.extensions.connection,
) -> dict[str, dict]:
    """
    Load existing Fact_Returns rows to get (fund_key, date_key) UPSERT keys
    and CAGR values needed for Alpha computation.

    Returns {scheme_code: {fund_key, date_key, cagr_1y, cagr_3y, cagr_5y}}.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fr.fund_key, df.scheme_code, fr.date_key,
                   fr.cagr_1y, fr.cagr_3y, fr.cagr_5y
            FROM dbo.Fact_Returns fr
            JOIN dbo.Dim_Fund df ON df.fund_key = fr.fund_key
        """)
        return {
            row[1]: {
                "fund_key": row[0],
                "date_key": row[2],
                "cagr_1y": _to_float(row[3]),
                "cagr_3y": _to_float(row[4]),
                "cagr_5y": _to_float(row[5]),
            }
            for row in cur.fetchall()
        }


# ----------------------------------------------------------------
# Metric computation
# ----------------------------------------------------------------
def compute_beta(
    fund_series: pd.Series,
    bench_series: pd.Series,
) -> float | None:
    """
    Compute Beta via OLS regression of fund daily returns on benchmark returns.

    Beta = Cov(R_fund, R_bench) / Var(R_bench)

    Uses all overlapping trading days between fund and benchmark.
    Returns None if fewer than MIN_REGRESSION_DAYS common days exist.
    """
    fund_ret = fund_series.pct_change().dropna()
    bench_ret = bench_series.pct_change().dropna()

    common = fund_ret.index.intersection(bench_ret.index)
    if len(common) < MIN_REGRESSION_DAYS:
        return None

    x = bench_ret.loc[common].values.astype(float)
    y = fund_ret.loc[common].values.astype(float)

    slope, _, r_value, _, _ = linregress(x, y)
    logger.debug(
        f"  Beta={slope:.4f}  R²={r_value**2:.4f}  n={len(common)} days"
    )
    return round(float(slope), 4)


def compute_alpha(
    fund_cagr_1y: float | None,
    fund_cagr_3y: float | None,
    fund_cagr_5y: float | None,
    bench_cagr_1y: float | None,
    bench_cagr_3y: float | None,
    bench_cagr_5y: float | None,
    beta: float | None,
) -> float | None:
    """
    Compute Jensen's Alpha using the longest available CAGR window.

    Formula:
        Alpha = CAGR_fund − [Rf + Beta × (CAGR_bench − Rf)]

    Priority: 5Y CAGR > 3Y CAGR > 1Y CAGR.
    All CAGR values are percentages (e.g. 10.19 not 0.1019).
    Result is also returned as a percentage.

    Returns None if Beta is None or no matching CAGR window exists.
    """
    if beta is None:
        return None

    rf = RISK_FREE_ANNUAL * 100  # convert to same % scale as stored CAGRs

    for f_cagr, b_cagr in [
        (fund_cagr_5y, bench_cagr_5y),
        (fund_cagr_3y, bench_cagr_3y),
        (fund_cagr_1y, bench_cagr_1y),
    ]:
        if f_cagr is not None and b_cagr is not None:
            alpha = f_cagr - (rf + beta * (b_cagr - rf))
            return round(alpha, 4)

    return None


# ----------------------------------------------------------------
# Validation
# ----------------------------------------------------------------
def validate_results(scheme_results: dict[str, dict]) -> None:
    """Sanity-check Beta for NIFTYBEES.NS and LIQUIDBEES.NS."""
    for fund, (low, high, direction) in {
        "NIFTYBEES.NS":  (NIFTYBEES_BETA_MIN, NIFTYBEES_BETA_MAX, "within"),
        "LIQUIDBEES.NS": (0.0, LIQUIDBEES_BETA_MAX, "below"),
    }.items():
        if fund not in scheme_results:
            continue
        beta = scheme_results[fund].get("beta")
        if beta is None:
            logger.warning(f"Validation skipped: {fund} beta is NULL")
            continue
        if low <= beta <= high:
            logger.info(f"Validation PASSED: {fund} beta={beta:.4f} ({direction} [{low}, {high}])")
        else:
            logger.warning(
                f"Validation WARNING: {fund} beta={beta:.4f} is OUTSIDE "
                f"expected [{low}, {high}]. Check regression alignment."
            )


# ----------------------------------------------------------------
# UPSERT — only alpha and beta columns
# ----------------------------------------------------------------
_UPSERT_MARKET = """
INSERT INTO dbo.Fact_Returns (date_key, fund_key, beta, alpha)
VALUES %s
ON CONFLICT (fund_key, date_key) DO UPDATE SET
    beta  = EXCLUDED.beta,
    alpha = EXCLUDED.alpha
"""


def upsert_market_metrics(
    conn: psycopg2.extensions.connection,
    fund_key_results: dict[int, dict],
) -> int:
    """
    Upsert Beta and Alpha into existing Fact_Returns rows.
    Returns row count.
    """
    records = [
        (d["date_key"], fund_key, d["beta"], d["alpha"])
        for fund_key, d in fund_key_results.items()
    ]
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_MARKET, records)
    conn.commit()
    logger.info(f"Fact_Returns: {len(records)} rows upserted (beta, alpha)")
    return len(records)


# ----------------------------------------------------------------
# Summary table
# ----------------------------------------------------------------
def print_summary(scheme_results: dict[str, dict]) -> None:
    logger.info("")
    logger.info(f"{'Fund':<20} {'Beta':>8} {'Alpha%':>10}")
    logger.info("-" * 42)
    for scheme, m in sorted(scheme_results.items()):
        beta_s = f"{m['beta']:>8.4f}" if m["beta"] is not None else "    NULL"
        alpha_s = f"{m['alpha']:>10.4f}" if m["alpha"] is not None else "      NULL"
        logger.info(f"{scheme:<20} {beta_s} {alpha_s}")
    logger.info("")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Compute Beta + Alpha into Fact_Returns")
    parser.add_argument("--fund-code", default=None, help="Single fund code (e.g. NIFTYBEES.NS)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("METRICS MARKET — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        existing = load_existing_metrics(conn)
        bench_metrics = existing.get(BENCHMARK_CODE, {})

        if not bench_metrics:
            logger.error(f"Benchmark {BENCHMARK_CODE} not found in Fact_Returns — run metrics_returns.py first")
            sys.exit(1)

        nav_data = load_nav_timeseries(conn, fund_code=args.fund_code)

        # Extract the benchmark series from loaded data
        bench_series: pd.Series | None = None
        for fk, (sc, series) in nav_data.items():
            if sc == BENCHMARK_CODE:
                bench_series = series
                break

        if bench_series is None:
            logger.error(f"Benchmark {BENCHMARK_CODE} NAV not in Fact_NAV — cannot compute Beta")
            sys.exit(1)

        fund_key_results: dict[int, dict] = {}
        scheme_results: dict[str, dict] = {}

        for fund_key, (scheme_code, series) in nav_data.items():
            if scheme_code not in existing:
                logger.warning(f"  {scheme_code}: no Fact_Returns row — skipping")
                continue

            row = existing[scheme_code]
            beta = compute_beta(series, bench_series)
            alpha = compute_alpha(
                row["cagr_1y"], row["cagr_3y"], row["cagr_5y"],
                bench_metrics.get("cagr_1y"),
                bench_metrics.get("cagr_3y"),
                bench_metrics.get("cagr_5y"),
                beta,
            )
            fund_key_results[fund_key] = {
                "date_key": row["date_key"],
                "beta": beta,
                "alpha": alpha,
            }
            scheme_results[scheme_code] = {"beta": beta, "alpha": alpha}

        print_summary(scheme_results)
        validate_results(scheme_results)
        upsert_market_metrics(conn, fund_key_results)

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("METRICS MARKET — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
