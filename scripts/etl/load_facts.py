"""
================================================================
ETL: Load Fact Tables
================================================================
Populates 3 fact tables using FK maps queried fresh from the DB.
Requires load_dimensions.py to have run successfully first.

    Fact_NAV          — daily NAV / price (Yahoo ETF + benchmark + AMFI)
    Fact_Transactions — individual SIP / Lumpsum / Redemption events
    Fact_SIP          — monthly SIP aggregation (derived in-memory)

Dedup strategy:
    Fact_NAV          ON CONFLICT (fund_key, date_key) DO UPDATE
    Fact_Transactions ON CONFLICT (transaction_hash) DO NOTHING
    Fact_SIP          ON CONFLICT (investor_key, fund_key, date_key) DO UPDATE

Rows with unresolvable FK (date before 2015, unknown ticker) are
dropped with a logged warning before any DB write.

Usage:
    python scripts/etl/load_facts.py
    python scripts/etl/load_facts.py --verify-only
================================================================
"""

import argparse
import hashlib
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
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

BATCH_SIZE = 1_000

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
        logging.FileHandler(LOG_DIR / "etl_facts.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("etl_facts")


# ----------------------------------------------------------------
# Helpers
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


def load_latest_processed(prefix: str) -> pd.DataFrame:
    """Load the most recent data/processed/<prefix>_*.parquet."""
    matches = sorted(DATA_PROCESSED.glob(f"{prefix}_*.parquet"))
    if not matches:
        raise FileNotFoundError(f"No processed parquet for prefix '{prefix}'")
    df = pd.read_parquet(matches[-1])
    logger.info(f"Loaded {matches[-1].name}: {len(df):,} rows")
    return df


def df_to_records(df: pd.DataFrame) -> list[tuple]:
    """Convert DataFrame to list of tuples, replacing NaN/NaT with None."""
    obj = df.astype(object).where(df.notna(), other=None)
    return [tuple(row) for row in obj.itertuples(index=False, name=None)]


def make_txn_hash(
    investor_id: str,
    scheme_code: str,
    txn_date: str,
    amount: float,
    txn_type: str,
) -> str:
    """SHA-256 dedup key for a transaction row. Produces a 64-char hex string."""
    key = f"{investor_id}|{scheme_code}|{txn_date}|{amount:.2f}|{txn_type}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _drop_unmapped(df: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    """Drop rows where col is None/NaN, log count. Returns cleaned df."""
    mask = df[col].isna()
    n = mask.sum()
    if n > 0:
        logger.warning(f"  Dropped {n:,} rows with no {label} match (FK unresolvable)")
    return df[~mask].copy()


# ----------------------------------------------------------------
# Schema migration — add transaction_hash to existing table
# ----------------------------------------------------------------
def apply_migrations(conn: psycopg2.extensions.connection) -> None:
    """
    Idempotently add transaction_hash column + unique constraint to
    Fact_Transactions. Safe to re-run; IF NOT EXISTS guards prevent errors.
    """
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE dbo.Fact_Transactions
                ADD COLUMN IF NOT EXISTS transaction_hash CHAR(64)
        """)
        # ADD CONSTRAINT IF NOT EXISTS is not supported in PostgreSQL.
        # CREATE UNIQUE INDEX IF NOT EXISTS achieves identical enforcement
        # and also enables ON CONFLICT (transaction_hash) DO NOTHING.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_txn_hash
                ON dbo.Fact_Transactions (transaction_hash)
        """)
    conn.commit()
    logger.info("Migration applied: transaction_hash column + unique index ready")


# ----------------------------------------------------------------
# FK map builders (queried fresh from DB each run)
# ----------------------------------------------------------------
def build_fund_map(conn: psycopg2.extensions.connection) -> dict[str, int]:
    """Return {scheme_code: fund_key} for all rows in Dim_Fund."""
    with conn.cursor() as cur:
        cur.execute("SELECT scheme_code, fund_key FROM dbo.Dim_Fund")
        m = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"fund_map: {len(m):,} entries")
    return m


def build_date_map(conn: psycopg2.extensions.connection) -> dict[str, int]:
    """Return {'YYYY-MM-DD': date_key} for all rows in Dim_Date."""
    with conn.cursor() as cur:
        cur.execute("SELECT full_date::text, date_key FROM dbo.Dim_Date")
        m = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"date_map: {len(m):,} entries")
    return m


def build_investor_map(conn: psycopg2.extensions.connection) -> dict[str, int]:
    """Return {investor_id: investor_key} for all rows in Dim_Investor."""
    with conn.cursor() as cur:
        cur.execute("SELECT investor_id, investor_key FROM dbo.Dim_Investor")
        m = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"investor_map: {len(m):,} entries")
    return m


# ----------------------------------------------------------------
# Fact_NAV
# ----------------------------------------------------------------
_UPSERT_FACT_NAV = """
INSERT INTO dbo.Fact_NAV (
    date_key, fund_key, nav, open_price, high_price, low_price,
    volume, source, is_outlier
) VALUES %s
ON CONFLICT (fund_key, date_key) DO UPDATE SET
    nav        = EXCLUDED.nav,
    open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price  = EXCLUDED.low_price,
    volume     = EXCLUDED.volume,
    source     = EXCLUDED.source,
    is_outlier = EXCLUDED.is_outlier
"""


def load_fact_nav(
    conn: psycopg2.extensions.connection,
    yahoo_df: pd.DataFrame,
    amfi_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
) -> tuple[int, int]:
    """
    Upsert Fact_NAV from both Yahoo and AMFI processed parquets.

    AMFI rows dated before 2015-01-01 (outside Dim_Date spine) are dropped
    with a warning — intentional scope cut, not data loss.

    Returns (rows_loaded, rows_dropped).
    """
    combined = pd.concat([yahoo_df, amfi_df], ignore_index=True)
    logger.info(f"Fact_NAV source: {len(combined):,} rows combined")

    # Normalise date to 'YYYY-MM-DD' string for map lookup
    combined["date_str"] = pd.to_datetime(combined["date"]).dt.normalize().dt.date.astype(str)
    combined["date_key"] = combined["date_str"].map(date_map)
    combined["fund_key"] = combined["ticker"].map(fund_map)

    before = len(combined)
    combined = _drop_unmapped(combined, "date_key", "date in Dim_Date")
    combined = _drop_unmapped(combined, "fund_key", "ticker in Dim_Fund")

    # Drop rows where NAV is zero or negative — violates CHECK (nav > 0).
    # Zero NAVs exist in AMFI data for newly-registered schemes with no trading history.
    invalid_nav = combined["nav"].isna() | (combined["nav"] <= 0)
    n_invalid = int(invalid_nav.sum())
    if n_invalid > 0:
        logger.warning(f"  Dropped {n_invalid:,} rows with nav <= 0 (no trading history yet)")
        combined = combined[~invalid_nav]

    dropped = before - len(combined)

    cols = ["date_key", "fund_key", "nav", "open", "high", "low", "volume", "source", "is_outlier"]
    combined = combined[cols].rename(columns={"open": "open_price", "high": "high_price", "low": "low_price"})

    # volume: Yahoo has int64, AMFI has float NaN — coerce to nullable int then None
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")

    records = df_to_records(combined)
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_FACT_NAV, records, page_size=BATCH_SIZE)
    conn.commit()

    logger.info(f"Fact_NAV: {len(records):,} rows upserted, {dropped:,} dropped (unresolvable FK)")
    return len(records), dropped


# ----------------------------------------------------------------
# Fact_Transactions
# ----------------------------------------------------------------
_UPSERT_FACT_TXN = """
INSERT INTO dbo.Fact_Transactions (
    date_key, fund_key, investor_key,
    transaction_type, amount, units, nav_at_transaction, transaction_hash
) VALUES %s
ON CONFLICT (transaction_hash) DO NOTHING
"""


def load_fact_transactions(
    conn: psycopg2.extensions.connection,
    txn_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
    investor_map: dict[str, int],
) -> tuple[int, int]:
    """
    Upsert Fact_Transactions.

    Dedup key: SHA-256 hash of (investor_id|scheme_code|date|amount|type).
    ON CONFLICT (transaction_hash) DO NOTHING — transactions are immutable.

    Returns (rows_loaded, rows_dropped).
    """
    df = txn_df.copy()

    # Normalise transaction_date to 'YYYY-MM-DD' (strip time component)
    df["date_str"] = pd.to_datetime(df["transaction_date"]).dt.normalize().dt.date.astype(str)
    df["date_key"] = df["date_str"].map(date_map)
    df["fund_key"] = df["scheme_code"].map(fund_map)
    df["investor_key"] = df["investor_id"].map(investor_map)

    before = len(df)
    df = _drop_unmapped(df, "date_key", "date in Dim_Date")
    df = _drop_unmapped(df, "fund_key", "scheme_code in Dim_Fund")
    df = _drop_unmapped(df, "investor_key", "investor_id in Dim_Investor")
    dropped = before - len(df)

    # Compute SHA-256 dedup hash
    df["transaction_hash"] = [
        make_txn_hash(row.investor_id, row.scheme_code, row.date_str, row.amount, row.transaction_type)
        for row in df.itertuples(index=False)
    ]

    cols = [
        "date_key", "fund_key", "investor_key",
        "transaction_type", "amount", "units", "nav_at_transaction", "transaction_hash",
    ]
    records = df_to_records(df[cols])
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_FACT_TXN, records, page_size=BATCH_SIZE)
    conn.commit()

    logger.info(f"Fact_Transactions: {len(records):,} rows inserted, {dropped:,} dropped")
    return len(records), dropped


# ----------------------------------------------------------------
# Fact_SIP (derived in-memory from transaction data)
# ----------------------------------------------------------------
_UPSERT_FACT_SIP = """
INSERT INTO dbo.Fact_SIP (
    date_key, fund_key, investor_key,
    monthly_sip_amount, cumulative_invested, units_purchased, current_units_held
) VALUES %s
ON CONFLICT (investor_key, fund_key, date_key) DO UPDATE SET
    monthly_sip_amount  = EXCLUDED.monthly_sip_amount,
    cumulative_invested  = EXCLUDED.cumulative_invested,
    units_purchased      = EXCLUDED.units_purchased,
    current_units_held   = EXCLUDED.current_units_held
"""


def derive_fact_sip(
    txn_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
    investor_map: dict[str, int],
) -> pd.DataFrame:
    """
    Aggregate transaction data into monthly SIP records.

    No DB round-trip — computed entirely in pandas from the same txn_df
    used for Fact_Transactions so the two tables stay consistent.

    SIP and Redemption transactions both contribute to current_units_held:
        current_units_held = cumulative(SIP units) - cumulative(Redemption units)
    """
    df = txn_df.copy()
    df["month_start"] = pd.to_datetime(df["transaction_date"]).dt.to_period("M").dt.to_timestamp()
    df["date_str"] = df["month_start"].dt.date.astype(str)

    # Monthly SIP aggregation (SIP only)
    sip = (
        df[df["transaction_type"] == "SIP"]
        .groupby(["investor_id", "scheme_code", "month_start", "date_str"])
        .agg(monthly_sip_amount=("amount", "sum"), units_purchased=("units", "sum"))
        .reset_index()
    )

    # Monthly Redemption aggregation
    red = (
        df[df["transaction_type"] == "Redemption"]
        .groupby(["investor_id", "scheme_code", "month_start"])
        .agg(units_redeemed=("units", "sum"))
        .reset_index()
    )

    sip = sip.merge(red, on=["investor_id", "scheme_code", "month_start"], how="left")
    sip["units_redeemed"] = sip["units_redeemed"].fillna(0.0)

    # Cumulative calculations per investor-fund timeline
    sip = sip.sort_values(["investor_id", "scheme_code", "month_start"])
    g = sip.groupby(["investor_id", "scheme_code"])
    sip["cumulative_invested"] = g["monthly_sip_amount"].cumsum()
    sip["cum_units_purchased"] = g["units_purchased"].cumsum()
    sip["cum_units_redeemed"] = g["units_redeemed"].cumsum()
    sip["current_units_held"] = (sip["cum_units_purchased"] - sip["cum_units_redeemed"]).clip(lower=0)

    # Resolve FKs
    sip["date_key"] = sip["date_str"].map(date_map)
    sip["fund_key"] = sip["scheme_code"].map(fund_map)
    sip["investor_key"] = sip["investor_id"].map(investor_map)

    before = len(sip)
    sip = sip.dropna(subset=["date_key", "fund_key", "investor_key"])
    dropped = before - len(sip)
    if dropped > 0:
        logger.warning(f"  Fact_SIP: dropped {dropped:,} rows with unresolvable FK")

    sip[["date_key", "fund_key", "investor_key"]] = sip[
        ["date_key", "fund_key", "investor_key"]
    ].astype(int)

    logger.info(f"Fact_SIP derived: {len(sip):,} monthly records")
    return sip


def load_fact_sip(
    conn: psycopg2.extensions.connection,
    sip_df: pd.DataFrame,
) -> int:
    """Upsert pre-derived Fact_SIP DataFrame. Returns row count."""
    cols = [
        "date_key", "fund_key", "investor_key",
        "monthly_sip_amount", "cumulative_invested",
        "units_purchased", "current_units_held",
    ]
    records = df_to_records(sip_df[cols])
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_FACT_SIP, records, page_size=BATCH_SIZE)
    conn.commit()
    logger.info(f"Fact_SIP: {len(records):,} rows upserted")
    return len(records)


# ----------------------------------------------------------------
# Verification
# ----------------------------------------------------------------
def verify_all_counts(conn: psycopg2.extensions.connection) -> None:
    """Log row counts for all 9 tables and check key fact FKs are valid."""
    tables = [
        "Dim_Date", "Dim_AMC", "Dim_Category", "Dim_Fund", "Dim_Investor",
        "Fact_NAV", "Fact_Transactions", "Fact_SIP", "Fact_Returns",
    ]
    logger.info("-" * 60)
    logger.info("Full schema row counts:")
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM dbo.{t}")
            logger.info(f"  {t:<22}: {cur.fetchone()[0]:>10,}")

        # Referential integrity spot-checks
        cur.execute("""
            SELECT COUNT(*) FROM dbo.Fact_NAV fn
            WHERE NOT EXISTS (
                SELECT 1 FROM dbo.Dim_Fund df WHERE df.fund_key = fn.fund_key
            )
        """)
        orphan_nav = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM dbo.Fact_Transactions ft
            WHERE NOT EXISTS (
                SELECT 1 FROM dbo.Dim_Investor di WHERE di.investor_key = ft.investor_key
            )
        """)
        orphan_txn = cur.fetchone()[0]

    logger.info("")
    logger.info(f"  Orphan Fact_NAV rows (no Dim_Fund match) : {orphan_nav}")
    logger.info(f"  Orphan Fact_Transactions (no investor)   : {orphan_txn}")
    status = "PASSED" if orphan_nav == 0 and orphan_txn == 0 else "FAILED"
    logger.info(f"  Referential integrity check              : {status}")
    logger.info("-" * 60)


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Load fact tables into mf_analytics")
    parser.add_argument("--verify-only", action="store_true", help="Print counts only, skip loading")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("ETL FACTS — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        if args.verify_only:
            verify_all_counts(conn)
            return

        # Migration: idempotently add transaction_hash
        apply_migrations(conn)

        # Load source data
        yahoo_df = load_latest_processed("nav_yahoo_clean")
        amfi_df = load_latest_processed("nav_amfi_clean")
        txn_df = load_latest_processed("transactions_clean")

        # Build FK maps from the already-loaded dimension tables
        fund_map = build_fund_map(conn)
        date_map = build_date_map(conn)
        investor_map = build_investor_map(conn)

        # Load facts
        logger.info("--- Loading Fact_NAV ---")
        load_fact_nav(conn, yahoo_df, amfi_df, fund_map, date_map)

        logger.info("--- Loading Fact_Transactions ---")
        load_fact_transactions(conn, txn_df, fund_map, date_map, investor_map)

        logger.info("--- Deriving + Loading Fact_SIP ---")
        sip_df = derive_fact_sip(txn_df, fund_map, date_map, investor_map)
        load_fact_sip(conn, sip_df)

        verify_all_counts(conn)

    except Exception as e:
        conn.rollback()
        logger.error(f"ETL failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("ETL FACTS — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
