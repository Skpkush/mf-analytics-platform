"""
================================================================
Transaction Data Cleaning
================================================================
Cleans real investor/SIP transaction data, or generates a
reproducible synthetic dataset when real data is unavailable.

Synthetic data uses real AMFI scheme codes (from data/raw/) so
foreign-key integrity holds when Day 3 ETL loads Fact_Transactions.

Inputs (real mode):
    --input <path>  CSV or parquet with transaction records

Inputs (synthetic mode, default when --input is omitted):
    data/raw/amfi_nav_current_*.parquet  (for real scheme codes)

Outputs:
    data/processed/transactions_clean_<date>.parquet

Usage:
    python scripts/transformation/clean_transactions.py
    python scripts/transformation/clean_transactions.py --input data/external/sip_data.csv
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

# Synthetic generation parameters
N_INVESTORS = 500
N_FUNDS = 30
N_MONTHS = 36
SYNTHETIC_SEED = 42

SIP_AMOUNTS = [500, 1_000, 1_500, 2_000, 2_500, 3_000, 5_000, 10_000]
LUMPSUM_AMOUNTS = [5_000, 10_000, 25_000, 50_000, 1_00_000]
TRANSACTION_TYPES = ["SIP", "Lumpsum", "Redemption"]

# Transaction probability distribution (must sum to 1.0)
PROB_SIP = 0.80
PROB_LUMPSUM = 0.15
PROB_REDEMPTION = 0.05

# Schema that real transaction data must satisfy
EXPECTED_SCHEMA: dict[str, str] = {
    "investor_id": "object",
    "scheme_code": "object",
    "transaction_date": "datetime64",
    "amount": "float64",
    "transaction_type": "object",
    "units": "float64",
    "nav_at_transaction": "float64",
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
        logging.FileHandler(LOG_DIR / "transaction_cleaning.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("transaction_cleaning")


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _load_amfi_schemes() -> pd.DataFrame:
    """
    Load AMFI raw parquet to get real scheme codes for FK integrity.

    Prefers equity scheme codes (more realistic for SIP simulation).
    Falls back to all schemes if equity count is below N_FUNDS.
    """
    matches = sorted(DATA_RAW.glob("amfi_nav_current_*.parquet"))
    if not matches:
        logger.warning("No AMFI raw data found — synthetic data will use placeholder scheme codes")
        return pd.DataFrame()

    df = pd.read_parquet(matches[-1])
    equity = df[df["scheme_type"].str.contains("Equity", na=False, case=False)]
    pool = equity if len(equity) >= N_FUNDS else df

    return (
        pool[["scheme_code", "scheme_name", "nav", "amc"]]
        .dropna(subset=["scheme_code", "nav"])
        .query("nav > 0")
        .reset_index(drop=True)
    )


# ----------------------------------------------------------------
# Synthetic data generation
# ----------------------------------------------------------------
def generate_synthetic_sip_data(
    n_investors: int = N_INVESTORS,
    n_funds: int = N_FUNDS,
    n_months: int = N_MONTHS,
    seed: int = SYNTHETIC_SEED,
) -> pd.DataFrame:
    """
    Generate a reproducible synthetic SIP/transaction dataset.

    Scheme codes are sampled from live AMFI data so foreign-key integrity
    holds when this data is loaded into Fact_Transactions on Day 3.

    WARNING: This is synthetic data for schema and pipeline demonstration
    only. All investor IDs, amounts, and unit counts are fabricated.
    Replace with a real Kaggle/provider dataset when available.

    Args:
        n_investors: Number of unique synthetic investors.
        n_funds: Number of funds to distribute investment across.
        n_months: Months of transaction history to generate.
        seed: Random seed — change only to regenerate a different dataset.

    Returns:
        DataFrame matching EXPECTED_SCHEMA, sorted by investor_id + date.
    """
    rng = np.random.default_rng(seed)

    # --- Scheme universe ---
    amfi_df = _load_amfi_schemes()
    if amfi_df.empty:
        scheme_codes = [f"FUND{i:04d}" for i in range(n_funds)]
        scheme_navs: dict[str, float] = {c: float(rng.uniform(10.0, 500.0)) for c in scheme_codes}
    else:
        n_sample = min(n_funds, len(amfi_df))
        sample = amfi_df.sample(n=n_sample, random_state=seed)
        scheme_codes = sample["scheme_code"].tolist()
        scheme_navs = dict(zip(sample["scheme_code"], sample["nav"].clip(lower=1.0)))

    # --- Date spine: monthly, last n_months up to today ---
    end_date = datetime.now().replace(day=1)
    date_spine = pd.date_range(end=end_date, periods=n_months, freq="MS")

    investor_ids = [f"INV{i:05d}" for i in range(n_investors)]

    records: list[dict] = []
    for inv_id in investor_ids:
        # Each investor holds 1–3 funds
        n_active = int(rng.integers(1, 4))
        inv_funds: list[str] = rng.choice(scheme_codes, size=n_active, replace=False).tolist()
        sip_amount = float(rng.choice(SIP_AMOUNTS))

        for fund_code in inv_funds:
            base_nav = scheme_navs.get(fund_code, 100.0)

            for dt in date_spine:
                roll = rng.random()
                if roll < PROB_SIP:
                    txn_type = "SIP"
                    amount = sip_amount
                elif roll < PROB_SIP + PROB_LUMPSUM:
                    txn_type = "Lumpsum"
                    amount = float(rng.choice(LUMPSUM_AMOUNTS))
                else:
                    txn_type = "Redemption"
                    amount = sip_amount * float(rng.uniform(0.5, 2.0))

                # Simulate modest NAV drift over time
                nav = base_nav * float(rng.uniform(0.90, 1.50))
                units = round(amount / max(nav, 0.01), 4)

                records.append({
                    "investor_id": inv_id,
                    "scheme_code": fund_code,
                    "transaction_date": dt,
                    "amount": round(amount, 2),
                    "transaction_type": txn_type,
                    "units": units,
                    "nav_at_transaction": round(nav, 4),
                })

    df = pd.DataFrame(records)
    logger.info(
        f"Generated synthetic dataset: {len(df):,} transactions | "
        f"{df['investor_id'].nunique()} investors | "
        f"{df['scheme_code'].nunique()} funds | "
        f"{n_months} months"
    )
    return df


# ----------------------------------------------------------------
# Real data cleaning
# ----------------------------------------------------------------
def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and validate a raw transaction DataFrame.

    Applies dtype coercion, drops rows missing critical fields,
    and normalises transaction_type casing. Safe to call on both
    real and synthetic data (synthetic is pre-clean but still runs through).

    Args:
        df: Raw transaction DataFrame.

    Returns:
        Cleaned DataFrame sorted by investor_id, transaction_date.
    """
    df = df.copy()

    # Coerce dtypes
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["units"] = pd.to_numeric(df["units"], errors="coerce")
    df["nav_at_transaction"] = pd.to_numeric(df["nav_at_transaction"], errors="coerce")
    df["scheme_code"] = df["scheme_code"].astype(str).str.strip()
    df["investor_id"] = df["investor_id"].astype(str).str.strip()
    # Drop rows with null critical fields
    critical = ["investor_id", "scheme_code", "transaction_date", "amount"]
    before = len(df)
    df = df.dropna(subset=critical)
    dropped = before - len(df)
    if dropped > 0:
        logger.warning(f"Dropped {dropped} rows with null critical fields")

    # Drop non-positive amounts
    invalid = df["amount"] <= 0
    if invalid.sum() > 0:
        logger.warning(f"Dropping {invalid.sum()} rows with non-positive amount")
        df = df[~invalid]

    # Normalise transaction_type using a canonical map (case-insensitive lookup).
    # Avoids str.title() which corrupts acronyms like "SIP" → "Sip".
    _canonical = {t.upper(): t for t in TRANSACTION_TYPES}
    raw_types = df["transaction_type"].astype(str).str.strip().str.upper()
    df["transaction_type"] = raw_types.map(_canonical).fillna("Unknown")
    unknown_count = (df["transaction_type"] == "Unknown").sum()
    if unknown_count > 0:
        logger.warning(f"Set {unknown_count} unrecognised transaction_type values to 'Unknown'")

    return df.sort_values(["investor_id", "transaction_date"]).reset_index(drop=True)


def validate_transaction_schema(df: pd.DataFrame) -> list[str]:
    """
    Check that df contains all columns defined in EXPECTED_SCHEMA.

    Args:
        df: DataFrame to validate.

    Returns:
        List of schema violation strings. Empty list means valid.
    """
    return [f"Missing column: '{col}'" for col in EXPECTED_SCHEMA if col not in df.columns]


def save_processed(df: pd.DataFrame, filename: str) -> Path:
    """Save DataFrame to data/processed/ with date-stamp suffix."""
    date_stamp = datetime.now().strftime("%Y%m%d")
    output_path = DATA_PROCESSED / f"{filename}_{date_stamp}.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"Saved: {output_path.name} ({len(df):,} rows, {size_kb:.1f} KB)")
    return output_path


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean real investor data, or generate a synthetic SIP dataset"
    )
    parser.add_argument(
        "--input",
        default=None,
        metavar="PATH",
        help="Path to real transaction CSV or parquet. Omit to generate synthetic data.",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("TRANSACTION CLEANING — START")
    logger.info("=" * 60)
    start_ts = datetime.now()

    if args.input:
        path = Path(args.input)
        if not path.exists():
            logger.error(f"Input file not found: {path}")
            sys.exit(1)
        logger.info(f"Loading real transaction data from: {path.name}")
        df: pd.DataFrame = (
            pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        )
        logger.info(f"Loaded {len(df):,} rows")
    else:
        logger.info("No --input specified — generating synthetic SIP dataset")
        df = generate_synthetic_sip_data()

    df = clean_transactions(df)

    violations = validate_transaction_schema(df)
    if violations:
        for v in violations:
            logger.error(f"Schema violation: {v}")
        sys.exit(1)

    report = generate_quality_report(
        df=df,
        label="transactions_clean",
        required_cols=["investor_id", "scheme_code", "transaction_date", "amount"],
        key_cols=["investor_id", "scheme_code", "transaction_date"],
        date_col="transaction_date",
        max_age_days=60,  # synthetic data spans historical months — wider freshness window
    )
    log_quality_report(report, logger)

    save_processed(df, "transactions_clean")

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info("=" * 60)
    logger.info(f"TRANSACTION CLEANING — COMPLETE in {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
