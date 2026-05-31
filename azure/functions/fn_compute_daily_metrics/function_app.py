"""
Azure Function: fn_compute_daily_metrics
=========================================
Refreshes Fact_SIP and Fact_Returns in Azure SQL on a daily schedule.

Triggers:
  Timer  — daily at 01:30 UTC (07:00 IST), CRON: "30 1 * * *"
  HTTP   — POST /api/compute-metrics (manual trigger, returns JSON summary)

Environment variables (Azure Function App → Configuration):
  AZURE_SQL_CONNECTION_STRING  full ODBC connection string
     OR the 5 individual vars: AZURE_SQL_DRIVER, AZURE_SQL_SERVER,
     AZURE_SQL_DATABASE, AZURE_SQL_USER, AZURE_SQL_PASSWORD

Execution order (matches run_azure_etl.py):
  1. Fact_SIP   — TRUNCATE + re-derive from Fact_Transactions
  2. Fact_Returns — DELETE + recompute (returns → risk → market → risk-adj)

Returns JSON on HTTP:
  {
    "status": "ok",
    "run_utc": "...",
    "elapsed_seconds": 42.1,
    "fact_sip_rows": 28224,
    "fact_returns": {"returns_rows": 16, "risk_updates": 16, ...}
  }
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import azure.functions as func
import pyodbc
from dotenv import load_dotenv

from compute import refresh_fact_returns, refresh_fact_sip

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
log = logging.getLogger("fn_compute_daily_metrics")

# Load .env for local development (no-op in Azure where app settings are used)
load_dotenv()

# ── Azure Function app ────────────────────────────────────────────────────────
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


# ── Connection ────────────────────────────────────────────────────────────────
def _get_conn() -> pyodbc.Connection:
    """
    Open Azure SQL connection.
    Prefers AZURE_SQL_CONNECTION_STRING (Key Vault reference in Azure).
    Falls back to individual env vars for local/CI testing.
    """
    cs = os.getenv("AZURE_SQL_CONNECTION_STRING")
    if not cs:
        cs = (
            f"DRIVER={os.getenv('AZURE_SQL_DRIVER', '{ODBC Driver 18 for SQL Server}')};"
            f"SERVER={os.getenv('AZURE_SQL_SERVER')};"
            f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
            f"UID={os.getenv('AZURE_SQL_USER')};"
            f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
    return pyodbc.connect(cs, autocommit=False)


# ── Core compute (shared by both triggers) ────────────────────────────────────
def _run_compute() -> dict:
    """Run Fact_SIP refresh and Fact_Returns recompute. Returns summary dict."""
    t0 = time.monotonic()
    run_utc = datetime.now(timezone.utc).isoformat()
    log.info("=" * 60)
    log.info("fn_compute_daily_metrics — START")
    log.info("=" * 60)

    conn = _get_conn()
    try:
        log.info("Step 1: Fact_SIP refresh")
        sip_rows = refresh_fact_sip(conn)

        log.info("Step 2: Fact_Returns recompute")
        returns_counts = refresh_fact_returns(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    elapsed = round(time.monotonic() - t0, 1)
    log.info(f"fn_compute_daily_metrics — DONE in {elapsed}s")

    return {
        "status": "ok",
        "run_utc": run_utc,
        "elapsed_seconds": elapsed,
        "fact_sip_rows": sip_rows,
        "fact_returns": returns_counts,
    }


# ── Timer trigger ─────────────────────────────────────────────────────────────
@app.timer_trigger(
    schedule="30 1 * * *",   # 01:30 UTC = 07:00 IST
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def compute_metrics_scheduled(timer: func.TimerRequest) -> None:
    """Daily 7 AM IST run — fires after ADF pl_transform_facts completes."""
    if timer.past_due:
        log.warning("Timer is past due — running now")
    _run_compute()


# ── HTTP trigger ──────────────────────────────────────────────────────────────
@app.route(
    route="compute-metrics",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
def compute_metrics_http(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manual trigger via POST /api/compute-metrics.
    Accepts optional JSON body: {"dry_run": true} to skip actual DB writes.
    Returns JSON summary.
    """
    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}

    if body.get("dry_run"):
        log.info("Dry-run requested — skipping DB writes")
        return func.HttpResponse(
            json.dumps({"status": "dry_run", "message": "No DB writes performed"}),
            mimetype="application/json",
            status_code=200,
        )

    try:
        result = _run_compute()
        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as exc:
        log.exception("Compute failed")
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(exc)}),
            mimetype="application/json",
            status_code=500,
        )
