"""
================================================================
Data Quality Framework
================================================================
Reusable quality checks for any DataFrame in the pipeline.
Import this module from other transformation scripts, or run
standalone to check any processed parquet:

    python scripts/transformation/data_quality.py \\
        data/processed/nav_yahoo_clean_20260529.parquet \\
        --required-cols ticker date nav \\
        --key-cols ticker date

Exit code 1 if quality checks fail.
================================================================
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

Z_ANOMALY_THRESHOLD = 5.0

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
        logging.FileHandler(LOG_DIR / "data_quality.log", encoding="utf-8"),
        _stream_handler,
    ],
)
logger = logging.getLogger("data_quality")


# ----------------------------------------------------------------
# Quality checks
# ----------------------------------------------------------------
def check_completeness(
    df: pd.DataFrame,
    required_cols: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Compute null counts and percentages for required columns.

    Args:
        df: Input DataFrame.
        required_cols: Columns that must be non-null.

    Returns:
        Dict of {col: {"null_count": int, "null_pct": float, "missing_column": bool}}.
        Only columns with nulls (or absent entirely) are included.
        Empty dict means fully complete.
    """
    result: dict[str, dict[str, Any]] = {}
    for col in required_cols:
        if col not in df.columns:
            result[col] = {"null_count": len(df), "null_pct": 100.0, "missing_column": True}
            continue
        null_count = int(df[col].isna().sum())
        if null_count > 0:
            result[col] = {
                "null_count": null_count,
                "null_pct": round(null_count / len(df) * 100, 2),
                "missing_column": False,
            }
    return result


def check_schema(
    df: pd.DataFrame,
    expected_schema: dict[str, str],
) -> list[str]:
    """
    Validate column dtypes against an expected schema.

    Args:
        df: Input DataFrame.
        expected_schema: Dict of {col_name: expected_dtype_prefix}.
            Use dtype prefix strings, e.g. "float64", "object", "datetime64".
            Prefix matching is used so "datetime64" matches "datetime64[ns]"
            and "datetime64[ms, Asia/Kolkata]".
            "object" and "str" are treated as equivalent — pandas 3.x
            represents string columns as "str" rather than "object".

    Returns:
        List of violation strings. Empty list means schema is valid.
    """
    # pandas 3.x uses "str" for what pandas 2.x called "object" (string columns)
    _STR_ALIASES: frozenset[str] = frozenset({"object", "str"})

    violations: list[str] = []
    for col, expected_dtype in expected_schema.items():
        if col not in df.columns:
            violations.append(f"Missing column: '{col}'")
            continue
        actual_dtype = str(df[col].dtype)
        expected_str = str(expected_dtype)
        # Accept "object" ↔ "str" interchangeably
        if expected_str in _STR_ALIASES:
            if actual_dtype not in _STR_ALIASES:
                violations.append(
                    f"Column '{col}': expected '{expected_str}', got '{actual_dtype}'"
                )
        elif not actual_dtype.startswith(expected_str):
            violations.append(
                f"Column '{col}': expected '{expected_str}', got '{actual_dtype}'"
            )
    return violations


def check_freshness(
    df: pd.DataFrame,
    date_col: str,
    max_age_days: int,
) -> bool:
    """
    Check whether the most recent date is within max_age_days of today.

    Args:
        df: Input DataFrame.
        date_col: Column containing dates or datetimes.
        max_age_days: Maximum acceptable data age in days.

    Returns:
        True if data is fresh enough, False if stale or date_col is missing.
    """
    if date_col not in df.columns or df.empty:
        return False
    most_recent = pd.to_datetime(df[date_col]).max()
    if hasattr(most_recent, "tzinfo") and most_recent.tzinfo is not None:
        most_recent = most_recent.tz_localize(None)
    age_days = (pd.Timestamp.now() - most_recent).days
    return age_days <= max_age_days


def check_duplicates(
    df: pd.DataFrame,
    key_cols: list[str],
) -> int:
    """
    Count duplicate rows on a composite key.

    Args:
        df: Input DataFrame.
        key_cols: Columns that should form a unique composite key.

    Returns:
        Number of duplicate rows (first occurrence is kept; duplicates are counted).
        0 means no duplicates.
    """
    valid_cols = [c for c in key_cols if c in df.columns]
    if not valid_cols:
        return 0
    return int(df.duplicated(subset=valid_cols, keep="first").sum())


def check_nav_anomalies(
    df: pd.DataFrame,
    value_col: str,
    group_col: str,
    z_threshold: float = Z_ANOMALY_THRESHOLD,
) -> pd.DataFrame:
    """
    Detect anomalous NAV/price values using per-group z-score.

    Args:
        df: Input DataFrame.
        value_col: Column to check (e.g., "nav", "close").
        group_col: Grouping column (e.g., "ticker", "scheme_code").
        z_threshold: Rows with |z| > this are flagged.

    Returns:
        DataFrame of flagged rows with added 'z_score' column.
        Empty DataFrame if value_col or group_col is absent.
    """
    if value_col not in df.columns or group_col not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    mean = df.groupby(group_col)[value_col].transform("mean")
    std = df.groupby(group_col)[value_col].transform("std").replace(0, np.nan)
    df["z_score"] = (df[value_col] - mean) / std

    flagged = df[df["z_score"].abs() > z_threshold].copy()
    return flagged.reset_index(drop=True)


def generate_quality_report(
    df: pd.DataFrame,
    label: str,
    required_cols: list[str],
    key_cols: list[str],
    date_col: str,
    max_age_days: int = 3,
) -> dict[str, Any]:
    """
    Run all quality checks and return a structured report dict.

    Args:
        df: Input DataFrame.
        label: Human-readable dataset name for the report.
        required_cols: Columns expected to be fully non-null.
        key_cols: Columns forming the unique composite key.
        date_col: Column containing dates (for freshness check).
        max_age_days: Maximum acceptable data age in days.

    Returns:
        Dict with keys: label, row_count, completeness, duplicate_count,
        freshness, passed. 'passed' is True only if all checks are clean.
    """
    completeness = check_completeness(df, required_cols)
    duplicate_count = check_duplicates(df, key_cols)
    fresh = check_freshness(df, date_col, max_age_days)

    passed = len(completeness) == 0 and duplicate_count == 0 and fresh

    return {
        "label": label,
        "row_count": len(df),
        "completeness": completeness,
        "duplicate_count": duplicate_count,
        "freshness": fresh,
        "passed": passed,
    }


def log_quality_report(
    report: dict[str, Any],
    log: logging.Logger = logger,
) -> None:
    """
    Log a quality report dict in human-readable format.

    Args:
        report: Output of generate_quality_report().
        log: Logger instance to write to.
    """
    status = "PASSED" if report["passed"] else "FAILED"
    log.info("-" * 60)
    log.info(f"Quality Report [{status}]: {report['label']}")
    log.info(f"  Rows            : {report['row_count']:,}")
    log.info(f"  Freshness       : {'OK' if report['freshness'] else 'STALE'}")
    log.info(f"  Duplicates      : {report['duplicate_count']}")
    if report["completeness"]:
        log.warning("  Completeness issues:")
        for col, info in report["completeness"].items():
            log.warning(f"    {col}: {info['null_count']} nulls ({info['null_pct']}%)")
    else:
        log.info("  Completeness    : OK")
    log.info("-" * 60)


# ----------------------------------------------------------------
# CLI: run a quality report on any parquet
# ----------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run data quality checks on a parquet file"
    )
    parser.add_argument("parquet_path", help="Path to the parquet file to check")
    parser.add_argument(
        "--required-cols",
        nargs="+",
        default=[],
        metavar="COL",
        help="Columns that must be non-null",
    )
    parser.add_argument(
        "--key-cols",
        nargs="+",
        default=[],
        metavar="COL",
        help="Columns forming the unique composite key",
    )
    parser.add_argument("--date-col", default="date", help="Date column name")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=3,
        help="Max acceptable data age in days (default: 3)",
    )
    args = parser.parse_args()

    path = Path(args.parquet_path)
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)

    df = pd.read_parquet(path)
    logger.info(f"Loaded {path.name}: {len(df):,} rows, {len(df.columns)} columns")

    report = generate_quality_report(
        df=df,
        label=path.name,
        required_cols=args.required_cols,
        key_cols=args.key_cols,
        date_col=args.date_col,
        max_age_days=args.max_age_days,
    )
    log_quality_report(report)

    if not report["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
