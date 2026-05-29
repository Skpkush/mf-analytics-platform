"""
================================================================
SQL Layer Runner
================================================================
Executes all view and stored-procedure SQL files against
mf_analytics. Mirrors the run_ddl.py pattern.

File execution order:
    1. sql/views/*.sql   — CREATE OR REPLACE VIEW (alphabetical)
    2. sql/procs/*.sql   — CREATE OR REPLACE FUNCTION (alphabetical)

All files use CREATE OR REPLACE so re-running is always safe.

Usage:
    python scripts/etl/run_sql_layer.py
    python scripts/etl/run_sql_layer.py --views-only
    python scripts/etl/run_sql_layer.py --procs-only
    python scripts/etl/run_sql_layer.py --dry-run
================================================================
"""

import argparse
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
SQL_VIEWS_DIR = PROJECT_ROOT / "sql" / "views"
SQL_PROCS_DIR = PROJECT_ROOT / "sql" / "procs"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)
if hasattr(_stream_handler.stream, "reconfigure"):
    try:
        _stream_handler.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_DIR / "sql_layer.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("sql_layer")


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("LOCAL_DB_HOST", "localhost"),
        port=int(os.getenv("LOCAL_DB_PORT", "5432")),
        dbname=os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        user=os.getenv("LOCAL_DB_USER", "postgres"),
        password=os.getenv("LOCAL_DB_PASSWORD", ""),
    )


def get_sql_files(directory: Path) -> list[Path]:
    """Return .sql files in a directory sorted alphabetically."""
    if not directory.exists():
        logger.warning(f"Directory not found: {directory}")
        return []
    return sorted(directory.glob("*.sql"))


def run_sql_file(
    conn: psycopg2.extensions.connection,
    path: Path,
) -> None:
    """Execute a single SQL file and commit."""
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info(f"  OK  {path.name}")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQL views and stored procedures")
    parser.add_argument("--views-only", action="store_true", help="Only run sql/views/*.sql")
    parser.add_argument("--procs-only", action="store_true", help="Only run sql/procs/*.sql")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print SQL to stdout without executing",
    )
    args = parser.parse_args()

    # Determine which groups to run
    run_views = not args.procs_only
    run_procs = not args.views_only

    view_files = get_sql_files(SQL_VIEWS_DIR) if run_views else []
    proc_files = get_sql_files(SQL_PROCS_DIR) if run_procs else []
    all_files = view_files + proc_files

    if not all_files:
        logger.warning("No SQL files found to execute")
        return

    if args.dry_run:
        logger.info("DRY RUN — printing SQL only, not executing")
        for f in all_files:
            print(f"\n-- {f.name} " + "-" * 50)
            print(f.read_text(encoding="utf-8"))
        return

    logger.info("=" * 60)
    logger.info("SQL LAYER — START")
    logger.info("=" * 60)

    conn = get_connection()
    try:
        if view_files:
            logger.info(f"--- Views ({len(view_files)} files) ---")
            for path in view_files:
                try:
                    run_sql_file(conn, path)
                except Exception as e:
                    conn.rollback()
                    logger.error(f"  FAIL {path.name}: {e}")
                    sys.exit(1)

        if proc_files:
            logger.info(f"--- Stored functions ({len(proc_files)} files) ---")
            for path in proc_files:
                try:
                    run_sql_file(conn, path)
                except Exception as e:
                    conn.rollback()
                    logger.error(f"  FAIL {path.name}: {e}")
                    sys.exit(1)

    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("SQL LAYER — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
