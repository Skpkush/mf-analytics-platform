"""
================================================================
Yahoo Finance NAV Data Ingestion
================================================================
Pulls historical NAV data for top Indian Mutual Funds and the
Nifty 50 benchmark from Yahoo Finance.

Outputs:
    data/raw/yahoo_funds_<date>.parquet
    data/raw/yahoo_benchmark_<date>.parquet

Usage:
    python scripts/ingestion/fetch_yahoo_finance.py
    python scripts/ingestion/fetch_yahoo_finance.py --start 2020-01-01 --end 2026-05-23
================================================================
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yfinance as yf
from tqdm import tqdm

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"

DATA_RAW.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Top Indian Mutual Fund tickers on Yahoo Finance
# Format: AMC_FundName_TickerOnYahoo
# Note: Yahoo's coverage of Indian MFs is limited; for full AMFI data
# use fetch_amfi_nav.py. This script focuses on ETFs + index funds
# that have clean Yahoo tickers.
FUND_TICKERS = {
    # ETFs (best Yahoo coverage)
    "NIFTYBEES.NS": "Nippon India ETF Nifty BeES",
    "BANKBEES.NS": "Nippon India ETF Bank BeES",
    "GOLDBEES.NS": "Nippon India ETF Gold BeES",
    "JUNIORBEES.NS": "Nippon India ETF Junior BeES",
    "LIQUIDBEES.NS": "Nippon India ETF Liquid BeES",
    "ICICINIFTY.NS": "ICICI Prudential Nifty ETF",
    "ICICIB22.NS": "ICICI Prudential Bharat 22 ETF",
    "SETFNIF50.NS": "SBI ETF Nifty 50",
    "SETFNIFBK.NS": "SBI ETF Nifty Bank",
    "HDFCNIFTY.NS": "HDFC Nifty 50 ETF",
    "KOTAKNV20.NS": "Kotak NV 20 ETF",
    "UTINIFTETF.NS": "UTI Nifty ETF",
    "MON100.NS": "Motilal Oswal NASDAQ 100 ETF",
    "MONIFTY500.NS": "Motilal Oswal Nifty 500 ETF",
    "ICICIPRAMC.NS": "ICICI Prudential Pharma ETF",
    "ICICIBANKN.NS": "ICICI Prudential Bank ETF",
}

# Benchmark indices
BENCHMARK_TICKERS = {
    "^NSEI": "Nifty 50",
    "^BSESN": "BSE Sensex",
    "^NSEBANK": "Nifty Bank",
    "^CNXIT": "Nifty IT",
    "^CRSLDX": "Nifty 500",
}

# ----------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "yahoo_ingestion.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("yahoo_ingestion")


# ----------------------------------------------------------------
# Core functions
# ----------------------------------------------------------------
def fetch_ticker_history(
    ticker: str,
    start: str,
    end: str,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """
    Fetch historical price data for a single ticker with retry logic.

    Args:
        ticker: Yahoo Finance ticker symbol
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        max_retries: Number of retry attempts on failure

    Returns:
        DataFrame with OHLCV data, or None if all retries fail
    """
    for attempt in range(1, max_retries + 1):
        try:
            t = yf.Ticker(ticker)
            df = t.history(start=start, end=end, auto_adjust=False)

            if df.empty:
                logger.warning(f"  [{ticker}] Empty response on attempt {attempt}")
                continue

            df = df.reset_index()
            df["ticker"] = ticker
            df["fetch_timestamp"] = datetime.now()

            # Standardize column names
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]

            return df

        except Exception as e:
            logger.error(f"  [{ticker}] Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                logger.error(f"  [{ticker}] ALL RETRIES FAILED. Skipping.")
                return None

    return None


def fetch_batch(
    tickers: dict,
    start: str,
    end: str,
    label: str,
) -> pd.DataFrame:
    """
    Fetch a batch of tickers and combine into single DataFrame.

    Args:
        tickers: Dict of {ticker_symbol: fund_name}
        start: Start date
        end: End date
        label: Label for logging (e.g., "Funds", "Benchmarks")

    Returns:
        Combined DataFrame with all tickers
    """
    logger.info(f"=" * 60)
    logger.info(f"Fetching {len(tickers)} {label} from {start} to {end}")
    logger.info(f"=" * 60)

    all_dfs: List[pd.DataFrame] = []
    success_count = 0
    fail_count = 0

    for ticker, fund_name in tqdm(tickers.items(), desc=f"Fetching {label}"):
        df = fetch_ticker_history(ticker, start, end)

        if df is not None and not df.empty:
            df["fund_name"] = fund_name
            all_dfs.append(df)
            success_count += 1
            logger.info(f"  ✓ [{ticker}] {len(df)} rows -- {fund_name}")
        else:
            fail_count += 1

    logger.info(f"-" * 60)
    logger.info(f"{label} summary: {success_count} success / {fail_count} failed")
    logger.info(f"-" * 60)

    if not all_dfs:
        logger.error(f"No data fetched for {label}!")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    return combined


def save_parquet(df: pd.DataFrame, filename: str) -> Path:
    """Save DataFrame to parquet with date-stamped filename."""
    date_stamp = datetime.now().strftime("%Y%m%d")
    output_path = DATA_RAW / f"{filename}_{date_stamp}.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)
    logger.info(f"Saved: {output_path} ({len(df):,} rows, {output_path.stat().st_size / 1024:.1f} KB)")
    return output_path


def print_summary(df: pd.DataFrame, label: str) -> None:
    """Print a quality summary of fetched data."""
    if df.empty:
        logger.warning(f"{label} dataframe is empty")
        return

    logger.info(f"")
    logger.info(f"📊 {label} Summary")
    logger.info(f"   Rows           : {len(df):,}")
    logger.info(f"   Unique tickers : {df['ticker'].nunique()}")
    logger.info(f"   Date range     : {df['date'].min().date()} to {df['date'].max().date()}")
    logger.info(f"   Null close vals: {df['close'].isna().sum()}")
    logger.info(f"   Columns        : {list(df.columns)}")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch Yahoo Finance MF + benchmark data")
    parser.add_argument(
        "--start",
        default=(datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d"),
        help="Start date (YYYY-MM-DD). Default: 5 years ago.",
    )
    parser.add_argument(
        "--end",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--skip-funds",
        action="store_true",
        help="Skip fund data, fetch only benchmarks",
    )
    parser.add_argument(
        "--skip-benchmarks",
        action="store_true",
        help="Skip benchmark data, fetch only funds",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("YAHOO FINANCE INGESTION — START")
    logger.info(f"Date range: {args.start} to {args.end}")
    logger.info("=" * 60)

    start_ts = datetime.now()

    # Fetch funds
    if not args.skip_funds:
        funds_df = fetch_batch(FUND_TICKERS, args.start, args.end, "Funds (ETFs)")
        if not funds_df.empty:
            save_parquet(funds_df, "yahoo_funds")
            print_summary(funds_df, "Funds")

    # Fetch benchmarks
    if not args.skip_benchmarks:
        bench_df = fetch_batch(BENCHMARK_TICKERS, args.start, args.end, "Benchmarks")
        if not bench_df.empty:
            save_parquet(bench_df, "yahoo_benchmark")
            print_summary(bench_df, "Benchmarks")

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info("=" * 60)
    logger.info(f"✅ YAHOO FINANCE INGESTION — COMPLETE in {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
