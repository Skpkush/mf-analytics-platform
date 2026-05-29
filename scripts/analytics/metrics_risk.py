"""
================================================================
Financial Metrics: Risk
================================================================
Computes risk metrics for all Yahoo ETF/benchmark funds in
Fact_NAV, as of each fund's latest available date.

Metrics written to Fact_Returns (ON CONFLICT updates only these
columns — leaves return_1y/cagr columns etc. untouched):
    std_dev_1y   — annualised daily volatility, trailing 1 year (%)
    max_drawdown — maximum peak-to-trough decline since inception (%)

Formulas:
    std_dev_1y  = σ(daily_returns, trailing 252 days) × √252 × 100
    max_drawdown = min((cum_return_t − peak_t) / peak_t) × 100

NULL rules:
    std_dev_1y  : requires ≥ 50 trading days in the trailing 1-year window
    max_drawdown: requires ≥ 2 data points (always available for Yahoo funds)

Validation:
    NIFTYBEES.NS std_dev_1y expected within [8%, 20%] (typical Nifty 50 vol)
    max_drawdown must be ≤ 0 (drawdown is always non-positive)

Usage:
    python scripts/analytics/metrics_risk.py
    python scripts/analytics/metrics_risk.py --fund-code NIFTYBEES.NS
    python scripts/analytics/metrics_risk.py --as-of 2026-03-31
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

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

TRADING_DAYS_PER_YEAR = 252  # NSE/BSE standard
MIN_DAYS_STD_DEV = 50        # minimum observations in trailing window
TRAILING_WINDOW_DAYS = 365   # calendar days for trailing 1-year volatility

# Validation bounds
VALIDATION_FUND = "NIFTYBEES.NS"
VOL_MIN = 8.0    # % — annualised Nifty 50 vol rarely goes below this
VOL_MAX = 20.0   # % — typical upper range for Indian large-cap index

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
        logging.FileHandler(LOG_DIR / "metrics_risk.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("metrics_risk")


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


def load_nav_timeseries(
    conn: psycopg2.extensions.connection,
    fund_code: str | None = None,
) -> dict[int, tuple[str, pd.Series]]:
    """
    Load NAV time series for Yahoo ETF and benchmark funds from Fact_NAV.

    Returns:
        {fund_key: (scheme_code, nav_series)} where nav_series is indexed
        by pd.Timestamp, sorted ascending.
    """
    where_extra = "AND df.scheme_code = %s" if fund_code else ""
    params = (fund_code,) if fund_code else ()

    query = f"""
        SELECT fn.fund_key, df.scheme_code, dd.full_date, fn.nav
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
        JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
        WHERE df.source IN ('yahoo_etf', 'yahoo_benchmark')
          {where_extra}
        ORDER BY fn.fund_key, dd.full_date
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    fund_data: dict[int, dict] = {}
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
            name=d["scheme_code"],
        ).sort_index()
        result[fund_key] = (d["scheme_code"], series)

    logger.info(f"Loaded NAV time series for {len(result)} funds ({len(rows):,} rows total)")
    return result


# ----------------------------------------------------------------
# Metric computation
# ----------------------------------------------------------------
def compute_std_dev_1y(
    series: pd.Series,
    as_of: pd.Timestamp,
) -> float | None:
    """
    Annualised standard deviation of daily returns over trailing 1 year.

    Steps:
        1. Slice to [as_of - 365 days, as_of]
        2. Compute daily returns: r_t = NAV_t / NAV_{t-1} - 1
        3. σ_daily = sample std dev of daily returns
        4. σ_annual = σ_daily × √252  (annualisation factor)
        5. Return σ_annual × 100 (as percentage)

    Returns None if fewer than MIN_DAYS_STD_DEV observations in window.
    """
    cutoff = as_of - pd.Timedelta(days=TRAILING_WINDOW_DAYS)
    window = series[(series.index >= cutoff) & (series.index <= as_of)]

    daily_returns = window.pct_change().dropna()
    if len(daily_returns) < MIN_DAYS_STD_DEV:
        return None

    std_annual = float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    return round(std_annual * 100, 4)


def compute_max_drawdown(
    series: pd.Series,
    as_of: pd.Timestamp,
) -> float | None:
    """
    Maximum peak-to-trough decline over the full available history up to as_of.

    Steps:
        1. Compute daily returns over all available history
        2. Cumulative return series: (1 + r_1)(1 + r_2)...(1 + r_t)
        3. Rolling peak: max cumulative return seen up to time t
        4. Drawdown_t = (cum_t - peak_t) / peak_t   (always ≤ 0)
        5. Max drawdown = min(drawdown_t) × 100

    Stored as a negative percentage (e.g. -16.11 means 16.11% maximum loss).
    Returns None if series has fewer than 2 data points.
    """
    available = series[series.index <= as_of]
    if len(available) < 2:
        return None

    daily_returns = available.pct_change().dropna()
    if daily_returns.empty:
        return None

    cum_returns = (1 + daily_returns).cumprod()
    rolling_peak = cum_returns.cummax()
    drawdown = (cum_returns - rolling_peak) / rolling_peak
    return round(float(drawdown.min()) * 100, 4)


def compute_risk_for_fund(
    series: pd.Series,
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, dict[str, float | None]]:
    """
    Compute std_dev_1y and max_drawdown for a single fund.

    Args:
        series: NAV time series indexed by pd.Timestamp.
        as_of:  Compute as of this date. Defaults to series.index.max().

    Returns:
        (effective_as_of, {'std_dev_1y': ..., 'max_drawdown': ...})
        Values are percentages. None when insufficient data.
    """
    effective_as_of = as_of if as_of is not None else series.index.max()

    std_dev = compute_std_dev_1y(series, effective_as_of)
    max_dd = compute_max_drawdown(series, effective_as_of)

    return effective_as_of, {"std_dev_1y": std_dev, "max_drawdown": max_dd}


# ----------------------------------------------------------------
# Validation
# ----------------------------------------------------------------
def validate_results(
    results: dict[str, tuple[pd.Timestamp, dict]],
) -> None:
    """
    Sanity-check NIFTYBEES.NS risk metrics against known market ranges.
    Logs WARNING (does not abort) if any check fails.
    """
    if VALIDATION_FUND not in results:
        logger.warning(f"Validation skipped: {VALIDATION_FUND} not in results")
        return

    _, metrics = results[VALIDATION_FUND]
    vol = metrics.get("std_dev_1y")
    mdd = metrics.get("max_drawdown")

    # Volatility check
    if vol is None:
        logger.warning(f"Validation: {VALIDATION_FUND} std_dev_1y is NULL")
    elif VOL_MIN <= vol <= VOL_MAX:
        logger.info(
            f"Validation PASSED: {VALIDATION_FUND} std_dev_1y = {vol:.2f}% "
            f"(expected {VOL_MIN}–{VOL_MAX}%)"
        )
    else:
        logger.warning(
            f"Validation WARNING: {VALIDATION_FUND} std_dev_1y = {vol:.2f}% "
            f"is OUTSIDE expected [{VOL_MIN}%, {VOL_MAX}%]"
        )

    # Drawdown must be non-positive
    if mdd is not None and mdd > 0:
        logger.warning(
            f"Validation WARNING: {VALIDATION_FUND} max_drawdown = {mdd:.2f}% is positive — "
            f"max drawdown must always be <= 0. Check formula."
        )
    elif mdd is not None:
        logger.info(
            f"Validation PASSED: {VALIDATION_FUND} max_drawdown = {mdd:.2f}% (non-positive)"
        )


# ----------------------------------------------------------------
# UPSERT — only touches std_dev_1y and max_drawdown
# ----------------------------------------------------------------
_UPSERT_RISK = """
INSERT INTO dbo.Fact_Returns (
    date_key, fund_key,
    std_dev_1y, max_drawdown
) VALUES %s
ON CONFLICT (fund_key, date_key) DO UPDATE SET
    std_dev_1y   = EXCLUDED.std_dev_1y,
    max_drawdown = EXCLUDED.max_drawdown
"""


def _date_to_key(d: pd.Timestamp) -> int:
    return d.year * 10_000 + d.month * 100 + d.day


def upsert_fact_returns_risk(
    conn: psycopg2.extensions.connection,
    fund_key_results: dict[int, tuple[pd.Timestamp, dict]],
) -> int:
    """
    Upsert risk metrics into Fact_Returns.

    Only std_dev_1y and max_drawdown are written. Return/CAGR columns
    and Sharpe/alpha/beta (Day 6) are left untouched on conflict.

    Returns:
        Number of rows upserted.
    """
    records = [
        (
            _date_to_key(as_of),
            fund_key,
            metrics.get("std_dev_1y"),
            metrics.get("max_drawdown"),
        )
        for fund_key, (as_of, metrics) in fund_key_results.items()
    ]

    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_RISK, records)
    conn.commit()
    logger.info(f"Fact_Returns: {len(records)} rows upserted (std_dev_1y, max_drawdown)")
    return len(records)


# ----------------------------------------------------------------
# Summary table
# ----------------------------------------------------------------
def print_summary(
    scheme_results: dict[str, tuple[pd.Timestamp, dict]],
) -> None:
    """Log a human-readable table of all computed risk metrics."""
    logger.info("")
    logger.info(f"{'Fund':<20} {'As-Of':<12} {'StdDev1Y':>10} {'MaxDrawdown':>12}")
    logger.info("-" * 58)
    for scheme, (as_of, m) in sorted(scheme_results.items()):
        vol = f"{m['std_dev_1y']:>10.2f}%" if m["std_dev_1y"] is not None else "      NULL"
        mdd = f"{m['max_drawdown']:>11.2f}%" if m["max_drawdown"] is not None else "       NULL"
        logger.info(f"{scheme:<20} {str(as_of.date()):<12} {vol} {mdd}")
    logger.info("")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Compute risk metrics into Fact_Returns")
    parser.add_argument(
        "--fund-code", default=None,
        help="Compute for a single fund code only (e.g. NIFTYBEES.NS)",
    )
    parser.add_argument(
        "--as-of", default=None,
        help="As-of date YYYY-MM-DD (default: each fund's own latest date)",
    )
    args = parser.parse_args()

    as_of_override: pd.Timestamp | None = (
        pd.Timestamp(args.as_of) if args.as_of else None
    )

    logger.info("=" * 60)
    logger.info("METRICS RISK — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        nav_data = load_nav_timeseries(conn, fund_code=args.fund_code)

        fund_key_results: dict[int, tuple[pd.Timestamp, dict]] = {}
        scheme_results: dict[str, tuple[pd.Timestamp, dict]] = {}

        for fund_key, (scheme_code, series) in nav_data.items():
            as_of, metrics = compute_risk_for_fund(series, as_of=as_of_override)
            fund_key_results[fund_key] = (as_of, metrics)
            scheme_results[scheme_code] = (as_of, metrics)

        print_summary(scheme_results)
        validate_results(scheme_results)
        upsert_fact_returns_risk(conn, fund_key_results)

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("METRICS RISK — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
