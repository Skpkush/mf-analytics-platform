"""
================================================================
AMFI India NAV Data Ingestion
================================================================
Fetches official daily NAV data from AMFI India.

AMFI publishes a single text file with all schemes' NAVs daily.
URL: https://www.amfiindia.com/spages/NAVAll.txt

For HISTORICAL data, AMFI provides date-range scrapeable endpoints:
URL: https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx

Outputs:
    data/raw/amfi_nav_current_<date>.parquet  — today's snapshot
    data/raw/amfi_nav_history_<date>.parquet  — historical range

Usage:
    python scripts/ingestion/fetch_amfi_nav.py                    # today only
    python scripts/ingestion/fetch_amfi_nav.py --historical       # last 5 years
    python scripts/ingestion/fetch_amfi_nav.py --start 2020-01-01 # custom start
================================================================
"""

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"

DATA_RAW.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

AMFI_CURRENT_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
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
        logging.FileHandler(LOG_DIR / "amfi_ingestion.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("amfi_ingestion")


# ----------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------
def parse_amfi_text(raw_text: str) -> pd.DataFrame:
    """
    Parse AMFI NAV text file into a clean DataFrame.

    The AMFI file format:
        - Header section with field names
        - Section headers like "Open Ended Schemes(Equity Scheme - Large Cap Fund)"
        - Followed by AMC name line
        - Then scheme rows separated by ';'
        - Repeats for each AMC + category combination

    Returns:
        DataFrame with columns:
        scheme_code, isin_div_payout, isin_div_reinvestment, scheme_name,
        nav, repurchase_price, sale_price, date, amc, scheme_type
    """
    lines = raw_text.strip().split("\n")
    records = []

    current_amc = ""
    current_scheme_type = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Header line — skip
        if line.startswith("Scheme Code"):
            continue

        # Scheme type section header (e.g., "Open Ended Schemes(Equity Scheme - Large Cap Fund)")
        if "Schemes(" in line or line.startswith("Open Ended") or line.startswith("Close Ended"):
            current_scheme_type = line
            continue

        # AMC line — single value, no semicolons, all caps usually
        if ";" not in line:
            current_amc = line
            continue

        # Data row
        parts = line.split(";")
        if len(parts) >= 6:
            try:
                record = {
                    "scheme_code": parts[0].strip(),
                    "isin_div_payout": parts[1].strip(),
                    "isin_div_reinvestment": parts[2].strip(),
                    "scheme_name": parts[3].strip(),
                    "nav": parts[4].strip(),
                    "date": parts[5].strip() if len(parts) > 5 else "",
                    "amc": current_amc,
                    "scheme_type": current_scheme_type,
                }
                records.append(record)
            except Exception as e:
                logger.debug(f"Skipping malformed line: {line[:80]} | {e}")

    df = pd.DataFrame(records)

    if df.empty:
        return df

    # Clean NAV
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")

    # Parse date (format: DD-MMM-YYYY)
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")

    # Filter valid rows
    df = df[df["nav"].notna() & df["date"].notna()].copy()
    df["fetch_timestamp"] = datetime.now()

    return df.reset_index(drop=True)


# ----------------------------------------------------------------
# Fetchers
# ----------------------------------------------------------------
def fetch_amfi_current(max_retries: int = 3) -> Optional[pd.DataFrame]:
    """Fetch today's NAV snapshot from AMFI."""
    logger.info(f"Fetching current NAVs from {AMFI_CURRENT_URL}")

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(AMFI_CURRENT_URL, headers=HEADERS, timeout=30)
            response.raise_for_status()
            logger.info(f"  ✓ Response: {response.status_code}, {len(response.text):,} bytes")

            df = parse_amfi_text(response.text)
            logger.info(f"  ✓ Parsed {len(df):,} schemes")
            return df

        except Exception as e:
            logger.error(f"  Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                logger.error("  ALL RETRIES FAILED")
                return None

    return None


def fetch_amfi_historical(
    start_date: datetime,
    end_date: datetime,
    chunk_days: int = 90,
) -> Optional[pd.DataFrame]:
    """
    Fetch historical NAVs from AMFI for a date range.

    AMFI's historical endpoint accepts a date range but is unreliable
    for ranges > 90 days. We chunk requests.

    Args:
        start_date: Range start
        end_date: Range end
        chunk_days: Days per chunk request

    Returns:
        Combined historical DataFrame
    """
    logger.info(f"Fetching historical NAVs: {start_date.date()} to {end_date.date()}")
    logger.info(f"  Chunking by {chunk_days} days")

    all_chunks = []
    chunk_start = start_date

    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), end_date)
        logger.info(f"  Chunk: {chunk_start.date()} → {chunk_end.date()}")

        params = {
            "frmdt": chunk_start.strftime("%d-%b-%Y"),
            "todt": chunk_end.strftime("%d-%b-%Y"),
        }

        try:
            response = requests.get(
                AMFI_HISTORY_URL,
                params=params,
                headers=HEADERS,
                timeout=60,
            )
            response.raise_for_status()

            df_chunk = parse_amfi_text(response.text)

            if not df_chunk.empty:
                all_chunks.append(df_chunk)
                logger.info(f"    ✓ {len(df_chunk):,} rows")
            else:
                logger.warning(f"    Empty chunk")

            time.sleep(2)  # Be polite

        except Exception as e:
            logger.error(f"    Chunk failed: {e}")

        chunk_start = chunk_end + timedelta(days=1)

    if not all_chunks:
        logger.error("No historical data fetched")
        return None

    combined = pd.concat(all_chunks, ignore_index=True)
    combined = combined.drop_duplicates(subset=["scheme_code", "date"], keep="last")
    logger.info(f"  ✓ Total historical rows: {len(combined):,}")
    return combined


# ----------------------------------------------------------------
# Save + Summary
# ----------------------------------------------------------------
def save_parquet(df: pd.DataFrame, filename: str) -> Path:
    date_stamp = datetime.now().strftime("%Y%m%d")
    output_path = DATA_RAW / f"{filename}_{date_stamp}.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"Saved: {output_path} ({len(df):,} rows, {size_kb:.1f} KB)")
    return output_path


def print_summary(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        logger.warning(f"{label} dataframe is empty")
        return

    logger.info("")
    logger.info(f"📊 {label} Summary")
    logger.info(f"   Total rows         : {len(df):,}")
    logger.info(f"   Unique schemes     : {df['scheme_code'].nunique():,}")
    logger.info(f"   Unique AMCs        : {df['amc'].nunique()}")
    logger.info(f"   Unique scheme types: {df['scheme_type'].nunique()}")
    logger.info(f"   Date range         : {df['date'].min().date()} → {df['date'].max().date()}")
    logger.info(f"   NAV range          : ₹{df['nav'].min():.2f} → ₹{df['nav'].max():,.2f}")
    logger.info(f"   Null NAVs          : {df['nav'].isna().sum()}")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch AMFI India NAV data")
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Fetch historical range (in addition to current)",
    )
    parser.add_argument(
        "--start",
        default=(datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d"),
        help="Historical start date (YYYY-MM-DD). Default: 5 years ago.",
    )
    parser.add_argument(
        "--end",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Historical end date (YYYY-MM-DD). Default: today.",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AMFI INGESTION — START")
    logger.info("=" * 60)

    start_ts = datetime.now()

    # Always fetch current snapshot
    current_df = fetch_amfi_current()
    if current_df is not None and not current_df.empty:
        save_parquet(current_df, "amfi_nav_current")
        print_summary(current_df, "AMFI Current")

    # Optional historical
    if args.historical:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
        end_dt = datetime.strptime(args.end, "%Y-%m-%d")
        history_df = fetch_amfi_historical(start_dt, end_dt)
        if history_df is not None and not history_df.empty:
            save_parquet(history_df, "amfi_nav_history")
            print_summary(history_df, "AMFI Historical")

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info("=" * 60)
    logger.info(f"✅ AMFI INGESTION — COMPLETE in {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
