#!/usr/bin/env python3
"""
AMFI Historical NAV Pipeline — end-to-end.

Steps:
  1. Check Azure SQL free space (Basic = 2 GB hard limit)
  2. Fetch 5 years of AMFI daily NAVs from AMFI portal (chunked 90-day requests)
  3. Transform raw data to Fact_NAV schema
  4. Reload Fact_NAV: DELETE existing AMFI single-row snapshot, INSERT full history
  5. Truncate Fact_Returns (will be fully recomputed for all 14 k+ funds)
  6. Compute returns / risk / market / risk-adjusted metrics for ALL funds
  7. Insert Fact_Returns

Run:
    python scripts/etl/run_amfi_historical_pipeline.py
    python scripts/etl/run_amfi_historical_pipeline.py --start 2023-01-01  # shorter window
    python scripts/etl/run_amfi_historical_pipeline.py --skip-fetch        # if parquet already saved
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_RAW       = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
LOG_DIR        = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "amfi_historical_pipeline.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("amfi_hist")

# Import pure-computation helpers
from scripts.analytics.metrics_returns import compute_returns_for_fund
from scripts.analytics.metrics_risk import compute_risk_for_fund
from scripts.analytics.metrics_market import compute_beta, compute_alpha, BENCHMARK_CODE
from scripts.analytics.metrics_risk_adjusted import compute_risk_adjusted_for_fund

BATCH_INSERT  = 5_000
BATCH_METRICS = 500   # funds to load NAV series for at once

# ── Connection ────────────────────────────────────────────────────────────────
def _conn() -> pyodbc.Connection:
    cs = (
        f"DRIVER={os.getenv('AZURE_SQL_DRIVER')};"
        f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
        f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
        f"UID={os.getenv('AZURE_SQL_USER')};"
        f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(cs, autocommit=False)


# ── Helpers ───────────────────────────────────────────────────────────────────
_NUMERIC_10_4_MAX = 99999.9999   # NUMERIC(10,4) = 6 digits + 4 decimal → safe cap

def _v(val):
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    if isinstance(val, (np.bool_,)) or isinstance(val, bool):
        return int(val)
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        if np.isnan(val) or np.isinf(val):
            return None
        val = float(val)
        # Clamp to NUMERIC(10,4) range — extreme ratios (e.g. treynor when beta≈0) are NULL
        return None if abs(val) > _NUMERIC_10_4_MAX else val
    if isinstance(val, float):
        return None if abs(val) > _NUMERIC_10_4_MAX else val
    if isinstance(val, pd.Timestamp):
        return val.date()
    return val


def _bulk(cur: pyodbc.Cursor, sql: str, records: list[tuple], batch: int = BATCH_INSERT) -> None:
    cur.fast_executemany = True
    for i in range(0, len(records), batch):
        cur.executemany(sql, records[i: i + batch])
    cur.fast_executemany = False


def _count(conn: pyodbc.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM dbo.{table}")
        return cur.fetchone()[0]


def _dk(ts: pd.Timestamp) -> int:
    return ts.year * 10_000 + ts.month * 100 + ts.day


# ── Step 1: check DB size ─────────────────────────────────────────────────────
def check_db_size(conn: pyodbc.Connection) -> float:
    """Return used MB on Azure SQL (Basic tier hard limit = 2048 MB)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                SUM(reserved_page_count) * 8.0 / 1024.0 AS used_mb
            FROM sys.dm_db_partition_stats
        """)
        row = cur.fetchone()
        used_mb = float(row[0]) if row and row[0] else 0.0
    log.info(f"Azure SQL current usage: {used_mb:.1f} MB / 2048 MB")
    if used_mb > 1600:
        log.warning("  DB > 1.6 GB — reduce fetch window with --start 2024-01-01")
    return used_mb


# ── Step 2: fetch AMFI historical ─────────────────────────────────────────────
def fetch_amfi_historical(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Chunk requests to AMFI historical endpoint (90-day chunks, 2s sleep)."""
    from scripts.ingestion.fetch_amfi_nav import (
        fetch_amfi_historical as _fetch,
        save_parquet,
    )
    df = _fetch(start_date, end_date, chunk_days=90)
    if df is None or df.empty:
        raise RuntimeError("AMFI historical fetch returned no data")
    save_parquet(df, "amfi_nav_history")
    log.info(f"  Saved amfi_nav_history: {len(df):,} rows")
    return df


def load_saved_history() -> pd.DataFrame:
    """Load the most recent amfi_nav_history parquet."""
    files = sorted(DATA_RAW.glob("amfi_nav_history_*.parquet"))
    if not files:
        raise FileNotFoundError("No amfi_nav_history_*.parquet found. Run without --skip-fetch first.")
    path = files[-1]
    df = pd.read_parquet(path)
    log.info(f"  Loaded {path.name}: {len(df):,} rows")
    return df


# ── Step 3: transform to Fact_NAV schema ─────────────────────────────────────
def transform_amfi_history(
    raw_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
) -> pd.DataFrame:
    """
    Map raw AMFI history to Fact_NAV columns.
    Drops rows with unknown scheme_code or date.
    """
    df = raw_df.copy()

    # Normalise date
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df[df["date"].notna() & df["nav"].notna() & (df["nav"] > 0)].copy()

    df["date_str"] = df["date"].dt.date.astype(str)
    df["date_key"] = df["date_str"].map(date_map)
    df["fund_key"] = df["scheme_code"].astype(str).map(fund_map)

    before = len(df)
    df = df[df["date_key"].notna() & df["fund_key"].notna()].copy()
    dropped = before - len(df)
    if dropped:
        log.info(f"  Dropped {dropped:,} rows (date/fund not in dimension tables)")

    # Z-score outlier flag per fund (same logic as clean_nav.py)
    df["is_outlier"] = False
    for fk, grp in df.groupby("fund_key"):
        if len(grp) >= 5:
            z = np.abs((grp["nav"] - grp["nav"].mean()) / (grp["nav"].std() + 1e-9))
            df.loc[grp.index, "is_outlier"] = z > 5.0

    log.info(f"  Transformed: {len(df):,} rows, {df['fund_key'].nunique():,} funds")
    return df


# ── Step 4: reload Fact_NAV ───────────────────────────────────────────────────
def reload_fact_nav(conn: pyodbc.Connection, df: pd.DataFrame) -> int:
    """Delete existing AMFI rows, insert full history."""
    with conn.cursor() as cur:
        cur.execute("""
            DELETE fn FROM dbo.Fact_NAV fn
            JOIN dbo.Dim_Fund df ON df.fund_key = fn.fund_key
            WHERE df.source = 'amfi'
        """)
        deleted = cur.rowcount
        conn.commit()
    log.info(f"  Deleted {deleted:,} old AMFI rows from Fact_NAV")

    cols = ["date_key", "fund_key", "nav", "is_outlier"]
    records = [
        (int(row.date_key), int(row.fund_key), float(row.nav),
         None, None, None, None, "amfi", int(row.is_outlier))
        for row in df[cols].itertuples(index=False)
    ]
    sql = """INSERT INTO dbo.Fact_NAV
        (date_key, fund_key, nav, open_price, high_price, low_price,
         volume, source, is_outlier)
        VALUES (?,?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
    conn.commit()
    log.info(f"  Inserted {len(records):,} AMFI rows into Fact_NAV")
    return len(records)


# ── Step 5: Truncate Fact_Returns ─────────────────────────────────────────────
def truncate_fact_returns(conn: pyodbc.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM dbo.Fact_Returns")
        conn.commit()
    log.info("  Fact_Returns cleared (will be fully recomputed)")


# ── Step 6: load all NAV time series ─────────────────────────────────────────
def load_all_nav_ts(conn: pyodbc.Connection) -> dict[int, tuple[str, pd.Series]]:
    """Load time series for ALL sources (Yahoo + AMFI)."""
    log.info("  Loading all NAV time series from Fact_NAV ...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fn.fund_key, df.scheme_code, dd.full_date, fn.nav
            FROM dbo.Fact_NAV fn
            JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
            JOIN dbo.Dim_Fund df ON df.fund_key  = fn.fund_key
            WHERE fn.is_outlier = 0
            ORDER BY fn.fund_key, dd.full_date
        """)
        rows = cur.fetchall()

    fd: dict[int, dict] = {}
    for fk, sc, dt, nav in rows:
        if fk not in fd:
            fd[fk] = {"sc": sc, "dates": [], "navs": []}
        fd[fk]["dates"].append(pd.Timestamp(dt))
        fd[fk]["navs"].append(float(nav))

    result: dict[int, tuple[str, pd.Series]] = {}
    for fk, d in fd.items():
        s = pd.Series(d["navs"], index=pd.DatetimeIndex(d["dates"]),
                      dtype=float).sort_index()
        result[fk] = (d["sc"], s)
    log.info(f"  Loaded {len(result):,} fund series, {len(rows):,} total rows")
    return result


# ── Step 7: compute + insert Fact_Returns ────────────────────────────────────
def compute_and_insert_metrics(
    conn: pyodbc.Connection,
    nav_data: dict[int, tuple[str, pd.Series]],
    date_map: dict[str, int],
) -> int:
    """Compute all 6 metric groups and insert into Fact_Returns."""

    # -- pass 1: returns + risk (independent per fund) --
    log.info(f"  Computing returns + risk for {len(nav_data):,} funds ...")
    pass1_records: list[tuple] = []
    fund_meta: dict[int, dict] = {}   # fk → {date_key, cagr_1y, cagr_3y, cagr_5y, beta}

    bench_series: pd.Series | None = None

    for fk, (sc, series) in nav_data.items():
        if sc == BENCHMARK_CODE:
            bench_series = series

        as_of_ret, m_ret  = compute_returns_for_fund(series)
        as_of_risk, m_risk = compute_risk_for_fund(series)

        as_of = max(as_of_ret, as_of_risk)
        dk = _dk(as_of)

        pass1_records.append((
            dk, fk,
            _v(m_ret.get("return_1y")),  _v(m_ret.get("return_3y")),  _v(m_ret.get("return_5y")),
            _v(m_ret.get("cagr_1y")),    _v(m_ret.get("cagr_3y")),    _v(m_ret.get("cagr_5y")),
            _v(m_risk.get("std_dev_1y")), _v(m_risk.get("max_drawdown")),
        ))
        fund_meta[fk] = {
            "date_key": dk,
            "sc": sc,
            "cagr_1y": _v(m_ret.get("cagr_1y")),
            "cagr_3y": _v(m_ret.get("cagr_3y")),
            "cagr_5y": _v(m_ret.get("cagr_5y")),
            "beta": None,
        }

    sql_ins = """INSERT INTO dbo.Fact_Returns (
        date_key, fund_key,
        return_1y, return_3y, return_5y,
        cagr_1y,   cagr_3y,   cagr_5y,
        std_dev_1y, max_drawdown
    ) VALUES (?,?,?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql_ins, pass1_records)
    conn.commit()
    log.info(f"  Inserted {len(pass1_records):,} rows into Fact_Returns (returns + risk)")

    # -- pass 2: beta / alpha --
    if bench_series is None:
        log.warning(f"  {BENCHMARK_CODE} not in NAV data — skipping beta/alpha")
    else:
        bench_meta = next(
            (v for v in fund_meta.values() if v["sc"] == BENCHMARK_CODE), {}
        )
        log.info(f"  Computing beta/alpha for {len(nav_data):,} funds ...")
        beta_records: list[tuple] = []
        for fk, (sc, series) in nav_data.items():
            if fk not in fund_meta:
                continue
            meta = fund_meta[fk]
            beta  = compute_beta(series, bench_series)
            alpha = compute_alpha(
                meta["cagr_1y"], meta["cagr_3y"], meta["cagr_5y"],
                bench_meta.get("cagr_1y"), bench_meta.get("cagr_3y"), bench_meta.get("cagr_5y"),
                beta,
            )
            fund_meta[fk]["beta"] = _v(beta)
            beta_records.append((_v(beta), _v(alpha), fk, meta["date_key"]))

        sql_upd = "UPDATE dbo.Fact_Returns SET beta=?, alpha=? WHERE fund_key=? AND date_key=?"
        with conn.cursor() as cur:
            _bulk(cur, sql_upd, beta_records)
        conn.commit()
        log.info(f"  Updated {len(beta_records):,} rows (beta/alpha)")

    # -- pass 3: risk-adjusted (sharpe, sortino, treynor) --
    log.info(f"  Computing risk-adjusted metrics ...")
    ra_records: list[tuple] = []
    for fk, (sc, series) in nav_data.items():
        if fk not in fund_meta:
            continue
        meta = fund_meta[fk]
        m_ra = compute_risk_adjusted_for_fund(series, meta["cagr_1y"], meta["beta"])
        ra_records.append((
            _v(m_ra.get("sharpe_ratio")), _v(m_ra.get("sortino_ratio")),
            _v(m_ra.get("treynor_ratio")),
            fk, meta["date_key"],
        ))

    sql_ra = """UPDATE dbo.Fact_Returns
                SET sharpe_ratio=?, sortino_ratio=?, treynor_ratio=?
                WHERE fund_key=? AND date_key=?"""
    with conn.cursor() as cur:
        _bulk(cur, sql_ra, ra_records)
    conn.commit()
    log.info(f"  Updated {len(ra_records):,} rows (sharpe/sortino/treynor)")

    return len(pass1_records)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=(datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d"),
                        help="Historical start date (default: 5 years ago)")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Historical end date (default: today)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip fetch step, use existing amfi_nav_history_*.parquet")
    args = parser.parse_args()

    t0 = datetime.now()
    log.info("=" * 60)
    log.info("AMFI HISTORICAL PIPELINE — START")
    log.info(f"  Window: {args.start} to {args.end}")
    log.info("=" * 60)

    conn = _conn()

    # ── Step 1: DB size check ─────────────────────────────────────────────
    log.info("\nSTEP 1 — DB SIZE CHECK")
    used_mb = check_db_size(conn)
    available_mb = 2048 - used_mb
    log.info(f"  Available: {available_mb:.0f} MB")
    if available_mb < 200:
        log.error("  Less than 200 MB free — aborting. Use --start 2024-01-01 for a shorter window.")
        conn.close()
        sys.exit(1)

    # ── Step 2: Fetch ─────────────────────────────────────────────────────
    log.info("\nSTEP 2 — FETCH AMFI HISTORICAL NAV")
    if args.skip_fetch:
        raw_df = load_saved_history()
    else:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
        end_dt   = datetime.strptime(args.end,   "%Y-%m-%d")
        raw_df   = fetch_amfi_historical(start_dt, end_dt)
    log.info(f"  Raw rows: {len(raw_df):,}  Funds: {raw_df['scheme_code'].nunique():,}")
    log.info(f"  Date range: {raw_df['date'].min()} -> {raw_df['date'].max()}")

    # ── Step 3: Transform ─────────────────────────────────────────────────
    log.info("\nSTEP 3 — TRANSFORM")
    with conn.cursor() as cur:
        cur.execute("SELECT scheme_code, fund_key FROM dbo.Dim_Fund")
        fund_map = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT CONVERT(VARCHAR(10), full_date, 23), date_key FROM dbo.Dim_Date")
        date_map = {r[0]: r[1] for r in cur.fetchall()}

    clean_df = transform_amfi_history(raw_df, fund_map, date_map)
    del raw_df  # free memory

    # ── Step 4: Reload Fact_NAV ───────────────────────────────────────────
    log.info("\nSTEP 4 — RELOAD Fact_NAV")
    inserted_nav = reload_fact_nav(conn, clean_df)
    del clean_df  # free memory
    log.info(f"  Fact_NAV now: {_count(conn, 'Fact_NAV'):,} rows")

    # ── Step 5: Truncate Fact_Returns ─────────────────────────────────────
    log.info("\nSTEP 5 — CLEAR Fact_Returns")
    truncate_fact_returns(conn)

    # ── Step 6: Load all NAV time series ─────────────────────────────────
    log.info("\nSTEP 6 — LOAD NAV TIME SERIES (all funds)")
    nav_data = load_all_nav_ts(conn)

    # ── Step 7: Compute + insert metrics ─────────────────────────────────
    log.info("\nSTEP 7 — COMPUTE METRICS")
    n_returns = compute_and_insert_metrics(conn, nav_data, date_map)

    # ── Final summary ─────────────────────────────────────────────────────
    elapsed = (datetime.now() - t0).total_seconds()
    log.info("\n" + "=" * 60)
    log.info("PIPELINE COMPLETE")
    log.info(f"  Fact_NAV rows inserted : {inserted_nav:,}")
    log.info(f"  Fact_Returns rows      : {_count(conn, 'Fact_Returns'):,}")
    log.info(f"  Total time             : {elapsed:.0f}s  ({elapsed/60:.1f} min)")
    log.info("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
