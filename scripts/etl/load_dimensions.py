"""
================================================================
ETL: Load Dimension Tables
================================================================
Populates all 5 dimension tables in FK dependency order:

    1. Dim_Date      — 2015-01-01 → 2026-12-31 date spine (4,383 rows)
    2. Dim_AMC       — 51 AMCs from AMFI processed parquet
    3. Dim_Category  — 50 SEBI fund categories (parsed from raw strings)
    4. Dim_Fund      — 14,384 schemes/tickers from AMFI + Yahoo processed
    5. Dim_Investor  — 500 synthetic investors (seed=42, matches txn data)

All inserts use UPSERT (ON CONFLICT DO UPDATE) for idempotency.
Bulk-loaded via execute_values(page_size=1000) for performance.

Usage:
    python scripts/etl/load_dimensions.py
    python scripts/etl/load_dimensions.py --verify-only
================================================================
"""

import argparse
import logging
import os
import re
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
DATA_RAW = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

DATE_SPINE_START = "2015-01-01"
DATE_SPINE_END = "2026-12-31"
FIN_YEAR_MONTH_START = 4  # Indian FY starts April
BATCH_SIZE = 1_000
INVESTOR_SEED = 42  # matches clean_transactions.py seed

# Synthetic investor demographics (realistic Indian distribution)
CITIES_STATES: dict[str, str] = {
    "Mumbai": "Maharashtra", "Pune": "Maharashtra",
    "Nagpur": "Maharashtra", "Thane": "Maharashtra",
    "Delhi": "Delhi",
    "Bangalore": "Karnataka",
    "Chennai": "Tamil Nadu",
    "Hyderabad": "Telangana",
    "Kolkata": "West Bengal",
    "Ahmedabad": "Gujarat", "Surat": "Gujarat",
    "Jaipur": "Rajasthan",
    "Lucknow": "Uttar Pradesh", "Kanpur": "Uttar Pradesh",
    "Indore": "Madhya Pradesh",
}
CITIES = list(CITIES_STATES.keys())
AGE_GROUPS = ["18-25", "26-35", "36-45", "46-55", "55+"]
AGE_WEIGHTS = [0.12, 0.35, 0.28, 0.18, 0.07]
RISK_PROFILES = ["Conservative", "Moderate", "Aggressive"]
RISK_WEIGHTS = [0.35, 0.45, 0.20]
SEGMENTS = ["Retail", "HNI", "Institutional"]
SEGMENT_WEIGHTS = [0.80, 0.18, 0.02]

# Category parsing — matches 'Open Ended Schemes(Equity Scheme - Large Cap Fund)'
_CAT_PRIMARY_RE = re.compile(r"^(.+?)\((.+?)\s+-\s+(.+?)\)\s*$")
# Fallback for 'Close Ended Schemes(ELSS)' pattern (no asset_class separator)
_CAT_SECONDARY_RE = re.compile(r"^(.+?)\((.+?)\)\s*$")
_CAT_ASSET_HINTS: dict[str, str] = {
    "Gilt": "Debt Scheme",
    "Income": "Debt Scheme",
    "Money Market": "Debt Scheme",
    "ELSS": "Equity Scheme",
    "Growth": "Equity Scheme",
}

# Plan / option keyword maps for AMFI scheme name parsing
_PLAN_MAP: dict[str, str] = {
    "DIRECT": "Direct",
    "REGULAR": "Regular",
    "RETAIL": "Retail",
    "INSTITUTIONAL": "Institutional",
}
_OPTION_MAP: dict[str, str] = {
    "GROWTH": "Growth",
    "IDCW": "IDCW",
    "DIVIDEND": "IDCW",  # old name, normalised
    "BONUS": "Bonus",
}
_PLAN_SPLIT_RE = re.compile(
    r"\s*[-–]\s*(Direct|Regular|Retail|Institutional|Growth|IDCW|Dividend|Bonus)\b.*$",
    re.IGNORECASE,
)

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
        logging.FileHandler(LOG_DIR / "etl_dimensions.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("etl_dimensions")


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


def load_latest_raw(prefix: str) -> pd.DataFrame:
    """Load the most recent data/raw/<prefix>_*.parquet."""
    matches = sorted(DATA_RAW.glob(f"{prefix}_*.parquet"))
    if not matches:
        raise FileNotFoundError(f"No raw parquet for prefix '{prefix}'")
    df = pd.read_parquet(matches[-1])
    logger.info(f"Loaded (raw) {matches[-1].name}: {len(df):,} rows")
    return df


def df_to_records(df: pd.DataFrame) -> list[tuple]:
    """Convert DataFrame to list of tuples, replacing NaN/NaT with None."""
    obj = df.astype(object).where(df.notna(), other=None)
    return [tuple(row) for row in obj.itertuples(index=False, name=None)]


# ----------------------------------------------------------------
# Category parsing
# ----------------------------------------------------------------
def parse_category(raw: str) -> tuple[str, str, str]:
    """
    Parse an AMFI raw_category string into (structure_type, asset_class, sub_category).

    Primary pattern:   'Open Ended Schemes(Equity Scheme - Large Cap Fund)'
    Secondary pattern: 'Close Ended Schemes(ELSS)'  (no asset_class separator)
    """
    s = raw.strip()
    m = _CAT_PRIMARY_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()

    m = _CAT_SECONDARY_RE.match(s)
    if m:
        structure = m.group(1).strip()
        sub_cat = m.group(2).strip()
        asset_class = _CAT_ASSET_HINTS.get(sub_cat, "Other Scheme")
        return structure, asset_class, sub_cat

    return s, "Other Scheme", s


# ----------------------------------------------------------------
# Plan / option parsing
# ----------------------------------------------------------------
def parse_plan_option(name: str) -> tuple[str, str | None, str | None]:
    """
    Extract (base_fund_name, plan_type, option_type) from an AMFI scheme name.

    Example:
      'HDFC Top 100 Fund - Direct Plan - Growth Option'
        → ('HDFC Top 100 Fund', 'Direct', 'Growth')
    """
    upper = name.upper()
    plan = next((v for k, v in _PLAN_MAP.items() if k in upper), None)
    option = next((v for k, v in _OPTION_MAP.items() if k in upper), None)
    base = _PLAN_SPLIT_RE.split(name, maxsplit=1)[0].strip().rstrip("-– ").strip()
    return base, plan, option


# ----------------------------------------------------------------
# Dim_Date — date spine generation
# ----------------------------------------------------------------
def build_date_spine() -> pd.DataFrame:
    """
    Generate a complete date spine from DATE_SPINE_START to DATE_SPINE_END.

    All columns are derived via vectorised pandas operations — no Python loops.
    Indian financial year: April 1 – March 31.
    """
    dates = pd.date_range(DATE_SPINE_START, DATE_SPINE_END, freq="D")
    df = pd.DataFrame({"full_date": dates})

    month = df["full_date"].dt.month
    year = df["full_date"].dt.year
    iso = df["full_date"].dt.isocalendar()

    df["date_key"] = year * 10_000 + month * 100 + df["full_date"].dt.day
    df["day_of_week"] = iso["day"].astype(int)          # 1=Mon … 7=Sun
    df["day_name"] = df["full_date"].dt.day_name()
    df["day_of_month"] = df["full_date"].dt.day.astype(int)
    df["day_of_year"] = df["full_date"].dt.day_of_year.astype(int)
    df["week_of_year"] = iso["week"].astype(int)
    df["month_num"] = month.astype(int)
    df["month_name"] = df["full_date"].dt.month_name()
    df["quarter"] = df["full_date"].dt.quarter.astype(int)
    df["year"] = year.astype(int)
    df["is_weekday"] = df["day_of_week"] <= 5
    df["is_month_end"] = df["full_date"].dt.is_month_end
    df["is_quarter_end"] = df["is_month_end"] & month.isin([3, 6, 9, 12])
    df["is_year_end"] = (month == 12) & (df["full_date"].dt.day == 31)

    # Indian FY: April of year X → March of year X+1 = FY X-(X+1)
    fy_end_year = np.where(month >= FIN_YEAR_MONTH_START, year + 1, year)
    fy_end_2d = pd.Series(fy_end_year % 100, index=df.index).astype(str).str.zfill(2)
    fy_start = pd.Series(fy_end_year - 1, index=df.index).astype(str)
    df["financial_year"] = "FY" + fy_start + "-" + fy_end_2d

    # Financial quarter within Indian FY
    fin_q = np.select(
        [month.isin([4, 5, 6]), month.isin([7, 8, 9]), month.isin([10, 11, 12])],
        [1, 2, 3],
        default=4,  # Jan, Feb, Mar = Q4
    )
    df["financial_quarter"] = "Q" + pd.Series(fin_q, index=df.index).astype(str) + "FY" + fy_end_2d

    return df


_UPSERT_DIM_DATE = """
INSERT INTO dbo.Dim_Date (
    date_key, full_date, day_of_week, day_name, day_of_month, day_of_year,
    week_of_year, month_num, month_name, quarter, year,
    is_weekday, is_month_end, is_quarter_end, is_year_end,
    financial_year, financial_quarter
) VALUES %s
ON CONFLICT (date_key) DO UPDATE SET
    full_date         = EXCLUDED.full_date,
    day_of_week       = EXCLUDED.day_of_week,
    day_name          = EXCLUDED.day_name,
    day_of_month      = EXCLUDED.day_of_month,
    day_of_year       = EXCLUDED.day_of_year,
    week_of_year      = EXCLUDED.week_of_year,
    month_num         = EXCLUDED.month_num,
    month_name        = EXCLUDED.month_name,
    quarter           = EXCLUDED.quarter,
    year              = EXCLUDED.year,
    is_weekday        = EXCLUDED.is_weekday,
    is_month_end      = EXCLUDED.is_month_end,
    is_quarter_end    = EXCLUDED.is_quarter_end,
    is_year_end       = EXCLUDED.is_year_end,
    financial_year    = EXCLUDED.financial_year,
    financial_quarter = EXCLUDED.financial_quarter
"""


def load_dim_date(conn: psycopg2.extensions.connection) -> int:
    """Generate date spine and upsert into Dim_Date. Returns row count."""
    df = build_date_spine()
    cols = [
        "date_key", "full_date", "day_of_week", "day_name", "day_of_month",
        "day_of_year", "week_of_year", "month_num", "month_name", "quarter",
        "year", "is_weekday", "is_month_end", "is_quarter_end", "is_year_end",
        "financial_year", "financial_quarter",
    ]
    records = df_to_records(df[cols])
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_DIM_DATE, records, page_size=BATCH_SIZE)
    conn.commit()
    logger.info(f"Dim_Date: {len(records):,} rows upserted")
    return len(records)


# ----------------------------------------------------------------
# Dim_AMC
# ----------------------------------------------------------------
_UPSERT_DIM_AMC = """
INSERT INTO dbo.Dim_AMC (amc_name, amc_short_name)
VALUES %s
ON CONFLICT (amc_name) DO UPDATE SET
    amc_short_name = EXCLUDED.amc_short_name
"""


def _make_short_name(amc_name: str) -> str:
    return re.sub(r"\s*Mutual Fund.*$", "", amc_name, flags=re.IGNORECASE).strip()


def load_dim_amc(
    conn: psycopg2.extensions.connection,
    amfi_df: pd.DataFrame,
) -> dict[str, int]:
    """Upsert all unique AMC names. Returns {amc_name: amc_key} map."""
    names = amfi_df["amc"].dropna().str.strip().unique()
    records = [(name, _make_short_name(name)) for name in sorted(names)]
    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_DIM_AMC, records, page_size=BATCH_SIZE)
        conn.commit()
        cur.execute("SELECT amc_name, amc_key FROM dbo.Dim_AMC")
        amc_map = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"Dim_AMC: {len(records)} rows upserted")
    return amc_map


# ----------------------------------------------------------------
# Dim_Category
# ----------------------------------------------------------------
_UPSERT_DIM_CATEGORY = """
INSERT INTO dbo.Dim_Category (raw_category, structure_type, asset_class, sub_category)
VALUES %s
ON CONFLICT (raw_category) DO UPDATE SET
    structure_type = EXCLUDED.structure_type,
    asset_class    = EXCLUDED.asset_class,
    sub_category   = EXCLUDED.sub_category
"""


def load_dim_category(
    conn: psycopg2.extensions.connection,
    amfi_df: pd.DataFrame,
) -> dict[str, int]:
    """Upsert all unique fund categories. Returns {raw_category: category_key} map."""
    raw_cats = amfi_df["category"].dropna().str.strip().unique()
    records = []
    for raw in sorted(raw_cats):
        structure, asset_class, sub_cat = parse_category(raw)
        records.append((raw, structure, asset_class, sub_cat))

    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_DIM_CATEGORY, records, page_size=BATCH_SIZE)
        conn.commit()
        cur.execute("SELECT raw_category, category_key FROM dbo.Dim_Category")
        cat_map = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"Dim_Category: {len(records)} rows upserted")
    return cat_map


# ----------------------------------------------------------------
# Dim_Fund
# ----------------------------------------------------------------
_UPSERT_DIM_FUND = """
INSERT INTO dbo.Dim_Fund (
    scheme_code, fund_name, base_fund_name, plan_type, option_type,
    amc_key, category_key, isin_growth, isin_idcw,
    source, is_benchmark, is_active, inception_date
) VALUES %s
ON CONFLICT (scheme_code) DO UPDATE SET
    fund_name      = EXCLUDED.fund_name,
    base_fund_name = EXCLUDED.base_fund_name,
    plan_type      = EXCLUDED.plan_type,
    option_type    = EXCLUDED.option_type,
    amc_key        = EXCLUDED.amc_key,
    category_key   = EXCLUDED.category_key,
    isin_growth    = EXCLUDED.isin_growth,
    isin_idcw      = EXCLUDED.isin_idcw,
    is_active      = EXCLUDED.is_active
"""


def _build_amfi_fund_records(
    amfi_df: pd.DataFrame,
    raw_amfi_df: pd.DataFrame,
    amc_map: dict[str, int],
    cat_map: dict[str, int],
) -> list[tuple]:
    """Build Dim_Fund insert tuples for AMFI schemes."""
    # Join ISINs from raw parquet (stripped from processed parquet in clean_nav)
    isin = (
        raw_amfi_df[["scheme_code", "isin_div_payout", "isin_div_reinvestment"]]
        .drop_duplicates("scheme_code")
        .set_index("scheme_code")
    )

    records = []
    for row in amfi_df.itertuples(index=False):
        base, plan, option = parse_plan_option(str(row.name))
        amc_key = amc_map.get(str(row.amc).strip()) if row.amc else None
        cat_key = cat_map.get(str(row.category).strip()) if row.category else None

        scheme = str(row.ticker)
        isin_idcw = isin_growth = None
        if scheme in isin.index:
            raw = isin.loc[scheme]
            val = str(raw["isin_div_payout"]).strip()
            isin_idcw = val if val not in ("-", "nan", "") else None
            val = str(raw["isin_div_reinvestment"]).strip()
            isin_growth = val if val not in ("-", "nan", "") else None

        records.append((
            scheme, str(row.name), base, plan, option,
            amc_key, cat_key, isin_growth, isin_idcw,
            "amfi", False, True, None,
        ))
    return records


def _build_yahoo_fund_records(yahoo_df: pd.DataFrame) -> list[tuple]:
    """Build Dim_Fund insert tuples for Yahoo ETF and benchmark tickers."""
    unique = yahoo_df.drop_duplicates(subset=["ticker"])
    records = []
    for row in unique.itertuples(index=False):
        is_benchmark = str(row.source) == "yahoo_benchmark"
        records.append((
            str(row.ticker), str(row.name), str(row.name),
            None, None,   # plan_type, option_type
            None, None,   # amc_key, category_key
            None, None,   # isin_growth, isin_idcw
            str(row.source), is_benchmark, True, None,
        ))
    return records


def load_dim_fund(
    conn: psycopg2.extensions.connection,
    amfi_df: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    raw_amfi_df: pd.DataFrame,
    amc_map: dict[str, int],
    cat_map: dict[str, int],
) -> dict[str, int]:
    """Upsert all funds/benchmarks. Returns {scheme_code: fund_key} map."""
    amfi_records = _build_amfi_fund_records(amfi_df, raw_amfi_df, amc_map, cat_map)
    yahoo_records = _build_yahoo_fund_records(yahoo_df)
    all_records = amfi_records + yahoo_records

    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_DIM_FUND, all_records, page_size=BATCH_SIZE)
        conn.commit()
        cur.execute("SELECT scheme_code, fund_key FROM dbo.Dim_Fund")
        fund_map = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(
        f"Dim_Fund: {len(amfi_records):,} AMFI + {len(yahoo_records)} Yahoo "
        f"= {len(all_records):,} rows upserted"
    )
    return fund_map


# ----------------------------------------------------------------
# Dim_Investor
# ----------------------------------------------------------------
_UPSERT_DIM_INVESTOR = """
INSERT INTO dbo.Dim_Investor (
    investor_id, age_group, city, state, risk_profile, investor_segment, kyc_status
) VALUES %s
ON CONFLICT (investor_id) DO UPDATE SET
    age_group        = EXCLUDED.age_group,
    city             = EXCLUDED.city,
    state            = EXCLUDED.state,
    risk_profile     = EXCLUDED.risk_profile,
    investor_segment = EXCLUDED.investor_segment,
    kyc_status       = EXCLUDED.kyc_status
"""


def load_dim_investor(
    conn: psycopg2.extensions.connection,
    investor_ids: list[str],
) -> dict[str, int]:
    """
    Generate synthetic demographic attributes for each investor_id and upsert.

    Uses seed=42 (matching clean_transactions.py) so every re-run produces
    identical attributes for the same investor set.

    Returns {investor_id: investor_key} map.
    """
    rng = np.random.default_rng(INVESTOR_SEED)
    n = len(investor_ids)

    cities_arr = rng.choice(CITIES, size=n)
    states_arr = np.array([CITIES_STATES[c] for c in cities_arr])
    age_arr = rng.choice(AGE_GROUPS, size=n, p=AGE_WEIGHTS)
    risk_arr = rng.choice(RISK_PROFILES, size=n, p=RISK_WEIGHTS)
    seg_arr = rng.choice(SEGMENTS, size=n, p=SEGMENT_WEIGHTS)
    # 95% KYC-compliant for realistic Indian MF universe
    kyc_arr = rng.random(size=n) < 0.95

    records = [
        (
            investor_ids[i],
            age_arr[i],
            cities_arr[i],
            states_arr[i],
            risk_arr[i],
            seg_arr[i],
            bool(kyc_arr[i]),
        )
        for i in range(n)
    ]

    with conn.cursor() as cur:
        execute_values(cur, _UPSERT_DIM_INVESTOR, records, page_size=BATCH_SIZE)
        conn.commit()
        cur.execute("SELECT investor_id, investor_key FROM dbo.Dim_Investor")
        investor_map = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(f"Dim_Investor: {len(records)} rows upserted")
    return investor_map


# ----------------------------------------------------------------
# Verification
# ----------------------------------------------------------------
def verify_dim_counts(conn: psycopg2.extensions.connection) -> None:
    """Log row counts for all 5 dimension tables."""
    tables = ["Dim_Date", "Dim_AMC", "Dim_Category", "Dim_Fund", "Dim_Investor"]
    logger.info("-" * 50)
    logger.info("Dimension table row counts:")
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM dbo.{t}")
            count = cur.fetchone()[0]
            logger.info(f"  {t:<20}: {count:>8,}")
    logger.info("-" * 50)


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Load all dimension tables into mf_analytics")
    parser.add_argument("--verify-only", action="store_true", help="Print counts only, skip loading")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("ETL DIMENSIONS — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        if args.verify_only:
            verify_dim_counts(conn)
            return

        # Load source data
        amfi_df = load_latest_processed("nav_amfi_clean")
        yahoo_df = load_latest_processed("nav_yahoo_clean")
        txn_df = load_latest_processed("transactions_clean")
        raw_amfi_df = load_latest_raw("amfi_nav_current")

        investor_ids = sorted(txn_df["investor_id"].unique().tolist())

        # Load in FK dependency order
        logger.info("--- Pass 1: no-dependency dims ---")
        load_dim_date(conn)
        amc_map = load_dim_amc(conn, amfi_df)
        cat_map = load_dim_category(conn, amfi_df)

        logger.info("--- Pass 2: Dim_Fund (FK -> AMC, Category) ---")
        load_dim_fund(conn, amfi_df, yahoo_df, raw_amfi_df, amc_map, cat_map)

        logger.info("--- Pass 3: Dim_Investor ---")
        load_dim_investor(conn, investor_ids)

        verify_dim_counts(conn)

    except Exception as e:
        conn.rollback()
        logger.error(f"ETL failed: {e}")
        raise
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("ETL DIMENSIONS — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
