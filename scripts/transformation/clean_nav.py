"""
================================================================
NAV Data Cleaning
================================================================
Cleans and standardizes the three raw Day 1 parquets into a
unified schema ready for Day 3's star schema ETL.

Inputs:
    data/raw/yahoo_funds_*.parquet
    data/raw/yahoo_benchmark_*.parquet
    data/raw/amfi_nav_current_*.parquet

Outputs:
    data/processed/nav_yahoo_clean_<date>.parquet
        -- ETFs + benchmarks in unified schema
    data/processed/nav_amfi_clean_<date>.parquet
        -- AMFI snapshot in unified schema

Usage:
    python scripts/transformation/clean_nav.py
    python scripts/transformation/clean_nav.py --skip-amfi
    python scripts/transformation/clean_nav.py --skip-yahoo
================================================================
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from data_quality import generate_quality_report, log_quality_report

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
LOG_DIR = PROJECT_ROOT / "logs"

DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

NAV_OUTLIER_Z_THRESHOLD = 5.0
MIN_VALID_NAV = 0.01

# Unified column order for all processed NAV parquets.
# Day 3 ETL reads this exact schema to load Fact_NAV.
UNIFIED_COLS = [
    "ticker",       # scheme_code (AMFI) or Yahoo ticker symbol
    "name",         # scheme_name (AMFI) or fund_name (Yahoo)
    "date",         # tz-naive date
    "nav",          # closing NAV / price
    "open",         # open price (Yahoo only; NaN for AMFI)
    "high",         # high price (Yahoo only; NaN for AMFI)
    "low",          # low price (Yahoo only; NaN for AMFI)
    "volume",       # volume (Yahoo only; NaN for AMFI)
    "source",       # "amfi" | "yahoo_etf" | "yahoo_benchmark"
    "amc",          # AMC name (AMFI) or "" (Yahoo — joined in Day 3)
    "category",     # scheme_type (AMFI) or "" (Yahoo)
    "is_outlier",   # True if |z-score| > NAV_OUTLIER_Z_THRESHOLD
    "fetch_timestamp",
]

# Delisted Yahoo tickers encountered during Day 1 ingestion.
# TODO: verify replacement tickers on Yahoo Finance and populate values.
DELISTED_TICKERS: dict[str, Optional[str]] = {
    "ICICINIFTY.NS": None,
    "KOTAKNV20.NS": None,
    "UTINIFTETF.NS": None,
    "ICICIPRAMC.NS": None,
    "ICICIBANKN.NS": None,
}

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
        logging.FileHandler(LOG_DIR / "nav_cleaning.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("nav_cleaning")


# ----------------------------------------------------------------
# Loading
# ----------------------------------------------------------------
def load_latest_raw(prefix: str) -> Optional[pd.DataFrame]:
    """
    Load the most recent data/raw/<prefix>_*.parquet by date-stamp.

    Using the date-stamp suffix means this is decoupled from hardcoded
    filenames — tomorrow's run automatically picks up today's new file.

    Args:
        prefix: File name prefix, e.g. "yahoo_funds" or "amfi_nav_current".

    Returns:
        Loaded DataFrame, or None if no matching file exists.
    """
    matches = sorted(DATA_RAW.glob(f"{prefix}_*.parquet"))
    if not matches:
        logger.error(f"No file found for prefix '{prefix}' in {DATA_RAW}")
        return None
    path = matches[-1]
    df = pd.read_parquet(path)
    logger.info(f"Loaded: {path.name} ({len(df):,} rows, {df.columns.tolist()})")
    return df


# ----------------------------------------------------------------
# Cleaning steps (each is a pure transformation — input in, output out)
# ----------------------------------------------------------------
def strip_timezone(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    """
    Convert a tz-aware datetime column to tz-naive date-only values.

    Yahoo Finance returns Asia/Kolkata-aware timestamps. AMFI uses
    tz-naive dates. We normalize everything to tz-naive so joins work.

    Args:
        df: Input DataFrame.
        col: Name of the datetime column to normalize.

    Returns:
        DataFrame with tz-naive, time-stripped date column.
    """
    if col not in df.columns:
        return df
    series = pd.to_datetime(df[col])
    if series.dt.tz is not None:
        series = series.dt.tz_localize(None)
    df = df.copy()
    df[col] = series.dt.normalize()
    return df


def drop_trailing_null_rows(
    df: pd.DataFrame,
    value_col: str = "nav",
    group_col: str = "ticker",
) -> pd.DataFrame:
    """
    Drop the last row per group only when its value is null.

    The 2026-05-28 nulls in Yahoo data are trailing rows where market
    data hadn't settled at fetch time. We only remove the last row per
    ticker when null — never touching genuine mid-series gaps.

    Args:
        df: Input DataFrame.
        value_col: Column to check for trailing nulls.
        group_col: Column used to define groups (one drop per group).

    Returns:
        DataFrame with trailing null rows removed, reset index.
    """
    df = df.sort_values([group_col, "date"]).copy()
    last_rows = df.groupby(group_col, sort=False).tail(1)
    trailing_null_idx = last_rows[last_rows[value_col].isna()].index
    removed = len(trailing_null_idx)
    if removed > 0:
        logger.info(f"Dropped {removed} trailing null row(s) in '{value_col}' (unsettled market data)")
    return df.drop(index=trailing_null_idx).reset_index(drop=True)


def flag_nav_outliers(
    df: pd.DataFrame,
    value_col: str = "nav",
    group_col: str = "ticker",
    z_threshold: float = NAV_OUTLIER_Z_THRESHOLD,
) -> pd.DataFrame:
    """
    Add 'is_outlier' column: True where per-group z-score exceeds threshold.

    Flags rather than removes — downstream analytics can decide whether
    to exclude outliers. The flag is preserved through to the star schema
    so it can be used in DAX measures and Streamlit filters.

    Args:
        df: Input DataFrame.
        value_col: Column to analyse for outliers.
        group_col: Column used for per-series z-score computation.
        z_threshold: Flag rows with |z| > this value.

    Returns:
        DataFrame with added 'is_outlier' boolean column.
    """
    df = df.copy()
    mean = df.groupby(group_col)[value_col].transform("mean")
    std = df.groupby(group_col)[value_col].transform("std").replace(0, np.nan)
    z = (df[value_col] - mean) / std
    df["is_outlier"] = z.abs() > z_threshold

    n_flagged = int(df["is_outlier"].sum())
    if n_flagged > 0:
        logger.warning(f"Flagged {n_flagged} outlier(s) in '{value_col}' (|z| > {z_threshold})")
    else:
        logger.info(f"Outlier check passed for '{value_col}' — no anomalies detected")
    return df


def standardize_yahoo_schema(
    df: pd.DataFrame,
    source: str = "yahoo",
) -> pd.DataFrame:
    """
    Map Yahoo Finance columns to the unified NAV schema.

    Yahoo:   date, open, high, low, close, adj_close, volume,
             dividends, stock_splits, ticker, fetch_timestamp, fund_name
    Unified: ticker, name, date, nav, open, high, low, volume,
             source, amc, category, is_outlier, fetch_timestamp

    Args:
        df: Yahoo Finance DataFrame (funds or benchmarks).
        source: Value for the 'source' column (e.g. "yahoo_etf").

    Returns:
        DataFrame conforming to UNIFIED_COLS.
    """
    df = df.copy()
    df = df.rename(columns={"close": "nav", "fund_name": "name"})
    df["source"] = source
    df["amc"] = ""       # populated by Dim_Fund join in Day 3 ETL
    df["category"] = ""  # populated by cross-reference with AMFI scheme_type in Day 3
    if "is_outlier" not in df.columns:
        df["is_outlier"] = False

    available = [c for c in UNIFIED_COLS if c in df.columns]
    return df[available].reset_index(drop=True)


def standardize_amfi_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map AMFI NAV columns to the unified NAV schema.

    AMFI:    scheme_code, isin_div_payout, isin_div_reinvestment,
             scheme_name, nav, date, amc, scheme_type, fetch_timestamp
    Unified: ticker (=scheme_code), name (=scheme_name),
             date, nav, amc, category (=scheme_type), ...

    OHLCV columns are set to NaN — AMFI publishes only end-of-day NAV.

    Args:
        df: AMFI NAV DataFrame from fetch_amfi_nav.py.

    Returns:
        DataFrame conforming to UNIFIED_COLS.
    """
    df = df.copy()
    df = df.rename(columns={
        "scheme_code": "ticker",
        "scheme_name": "name",
        "scheme_type": "category",
    })
    df["source"] = "amfi"
    df["open"] = np.nan
    df["high"] = np.nan
    df["low"] = np.nan
    df["volume"] = np.nan
    if "is_outlier" not in df.columns:
        df["is_outlier"] = False

    available = [c for c in UNIFIED_COLS if c in df.columns]
    return df[available].reset_index(drop=True)


def validate_cleaned(df: pd.DataFrame, label: str) -> None:
    """
    Assert that critical key columns contain no nulls. Log a summary.

    Args:
        df: Cleaned DataFrame to validate.
        label: Dataset label for log messages.

    Raises:
        ValueError: If 'ticker', 'date', or 'nav' contain nulls after cleaning.
    """
    for col in ("ticker", "date", "nav"):
        if col not in df.columns:
            continue
        null_count = int(df[col].isna().sum())
        if null_count > 0:
            raise ValueError(
                f"[{label}] Critical column '{col}' has {null_count} nulls after cleaning"
            )
    logger.info(
        f"[{label}] Validation OK: {len(df):,} rows | "
        f"{df['ticker'].nunique()} unique tickers | "
        f"{df['is_outlier'].sum()} outliers flagged"
    )


def save_processed(df: pd.DataFrame, filename: str) -> Path:
    """Save cleaned DataFrame to data/processed/ with a date-stamp suffix."""
    date_stamp = datetime.now().strftime("%Y%m%d")
    output_path = DATA_PROCESSED / f"{filename}_{date_stamp}.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"Saved: {output_path.name} ({len(df):,} rows, {size_kb:.1f} KB)")
    return output_path


# ----------------------------------------------------------------
# Pipeline functions
# ----------------------------------------------------------------
def clean_yahoo(skip: bool = False) -> Optional[pd.DataFrame]:
    """
    Load, clean, and return unified Yahoo NAV DataFrame (ETFs + benchmarks).

    Returns None if skip=True or no raw files are found.
    """
    if skip:
        logger.info("Skipping Yahoo Finance cleaning (--skip-yahoo)")
        return None

    logger.info("=" * 60)
    logger.info("Cleaning Yahoo Finance data")
    logger.info("=" * 60)

    frames: list[pd.DataFrame] = []

    for prefix, source_label in [
        ("yahoo_funds", "yahoo_etf"),
        ("yahoo_benchmark", "yahoo_benchmark"),
    ]:
        df = load_latest_raw(prefix)
        if df is None:
            continue

        df = strip_timezone(df, col="date")
        df = drop_trailing_null_rows(df, value_col="close", group_col="ticker")
        df = flag_nav_outliers(df, value_col="close", group_col="ticker")
        df = standardize_yahoo_schema(df, source=source_label)
        frames.append(df)
        logger.info(f"  [{source_label}] {len(df):,} rows after cleaning")

    if not frames:
        logger.error("No Yahoo data loaded — skipping Yahoo output")
        return None

    combined = pd.concat(frames, ignore_index=True)
    validate_cleaned(combined, "Yahoo")

    report = generate_quality_report(
        df=combined,
        label="nav_yahoo_clean",
        required_cols=["ticker", "date", "nav"],
        key_cols=["ticker", "date"],
        date_col="date",
        max_age_days=5,
    )
    log_quality_report(report, logger)
    return combined


def clean_amfi(skip: bool = False) -> Optional[pd.DataFrame]:
    """
    Load, clean, and return unified AMFI NAV DataFrame.

    Returns None if skip=True or no raw file is found.
    """
    if skip:
        logger.info("Skipping AMFI cleaning (--skip-amfi)")
        return None

    logger.info("=" * 60)
    logger.info("Cleaning AMFI data")
    logger.info("=" * 60)

    df = load_latest_raw("amfi_nav_current")
    if df is None:
        return None

    # AMFI current snapshot has no trailing nulls (already filtered at ingestion)
    df = flag_nav_outliers(df, value_col="nav", group_col="scheme_code")
    df = standardize_amfi_schema(df)
    validate_cleaned(df, "AMFI")

    report = generate_quality_report(
        df=df,
        label="nav_amfi_clean",
        required_cols=["ticker", "date", "nav"],
        key_cols=["ticker", "date"],
        date_col="date",
        max_age_days=3,
    )
    log_quality_report(report, logger)
    return df


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw NAV parquets to unified schema")
    parser.add_argument("--skip-yahoo", action="store_true", help="Skip Yahoo Finance cleaning")
    parser.add_argument("--skip-amfi", action="store_true", help="Skip AMFI cleaning")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("NAV CLEANING — START")
    logger.info("=" * 60)
    start_ts = datetime.now()

    yahoo_df = clean_yahoo(skip=args.skip_yahoo)
    if yahoo_df is not None:
        save_processed(yahoo_df, "nav_yahoo_clean")

    amfi_df = clean_amfi(skip=args.skip_amfi)
    if amfi_df is not None:
        save_processed(amfi_df, "nav_amfi_clean")

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info("=" * 60)
    logger.info(f"NAV CLEANING — COMPLETE in {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
