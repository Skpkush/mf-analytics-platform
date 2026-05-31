"""
Local smoke test for compute.py — runs against local PostgreSQL via psycopg2.
Used to verify compute logic without needing Azure SQL or azure-functions installed.

Usage:
    python azure/functions/fn_compute_daily_metrics/test_local.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("test_local")


class _PsycopgWrapper:
    """Thin wrapper making psycopg2 connection behave like pyodbc for compute.py."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _get_pg_conn() -> object:
    import psycopg2
    raw = psycopg2.connect(
        host=os.getenv("LOCAL_DB_HOST", "localhost"),
        port=int(os.getenv("LOCAL_DB_PORT", "5432")),
        dbname=os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        user=os.getenv("LOCAL_DB_USER", "postgres"),
        password=os.getenv("LOCAL_DB_PASSWORD", ""),
    )
    return _PsycopgWrapper(raw)


def patch_compute_for_postgres():
    """
    Monkey-patch compute.py to work with psycopg2 cursor API.
    psycopg2 cursors use %s placeholders and execute_values, not ?/.executemany.
    This test verifies the computation logic only — not the T-SQL write path.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import compute as c

    orig_load_nav = c.load_nav_ts
    orig_load_existing = c.load_existing_metrics

    def _load_nav_pg(conn):
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
            s = pd.Series(d["navs"], index=pd.DatetimeIndex(d["dates"]), dtype=float).sort_index()
            result[fk] = (d["sc"], s)
        log.info(f"NAV time series (PG): {len(result)} funds, {len(rows):,} rows")
        return result

    def _load_existing_pg(conn):
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

    c.load_nav_ts = _load_nav_pg
    c.load_existing_metrics = _load_existing_pg
    return c


def test_metric_computations():
    """Verify all metric functions produce valid results on local PostgreSQL data."""
    import compute as c

    log.info("=" * 55)
    log.info("LOCAL SMOKE TEST — compute.py")
    log.info("=" * 55)

    conn = _get_pg_conn()
    c_patched = patch_compute_for_postgres()

    nav_data = c_patched.load_nav_ts(conn)
    assert len(nav_data) == 16, f"Expected 16 Yahoo funds, got {len(nav_data)}"

    # Test returns
    results_by_sc = {}
    for fk, (sc, series) in nav_data.items():
        as_of, m = c.compute_returns(series)
        results_by_sc[sc] = m

    nifty = results_by_sc.get("NIFTYBEES.NS", {})
    assert nifty.get("cagr_5y") is not None, "NIFTYBEES.NS cagr_5y is None"
    assert 8.0 <= nifty["cagr_5y"] <= 14.0, f"NIFTYBEES.NS cagr_5y out of range: {nifty['cagr_5y']}"
    log.info(f"  Returns PASSED: NIFTYBEES cagr_5y={nifty['cagr_5y']:.2f}%")

    # Test risk
    _, risk = c.compute_risk(nav_data[list(nav_data.keys())[0]][1])
    assert risk["max_drawdown"] is None or risk["max_drawdown"] <= 0, "max_drawdown must be ≤ 0"
    log.info(f"  Risk PASSED: max_drawdown={risk['max_drawdown']}")

    # Test market
    bench_series = None
    for fk, (sc, s) in nav_data.items():
        if sc == c.BENCHMARK_CODE:
            bench_series = s
            break
    assert bench_series is not None, f"{c.BENCHMARK_CODE} not found"

    for fk, (sc, series) in nav_data.items():
        if sc == c.BENCHMARK_CODE:
            continue
        beta = c.compute_beta(series, bench_series)
        if beta is not None:
            break
    assert beta is not None, "Beta is None for all funds"
    log.info(f"  Market PASSED: computed beta={beta}")

    # Test risk-adjusted
    existing = c_patched.load_existing_metrics(conn)
    sc = "GOLDBEES.NS"
    if sc in existing:
        sc_data = next(((sc2, s) for _, (sc2, s) in nav_data.items() if sc2 == sc), None)
        if sc_data:
            m = c.compute_risk_adjusted(sc_data[1], existing[sc]["cagr_1y"], existing[sc]["beta"])
            assert m["sharpe_ratio"] is not None
            assert m["sharpe_ratio"] > 0, f"GOLDBEES sharpe should be > 0, got {m['sharpe_ratio']}"
            log.info(f"  Risk-adj PASSED: GOLDBEES sharpe={m['sharpe_ratio']:.2f}")

    conn.close()
    log.info("=" * 55)
    log.info("ALL SMOKE TESTS PASSED")
    log.info("=" * 55)


if __name__ == "__main__":
    test_metric_computations()
