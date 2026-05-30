#!/usr/bin/env python3
"""
run_azure_etl.py
Full 6-step ETL pipeline targeting Azure SQL Database.

Steps:
  1. Dimensions  — Dim_Date, Dim_AMC, Dim_Category, Dim_Fund, Dim_Investor
  2. Facts       — Fact_NAV, Fact_Transactions, Fact_SIP
  3. Returns     — Fact_Returns (return/cagr columns)
  4. Risk        — Fact_Returns (std_dev_1y, max_drawdown)
  5. Market      — Fact_Returns (beta, alpha)
  6. Risk-Adj    — Fact_Returns (sharpe, sortino, treynor)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc
from dotenv import load_dotenv

# ── Bootstrap ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_RAW       = PROJECT_ROOT / "data" / "raw"
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("azure_etl")

# Import pure-computation helpers (no DB calls in these functions).
# Their module-level load_dotenv / basicConfig are no-ops here.
from scripts.etl.load_dimensions import (          # noqa: E402
    build_date_spine, parse_category,
    _make_short_name, _build_amfi_fund_records, _build_yahoo_fund_records,
    CITIES_STATES, CITIES, AGE_GROUPS, AGE_WEIGHTS,
    RISK_PROFILES, RISK_WEIGHTS, SEGMENTS, SEGMENT_WEIGHTS, INVESTOR_SEED,
)
from scripts.etl.load_facts import make_txn_hash, derive_fact_sip   # noqa: E402
from scripts.analytics.metrics_returns import (                       # noqa: E402
    compute_returns_for_fund,
    validate_results as val_returns,
    print_summary as prt_returns,
)
from scripts.analytics.metrics_risk import (                          # noqa: E402
    compute_risk_for_fund,
    validate_results as val_risk,
    print_summary as prt_risk,
)
from scripts.analytics.metrics_market import (                        # noqa: E402
    compute_beta, compute_alpha,
    validate_results as val_market,
    print_summary as prt_market,
    BENCHMARK_CODE,
)
from scripts.analytics.metrics_risk_adjusted import (                 # noqa: E402
    compute_risk_adjusted_for_fund,
    validate_results as val_risk_adj,
    print_summary as prt_risk_adj,
)

BATCH = 2_000

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


# ── Type conversion ───────────────────────────────────────────────────────────
def _v(val):
    """Convert pandas/numpy value to pyodbc-safe Python native type."""
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    if isinstance(val, (np.bool_,)) or isinstance(val, bool):
        return int(val)
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return None if np.isnan(val) else float(val)
    if isinstance(val, pd.Timestamp):
        return val.date()
    return val


def _rows(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    sub = df[cols].astype(object).where(df[cols].notna(), other=None)
    return [tuple(_v(x) for x in row) for row in sub.itertuples(index=False)]


# ── Bulk helpers ─────────────────────────────────────────────────────────────
def _bulk(cur: pyodbc.Cursor, sql: str, records: list[tuple]) -> None:
    cur.fast_executemany = True
    for i in range(0, len(records), BATCH):
        cur.executemany(sql, records[i: i + BATCH])
    cur.fast_executemany = False


def _count(conn: pyodbc.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM dbo.{table}")
        return cur.fetchone()[0]


def _show_counts(conn: pyodbc.Connection, tables: list[str]) -> None:
    log.info("  " + "─" * 45)
    for t in tables:
        log.info(f"  {t:<25} {_count(conn, t):>10,}")
    log.info("  " + "─" * 45)


def _load(prefix: str, raw: bool = False) -> pd.DataFrame:
    base = DATA_RAW if raw else DATA_PROCESSED
    files = sorted(base.glob(f"{prefix}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet for '{prefix}' in {base}")
    df = pd.read_parquet(files[-1])
    log.info(f"  Loaded {files[-1].name}: {len(df):,} rows")
    return df


# ── Step 1 helpers ────────────────────────────────────────────────────────────
def _load_dim_date(conn: pyodbc.Connection) -> None:
    df = build_date_spine()
    cols = [
        "date_key", "full_date", "day_of_week", "day_name", "day_of_month",
        "day_of_year", "week_of_year", "month_num", "month_name", "quarter",
        "year", "is_weekday", "is_month_end", "is_quarter_end", "is_year_end",
        "financial_year", "financial_quarter",
    ]
    records = _rows(df, cols)
    sql = """INSERT INTO dbo.Dim_Date (
        date_key, full_date, day_of_week, day_name, day_of_month,
        day_of_year, week_of_year, month_num, month_name, quarter,
        year, is_weekday, is_month_end, is_quarter_end, is_year_end,
        financial_year, financial_quarter
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
    conn.commit()
    log.info(f"  Dim_Date: {len(records):,} rows")


def _load_dim_amc(conn: pyodbc.Connection, amfi_df: pd.DataFrame) -> dict[str, int]:
    names = amfi_df["amc"].dropna().str.strip().unique()
    records = [(n, _make_short_name(n)) for n in sorted(names)]
    sql = "INSERT INTO dbo.Dim_AMC (amc_name, amc_short_name) VALUES (?,?)"
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
        conn.commit()
        cur.execute("SELECT amc_name, amc_key FROM dbo.Dim_AMC")
        return {r[0]: r[1] for r in cur.fetchall()}


def _load_dim_category(conn: pyodbc.Connection, amfi_df: pd.DataFrame) -> dict[str, int]:
    raw_cats = amfi_df["category"].dropna().str.strip().unique()
    records = []
    for raw in sorted(raw_cats):
        structure, asset_class, sub = parse_category(raw)
        records.append((raw, structure, asset_class, sub))
    sql = """INSERT INTO dbo.Dim_Category
        (raw_category, structure_type, asset_class, sub_category)
        VALUES (?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
        conn.commit()
        cur.execute("SELECT raw_category, category_key FROM dbo.Dim_Category")
        return {r[0]: r[1] for r in cur.fetchall()}


def _load_dim_fund(
    conn: pyodbc.Connection,
    amfi_df: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    raw_amfi_df: pd.DataFrame,
    amc_map: dict[str, int],
    cat_map: dict[str, int],
) -> dict[str, int]:
    amfi_recs  = _build_amfi_fund_records(amfi_df, raw_amfi_df, amc_map, cat_map)
    yahoo_recs = _build_yahoo_fund_records(yahoo_df)
    all_recs   = [tuple(_v(x) for x in r) for r in amfi_recs + yahoo_recs]
    sql = """INSERT INTO dbo.Dim_Fund (
        scheme_code, fund_name, base_fund_name, plan_type, option_type,
        amc_key, category_key, isin_growth, isin_idcw,
        source, is_benchmark, is_active, inception_date
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, all_recs)
        conn.commit()
        cur.execute("SELECT scheme_code, fund_key FROM dbo.Dim_Fund")
        return {r[0]: r[1] for r in cur.fetchall()}


def _load_dim_investor(
    conn: pyodbc.Connection,
    investor_ids: list[str],
) -> dict[str, int]:
    rng = np.random.default_rng(INVESTOR_SEED)
    n   = len(investor_ids)
    cities = rng.choice(CITIES, size=n)
    states = [CITIES_STATES[c] for c in cities]
    ages   = rng.choice(AGE_GROUPS,   size=n, p=AGE_WEIGHTS)
    risks  = rng.choice(RISK_PROFILES, size=n, p=RISK_WEIGHTS)
    segs   = rng.choice(SEGMENTS,      size=n, p=SEGMENT_WEIGHTS)
    kycs   = (rng.random(size=n) < 0.95).astype(int)
    records = [
        (investor_ids[i], str(ages[i]), str(cities[i]), str(states[i]),
         str(risks[i]), str(segs[i]), int(kycs[i]))
        for i in range(n)
    ]
    sql = """INSERT INTO dbo.Dim_Investor
        (investor_id, age_group, city, state, risk_profile, investor_segment, kyc_status)
        VALUES (?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
        conn.commit()
        cur.execute("SELECT investor_id, investor_key FROM dbo.Dim_Investor")
        return {r[0]: r[1] for r in cur.fetchall()}


# ── Step 2 helpers ────────────────────────────────────────────────────────────
def _drop_unmapped(df: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    n = int(df[col].isna().sum())
    if n:
        log.warning(f"  Dropped {n:,} rows: no {label}")
    return df[df[col].notna()].copy()


def _load_fact_nav(
    conn: pyodbc.Connection,
    yahoo_df: pd.DataFrame,
    amfi_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
) -> int:
    df = pd.concat([yahoo_df, amfi_df], ignore_index=True)
    df["date_str"] = pd.to_datetime(df["date"]).dt.normalize().dt.date.astype(str)
    df["date_key"] = df["date_str"].map(date_map)
    df["fund_key"] = df["ticker"].map(fund_map)
    df = _drop_unmapped(df, "date_key", "date in Dim_Date")
    df = _drop_unmapped(df, "fund_key", "ticker in Dim_Fund")
    bad = df["nav"].isna() | (df["nav"] <= 0)
    if bad.sum():
        log.warning(f"  Dropped {int(bad.sum()):,} rows: nav <= 0")
    df = df[~bad]
    # volume: float NaN → None, valid float → int
    df["volume"] = df["volume"].apply(lambda x: int(x) if pd.notna(x) else None)
    cols = ["date_key", "fund_key", "nav", "open", "high", "low",
            "volume", "source", "is_outlier"]
    records = _rows(df, cols)
    sql = """INSERT INTO dbo.Fact_NAV
        (date_key, fund_key, nav, open_price, high_price, low_price,
         volume, source, is_outlier)
        VALUES (?,?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
    conn.commit()
    log.info(f"  Fact_NAV: {len(records):,} rows")
    return len(records)


def _load_fact_transactions(
    conn: pyodbc.Connection,
    txn_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
    inv_map: dict[str, int],
) -> int:
    df = txn_df.copy()
    df["date_str"] = pd.to_datetime(df["transaction_date"]).dt.normalize().dt.date.astype(str)
    df["date_key"]     = df["date_str"].map(date_map)
    df["fund_key"]     = df["scheme_code"].map(fund_map)
    df["investor_key"] = df["investor_id"].map(inv_map)
    df = _drop_unmapped(df, "date_key",     "date in Dim_Date")
    df = _drop_unmapped(df, "fund_key",     "scheme_code in Dim_Fund")
    df = _drop_unmapped(df, "investor_key", "investor_id in Dim_Investor")
    df["transaction_hash"] = [
        make_txn_hash(r.investor_id, r.scheme_code, r.date_str,
                      r.amount, r.transaction_type)
        for r in df.itertuples(index=False)
    ]
    cols = ["date_key", "fund_key", "investor_key", "transaction_type",
            "amount", "units", "nav_at_transaction", "transaction_hash"]
    records = _rows(df, cols)
    sql = """INSERT INTO dbo.Fact_Transactions
        (date_key, fund_key, investor_key, transaction_type,
         amount, units, nav_at_transaction, transaction_hash)
        VALUES (?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
    conn.commit()
    log.info(f"  Fact_Transactions: {len(records):,} rows")
    return len(records)


def _load_fact_sip(
    conn: pyodbc.Connection,
    txn_df: pd.DataFrame,
    fund_map: dict[str, int],
    date_map: dict[str, int],
    inv_map: dict[str, int],
) -> int:
    sip = derive_fact_sip(txn_df, fund_map, date_map, inv_map)
    cols = ["date_key", "fund_key", "investor_key",
            "monthly_sip_amount", "cumulative_invested",
            "units_purchased", "current_units_held"]
    records = _rows(sip, cols)
    sql = """INSERT INTO dbo.Fact_SIP
        (date_key, fund_key, investor_key,
         monthly_sip_amount, cumulative_invested,
         units_purchased, current_units_held)
        VALUES (?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, sql, records)
    conn.commit()
    log.info(f"  Fact_SIP: {len(records):,} rows")
    return len(records)


# ── Shared DB helpers for metrics ─────────────────────────────────────────────
def _date_map(conn: pyodbc.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT CONVERT(VARCHAR(10), full_date, 23), date_key FROM dbo.Dim_Date")
        return {r[0]: r[1] for r in cur.fetchall()}


def _load_nav_ts(conn: pyodbc.Connection) -> dict[int, tuple[str, pd.Series]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fn.fund_key, df.scheme_code, dd.full_date, fn.nav
            FROM dbo.Fact_NAV fn
            JOIN dbo.Dim_Date dd ON dd.date_key = fn.date_key
            JOIN dbo.Dim_Fund df ON df.fund_key  = fn.fund_key
            WHERE df.source IN ('yahoo_etf', 'yahoo_benchmark')
            ORDER BY fn.fund_key, dd.full_date
        """)
        rows = cur.fetchall()
    fd: dict = {}
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
    log.info(f"  NAV time series: {len(result)} funds, {len(rows):,} rows")
    return result


def _load_existing_metrics(conn: pyodbc.Connection) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fr.fund_key, df.scheme_code, fr.date_key,
                   fr.cagr_1y, fr.cagr_3y, fr.cagr_5y, fr.beta
            FROM dbo.Fact_Returns fr
            JOIN dbo.Dim_Fund df ON df.fund_key = fr.fund_key
        """)
        return {
            r[1]: {
                "fund_key": r[0], "date_key": r[2],
                "cagr_1y": float(r[3]) if r[3] is not None else None,
                "cagr_3y": float(r[4]) if r[4] is not None else None,
                "cagr_5y": float(r[5]) if r[5] is not None else None,
                "beta":    float(r[6]) if r[6] is not None else None,
            }
            for r in cur.fetchall()
        }


def _dk(ts: pd.Timestamp) -> int:
    return ts.year * 10_000 + ts.month * 100 + ts.day


# ── Step 3: metrics_returns ───────────────────────────────────────────────────
def _run_metrics_returns(conn: pyodbc.Connection) -> None:
    nav_data = _load_nav_ts(conn)
    fk_res: dict[int, tuple[pd.Timestamp, dict]] = {}
    sc_res: dict[str, tuple[pd.Timestamp, dict]] = {}
    for fk, (sc, series) in nav_data.items():
        as_of, m = compute_returns_for_fund(series)
        fk_res[fk] = (as_of, m)
        sc_res[sc]  = (as_of, m)
    prt_returns(sc_res)
    val_returns(sc_res)
    records = [
        (_dk(as_of), fk,
         m.get("return_1y"), m.get("return_3y"), m.get("return_5y"),
         m.get("cagr_1y"),   m.get("cagr_3y"),   m.get("cagr_5y"))
        for fk, (as_of, m) in fk_res.items()
    ]
    sql = """INSERT INTO dbo.Fact_Returns (
        date_key, fund_key,
        return_1y, return_3y, return_5y,
        cagr_1y, cagr_3y, cagr_5y
    ) VALUES (?,?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    log.info(f"  Fact_Returns: {len(records)} rows inserted (returns/CAGR)")


# ── Step 4: metrics_risk ──────────────────────────────────────────────────────
def _run_metrics_risk(conn: pyodbc.Connection) -> None:
    nav_data = _load_nav_ts(conn)
    fk_res: dict[int, tuple[pd.Timestamp, dict]] = {}
    sc_res: dict[str, tuple[pd.Timestamp, dict]] = {}
    for fk, (sc, series) in nav_data.items():
        as_of, m = compute_risk_for_fund(series)
        fk_res[fk] = (as_of, m)
        sc_res[sc]  = (as_of, m)
    prt_risk(sc_res)
    val_risk(sc_res)
    records = [
        (m.get("std_dev_1y"), m.get("max_drawdown"), fk, _dk(as_of))
        for fk, (as_of, m) in fk_res.items()
    ]
    sql = """UPDATE dbo.Fact_Returns
             SET std_dev_1y = ?, max_drawdown = ?
             WHERE fund_key = ? AND date_key = ?"""
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    log.info(f"  Fact_Returns: {len(records)} rows updated (std_dev, max_drawdown)")


# ── Step 5: metrics_market ────────────────────────────────────────────────────
def _run_metrics_market(conn: pyodbc.Connection) -> None:
    existing = _load_existing_metrics(conn)
    bench    = existing.get(BENCHMARK_CODE, {})
    if not bench:
        log.error(f"  {BENCHMARK_CODE} not in Fact_Returns — skipping market metrics")
        return
    nav_data = _load_nav_ts(conn)
    bench_series: pd.Series | None = None
    for _, (sc, s) in nav_data.items():
        if sc == BENCHMARK_CODE:
            bench_series = s
            break
    if bench_series is None:
        log.error(f"  {BENCHMARK_CODE} NAV not in Fact_NAV")
        return
    fk_res: dict[int, dict] = {}
    sc_res: dict[str, dict] = {}
    for fk, (sc, series) in nav_data.items():
        if sc not in existing:
            continue
        row  = existing[sc]
        beta = compute_beta(series, bench_series)
        alpha = compute_alpha(
            row["cagr_1y"], row["cagr_3y"], row["cagr_5y"],
            bench.get("cagr_1y"), bench.get("cagr_3y"), bench.get("cagr_5y"),
            beta,
        )
        fk_res[fk] = {"date_key": row["date_key"], "beta": beta, "alpha": alpha}
        sc_res[sc]  = {"beta": beta, "alpha": alpha}
    prt_market(sc_res)
    val_market(sc_res)
    records = [(d["beta"], d["alpha"], fk, d["date_key"]) for fk, d in fk_res.items()]
    sql = """UPDATE dbo.Fact_Returns
             SET beta = ?, alpha = ?
             WHERE fund_key = ? AND date_key = ?"""
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    log.info(f"  Fact_Returns: {len(records)} rows updated (beta, alpha)")


# ── Step 6: metrics_risk_adjusted ─────────────────────────────────────────────
def _run_metrics_risk_adjusted(conn: pyodbc.Connection) -> None:
    existing = _load_existing_metrics(conn)
    nav_data = _load_nav_ts(conn)
    fk_res: dict[int, dict] = {}
    sc_res: dict[str, dict] = {}
    for fk, (sc, series) in nav_data.items():
        if sc not in existing:
            continue
        row = existing[sc]
        m   = compute_risk_adjusted_for_fund(series, row["cagr_1y"], row["beta"])
        fk_res[fk] = {"date_key": row["date_key"], **m}
        sc_res[sc]  = m
    prt_risk_adj(sc_res)
    val_risk_adj(sc_res)
    records = [
        (d.get("sharpe_ratio"), d.get("sortino_ratio"), d.get("treynor_ratio"),
         fk, d["date_key"])
        for fk, d in fk_res.items()
    ]
    sql = """UPDATE dbo.Fact_Returns
             SET sharpe_ratio = ?, sortino_ratio = ?, treynor_ratio = ?
             WHERE fund_key = ? AND date_key = ?"""
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    log.info(f"  Fact_Returns: {len(records)} rows updated (sharpe, sortino, treynor)")


# ── View samples ──────────────────────────────────────────────────────────────
def _show_views(conn: pyodbc.Connection) -> None:
    queries = [
        ("vw_fund_performance",
         "SELECT TOP 5 fund_name, cagr_1y, cagr_5y, sharpe_ratio, risk_tier_placeholder "
         "FROM (SELECT fp.fund_name, fp.cagr_1y, fp.cagr_5y, fp.sharpe_ratio, "
         "      CASE WHEN fp.std_dev_1y < 10 THEN 'Low' "
         "           WHEN fp.std_dev_1y < 18 THEN 'Medium' ELSE 'High' END AS risk_tier_placeholder "
         "      FROM dbo.vw_fund_performance fp WHERE fp.cagr_5y IS NOT NULL) t "
         "ORDER BY cagr_5y DESC"),
        ("vw_risk_summary",
         "SELECT TOP 5 fund_name, std_dev_1y, max_drawdown, risk_tier "
         "FROM dbo.vw_risk_summary ORDER BY std_dev_1y ASC"),
        ("vw_investor_segmentation",
         "SELECT TOP 5 investor_id, risk_profile, total_invested, active_funds "
         "FROM dbo.vw_investor_segmentation ORDER BY total_invested DESC"),
    ]
    for view_name, qry in queries:
        log.info(f"\n  ── {view_name} ──")
        try:
            with conn.cursor() as cur:
                cur.execute(qry)
                cols = [d[0] for d in cur.description]
                log.info("  " + " | ".join(f"{c:<22}" for c in cols))
                log.info("  " + "-" * (25 * len(cols)))
                for row in cur.fetchall():
                    log.info("  " + " | ".join(f"{str(v) if v is not None else 'NULL':<22}" for v in row))
        except Exception as exc:
            log.error(f"  View {view_name} error: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────
ALL_TABLES = [
    "Dim_Date", "Dim_AMC", "Dim_Category", "Dim_Fund", "Dim_Investor",
    "Fact_NAV", "Fact_Transactions", "Fact_SIP", "Fact_Returns",
]


def main() -> None:
    conn = _conn()

    # ─── Step 1: Dimensions ───────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 1 — DIMENSIONS")
    log.info("═" * 60)
    amfi_df     = _load("nav_amfi_clean")
    yahoo_df    = _load("nav_yahoo_clean")
    txn_df      = _load("transactions_clean")
    raw_amfi_df = _load("amfi_nav_current", raw=True)
    investor_ids = sorted(txn_df["investor_id"].unique().tolist())

    _load_dim_date(conn)
    amc_map  = _load_dim_amc(conn, amfi_df)
    cat_map  = _load_dim_category(conn, amfi_df)
    fund_map = _load_dim_fund(conn, amfi_df, yahoo_df, raw_amfi_df, amc_map, cat_map)
    inv_map  = _load_dim_investor(conn, investor_ids)
    log.info("  Row counts after Step 1:")
    _show_counts(conn, ["Dim_Date", "Dim_AMC", "Dim_Category", "Dim_Fund", "Dim_Investor"])

    # ─── Step 2: Facts ────────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 2 — FACTS")
    log.info("═" * 60)
    date_map = _date_map(conn)
    _load_fact_nav(conn, yahoo_df, amfi_df, fund_map, date_map)
    _load_fact_transactions(conn, txn_df, fund_map, date_map, inv_map)
    _load_fact_sip(conn, txn_df, fund_map, date_map, inv_map)
    log.info("  Row counts after Step 2:")
    _show_counts(conn, ["Fact_NAV", "Fact_Transactions", "Fact_SIP", "Fact_Returns"])

    # ─── Step 3: Returns ──────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 3 — METRICS RETURNS")
    log.info("═" * 60)
    _run_metrics_returns(conn)
    _show_counts(conn, ["Fact_Returns"])

    # ─── Step 4: Risk ─────────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 4 — METRICS RISK")
    log.info("═" * 60)
    _run_metrics_risk(conn)

    # ─── Step 5: Market ───────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 5 — METRICS MARKET (beta/alpha)")
    log.info("═" * 60)
    _run_metrics_market(conn)

    # ─── Step 6: Risk-Adjusted ────────────────────────────────────────────
    log.info("═" * 60)
    log.info("STEP 6 — METRICS RISK-ADJUSTED")
    log.info("═" * 60)
    _run_metrics_risk_adjusted(conn)

    # ─── Final counts ─────────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("FINAL ROW COUNTS — ALL TABLES")
    log.info("═" * 60)
    _show_counts(conn, ALL_TABLES)

    # ─── View samples ─────────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("VIEW SAMPLES")
    log.info("═" * 60)
    _show_views(conn)

    conn.close()
    log.info("═" * 60)
    log.info("ETL COMPLETE")
    log.info("═" * 60)


if __name__ == "__main__":
    main()
