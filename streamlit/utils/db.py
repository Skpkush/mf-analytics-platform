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

import logging
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import URL, bindparam, create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger("mf.db")

CACHE_TTL = 3600  # 1 hour, per spec

# Recognised secrets section names (Streamlit Cloud style first).
_DB_SECTIONS = ("database", "postgres", "supabase")
# A secrets table is "DB-shaped" if it carries a host under any of these keys.
_HOST_KEYS = ("host", "hostname")


def _secrets_top_level_keys() -> list[str] | None:
    """Top-level keys in st.secrets, or None if there is no secrets file.

    Reading st.secrets with no secrets.toml raises — that is the *only*
    legitimate signal to fall back to .env (local dev). Anything else must
    surface, so we never blanket-swallow here.
    """
    try:
        return list(st.secrets.keys())
    except Exception:  # StreamlitSecretNotFoundError — no secrets file at all
        return None


def _extract_db_config(s: object, where: str) -> dict[str, object]:
    """Map a secrets table (or st.secrets itself, for flat keys) to db params.

    Accepts either key spelling for the db/user fields (`database`/`username`
    or `dbname`/`user`). Raises a loud, descriptive KeyError on a missing key —
    never silently degrades to localhost.
    """
    present = list(s.keys())  # type: ignore[attr-defined]
    try:
        host = s["host"] if "host" in s else s["hostname"]  # type: ignore[operator]
        return {
            "host": host,
            "port": int(s["port"]) if "port" in s else 5432,  # type: ignore[operator]
            "dbname": s["dbname"] if "dbname" in s else s["database"],  # type: ignore[index,operator]
            "user": s["user"] if "user" in s else s["username"],  # type: ignore[index,operator]
            "password": s["password"],  # type: ignore[index]
            "sslmode": s["sslmode"] if "sslmode" in s else None,  # type: ignore[index,operator]
        }
    except KeyError as exc:
        raise KeyError(
            f"Streamlit secrets {where} is missing required key {exc}. "
            f"Keys present: {present}. Expected: host(|hostname), port, "
            f"dbname|database, user|username, password."
        ) from exc


def _resolve_db_config() -> dict[str, object]:
    """Return DB connection params, reading st.secrets FIRST, env only as a
    true last resort when no secrets file exists.

    Resolution order:
      1. st.secrets[<section>]  — section ∈ {database, postgres, supabase}
      2. st.secrets flat keys   — host/port/... at the top level (no header)
      3. .env LOCAL_DB_*        — ONLY when there is no secrets file at all

    When a secrets file exists but contains no DB-shaped config, this raises a
    loud error instead of silently connecting to localhost (the bug that made
    Streamlit Cloud hit 127.0.0.1 despite secrets being set).
    """
    top_keys = _secrets_top_level_keys()

    if top_keys is not None:
        # A secrets file IS present on this host — never fall back to localhost.
        # 1) Named section.
        for section in _DB_SECTIONS:
            if section in top_keys:
                cfg = _extract_db_config(st.secrets[section], f"[{section}]")
                logger.warning("DB config source: st.secrets[%s] host=%s", section, cfg["host"])
                return cfg
        # 2) Flat top-level keys (user pasted host=... without a [database] header).
        if any(k in top_keys for k in _HOST_KEYS):
            cfg = _extract_db_config(st.secrets, "(top-level)")
            logger.warning("DB config source: st.secrets top-level host=%s", cfg["host"])
            return cfg
        # 3) Secrets exist but no DB config — fail loudly, do NOT use localhost.
        raise KeyError(
            "Streamlit secrets are present but contain no database config. "
            f"Top-level keys found: {top_keys}. Add a [database] section with "
            "host, port, dbname|database, user|username, password."
        )

    # No secrets file at all → genuine local dev. Use .env (defaults to localhost).
    cfg = {
        "host": os.getenv("LOCAL_DB_HOST", "localhost"),
        "port": int(os.getenv("LOCAL_DB_PORT", "5432")),
        "dbname": os.getenv("LOCAL_DB_NAME", "mf_analytics"),
        "user": os.getenv("LOCAL_DB_USER", "postgres"),
        "password": os.getenv("LOCAL_DB_PASSWORD", ""),
    }
    logger.warning("DB config source: .env fallback (no secrets file) host=%s", cfg["host"])
    return cfg


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
    # Supabase (and Streamlit Cloud egress) require TLS. sslmode defaults to
    # "require" but can be overridden per-section via secrets for local Postgres.
    sslmode = str(c.get("sslmode") or os.getenv("DB_SSLMODE") or "require")
    logger.warning(
        "Creating engine -> host=%s port=%s db=%s user=%s sslmode=%s",
        c["host"], c["port"], c["dbname"], c["user"], sslmode,
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"sslmode": sslmode},
    )


def last_connection_error() -> str | None:
    """Run a trivial query and return None on success, or the error string.

    Unlike check_connection(), this preserves the underlying driver message so
    the UI/logs can show the real reason (SSL, host unreachable, auth, missing
    secret key) instead of a generic "cannot reach database".
    """
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # SQLAlchemyError + KeyError from _resolve_db_config
        # str(exc) on a DBAPIError already includes the psycopg2 diagnostic.
        return f"{type(exc).__name__}: {exc}"


def check_connection() -> bool:
    """Return True if the database answers a trivial query."""
    return last_connection_error() is None


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
