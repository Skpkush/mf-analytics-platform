"""
================================================================
Financial Metrics: Risk-Adjusted Returns (Sharpe, Sortino, Treynor)
================================================================
Computes three risk-adjusted metrics for all Yahoo ETF/benchmark
funds. All metrics use trailing 1-year data for consistency.

    Sharpe  = mean(excess_ret) / σ(excess_ret) × √252
    Sortino = mean(excess_ret) × 252 / downside_deviation_annual
    Treynor = (CAGR_1Y − Rf) / Beta

Where:
    excess_ret_t = daily_return_t − (Rf / 252)
    Rf           = 6.5% / year  (RBI repo rate)
    downside_dev = √(mean(downside_excess_returns²)) × √252
    Beta         = from dbo.Fact_Returns (populated by metrics_market.py)

UPSERT targets existing (fund_key, date_key) rows in Fact_Returns.
Only sharpe_ratio, sortino_ratio, treynor_ratio are written.

RUN AFTER metrics_market.py — Treynor reads Beta from Fact_Returns.

Validation:
    GOLDBEES.NS sharpe_ratio expected > 0 (cagr_1y=61% >> Rf=6.5%)
    NIFTYBEES.NS sharpe_ratio expected < 0 (cagr_1y=-2.43% < Rf=6.5%)

Usage:
    python scripts/analytics/metrics_risk_adjusted.py
    python scripts/analytics/metrics_risk_adjusted.py --fund-code GOLDBEES.NS
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

RISK_FREE_ANNUAL = 0.065       # 6.5% RBI repo rate
TRADING_DAYS = 252             # NSE/BSE annual trading days
TRAILING_WINDOW_DAYS = 365     # calendar days for 1-year trailing window
MIN_OBS_SHARPE = 50            # minimum observations for Sharpe/Sortino

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
        logging.FileHandler(LOG_DIR / "metrics_risk_adjusted.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("metrics_risk_adjusted")


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
    return float(v) if v is not None else None


def load_nav_timeseries(
    conn: psycopg2.extensions.connection,
    fund_code: str | None = None,
) -> dict[int, tuple[str, pd.Series]]:
    """Load NAV time series for Yahoo ETF and benchmark funds."""
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
    Load existing Fact_Returns for UPSERT keys, cagr_1y, and beta
    (Treynor needs both cagr_1y and beta).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fr.fund_key, df.scheme_code, fr.date_key,
                   fr.cagr_1y, fr.beta
            FROM dbo.Fact_Returns fr
            JOIN dbo.Dim_Fund df ON df.fund_key = fr.fund_key
        """)
        return {
            row[1]: {
                "fund_key": row[0],
                "date_key": row[2],
                "cagr_1y": _to_float(row[3]),
                "beta": _to_float(row[4]),
            }
            for row in cur.fetchall()
        }


# ----------------------------------------------------------------
# Metric computation
# ----------------------------------------------------------------
def _excess_returns(
    series: pd.Series,
    as_of: pd.Timestamp,
) -> pd.Series | None:
    """
    Compute daily excess returns = daily_return − (Rf/252)
    over the trailing TRAILING_WINDOW_DAYS calendar days up to as_of.

    Returns None if fewer than MIN_OBS_SHARPE observations.
    """
    cutoff = as_of - pd.Timedelta(days=TRAILING_WINDOW_DAYS)
    window = series[(series.index >= cutoff) & (series.index <= as_of)]
    daily_ret = window.pct_change().dropna()

    if len(daily_ret) < MIN_OBS_SHARPE:
        return None

    rf_daily = RISK_FREE_ANNUAL / TRADING_DAYS
    return daily_ret - rf_daily


def compute_sharpe(excess_ret: pd.Series | None) -> float | None:
    """
    Annualised Sharpe ratio.

    Sharpe = mean(excess_ret) / σ(excess_ret) × √252

    Returns None if std dev is zero (avoids division by zero for
    near-cash funds like LIQUIDBEES).
    """
    if excess_ret is None or excess_ret.empty:
        return None
    std = float(excess_ret.std())
    if std == 0.0:
        return None
    sharpe = float(excess_ret.mean()) / std * np.sqrt(TRADING_DAYS)
    return round(sharpe, 4)


def compute_sortino(excess_ret: pd.Series | None) -> float | None:
    """
    Annualised Sortino ratio.

    downside_dev = √(mean(negative_excess_returns²)) × √252
    Sortino      = mean(excess_ret) × 252 / downside_dev

    Uses semi-deviation (only negative excess returns) in denominator,
    making it a better measure of downside risk than Sharpe.
    """
    if excess_ret is None or excess_ret.empty:
        return None
    downside = excess_ret[excess_ret < 0]
    if downside.empty:
        return None
    downside_dev = float(np.sqrt((downside**2).mean()) * np.sqrt(TRADING_DAYS))
    if downside_dev == 0.0:
        return None
    sortino = float(excess_ret.mean()) * TRADING_DAYS / downside_dev
    return round(sortino, 4)


def compute_treynor(
    cagr_1y: float | None,
    beta: float | None,
) -> float | None:
    """
    Treynor ratio = (CAGR_1Y − Rf) / Beta

    Uses cagr_1y (%) from Fact_Returns — consistent with the 1-year
    window used by Sharpe and Sortino.
    Beta must already be populated by metrics_market.py.

    Returns None if beta is None, zero, or cagr_1y is None.
    """
    if cagr_1y is None or beta is None or beta == 0.0:
        return None
    rf_pct = RISK_FREE_ANNUAL * 100  # same % scale as stored cagr_1y
    treynor = (cagr_1y - rf_pct) / beta
    return round(treynor, 4)


def compute_risk_adjusted_for_fund(
    series: pd.Series,
    cagr_1y: float | None,
    beta: float | None,
    as_of: pd.Timestamp | None = None,
) -> dict[str, float | None]:
    """
    Compute Sharpe, Sortino, and Treynor for a single fund.

    Args:
        series:  NAV time series indexed by pd.Timestamp.
        cagr_1y: From Fact_Returns (% e.g. -2.43). Used for Treynor.
        beta:    From Fact_Returns. Required for Treynor; must be
                 populated by metrics_market.py first.
        as_of:   Compute as of this date. Defaults to series.index.max().

    Returns:
        {'sharpe_ratio': ..., 'sortino_ratio': ..., 'treynor_ratio': ...}
    """
    effective_as_of = as_of if as_of is not None else series.index.max()
    excess_ret = _excess_returns(series, effective_as_of)

    return {
        "sharpe_ratio": compute_sharpe(excess_ret),
        "sortino_ratio": compute_sortino(excess_ret),
        "treynor_ratio": compute_treynor(cagr_1y, beta),
    }


# ----------------------------------------------------------------
# Validation
# ----------------------------------------------------------------
def validate_results(scheme_results: dict[str, dict]) -> None:
    """
    Sanity-check directional correctness of Sharpe ratios.
    GOLDBEES: cagr_1y=61% >> Rf=6.5% → Sharpe must be positive.
    NIFTYBEES: cagr_1y=-2.43% < Rf=6.5% → Sharpe must be negative.
    """
    checks = {
        "GOLDBEES.NS":  ("sharpe_ratio", ">", 0),
        "NIFTYBEES.NS": ("sharpe_ratio", "<", 0),
    }
    for fund, (col, direction, threshold) in checks.items():
        if fund not in scheme_results:
            continue
        val = scheme_results[fund].get(col)
        if val is None:
            logger.warning(f"Validation skipped: {fund} {col} is NULL")
            continue
        passed = (val > threshold if direction == ">" else val < threshold)
        status = "PASSED" if passed else "WARNING"
        logger.info(
            f"Validation {status}: {fund} {col} = {val:.4f} "
            f"(expected {direction} {threshold})"
        )


# ----------------------------------------------------------------
# UPSERT — only Sharpe, Sortino, Treynor columns
# ----------------------------------------------------------------
_UPSERT_RISK_ADJ = """
INSERT INTO dbo.Fact_Returns (
    date_key, fund_key, sharpe_ratio, sortino_ratio, treynor_ratio
) VALUES %s
ON CONFLICT (fund_key, date_key) DO UPDATE SET
    sharpe_ratio  = EXCLUDED.sharpe_ratio,
    sortino_ratio = EXCLUDED.sortino_ratio,
    treynor_ratio = EXCLUDED.treynor_ratio
"""


def upsert_risk_adjusted(
    conn: psycopg2.extensions.connection,
    fund_key_results: dict[int, dict],
) -> int:
    """Upsert Sharpe, Sortino, Treynor into existing Fact_Returns rows."""
    def _f(v: float | None) -> float | None:
        return float(v) if v is not None else None

    records = [
        (
            d["date_key"],
            fund_key,
            _f(d["sharpe_ratio"]),
            _f(d["sortino_ratio"]),
            _f(d["treynor_ratio"]),
        )
        for fund_key, d in fund_key_results.items()
    ]
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_RISK_ADJ, records)
    conn.commit()
    logger.info(f"Fact_Returns: {len(records)} rows upserted (sharpe, sortino, treynor)")
    return len(records)


# ----------------------------------------------------------------
# Summary table
# ----------------------------------------------------------------
def print_summary(scheme_results: dict[str, dict]) -> None:
    logger.info("")
    logger.info(f"{'Fund':<20} {'Sharpe':>9} {'Sortino':>9} {'Treynor':>9}")
    logger.info("-" * 52)
    for scheme, m in sorted(scheme_results.items()):
        def fmt(v: float | None) -> str:
            return f"{v:>9.4f}" if v is not None else "     NULL"
        logger.info(
            f"{scheme:<20} "
            f"{fmt(m.get('sharpe_ratio'))} "
            f"{fmt(m.get('sortino_ratio'))} "
            f"{fmt(m.get('treynor_ratio'))}"
        )
    logger.info("")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute Sharpe, Sortino, Treynor into Fact_Returns"
    )
    parser.add_argument("--fund-code", default=None)
    parser.add_argument(
        "--as-of", default=None,
        help="As-of date YYYY-MM-DD (default: each fund's own latest date)",
    )
    args = parser.parse_args()

    as_of_override: pd.Timestamp | None = (
        pd.Timestamp(args.as_of) if args.as_of else None
    )

    logger.info("=" * 60)
    logger.info("METRICS RISK-ADJUSTED — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        existing = load_existing_metrics(conn)
        nav_data = load_nav_timeseries(conn, fund_code=args.fund_code)

        fund_key_results: dict[int, dict] = {}
        scheme_results: dict[str, dict] = {}

        for fund_key, (scheme_code, series) in nav_data.items():
            if scheme_code not in existing:
                logger.warning(f"  {scheme_code}: no Fact_Returns row — skipping")
                continue

            row = existing[scheme_code]
            as_of = as_of_override if as_of_override else series.index.max()
            metrics = compute_risk_adjusted_for_fund(
                series,
                cagr_1y=row["cagr_1y"],
                beta=row["beta"],
                as_of=as_of,
            )
            fund_key_results[fund_key] = {"date_key": row["date_key"], **metrics}
            scheme_results[scheme_code] = metrics

        print_summary(scheme_results)
        validate_results(scheme_results)
        upsert_risk_adjusted(conn, fund_key_results)

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("METRICS RISK-ADJUSTED — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
