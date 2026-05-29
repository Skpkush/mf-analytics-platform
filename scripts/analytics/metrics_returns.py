"""
================================================================
Financial Metrics: Returns
================================================================
Computes trailing returns and CAGR for all Yahoo ETF/benchmark
funds in Fact_NAV, as of each fund's latest available date.

Metrics written to Fact_Returns (ON CONFLICT updates only these
columns — leaves std_dev_1y, max_drawdown, Sharpe etc. untouched):
    return_1y / return_3y / return_5y  — absolute total return (%)
    cagr_1y   / cagr_3y   / cagr_5y   — compound annual growth rate (%)

NULL rules:
    cagr_1y / return_1y : requires ≥ 200 trading days of history
    cagr_3y / return_3y : requires ≥ 550 trading days
    cagr_5y / return_5y : requires ≥ 1,000 trading days
    Also NULL when the closest available NAV is > 30 days before
    the target date (i.e. fund didn't exist yet for that window).

Note: AMFI schemes have only one NAV snapshot — no time series.
      Metrics are computed exclusively for Yahoo ETF/benchmark data
      (16 funds). Run fetch_amfi_nav.py --historical to unlock AMFI.

Validation: NIFTYBEES.NS cagr_5y is asserted within [8%, 14%].
Expected from market data: ~10.18% (2021-06-01 → 2026-05-28).

Usage:
    python scripts/analytics/metrics_returns.py
    python scripts/analytics/metrics_returns.py --fund-code NIFTYBEES.NS
    python scripts/analytics/metrics_returns.py --as-of 2026-03-31
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

# Minimum trading days of history required per window
MIN_TRADING_DAYS: dict[int, int] = {1: 200, 3: 550, 5: 1_000}

# Allow up to 30 calendar days of gap between target date and nearest
# available NAV before treating the window as "insufficient history".
# Handles weekends, public holidays, and minor data gaps gracefully.
MAX_DATE_GAP_DAYS = 30

# Validation bounds for NIFTYBEES.NS 5Y CAGR (%)
VALIDATION_FUND = "NIFTYBEES.NS"
CAGR5Y_MIN = 8.0
CAGR5Y_MAX = 14.0

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
        logging.FileHandler(LOG_DIR / "metrics_returns.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("metrics_returns")


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

    Args:
        conn: Active psycopg2 connection.
        fund_code: Optional single ticker to filter (e.g. 'NIFTYBEES.NS').

    Returns:
        {fund_key: (scheme_code, nav_series)} where nav_series is a
        pd.Series indexed by pd.Timestamp, sorted ascending.
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
def _find_nav_n_years_ago(
    series: pd.Series,
    as_of: pd.Timestamp,
    years: int,
) -> float | None:
    """
    Return the NAV on the trading day closest to (as_of - N years).

    Looks backward first (standard: use last available day before target),
    then forward within MAX_DATE_GAP_DAYS (handles the common case where
    our data window starts a few days after the target date — e.g.
    NIFTYBEES.NS data starts 2021-05-31 but the 5Y target is 2021-05-28).

    Returns None when no data exists within MAX_DATE_GAP_DAYS of the target
    in either direction (fund genuinely didn't exist for that window).
    """
    target = as_of - pd.DateOffset(years=years)

    # Backward: last available trading day on or before target
    before = series[series.index <= target]
    if not before.empty:
        gap = int((target - before.index[-1]).days)
        if gap <= MAX_DATE_GAP_DAYS:
            return float(before.iloc[-1])

    # Forward: first available trading day within gap limit after target
    # (covers data-window-start falling just after the target date)
    after = series[
        (series.index > target)
        & (series.index <= target + pd.Timedelta(days=MAX_DATE_GAP_DAYS))
    ]
    if not after.empty:
        return float(after.iloc[0])

    return None


def compute_returns_for_fund(
    series: pd.Series,
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, dict[str, float | None]]:
    """
    Compute all return and CAGR metrics for a single fund.

    Args:
        series: NAV time series indexed by pd.Timestamp.
        as_of:  Compute as of this date. Defaults to series.index.max().

    Returns:
        (effective_as_of, metrics_dict)
        Metrics dict keys: return_1y, return_3y, return_5y,
                           cagr_1y, cagr_3y, cagr_5y
        Values are percentages (10.18, not 0.1018). None when insufficient.
    """
    effective_as_of = as_of if as_of is not None else series.index.max()

    # Slice to as-of date
    available = series[series.index <= effective_as_of]
    if available.empty:
        return effective_as_of, {k: None for k in (
            "return_1y", "return_3y", "return_5y", "cagr_1y", "cagr_3y", "cagr_5y"
        )}

    n_days = len(available)
    nav_latest = float(available.iloc[-1])
    metrics: dict[str, float | None] = {}

    for years in (1, 3, 5):
        ret_col = f"return_{years}y"
        cagr_col = f"cagr_{years}y"

        if n_days < MIN_TRADING_DAYS[years]:
            metrics[ret_col] = None
            metrics[cagr_col] = None
            continue

        nav_start = _find_nav_n_years_ago(series, effective_as_of, years)
        if nav_start is None or nav_start <= 0:
            metrics[ret_col] = None
            metrics[cagr_col] = None
            continue

        total_return = (nav_latest / nav_start - 1) * 100
        cagr = ((nav_latest / nav_start) ** (1.0 / years) - 1) * 100

        metrics[ret_col] = round(total_return, 4)
        metrics[cagr_col] = round(cagr, 4)

    return effective_as_of, metrics


# ----------------------------------------------------------------
# Validation
# ----------------------------------------------------------------
def validate_results(
    results: dict[str, tuple[pd.Timestamp, dict]],
) -> None:
    """
    Assert NIFTYBEES.NS 5Y CAGR falls within the expected market range.
    Logs WARNING (does not abort) if the check fails — acts as a
    signal that date alignment or data quality may be wrong.
    """
    if VALIDATION_FUND not in results:
        logger.warning(f"Validation skipped: {VALIDATION_FUND} not in results")
        return

    _, metrics = results[VALIDATION_FUND]
    cagr_5y = metrics.get("cagr_5y")

    if cagr_5y is None:
        logger.warning(f"Validation skipped: {VALIDATION_FUND} cagr_5y is NULL (insufficient data)")
        return

    if CAGR5Y_MIN <= cagr_5y <= CAGR5Y_MAX:
        logger.info(
            f"Validation PASSED: {VALIDATION_FUND} cagr_5y = {cagr_5y:.2f}% "
            f"(expected {CAGR5Y_MIN}–{CAGR5Y_MAX}%)"
        )
    else:
        logger.warning(
            f"Validation WARNING: {VALIDATION_FUND} cagr_5y = {cagr_5y:.2f}% "
            f"is OUTSIDE expected [{CAGR5Y_MIN}%, {CAGR5Y_MAX}%]. "
            f"Check date alignment or data quality."
        )


# ----------------------------------------------------------------
# UPSERT — only touches return/CAGR columns
# ----------------------------------------------------------------
_UPSERT_RETURNS = """
INSERT INTO dbo.Fact_Returns (
    date_key, fund_key,
    return_1y, return_3y, return_5y,
    cagr_1y,   cagr_3y,   cagr_5y
) VALUES %s
ON CONFLICT (fund_key, date_key) DO UPDATE SET
    return_1y = EXCLUDED.return_1y,
    return_3y = EXCLUDED.return_3y,
    return_5y = EXCLUDED.return_5y,
    cagr_1y   = EXCLUDED.cagr_1y,
    cagr_3y   = EXCLUDED.cagr_3y,
    cagr_5y   = EXCLUDED.cagr_5y
"""


def _date_to_key(d: pd.Timestamp) -> int:
    return d.year * 10_000 + d.month * 100 + d.day


def upsert_fact_returns(
    conn: psycopg2.extensions.connection,
    fund_key_results: dict[int, tuple[pd.Timestamp, dict]],
) -> int:
    """
    Upsert return/CAGR metrics into Fact_Returns.

    Only the six return/CAGR columns are written. Risk columns
    (std_dev_1y, max_drawdown, Sharpe etc.) are left untouched so
    metrics_risk.py can populate them independently.

    Returns:
        Number of rows upserted.
    """
    records = []
    for fund_key, (as_of, metrics) in fund_key_results.items():
        date_key = _date_to_key(as_of)
        records.append((
            date_key,
            fund_key,
            metrics.get("return_1y"),
            metrics.get("return_3y"),
            metrics.get("return_5y"),
            metrics.get("cagr_1y"),
            metrics.get("cagr_3y"),
            metrics.get("cagr_5y"),
        ))

    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_RETURNS, records)
    conn.commit()
    logger.info(f"Fact_Returns: {len(records)} rows upserted (return/CAGR columns)")
    return len(records)


# ----------------------------------------------------------------
# Summary table
# ----------------------------------------------------------------
def print_summary(
    scheme_results: dict[str, tuple[pd.Timestamp, dict]],
) -> None:
    """Log a human-readable table of all computed metrics."""
    logger.info("")
    logger.info(
        f"{'Fund':<20} {'As-Of':<12} {'1Y%':>7} {'3Y%':>7} {'5Y%':>7} "
        f"{'CAGR1Y':>8} {'CAGR3Y':>8} {'CAGR5Y':>8}"
    )
    logger.info("-" * 82)
    for scheme, (as_of, m) in sorted(scheme_results.items()):
        def fmt(v: float | None) -> str:
            return f"{v:>7.2f}" if v is not None else "   NULL"

        logger.info(
            f"{scheme:<20} {str(as_of.date()):<12} "
            f"{fmt(m.get('return_1y'))} {fmt(m.get('return_3y'))} {fmt(m.get('return_5y'))} "
            f"{fmt(m.get('cagr_1y'))} {fmt(m.get('cagr_3y'))} {fmt(m.get('cagr_5y'))}"
        )
    logger.info("")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Compute return + CAGR metrics into Fact_Returns")
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
    logger.info("METRICS RETURNS — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        nav_data = load_nav_timeseries(conn, fund_code=args.fund_code)

        # Compute metrics per fund
        fund_key_results: dict[int, tuple[pd.Timestamp, dict]] = {}
        scheme_results: dict[str, tuple[pd.Timestamp, dict]] = {}

        for fund_key, (scheme_code, series) in nav_data.items():
            as_of, metrics = compute_returns_for_fund(series, as_of=as_of_override)
            fund_key_results[fund_key] = (as_of, metrics)
            scheme_results[scheme_code] = (as_of, metrics)

        print_summary(scheme_results)
        validate_results(scheme_results)
        upsert_fact_returns(conn, fund_key_results)

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("METRICS RETURNS — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
