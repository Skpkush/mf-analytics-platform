"""
Unit tests for scripts/transformation/data_quality.py

Run from project root:
    pytest tests/test_data_quality.py -v
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from data_quality import (
    check_completeness,
    check_duplicates,
    check_freshness,
    check_nav_anomalies,
    check_schema,
    generate_quality_report,
    log_quality_report,
)


# ----------------------------------------------------------------
# Shared fixtures
# ----------------------------------------------------------------
@pytest.fixture
def nav_df() -> pd.DataFrame:
    """Minimal valid NAV DataFrame — two tickers, five rows each."""
    return pd.DataFrame(
        {
            "ticker": ["NIFTYBEES.NS"] * 5 + ["BANKBEES.NS"] * 5,
            "date": pd.date_range("2026-01-01", periods=5).tolist() * 2,
            "nav": [100.0, 101.0, 102.0, 103.0, 104.0, 200.0, 202.0, 198.0, 201.0, 205.0],
            "source": ["yahoo_etf"] * 10,
        }
    )


@pytest.fixture
def fresh_nav_df(nav_df: pd.DataFrame) -> pd.DataFrame:
    """nav_df with all dates shifted to be recent, preserving uniqueness per ticker."""
    df = nav_df.copy()
    # Shift the entire date series so the most recent row is yesterday.
    # This keeps each (ticker, date) pair unique while satisfying freshness checks.
    max_date = pd.to_datetime(df["date"]).max()
    shift = pd.Timestamp.now().normalize() - timedelta(days=1) - max_date
    df["date"] = pd.to_datetime(df["date"]) + shift
    return df


# ----------------------------------------------------------------
# check_completeness
# ----------------------------------------------------------------
class TestCheckCompleteness:
    def test_no_nulls_returns_empty_dict(self, nav_df: pd.DataFrame) -> None:
        result = check_completeness(nav_df, ["ticker", "date", "nav"])
        assert result == {}

    def test_detects_null_count_and_pct(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df.loc[[0, 1], "nav"] = np.nan
        result = check_completeness(df, ["nav"])
        assert "nav" in result
        assert result["nav"]["null_count"] == 2
        assert result["nav"]["null_pct"] == 20.0

    def test_missing_column_reported(self, nav_df: pd.DataFrame) -> None:
        result = check_completeness(nav_df, ["ticker", "ghost_column"])
        assert "ghost_column" in result
        assert result["ghost_column"]["missing_column"] is True
        assert result["ghost_column"]["null_count"] == len(nav_df)

    def test_partial_nulls_only_flagged_columns(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df.loc[0, "nav"] = np.nan
        result = check_completeness(df, ["ticker", "nav"])
        # ticker has no nulls — should not appear in result
        assert "ticker" not in result
        assert "nav" in result


# ----------------------------------------------------------------
# check_schema
# ----------------------------------------------------------------
class TestCheckSchema:
    def test_valid_schema_returns_empty_list(self, nav_df: pd.DataFrame) -> None:
        violations = check_schema(nav_df, {"ticker": "object", "nav": "float64"})
        assert violations == []

    def test_wrong_dtype_returns_violation(self, nav_df: pd.DataFrame) -> None:
        violations = check_schema(nav_df, {"nav": "int64"})
        assert len(violations) == 1
        assert "nav" in violations[0]

    def test_missing_column_returns_violation(self, nav_df: pd.DataFrame) -> None:
        violations = check_schema(nav_df, {"nonexistent": "object"})
        assert any("Missing" in v for v in violations)

    def test_datetime_prefix_matching(self, nav_df: pd.DataFrame) -> None:
        # "datetime64" should match "datetime64[ns]"
        violations = check_schema(nav_df, {"date": "datetime64"})
        assert violations == []


# ----------------------------------------------------------------
# check_freshness
# ----------------------------------------------------------------
class TestCheckFreshness:
    def test_recent_date_is_fresh(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df["date"] = datetime.now() - timedelta(days=1)
        assert check_freshness(df, "date", max_age_days=3) is True

    def test_old_date_is_stale(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df["date"] = datetime(2020, 1, 1)
        assert check_freshness(df, "date", max_age_days=3) is False

    def test_exactly_at_limit_is_fresh(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df["date"] = datetime.now() - timedelta(days=3)
        assert check_freshness(df, "date", max_age_days=3) is True

    def test_missing_date_col_returns_false(self, nav_df: pd.DataFrame) -> None:
        assert check_freshness(nav_df, "nonexistent_date", max_age_days=3) is False

    def test_empty_df_returns_false(self) -> None:
        df = pd.DataFrame({"date": pd.Series([], dtype="datetime64[ns]")})
        assert check_freshness(df, "date", max_age_days=3) is False


# ----------------------------------------------------------------
# check_duplicates
# ----------------------------------------------------------------
class TestCheckDuplicates:
    def test_no_duplicates_returns_zero(self, nav_df: pd.DataFrame) -> None:
        assert check_duplicates(nav_df, ["ticker", "date"]) == 0

    def test_inserted_duplicates_counted(self, nav_df: pd.DataFrame) -> None:
        df = pd.concat([nav_df, nav_df.iloc[:3]], ignore_index=True)
        assert check_duplicates(df, ["ticker", "date"]) == 3

    def test_invalid_key_cols_returns_zero(self, nav_df: pd.DataFrame) -> None:
        assert check_duplicates(nav_df, ["nonexistent_col"]) == 0

    def test_single_key_col(self, nav_df: pd.DataFrame) -> None:
        # Five rows per ticker; no dupes on ticker alone within the fixture
        # (each ticker appears 5 times — these ARE duplicates on a single-col key)
        count = check_duplicates(nav_df, ["ticker"])
        assert count == 8  # 10 rows - 2 unique tickers = 8 duplicates


# ----------------------------------------------------------------
# check_nav_anomalies
# ----------------------------------------------------------------
class TestCheckNavAnomalies:
    def test_spike_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "ticker": ["FUND"] * 100,
                "nav": [100.0] * 99 + [100_000.0],  # extreme spike
            }
        )
        flagged = check_nav_anomalies(df, value_col="nav", group_col="ticker", z_threshold=3.0)
        assert len(flagged) >= 1
        assert flagged["nav"].iloc[0] == pytest.approx(100_000.0)

    def test_clean_data_has_no_flags(self, nav_df: pd.DataFrame) -> None:
        flagged = check_nav_anomalies(nav_df, value_col="nav", group_col="ticker", z_threshold=5.0)
        assert len(flagged) == 0

    def test_missing_value_col_returns_empty(self, nav_df: pd.DataFrame) -> None:
        flagged = check_nav_anomalies(nav_df, value_col="price", group_col="ticker")
        assert flagged.empty

    def test_missing_group_col_returns_empty(self, nav_df: pd.DataFrame) -> None:
        flagged = check_nav_anomalies(nav_df, value_col="nav", group_col="fund_id")
        assert flagged.empty

    def test_z_score_column_present_in_output(self) -> None:
        df = pd.DataFrame({"ticker": ["A"] * 50, "nav": [10.0] * 49 + [10_000.0]})
        flagged = check_nav_anomalies(df, value_col="nav", group_col="ticker", z_threshold=2.0)
        assert "z_score" in flagged.columns


# ----------------------------------------------------------------
# generate_quality_report
# ----------------------------------------------------------------
class TestGenerateQualityReport:
    REQUIRED_KEYS = {"label", "row_count", "completeness", "duplicate_count", "freshness", "passed"}

    def test_report_has_all_keys(self, fresh_nav_df: pd.DataFrame) -> None:
        report = generate_quality_report(
            df=fresh_nav_df,
            label="test",
            required_cols=["ticker", "date", "nav"],
            key_cols=["ticker", "date"],
            date_col="date",
        )
        assert self.REQUIRED_KEYS == set(report.keys())

    def test_passes_on_clean_data(self, fresh_nav_df: pd.DataFrame) -> None:
        report = generate_quality_report(
            df=fresh_nav_df,
            label="clean",
            required_cols=["ticker", "date", "nav"],
            key_cols=["ticker", "date"],
            date_col="date",
        )
        assert report["passed"] is True
        assert report["row_count"] == len(fresh_nav_df)
        assert report["label"] == "clean"

    def test_fails_when_nulls_present(self, fresh_nav_df: pd.DataFrame) -> None:
        df = fresh_nav_df.copy()
        df.loc[0, "nav"] = np.nan
        report = generate_quality_report(
            df=df,
            label="dirty",
            required_cols=["ticker", "date", "nav"],
            key_cols=["ticker", "date"],
            date_col="date",
        )
        assert report["passed"] is False
        assert "nav" in report["completeness"]

    def test_fails_when_stale(self, nav_df: pd.DataFrame) -> None:
        df = nav_df.copy()
        df["date"] = datetime(2020, 1, 1)
        report = generate_quality_report(
            df=df,
            label="stale",
            required_cols=["ticker"],
            key_cols=["ticker", "date"],
            date_col="date",
            max_age_days=3,
        )
        assert report["freshness"] is False
        assert report["passed"] is False

    def test_fails_when_duplicates_present(self, fresh_nav_df: pd.DataFrame) -> None:
        df = pd.concat([fresh_nav_df, fresh_nav_df.iloc[:2]], ignore_index=True)
        report = generate_quality_report(
            df=df,
            label="dupes",
            required_cols=["ticker"],
            key_cols=["ticker", "date"],
            date_col="date",
        )
        assert report["duplicate_count"] > 0
        assert report["passed"] is False

    def test_log_quality_report_runs_without_error(
        self, fresh_nav_df: pd.DataFrame
    ) -> None:
        report = generate_quality_report(
            df=fresh_nav_df,
            label="smoke_test",
            required_cols=["ticker", "nav"],
            key_cols=["ticker", "date"],
            date_col="date",
        )
        # Should not raise
        log_quality_report(report)
