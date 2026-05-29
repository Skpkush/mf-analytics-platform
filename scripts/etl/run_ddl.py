"""
================================================================
DDL Runner
================================================================
Creates the mf_analytics database (if absent) then executes
all sql/ddl/*.sql files in numeric order against it.

Usage:
    python scripts/etl/run_ddl.py
    python scripts/etl/run_ddl.py --dry-run   # print SQL, no execute

Requires LOCAL_DB_* vars in .env (copy from .env.example).
================================================================
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
import os

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
DDL_DIR = PROJECT_ROOT / "sql" / "ddl"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("LOCAL_DB_HOST", "localhost")
DB_PORT = int(os.getenv("LOCAL_DB_PORT", "5432"))
DB_NAME = os.getenv("LOCAL_DB_NAME", "mf_analytics")
DB_USER = os.getenv("LOCAL_DB_USER", "postgres")
DB_PASS = os.getenv("LOCAL_DB_PASSWORD", "")

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
        logging.FileHandler(LOG_DIR / "ddl_runner.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("ddl_runner")


# ----------------------------------------------------------------
# Database creation
# ----------------------------------------------------------------
def ensure_database_exists() -> None:
    """
    Connect to the default 'postgres' database and create mf_analytics
    if it does not already exist.

    CREATE DATABASE cannot run inside a transaction, so autocommit is
    required for this connection.
    """
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname="postgres",
        user=DB_USER,
        password=DB_PASS,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (DB_NAME,),
            )
            if cur.fetchone():
                logger.info(f"Database '{DB_NAME}' already exists — skipping creation")
            else:
                cur.execute(f'CREATE DATABASE "{DB_NAME}"')
                logger.info(f"Created database '{DB_NAME}'")
    finally:
        conn.close()


# ----------------------------------------------------------------
# DDL execution
# ----------------------------------------------------------------
def get_ddl_files() -> list[Path]:
    """Return all sql/ddl/*.sql files sorted numerically."""
    files = sorted(DDL_DIR.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"No .sql files found in {DDL_DIR}")
    return files


def run_ddl_file(conn: psycopg2.extensions.connection, path: Path) -> None:
    """Execute a single DDL file inside a transaction."""
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info(f"  OK  {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create mf_analytics DB and run DDL scripts")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL to stdout without executing",
    )
    args = parser.parse_args()

    if not DB_PASS and not args.dry_run:
        logger.error(
            "LOCAL_DB_PASSWORD is empty. "
            "Copy .env.example to .env and set LOCAL_DB_PASSWORD, then retry."
        )
        sys.exit(1)

    ddl_files = get_ddl_files()

    if args.dry_run:
        logger.info("DRY RUN — printing SQL only, not executing")
        for f in ddl_files:
            print(f"\n-- {f.name} " + "-" * 50)
            print(f.read_text(encoding="utf-8"))
        return

    logger.info("=" * 60)
    logger.info("DDL RUNNER — START")
    logger.info(f"Target: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    logger.info("=" * 60)

    try:
        ensure_database_exists()
    except Exception as e:
        logger.error(f"Failed to ensure database exists: {e}")
        sys.exit(1)

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
        )
    except Exception as e:
        logger.error(f"Cannot connect to {DB_NAME}: {e}")
        sys.exit(1)

    try:
        logger.info(f"Running {len(ddl_files)} DDL files:")
        for path in ddl_files:
            try:
                run_ddl_file(conn, path)
            except Exception as e:
                conn.rollback()
                logger.error(f"  FAIL {path.name}: {e}")
                sys.exit(1)
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("DDL RUNNER — COMPLETE. Schema is ready.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
