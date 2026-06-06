"""
================================================================
Database access layer (SQLAlchemy + PostgreSQL)
================================================================
Central data layer for the Streamlit app. All queries are cached
with st.cache_data (TTL 1h) and read through a single pooled
SQLAlchemy engine (st.cache_resource).

Credentials resolve in this order:
    1. st.secrets["postgres"]   (deployment — .streamlit/secrets.toml)
    2. .env  LOCAL_DB_*          (local dev — falls back automatically)

This is why the same code runs locally and on the VPS unchanged.

Data-reality note: only 16 funds (11 Yahoo ETFs + 5 benchmarks)
carry a NAV time series and computed metrics. The other ~14k
AMFI funds are a single NAV snapshot — query helpers below expose
both universes explicitly so pages can degrade gracefully.
================================================================
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import URL, bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

CACHE_TTL = 3600  # 1 hour, per spec


# ----------------------------------------------------------------
# Engine / configuration
# ----------------------------------------------------------------
def _resolve_db_config() -> dict[str, object]:
    """Return DB connection params from st.secrets, falling back to env."""
    try:
        s = st.secrets["postgres"]  # raises if no secrets file / section
        return {
            "host": s["host"],
            "port": int(s["port"]),
            "dbname": s["dbname"],
            "user": s["user"],
            "password": s["password"],
        }
    except Exception:
        return {
            "host": os.getenv("LOCAL_DB_HOST", "localhost"),
            "port": int(os.getenv("LOCAL_DB_PORT", "5432")),
            "dbname": os.getenv("LOCAL_DB_NAME", "mf_analytics"),
            "user": os.getenv("LOCAL_DB_USER", "postgres"),
            "password": os.getenv("LOCAL_DB_PASSWORD", ""),
        }


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    """Create a pooled SQLAlchemy engine (shared across reruns/sessions)."""
    c = _resolve_db_config()
    # URL.create escapes special characters in user/password (e.g. @, #, /)
    # that would otherwise corrupt a hand-built connection string.
    url = URL.create(
        "postgresql+psycopg2",
        username=str(c["user"]),
        password=str(c["password"]),
        host=str(c["host"]),
        port=int(c["port"]),
        database=str(c["dbname"]),
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


def check_connection() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def _read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute a SELECT and return a DataFrame. Raises on DB error."""
    return pd.read_sql(text(sql), get_engine(), params=params or {})


# ----------------------------------------------------------------
# Home KPIs
# ----------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_kpis() -> dict[str, object]:
    """Headline numbers for the home dashboard."""
    sql = """
        SELECT
            (SELECT COUNT(*) FROM dbo.dim_fund WHERE is_active)            AS total_funds,
            (SELECT COUNT(*) FROM dbo.dim_amc)                             AS total_amcs,
            (SELECT COUNT(*) FROM dbo.dim_category)                        AS total_categories,
            (SELECT COUNT(*) FROM dbo.fact_nav)                            AS total_nav_rows,
            (SELECT COUNT(*) FROM dbo.fact_returns WHERE sharpe_ratio IS NOT NULL)
                                                                          AS funds_with_metrics,
            (SELECT MAX(dd.full_date)
               FROM dbo.fact_nav fn
               JOIN dbo.dim_date dd ON dd.date_key = fn.date_key)         AS latest_nav_date
    """
    return _read_sql(sql).iloc[0].to_dict()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_top_performer() -> dict[str, object] | None:
    """Best fund by 1Y CAGR (from the metric-bearing universe)."""
    df = _read_sql("""
        SELECT fund_name, scheme_code, amc_short_name, asset_class, cagr_1y
        FROM dbo.vw_fund_performance
        WHERE cagr_1y IS NOT NULL
        ORDER BY cagr_1y DESC
        LIMIT 1
    """)
    return None if df.empty else df.iloc[0].to_dict()


# ----------------------------------------------------------------
# Fund Explorer
# ----------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading fund directory…")
def get_fund_directory() -> pd.DataFrame:
    """All active funds + latest NAV + observation count (full ~14k universe).

    `n_obs > 1` flags the 16 funds that have a real time series; everything
    else is a single AMFI snapshot. One pass over Fact_NAV via DISTINCT ON.
    """
    sql = """
        SELECT
            df.scheme_code,
            df.fund_name,
            df.base_fund_name,
            df.plan_type,
            df.option_type,
            df.source,
            df.is_benchmark,
            COALESCE(da.amc_short_name,
                     CASE WHEN df.is_benchmark THEN 'Index' END) AS amc,
            dc.asset_class,
            dc.sub_category,
            agg.latest_nav,
            ddl.full_date AS latest_nav_date,
            COALESCE(agg.n_obs, 0) AS n_obs
        FROM dbo.dim_fund df
        LEFT JOIN dbo.dim_amc      da ON da.amc_key      = df.amc_key
        LEFT JOIN dbo.dim_category dc ON dc.category_key = df.category_key
        LEFT JOIN (
            SELECT DISTINCT ON (fund_key)
                   fund_key,
                   nav AS latest_nav,
                   date_key,
                   COUNT(*) OVER (PARTITION BY fund_key) AS n_obs
            FROM dbo.fact_nav
            ORDER BY fund_key, date_key DESC
        ) agg ON agg.fund_key = df.fund_key
        LEFT JOIN dbo.dim_date ddl ON ddl.date_key = agg.date_key
        WHERE df.is_active
        ORDER BY df.fund_name
    """
    return _read_sql(sql)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_fund_performance() -> pd.DataFrame:
    """Full performance + risk metrics for the 16 metric-bearing funds."""
    return _read_sql("SELECT * FROM dbo.vw_fund_performance ORDER BY fund_name")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_risk_summary() -> pd.DataFrame:
    """Risk metrics + risk_tier for the 16 metric-bearing funds."""
    return _read_sql("SELECT * FROM dbo.vw_risk_summary ORDER BY fund_name")


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading NAV history…")
def get_nav_history(scheme_code: str) -> pd.DataFrame:
    """Daily NAV history for one fund (date, nav). Empty for snapshot-only funds."""
    sql = """
        SELECT dd.full_date AS date, fn.nav
        FROM dbo.fact_nav fn
        JOIN dbo.dim_date dd ON dd.date_key = fn.date_key
        JOIN dbo.dim_fund df ON df.fund_key = fn.fund_key
        WHERE df.scheme_code = :code
        ORDER BY dd.full_date
    """
    df = _read_sql(sql, {"code": scheme_code})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["nav"] = df["nav"].astype(float)
    return df


def get_nav_series(scheme_code: str) -> pd.Series:
    """NAV history as a pd.Series (DatetimeIndex) — feeds Prophet."""
    df = get_nav_history(scheme_code)
    if df.empty:
        return pd.Series(dtype=float, name=scheme_code)
    return pd.Series(df["nav"].to_numpy(), index=pd.DatetimeIndex(df["date"]), name=scheme_code)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_forecastable_funds() -> pd.DataFrame:
    """Funds with a usable NAV time series (>= 200 obs), for forecasting."""
    sql = """
        SELECT df.scheme_code, df.fund_name, COUNT(*) AS n_obs
        FROM dbo.fact_nav fn
        JOIN dbo.dim_fund df ON df.fund_key = fn.fund_key
        WHERE fn.source IN ('yahoo_etf', 'yahoo_benchmark')
        GROUP BY df.scheme_code, df.fund_name
        HAVING COUNT(*) >= 200
        ORDER BY df.fund_name
    """
    return _read_sql(sql)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading aligned price history…")
def get_price_matrix(scheme_codes: tuple[str, ...]) -> pd.DataFrame:
    """Wide NAV matrix (index=date, columns=scheme_code) for given funds.

    Inner-aligned on common dates — used by the Portfolio Analyzer for
    covariance / correlation / efficient-frontier math.
    """
    if not scheme_codes:
        return pd.DataFrame()
    sql = """
        SELECT df.scheme_code, dd.full_date AS date, fn.nav
        FROM dbo.fact_nav fn
        JOIN dbo.dim_date dd ON dd.date_key = fn.date_key
        JOIN dbo.dim_fund df ON df.fund_key = fn.fund_key
        WHERE df.scheme_code IN :codes
        ORDER BY dd.full_date
    """
    # Expanding bind so IN (:codes) accepts a Python list.
    stmt = text(sql).bindparams(bindparam("codes", expanding=True))
    df = pd.read_sql(stmt, get_engine(), params={"codes": list(scheme_codes)})
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot(index="date", columns="scheme_code", values="nav").astype(float)
    wide.index = pd.to_datetime(wide.index)
    return wide.dropna()
