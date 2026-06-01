#!/usr/bin/env python3
"""
Resume: compute and update sharpe_ratio, sortino_ratio, treynor_ratio only.

Use after run_amfi_historical_pipeline.py fails on the risk-adjusted step.
Fact_NAV and Fact_Returns (with returns/risk/beta/alpha) must already be loaded.

Usage:
    python scripts/etl/resume_risk_adjusted.py
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "resume_risk_adjusted.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("resume_ra")

from scripts.analytics.metrics_risk_adjusted import compute_risk_adjusted_for_fund

BATCH = 2_000
_MAX = 99999.9999   # NUMERIC(10,4) safe cap


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


def _safe(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return None if abs(f) > _MAX else f


def load_nav_ts(conn: pyodbc.Connection) -> dict[int, tuple[str, pd.Series]]:
    log.info("Loading NAV time series from Fact_NAV ...")
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
    fd: dict = {}
    for fk, sc, dt, nav in rows:
        if fk not in fd:
            fd[fk] = {"sc": sc, "dates": [], "navs": []}
        fd[fk]["dates"].append(pd.Timestamp(dt))
        fd[fk]["navs"].append(float(nav))
    result: dict[int, tuple[str, pd.Series]] = {}
    for fk, d in fd.items():
        s = pd.Series(d["navs"], index=pd.DatetimeIndex(d["dates"]), dtype=float).sort_index()
        result[fk] = (d["sc"], s)
    log.info(f"  {len(result):,} fund series, {len(rows):,} rows")
    return result


def load_existing_metrics(conn: pyodbc.Connection) -> dict[int, dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fund_key, date_key, cagr_1y, beta
            FROM dbo.Fact_Returns
        """)
        return {
            r[0]: {"date_key": r[1], "cagr_1y": float(r[2]) if r[2] is not None else None,
                   "beta": float(r[3]) if r[3] is not None else None}
            for r in cur.fetchall()
        }


def main() -> None:
    t0 = datetime.now()
    log.info("=" * 60)
    log.info("RESUME: risk-adjusted metrics (sharpe / sortino / treynor)")
    log.info("=" * 60)

    conn = _conn()

    # Verify Fact_Returns has data
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM dbo.Fact_Returns")
        n = cur.fetchone()[0]
    if n == 0:
        log.error("Fact_Returns is empty — run full pipeline first")
        conn.close()
        sys.exit(1)
    log.info(f"Fact_Returns has {n:,} rows — proceeding")

    nav_data   = load_nav_ts(conn)
    fund_meta  = load_existing_metrics(conn)
    log.info(f"fund_meta entries: {len(fund_meta):,}")

    log.info("Computing risk-adjusted metrics ...")
    records: list[tuple] = []
    skipped_extreme = 0

    for fk, (sc, series) in nav_data.items():
        if fk not in fund_meta:
            continue
        meta = fund_meta[fk]
        m = compute_risk_adjusted_for_fund(series, meta["cagr_1y"], meta["beta"])
        sh = _safe(m.get("sharpe_ratio"))
        so = _safe(m.get("sortino_ratio"))
        tr = _safe(m.get("treynor_ratio"))
        if m.get("treynor_ratio") is not None and tr is None:
            skipped_extreme += 1
        records.append((sh, so, tr, fk, meta["date_key"]))

    log.info(f"  {len(records):,} funds to update  ({skipped_extreme} treynor values clamped to NULL)")

    sql = """UPDATE dbo.Fact_Returns
             SET sharpe_ratio=?, sortino_ratio=?, treynor_ratio=?
             WHERE fund_key=? AND date_key=?"""
    with conn.cursor() as cur:
        cur.fast_executemany = True
        for i in range(0, len(records), BATCH):
            cur.executemany(sql, records[i: i + BATCH])
        cur.fast_executemany = False
    conn.commit()
    log.info(f"  Updated {len(records):,} rows")

    elapsed = (datetime.now() - t0).total_seconds()
    log.info("=" * 60)
    log.info(f"DONE  ({elapsed:.0f}s)")
    log.info("=" * 60)
    conn.close()


if __name__ == "__main__":
    main()
