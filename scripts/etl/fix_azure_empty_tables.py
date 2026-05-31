"""
fix_azure_empty_tables.py
Reload only the 6 empty Azure SQL tables (Dim_AMC, Dim_Fund,
Fact_NAV, Fact_Transactions, Fact_SIP, Fact_Returns).
Skips Dim_Date / Dim_Category / Dim_Investor — already populated.
"""
from __future__ import annotations
import logging, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("fix_azure")

# ── import helpers from run_azure_etl (pure functions, no side-effects) ──────
from scripts.etl.run_azure_etl import (
    _conn, _load, _date_map, _bulk, _rows, _count, _show_counts,
    _load_dim_amc, _load_dim_fund,
    _load_fact_nav, _load_fact_transactions, _load_fact_sip,
    _run_metrics_returns, _run_metrics_risk,
    _run_metrics_market, _run_metrics_risk_adjusted,
)
import pyodbc

EMPTY_TABLES  = ["Dim_AMC", "Dim_Fund",
                 "Fact_NAV", "Fact_Transactions", "Fact_SIP", "Fact_Returns"]
ALL_TABLES    = ["Dim_Date","Dim_AMC","Dim_Category","Dim_Fund","Dim_Investor",
                 "Fact_NAV","Fact_Transactions","Fact_SIP","Fact_Returns"]

def _cat_map(conn: pyodbc.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT raw_category, category_key FROM dbo.Dim_Category")
        return {r[0]: r[1] for r in cur.fetchall()}

def _inv_map(conn: pyodbc.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT investor_id, investor_key FROM dbo.Dim_Investor")
        return {r[0]: r[1] for r in cur.fetchall()}

def _fund_map(conn: pyodbc.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT scheme_code, fund_key FROM dbo.Dim_Fund")
        return {r[0]: r[1] for r in cur.fetchall()}


def main() -> None:
    conn = _conn()

    # ── Verify which tables are actually empty ────────────────────────────
    log.info("=== Current Azure SQL state ===")
    truly_empty = [t for t in ALL_TABLES if _count(conn, t) == 0]
    log.info(f"Empty tables: {truly_empty}")

    if not truly_empty:
        log.info("All tables already populated — nothing to do.")
        _show_counts(conn, ALL_TABLES)
        conn.close()
        return

    # ── Load source parquets once ─────────────────────────────────────────
    amfi_df     = _load("nav_amfi_clean")
    yahoo_df    = _load("nav_yahoo_clean")
    txn_df      = _load("transactions_clean")
    raw_amfi_df = _load("amfi_nav_current", raw=True)

    # ── Dim_AMC ───────────────────────────────────────────────────────────
    if "Dim_AMC" in truly_empty:
        log.info("=== Loading Dim_AMC ===")
        amc_map = _load_dim_amc(conn, amfi_df)
        log.info(f"  Dim_AMC: {_count(conn, 'Dim_AMC'):,} rows")
    else:
        log.info("  Dim_AMC already populated — querying map")
        with conn.cursor() as cur:
            cur.execute("SELECT amc_name, amc_key FROM dbo.Dim_AMC")
            amc_map = {r[0]: r[1] for r in cur.fetchall()}

    # ── Dim_Fund ──────────────────────────────────────────────────────────
    if "Dim_Fund" in truly_empty:
        log.info("=== Loading Dim_Fund ===")
        cat_map  = _cat_map(conn)
        fund_map = _load_dim_fund(conn, amfi_df, yahoo_df, raw_amfi_df, amc_map, cat_map)
        log.info(f"  Dim_Fund: {_count(conn, 'Dim_Fund'):,} rows")
    else:
        log.info("  Dim_Fund already populated — querying map")
        fund_map = _fund_map(conn)

    # ── Build remaining FK maps from existing tables ──────────────────────
    date_map = _date_map(conn)
    inv_map  = _inv_map(conn)
    log.info(f"  FK maps — date:{len(date_map):,}  fund:{len(fund_map):,}  investor:{len(inv_map):,}")

    # ── Fact_NAV ──────────────────────────────────────────────────────────
    if "Fact_NAV" in truly_empty:
        log.info("=== Loading Fact_NAV ===")
        _load_fact_nav(conn, yahoo_df, amfi_df, fund_map, date_map)
        log.info(f"  Fact_NAV: {_count(conn, 'Fact_NAV'):,} rows")

    # ── Fact_Transactions ─────────────────────────────────────────────────
    if "Fact_Transactions" in truly_empty:
        log.info("=== Loading Fact_Transactions ===")
        _load_fact_transactions(conn, txn_df, fund_map, date_map, inv_map)
        log.info(f"  Fact_Transactions: {_count(conn, 'Fact_Transactions'):,} rows")

    # ── Fact_SIP ──────────────────────────────────────────────────────────
    if "Fact_SIP" in truly_empty:
        log.info("=== Loading Fact_SIP ===")
        _load_fact_sip(conn, txn_df, fund_map, date_map, inv_map)
        log.info(f"  Fact_SIP: {_count(conn, 'Fact_SIP'):,} rows")

    # ── Metrics ───────────────────────────────────────────────────────────
    if "Fact_Returns" in truly_empty:
        log.info("=== Metrics: Returns ===")
        _run_metrics_returns(conn)
        log.info("=== Metrics: Risk ===")
        _run_metrics_risk(conn)
        log.info("=== Metrics: Market (Beta/Alpha) ===")
        _run_metrics_market(conn)
        log.info("=== Metrics: Risk-Adjusted ===")
        _run_metrics_risk_adjusted(conn)
        log.info(f"  Fact_Returns: {_count(conn, 'Fact_Returns'):,} rows")

    # ── Final counts ──────────────────────────────────────────────────────
    log.info("=== Final Azure SQL row counts ===")
    _show_counts(conn, ALL_TABLES)
    conn.close()
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
