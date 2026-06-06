"""
================================================================
ML: NAV Forecasting (Prophet)
================================================================
Fits a Facebook Prophet time-series model on a fund's historical
NAV (from dbo.Fact_NAV) and projects 30 / 60 / 90-day NAV
trajectories with confidence (uncertainty) intervals.

Only Yahoo ETF/benchmark funds carry a true daily time series
(~1,236 trading days each). AMFI schemes hold a single NAV
snapshot and are therefore not forecastable.

Reusable API (imported by streamlit/app.py):
    get_connection()                 -> psycopg2 connection
    list_forecastable_funds(conn)    -> list[FundRef]
    load_nav_series(conn, code)      -> pd.Series  (DatetimeIndex)
    generate_forecast(series, ...)   -> ForecastResult

Usage:
    python scripts/ml/forecast_nav.py --fund-code NIFTYBEES.NS
    python scripts/ml/forecast_nav.py --fund-code GOLDBEES.NS --save
================================================================
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

# Forecast horizons exposed in the dashboard (calendar days)
FORECAST_HORIZONS: tuple[int, ...] = (30, 60, 90)
MAX_HORIZON_DAYS = max(FORECAST_HORIZONS)

# Prophet needs a reasonable history to learn trend + yearly seasonality.
# 200 trading days mirrors the 1-year threshold used in metrics_returns.py.
MIN_HISTORY_DAYS = 200

# Width of the Prophet uncertainty interval (0.80 = 80% CI band).
DEFAULT_INTERVAL_WIDTH = 0.80

# Only these Fact_NAV sources have a genuine daily time series.
YAHOO_SOURCES = ("yahoo_etf", "yahoo_benchmark")

# ----------------------------------------------------------------
# Logging  (mute Prophet/cmdstanpy chatter — INFO floods stdout)
# ----------------------------------------------------------------
for _noisy in ("prophet", "cmdstanpy", "stanio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

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
        logging.FileHandler(LOG_DIR / "forecast_nav.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("forecast_nav")


# ----------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------
@dataclass(frozen=True)
class FundRef:
    """A forecastable fund and the size of its NAV history."""

    fund_key: int
    scheme_code: str
    fund_name: str
    n_obs: int


@dataclass
class ForecastResult:
    """Output of a single Prophet fit.

    Attributes:
        scheme_code: Fund ticker the forecast belongs to.
        history: Observed NAV series (DatetimeIndex -> nav).
        forecast: Future-only frame with columns
            ['ds', 'yhat', 'yhat_lower', 'yhat_upper'] for MAX_HORIZON_DAYS.
        interval_width: Confidence level of the uncertainty band (e.g. 0.80).
    """

    scheme_code: str
    history: pd.Series
    forecast: pd.DataFrame
    interval_width: float

    def at_horizon(self, days: int) -> dict[str, float]:
        """Return the projected NAV + CI bounds `days` ahead of last actual."""
        horizon_date = self.history.index.max() + pd.Timedelta(days=days)
        # Nearest forecast row on or before the horizon date.
        window = self.forecast[self.forecast["ds"] <= horizon_date]
        row = (window.iloc[-1] if not window.empty else self.forecast.iloc[-1])
        return {
            "date": row["ds"],
            "yhat": float(row["yhat"]),
            "yhat_lower": float(row["yhat_lower"]),
            "yhat_upper": float(row["yhat_upper"]),
        }


# ----------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------
def get_connection() -> psycopg2.extensions.connection:
    """Open a connection to mf_analytics using .env credentials."""
    return psycopg2.connect(
        host=os.getenv("LOCAL_DB_HOST", "localhost"),
        port=int(os.getenv("LOCAL_DB_PORT", "5432")),
        dbname=os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        user=os.getenv("LOCAL_DB_USER", "postgres"),
        password=os.getenv("LOCAL_DB_PASSWORD", ""),
    )


def list_forecastable_funds(conn: psycopg2.extensions.connection) -> list[FundRef]:
    """Return Yahoo funds with at least MIN_HISTORY_DAYS of NAV history.

    Ordered by fund_name so the Streamlit dropdown reads naturally.
    """
    query = """
        SELECT df.fund_key, df.scheme_code, df.fund_name, COUNT(*) AS n_obs
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
        WHERE fn.source IN %s
        GROUP BY df.fund_key, df.scheme_code, df.fund_name
        HAVING COUNT(*) >= %s
        ORDER BY df.fund_name
    """
    with conn.cursor() as cur:
        cur.execute(query, (YAHOO_SOURCES, MIN_HISTORY_DAYS))
        rows = cur.fetchall()
    funds = [FundRef(fk, code, name, n) for fk, code, name, n in rows]
    logger.info(f"{len(funds)} forecastable funds (>= {MIN_HISTORY_DAYS} obs)")
    return funds


def load_nav_series(
    conn: psycopg2.extensions.connection,
    scheme_code: str,
) -> pd.Series:
    """Load a single fund's NAV time series from Fact_NAV.

    Args:
        conn: Active psycopg2 connection.
        scheme_code: Fund ticker (e.g. 'NIFTYBEES.NS').

    Returns:
        NAV values indexed by pd.Timestamp, sorted ascending, de-duplicated.

    Raises:
        ValueError: If the fund has no NAV rows.
    """
    query = """
        SELECT dd.full_date, fn.nav
        FROM dbo.Fact_NAV fn
        JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
        JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
        WHERE df.scheme_code = %s
        ORDER BY dd.full_date
    """
    with conn.cursor() as cur:
        cur.execute(query, (scheme_code,))
        rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No NAV history for '{scheme_code}'")

    series = pd.Series(
        [float(nav) for _, nav in rows],
        index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows]),
        name=scheme_code,
        dtype=float,
    )
    # Collapse any accidental duplicate dates (keep last).
    series = series[~series.index.duplicated(keep="last")].sort_index()
    logger.info(f"{scheme_code}: loaded {len(series):,} NAV observations")
    return series


# ----------------------------------------------------------------
# Forecasting
# ----------------------------------------------------------------
def generate_forecast(
    series: pd.Series,
    horizon_days: int = MAX_HORIZON_DAYS,
    interval_width: float = DEFAULT_INTERVAL_WIDTH,
) -> ForecastResult:
    """Fit Prophet on `series` and project `horizon_days` into the future.

    Yearly seasonality is enabled (NAVs show annual cyclicality); weekly and
    daily seasonality are disabled because NAV is published on trading days
    only, so an artificial weekday cycle would be misleading.

    Args:
        series: NAV series indexed by pd.Timestamp.
        horizon_days: Number of future calendar days to forecast.
        interval_width: Width of the uncertainty interval (0.80 = 80% CI).

    Returns:
        A populated ForecastResult.

    Raises:
        ValueError: If the series has fewer than MIN_HISTORY_DAYS points.
    """
    if len(series) < MIN_HISTORY_DAYS:
        raise ValueError(
            f"Need >= {MIN_HISTORY_DAYS} observations to forecast, "
            f"got {len(series)} for '{series.name}'"
        )

    # Imported lazily — Prophet import is slow (~1s) and not always needed.
    from prophet import Prophet

    frame = pd.DataFrame({"ds": series.index, "y": series.to_numpy()})

    model = Prophet(
        interval_width=interval_width,
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    model.fit(frame)

    future = model.make_future_dataframe(periods=horizon_days, freq="D")
    forecast = model.predict(future)

    # Keep only the future horizon (drop in-sample fitted rows).
    last_actual = series.index.max()
    future_only = (
        forecast.loc[
            forecast["ds"] > last_actual,
            ["ds", "yhat", "yhat_lower", "yhat_upper"],
        ]
        .reset_index(drop=True)
    )

    logger.info(
        f"{series.name}: forecast {len(future_only)} days "
        f"({interval_width:.0%} CI), last actual {last_actual.date()}"
    )
    return ForecastResult(
        scheme_code=str(series.name),
        history=series,
        forecast=future_only,
        interval_width=interval_width,
    )


# ----------------------------------------------------------------
# CLI helpers
# ----------------------------------------------------------------
def _print_horizon_table(result: ForecastResult) -> None:
    """Log projected NAV at each standard horizon."""
    last_nav = float(result.history.iloc[-1])
    logger.info("")
    logger.info(
        f"{result.scheme_code} — last actual NAV {last_nav:.4f} "
        f"on {result.history.index.max().date()} "
        f"({result.interval_width:.0%} CI)"
    )
    logger.info(f"{'Horizon':<9} {'Date':<12} {'Forecast':>12} {'Lower':>12} {'Upper':>12} {'Δ%':>8}")
    logger.info("-" * 68)
    for days in FORECAST_HORIZONS:
        p = result.at_horizon(days)
        change = (p["yhat"] / last_nav - 1) * 100
        logger.info(
            f"{f'+{days}d':<9} {str(pd.Timestamp(p['date']).date()):<12} "
            f"{p['yhat']:>12.4f} {p['yhat_lower']:>12.4f} {p['yhat_upper']:>12.4f} "
            f"{change:>7.2f}%"
        )
    logger.info("")


def _save_forecast(result: ForecastResult) -> Path:
    """Persist the future-horizon forecast to data/processed as parquet."""
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / f"forecast_{result.scheme_code.replace('.', '_')}.parquet"
    df = result.forecast.copy()
    df.insert(0, "scheme_code", result.scheme_code)
    df["interval_width"] = result.interval_width
    df.to_parquet(out, index=False)
    logger.info(f"Saved forecast -> {out.name}")
    return out


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Forecast fund NAV with Prophet")
    parser.add_argument(
        "--fund-code", default="NIFTYBEES.NS",
        help="Fund ticker to forecast (default: NIFTYBEES.NS)",
    )
    parser.add_argument(
        "--horizon", type=int, default=MAX_HORIZON_DAYS,
        help=f"Days ahead to forecast (default: {MAX_HORIZON_DAYS})",
    )
    parser.add_argument(
        "--interval-width", type=float, default=DEFAULT_INTERVAL_WIDTH,
        help=f"Uncertainty interval width 0-1 (default: {DEFAULT_INTERVAL_WIDTH})",
    )
    parser.add_argument(
        "--list", action="store_true", help="List forecastable funds and exit",
    )
    parser.add_argument(
        "--save", action="store_true", help="Save forecast to data/processed parquet",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("FORECAST NAV — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        if args.list:
            for f in list_forecastable_funds(conn):
                logger.info(f"  {f.scheme_code:<16} {f.fund_name:<40} {f.n_obs:>6,} obs")
            return

        series = load_nav_series(conn, args.fund_code)
        result = generate_forecast(
            series,
            horizon_days=args.horizon,
            interval_width=args.interval_width,
        )
        _print_horizon_table(result)
        if args.save:
            _save_forecast(result)

    except Exception as e:
        logger.error(f"Forecast failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("FORECAST NAV — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
