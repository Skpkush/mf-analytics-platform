"""
================================================================
ETL: Migrate local PostgreSQL → Supabase (minimal cloud replica)
================================================================
Stands up the analytics star schema on a Supabase Postgres project
for the deployed Streamlit app:

    1. Run DDL (scripts/sql/ddl/*.sql) to create the dbo schema.
    2. COPY-stream table data local → Supabase in FK-safe order.
    3. Recreate vw_fund_performance + vw_risk_summary.
    4. Reset identity sequences and verify row counts.

Minimal by design: Fact_NAV is filtered to the 16 funds that have
a real time series (yahoo_etf + yahoo_benchmark). Pass
--include-amfi-nav to also copy the ~14k AMFI single-NAV snapshots
(needed if you want Fund Explorer to show a latest NAV for AMFI
funds in the cloud).

Credentials
-----------
Local DB   : .env  LOCAL_DB_*
Supabase   : SUPABASE_DB_{HOST,PORT,NAME,USER,PASSWORD}
             Host/port/name/user default to the provided project;
             PASSWORD is read from env, else prompted via getpass
             (never hardcoded, never logged).

If the direct host times out from your machine (Supabase direct
connections are IPv6-only on the free tier), set
SUPABASE_DB_HOST / SUPABASE_DB_USER to the IPv4 Session pooler
(aws-0-<region>.pooler.supabase.com / postgres.<ref>).

Usage:
    python scripts/etl/migrate_to_supabase.py
    python scripts/etl/migrate_to_supabase.py --include-amfi-nav
    python scripts/etl/migrate_to_supabase.py --verify-only
    python scripts/etl/migrate_to_supabase.py --skip-ddl
================================================================
"""

from __future__ import annotations

import argparse
import getpass
import io
import logging
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DDL_DIR = PROJECT_ROOT / "scripts" / "sql" / "ddl"
VIEWS_DIR = PROJECT_ROOT / "scripts" / "sql" / "views"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

# Supabase connection defaults (override via env; password is never defaulted).
SUPABASE_DEFAULTS = {
    "host": "db.quhuvkvitvlmnjpjtvmn.supabase.co",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
}
CONNECT_TIMEOUT = 20  # seconds — fail fast on IPv6/unreachable host

# DDL files in dependency order (01 = schema, 02-10 = tables).
DDL_FILES = [
    "01_create_schema.sql", "02_dim_date.sql", "03_dim_amc.sql",
    "04_dim_category.sql", "05_dim_fund.sql", "06_dim_investor.sql",
    "07_fact_nav.sql", "08_fact_transactions.sql", "09_fact_sip.sql",
    "10_fact_returns.sql",
]

# Views to recreate after data load (depend on the fact/dim tables).
VIEW_FILES = ["vw_fund_performance.sql", "vw_risk_summary.sql"]

# FK-safe load order. Dim_Fund FK-references Dim_AMC + Dim_Category, so those
# load first (this reorders the user's numbered list for referential safety).
LOAD_ORDER = [
    "dim_date", "dim_amc", "dim_category", "dim_fund", "dim_investor",
    "fact_nav", "fact_returns", "fact_sip", "fact_transactions",
]

# Yahoo sources = the 16 funds that actually have a NAV time series.
YAHOO_NAV_FILTER = "source IN ('yahoo_etf', 'yahoo_benchmark')"

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
_stream = logging.StreamHandler(sys.stdout)
_stream.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
if hasattr(_stream.stream, "reconfigure"):
    try:
        _stream.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.FileHandler(LOG_DIR / "migrate_supabase.log", encoding="utf-8"), _stream],
)
logger = logging.getLogger("migrate_supabase")


# ----------------------------------------------------------------
# Connections
# ----------------------------------------------------------------
def local_connection() -> psycopg2.extensions.connection:
    """Open the local source database from .env LOCAL_DB_* credentials."""
    return psycopg2.connect(
        host=os.getenv("LOCAL_DB_HOST", "localhost"),
        port=int(os.getenv("LOCAL_DB_PORT", "5432")),
        dbname=os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        user=os.getenv("LOCAL_DB_USER", "postgres"),
        password=os.getenv("LOCAL_DB_PASSWORD", ""),
        connect_timeout=CONNECT_TIMEOUT,
    )


def supabase_connection() -> psycopg2.extensions.connection:
    """Open the Supabase target. Password from env, else getpass (never logged)."""
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if not password:
        password = getpass.getpass("Supabase database password: ")
    if not password:
        raise SystemExit("No Supabase password provided — aborting.")

    host = os.getenv("SUPABASE_DB_HOST", SUPABASE_DEFAULTS["host"])
    user = os.getenv("SUPABASE_DB_USER", SUPABASE_DEFAULTS["user"])
    logger.info(f"Connecting to Supabase {user}@{host} (SSL required)…")
    return psycopg2.connect(
        host=host,
        port=int(os.getenv("SUPABASE_DB_PORT", SUPABASE_DEFAULTS["port"])),
        dbname=os.getenv("SUPABASE_DB_NAME", SUPABASE_DEFAULTS["dbname"]),
        user=user,
        password=password,
        sslmode="require",
        connect_timeout=CONNECT_TIMEOUT,
    )


# ----------------------------------------------------------------
# DDL + views
# ----------------------------------------------------------------
def _run_sql_file(conn: psycopg2.extensions.connection, path: Path) -> None:
    """Execute a whole .sql file as a single batch."""
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info(f"  ran {path.name}")


def run_ddl(conn: psycopg2.extensions.connection) -> None:
    """Create schema + all tables on the target (idempotent)."""
    logger.info("Creating DDL on Supabase…")
    for name in DDL_FILES:
        _run_sql_file(conn, DDL_DIR / name)


def create_views(conn: psycopg2.extensions.connection) -> None:
    """(Re)create analytical views on the target."""
    logger.info("Creating views on Supabase…")
    for name in VIEW_FILES:
        _run_sql_file(conn, VIEWS_DIR / name)


# ----------------------------------------------------------------
# Data copy
# ----------------------------------------------------------------
def _columns(conn: psycopg2.extensions.connection, table: str) -> list[str]:
    """Ordered column names for dbo.<table> from information_schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'dbo' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def _source_query(table: str, include_amfi_nav: bool, select_clause: str = "*") -> str:
    """Return the SELECT used to read a table from the local DB."""
    if table == "fact_nav" and not include_amfi_nav:
        return f"SELECT {select_clause} FROM dbo.fact_nav WHERE {YAHOO_NAV_FILTER}"
    return f"SELECT {select_clause} FROM dbo.{table}"


def truncate_targets(conn: psycopg2.extensions.connection) -> None:
    """Empty all target tables so the migration is re-runnable."""
    tables = ", ".join(f"dbo.{t}" for t in reversed(LOAD_ORDER))
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    conn.commit()
    logger.info("Truncated all target tables (RESTART IDENTITY CASCADE)")


def copy_table(
    local: psycopg2.extensions.connection,
    supa: psycopg2.extensions.connection,
    table: str,
    include_amfi_nav: bool,
) -> int:
    """COPY one table local → Supabase via an in-memory text buffer.

    Returns the number of rows transferred.

    Columns are intersected target∩source (ordered by target) so the copy is
    resilient to schema drift — e.g. local Dim_Investor has an extra age_sort
    column that the DDL (and thus the Supabase table) doesn't.
    """
    src_cols = set(_columns(local, table))
    cols = [c for c in _columns(supa, table) if c in src_cols]
    collist = ", ".join(cols)
    dropped = src_cols - set(cols)
    if dropped:
        logger.warning(f"  {table}: source-only columns not migrated: {sorted(dropped)}")

    src = _source_query(table, include_amfi_nav, collist)
    buf = io.StringIO()
    with local.cursor() as lcur:
        lcur.copy_expert(f"COPY ({src}) TO STDOUT", buf)
    buf.seek(0)
    with supa.cursor() as scur:
        scur.copy_expert(f"COPY dbo.{table} ({collist}) FROM STDIN", buf)
    supa.commit()
    n = buf.getvalue().count("\n")
    logger.info(f"  {table:<20}: {n:>8,} rows copied")
    return n


def reset_sequences(conn: psycopg2.extensions.connection) -> None:
    """Advance each serial/identity sequence past the copied max value.

    COPY inserts explicit PK values without advancing the sequence, so any
    future INSERT would collide. Discovers sequence-backed columns dynamically
    (skips Dim_Date.date_key, which has no sequence).
    """
    with conn.cursor() as cur:
        for table in LOAD_ORDER:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'dbo' AND table_name = %s
                  AND column_default LIKE 'nextval%%'
                """,
                (table,),
            )
            for (col,) in cur.fetchall():
                cur.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('dbo.{table}', %s),
                        COALESCE((SELECT MAX({col}) FROM dbo.{table}), 1),
                        true
                    )
                    """,
                    (col,),
                )
    conn.commit()
    logger.info("Identity sequences reset")


# ----------------------------------------------------------------
# Verification
# ----------------------------------------------------------------
def _count(conn: psycopg2.extensions.connection, sql: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql)
        return int(cur.fetchone()[0])


def verify(
    local: psycopg2.extensions.connection,
    supa: psycopg2.extensions.connection,
    include_amfi_nav: bool,
) -> bool:
    """Compare local vs Supabase row counts; check the two views resolve."""
    logger.info("-" * 56)
    logger.info(f"{'table':<22}{'local':>12}{'supabase':>12}{'ok':>6}")
    logger.info("-" * 56)
    all_ok = True
    for table in LOAD_ORDER:
        src = _source_query(table, include_amfi_nav)
        local_n = _count(local, f"SELECT COUNT(*) FROM ({src}) s")
        supa_n = _count(supa, f"SELECT COUNT(*) FROM dbo.{table}")
        ok = local_n == supa_n
        all_ok &= ok
        logger.info(f"{table:<22}{local_n:>12,}{supa_n:>12,}{'✓' if ok else '✗':>6}")

    logger.info("-" * 56)
    for view in ("vw_fund_performance", "vw_risk_summary"):
        n = _count(supa, f"SELECT COUNT(*) FROM dbo.{view}")
        logger.info(f"view {view:<28}: {n:>6,} rows")
    logger.info("-" * 56)
    logger.info("VERIFY: %s", "ALL COUNTS MATCH ✓" if all_ok else "MISMATCH ✗ — check log")
    return all_ok


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local Postgres → Supabase")
    parser.add_argument("--include-amfi-nav", action="store_true",
                        help="Also copy the ~14k AMFI single-NAV snapshots (default: 16 funds only)")
    parser.add_argument("--skip-ddl", action="store_true", help="Assume schema/tables already exist")
    parser.add_argument("--verify-only", action="store_true", help="Only compare counts, no writes")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MIGRATE LOCAL → SUPABASE — START")
    logger.info("=" * 60)

    local = local_connection()
    supa = supabase_connection()
    try:
        if args.verify_only:
            verify(local, supa, args.include_amfi_nav)
            return

        if not args.skip_ddl:
            run_ddl(supa)

        logger.info("Copying data (FK-safe order)…")
        truncate_targets(supa)
        total = 0
        for table in LOAD_ORDER:
            total += copy_table(local, supa, table, args.include_amfi_nav)
        logger.info(f"Total rows copied: {total:,}")

        reset_sequences(supa)
        create_views(supa)

        ok = verify(local, supa, args.include_amfi_nav)
        if not ok:
            raise SystemExit("Verification failed — see migrate_supabase.log")

    except Exception as exc:
        supa.rollback()
        logger.error(f"Migration failed: {exc}")
        raise
    finally:
        local.close()
        supa.close()

    logger.info("=" * 60)
    logger.info("MIGRATE LOCAL → SUPABASE — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
