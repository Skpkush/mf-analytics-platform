"""
Pure computation helpers for fn_compute_daily_metrics.
No Azure Functions dependency — importable for local testing.

Metrics match exactly the algorithms in scripts/analytics/:
  metrics_returns.py, metrics_risk.py, metrics_market.py,
  metrics_risk_adjusted.py
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyodbc
from scipy.stats import linregress

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ── Constants (must match analytics scripts exactly) ──────────────────────────
BENCHMARK_CODE = "^NSEI"
RISK_FREE_ANNUAL = 0.065        # 6.5% RBI repo rate
TRADING_DAYS = 252              # NSE/BSE annual trading days
TRAILING_WINDOW_DAYS = 365      # calendar days for 1-year trailing window
MIN_TRADING_DAYS: dict[int, int] = {1: 200, 3: 550, 5: 1_000}
MAX_DATE_GAP_DAYS = 30
MIN_DAYS_STD_DEV = 50
MIN_OBS_SHARPE = 50
MIN_REGRESSION_DAYS = 100

_BATCH = 2_000


# ── DB helpers ────────────────────────────────────────────────────────────────

def _v(val: object) -> object:
    """Convert pandas/numpy value to pyodbc-safe Python native type."""
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    if isinstance(val, (np.bool_,)) or isinstance(val, bool):
        return int(val)
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return None if np.isnan(val) else float(val)
    if isinstance(val, pd.Timestamp):
        return val.date()
    return val


def _bulk(cur: pyodbc.Cursor, sql: str, records: list[tuple]) -> None:
    cur.fast_executemany = True
    for i in range(0, len(records), _BATCH):
        cur.executemany(sql, records[i: i + _BATCH])
    cur.fast_executemany = False


# ── NAV loader ────────────────────────────────────────────────────────────────

def load_nav_ts(conn: pyodbc.Connection) -> dict[int, tuple[str, pd.Series]]:
    """Load Yahoo ETF + benchmark NAV time series from Fact_NAV."""
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
        s = pd.Series(d["navs"], index=pd.DatetimeIndex(d["dates"]),
                      dtype=float, name=d["sc"]).sort_index()
        result[fk] = (d["sc"], s)
    log.info(f"NAV time series: {len(result)} funds, {len(rows):,} rows")
    return result


def load_existing_metrics(conn: pyodbc.Connection) -> dict[str, dict]:
    """Load existing Fact_Returns rows for use in market/risk-adjusted metrics."""
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


# ── Metrics: Returns / CAGR ───────────────────────────────────────────────────

def _find_nav_n_years_ago(series: pd.Series, as_of: pd.Timestamp, years: int) -> float | None:
    target = as_of - pd.DateOffset(years=years)
    before = series[series.index <= target]
    if not before.empty:
        if int((target - before.index[-1]).days) <= MAX_DATE_GAP_DAYS:
            return float(before.iloc[-1])
    after = series[
        (series.index > target)
        & (series.index <= target + pd.Timedelta(days=MAX_DATE_GAP_DAYS))
    ]
    if not after.empty:
        return float(after.iloc[0])
    return None


def compute_returns(
    series: pd.Series,
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, dict[str, float | None]]:
    effective_as_of = as_of if as_of is not None else series.index.max()
    available = series[series.index <= effective_as_of]
    keys = ("return_1y", "return_3y", "return_5y", "cagr_1y", "cagr_3y", "cagr_5y")
    if available.empty:
        return effective_as_of, {k: None for k in keys}
    n_days = len(available)
    nav_latest = float(available.iloc[-1])
    metrics: dict[str, float | None] = {}
    for years in (1, 3, 5):
        ret_col, cagr_col = f"return_{years}y", f"cagr_{years}y"
        if n_days < MIN_TRADING_DAYS[years]:
            metrics[ret_col] = metrics[cagr_col] = None
            continue
        nav_start = _find_nav_n_years_ago(series, effective_as_of, years)
        if nav_start is None or nav_start <= 0:
            metrics[ret_col] = metrics[cagr_col] = None
            continue
        metrics[ret_col]  = round((nav_latest / nav_start - 1) * 100, 4)
        metrics[cagr_col] = round(((nav_latest / nav_start) ** (1.0 / years) - 1) * 100, 4)
    return effective_as_of, metrics


# ── Metrics: Risk ─────────────────────────────────────────────────────────────

def compute_risk(
    series: pd.Series,
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, dict[str, float | None]]:
    effective_as_of = as_of if as_of is not None else series.index.max()
    window_start = effective_as_of - pd.Timedelta(days=TRAILING_WINDOW_DAYS)
    trailing = series[(series.index > window_start) & (series.index <= effective_as_of)]
    daily_rets = trailing.pct_change().dropna()

    std_dev_1y: float | None = None
    if len(daily_rets) >= MIN_DAYS_STD_DEV:
        std_dev_1y = round(float(daily_rets.std() * np.sqrt(TRADING_DAYS) * 100), 4)

    available = series[series.index <= effective_as_of]
    max_drawdown: float | None = None
    if len(available) >= 2:
        cum_ret = (1 + available.pct_change().fillna(0)).cumprod()
        rolling_peak = cum_ret.expanding().max()
        dd_series = (cum_ret - rolling_peak) / rolling_peak
        max_drawdown = round(float(dd_series.min() * 100), 4)

    return effective_as_of, {"std_dev_1y": std_dev_1y, "max_drawdown": max_drawdown}


# ── Metrics: Beta & Alpha ─────────────────────────────────────────────────────

def compute_beta(fund_series: pd.Series, bench_series: pd.Series) -> float | None:
    combined = pd.concat(
        [fund_series.pct_change(), bench_series.pct_change()], axis=1
    ).dropna()
    if len(combined) < MIN_REGRESSION_DAYS:
        return None
    slope, *_ = linregress(combined.iloc[:, 1], combined.iloc[:, 0])
    return round(float(slope), 4)


def compute_alpha(
    cagr_1y: float | None, cagr_3y: float | None, cagr_5y: float | None,
    bench_cagr_1y: float | None, bench_cagr_3y: float | None, bench_cagr_5y: float | None,
    beta: float | None,
) -> float | None:
    if beta is None:
        return None
    for fund_c, bench_c in [
        (cagr_5y, bench_cagr_5y), (cagr_3y, bench_cagr_3y), (cagr_1y, bench_cagr_1y)
    ]:
        if fund_c is not None and bench_c is not None:
            alpha = (fund_c / 100) - (
                RISK_FREE_ANNUAL + beta * ((bench_c / 100) - RISK_FREE_ANNUAL)
            )
            return round(alpha * 100, 4)
    return None


# ── Metrics: Risk-Adjusted (Sharpe / Sortino / Treynor) ──────────────────────

def compute_risk_adjusted(
    series: pd.Series,
    cagr_1y: float | None,
    beta: float | None,
) -> dict[str, float | None]:
    as_of = series.index.max()
    window_start = as_of - pd.Timedelta(days=TRAILING_WINDOW_DAYS)
    trailing = series[(series.index > window_start) & (series.index <= as_of)]
    daily_rets = trailing.pct_change().dropna()

    if len(daily_rets) < MIN_OBS_SHARPE:
        return {"sharpe_ratio": None, "sortino_ratio": None, "treynor_ratio": None}

    daily_rf = RISK_FREE_ANNUAL / TRADING_DAYS
    excess = daily_rets - daily_rf
    mean_excess = float(excess.mean())
    std_excess = float(excess.std())

    sharpe = round(mean_excess / std_excess * np.sqrt(TRADING_DAYS), 4) if std_excess != 0 else None

    downside = excess[excess < 0]
    if len(downside) >= 2:
        dd_dev = float(np.sqrt((downside ** 2).mean())) * np.sqrt(TRADING_DAYS)
        sortino = round(mean_excess * TRADING_DAYS / dd_dev, 4) if dd_dev != 0 else None
    else:
        sortino = None

    if cagr_1y is not None and beta is not None and beta != 0:
        treynor = round((cagr_1y - RISK_FREE_ANNUAL * 100) / beta, 4)
    else:
        treynor = None

    return {"sharpe_ratio": sharpe, "sortino_ratio": sortino, "treynor_ratio": treynor}


# ── Fact_SIP refresh ──────────────────────────────────────────────────────────

def refresh_fact_sip(conn: pyodbc.Connection) -> int:
    """
    Re-derive Fact_SIP from Fact_Transactions (TRUNCATE + re-insert).

    Reads Fact_Transactions directly from Azure SQL (already loaded by ADF),
    derives monthly SIP aggregates + cumulative columns, and refreshes
    Fact_SIP. Safe to run daily — idempotent via TRUNCATE.

    Returns number of rows inserted.
    """
    log.info("Fact_SIP: loading Fact_Transactions from Azure SQL...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ft.investor_key, ft.fund_key,
                   CONVERT(VARCHAR(10), dd.full_date, 23) AS txn_date,
                   ft.transaction_type, ft.amount, ft.units
            FROM dbo.Fact_Transactions ft
            JOIN dbo.Dim_Date dd ON dd.date_key = ft.date_key
        """)
        rows = cur.fetchall()

    if not rows:
        log.warning("Fact_Transactions is empty — Fact_SIP refresh skipped")
        return 0

    txn = pd.DataFrame(rows, columns=[
        "investor_key", "fund_key", "txn_date",
        "transaction_type", "amount", "units",
    ])
    log.info(f"Fact_Transactions: {len(txn):,} rows loaded")

    txn["month_start"] = pd.to_datetime(txn["txn_date"]).dt.to_period("M").dt.to_timestamp()
    txn["month_str"] = txn["month_start"].dt.date.astype(str)

    # Monthly SIP aggregation
    sip = (
        txn[txn["transaction_type"] == "SIP"]
        .groupby(["investor_key", "fund_key", "month_start", "month_str"])
        .agg(monthly_sip_amount=("amount", "sum"), units_purchased=("units", "sum"))
        .reset_index()
    )
    # Monthly redemptions
    red = (
        txn[txn["transaction_type"] == "Redemption"]
        .groupby(["investor_key", "fund_key", "month_start"])
        .agg(units_redeemed=("units", "sum"))
        .reset_index()
    )
    sip = sip.merge(red, on=["investor_key", "fund_key", "month_start"], how="left")
    sip["units_redeemed"] = sip["units_redeemed"].fillna(0.0)

    # Cumulative columns per investor-fund timeline
    sip = sip.sort_values(["investor_key", "fund_key", "month_start"])
    grp = sip.groupby(["investor_key", "fund_key"])
    sip["cumulative_invested"]  = grp["monthly_sip_amount"].cumsum()
    sip["cum_units_purchased"]  = grp["units_purchased"].cumsum()
    sip["cum_units_redeemed"]   = grp["units_redeemed"].cumsum()
    sip["current_units_held"]   = (
        sip["cum_units_purchased"] - sip["cum_units_redeemed"]
    ).clip(lower=0)

    # Map month_start → date_key
    with conn.cursor() as cur:
        cur.execute("SELECT CONVERT(VARCHAR(10), full_date, 23), date_key FROM dbo.Dim_Date")
        date_map = {r[0]: r[1] for r in cur.fetchall()}
    sip["date_key"] = sip["month_str"].map(date_map)
    dropped = int(sip["date_key"].isna().sum())
    if dropped:
        log.warning(f"Fact_SIP: {dropped} rows dropped — month not in Dim_Date")
    sip = sip.dropna(subset=["date_key"])
    sip["date_key"] = sip["date_key"].astype(int)

    # TRUNCATE + bulk INSERT (idempotent)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE dbo.Fact_SIP")
    conn.commit()

    cols = [
        "date_key", "fund_key", "investor_key",
        "monthly_sip_amount", "cumulative_invested",
        "units_purchased", "current_units_held",
    ]
    records = [
        tuple(_v(x) for x in row)
        for row in sip[cols].itertuples(index=False)
    ]
    insert_sql = """INSERT INTO dbo.Fact_SIP
        (date_key, fund_key, investor_key,
         monthly_sip_amount, cumulative_invested,
         units_purchased, current_units_held)
        VALUES (?,?,?,?,?,?,?)"""
    with conn.cursor() as cur:
        _bulk(cur, insert_sql, records)
    conn.commit()
    log.info(f"Fact_SIP: {len(records):,} rows inserted")
    return len(records)


# ── Fact_Returns refresh ──────────────────────────────────────────────────────

def _dk(ts: pd.Timestamp) -> int:
    return ts.year * 10_000 + ts.month * 100 + ts.day


def refresh_fact_returns(conn: pyodbc.Connection) -> dict[str, int]:
    """
    Delete and recompute all Fact_Returns rows from current Fact_NAV data.

    Runs four metric passes in order (matches run_azure_etl.py exactly):
      1. Returns / CAGR      — DELETE + INSERT 16 rows
      2. Risk                — UPDATE std_dev_1y, max_drawdown
      3. Market (Beta/Alpha) — UPDATE beta, alpha
      4. Risk-adjusted       — UPDATE sharpe, sortino, treynor

    Returns dict with row counts for each pass.
    """
    counts: dict[str, int] = {}
    nav_data = load_nav_ts(conn)

    # ── Pass 1: returns / CAGR ────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute("DELETE FROM dbo.Fact_Returns")
    conn.commit()
    log.info("Fact_Returns: cleared (DELETE)")

    fk_ret: dict[int, tuple[pd.Timestamp, dict]] = {}
    sc_ret: dict[str, tuple[pd.Timestamp, dict]] = {}
    for fk, (sc, series) in nav_data.items():
        as_of, m = compute_returns(series)
        fk_ret[fk] = (as_of, m)
        sc_ret[sc]  = (as_of, m)

    ret_records = [
        (_dk(as_of), fk,
         m.get("return_1y"), m.get("return_3y"), m.get("return_5y"),
         m.get("cagr_1y"),   m.get("cagr_3y"),   m.get("cagr_5y"))
        for fk, (as_of, m) in fk_ret.items()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dbo.Fact_Returns "
            "(date_key, fund_key, return_1y, return_3y, return_5y, cagr_1y, cagr_3y, cagr_5y) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ret_records,
        )
    conn.commit()
    counts["returns_rows"] = len(ret_records)
    log.info(f"Fact_Returns: {len(ret_records)} rows inserted (returns/CAGR)")

    # Validate NIFTYBEES 5Y CAGR
    nifty = sc_ret.get("NIFTYBEES.NS")
    if nifty:
        c5y = nifty[1].get("cagr_5y")
        if c5y is not None:
            status = "PASSED" if 8.0 <= c5y <= 14.0 else "WARNING"
            log.info(f"Validation {status}: NIFTYBEES.NS cagr_5y = {c5y:.2f}%")

    # ── Pass 2: risk metrics ──────────────────────────────────────────────────
    fk_risk: dict[int, tuple[pd.Timestamp, dict]] = {}
    for fk, (sc, series) in nav_data.items():
        as_of, m = compute_risk(series)
        fk_risk[fk] = (as_of, m)

    risk_records = [
        (m.get("std_dev_1y"), m.get("max_drawdown"), fk, _dk(as_of))
        for fk, (as_of, m) in fk_risk.items()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE dbo.Fact_Returns SET std_dev_1y=?, max_drawdown=? "
            "WHERE fund_key=? AND date_key=?",
            risk_records,
        )
    conn.commit()
    counts["risk_updates"] = len(risk_records)
    log.info(f"Fact_Returns: {len(risk_records)} rows updated (risk metrics)")

    # ── Pass 3: beta / alpha ──────────────────────────────────────────────────
    existing = load_existing_metrics(conn)
    bench_row = existing.get(BENCHMARK_CODE, {})
    bench_series: pd.Series | None = None
    for _, (sc, s) in nav_data.items():
        if sc == BENCHMARK_CODE:
            bench_series = s
            break

    market_records: list[tuple] = []
    if bench_series is not None and bench_row:
        for fk, (sc, series) in nav_data.items():
            if sc not in existing:
                continue
            row  = existing[sc]
            beta = compute_beta(series, bench_series)
            alpha = compute_alpha(
                row["cagr_1y"], row["cagr_3y"], row["cagr_5y"],
                bench_row.get("cagr_1y"), bench_row.get("cagr_3y"), bench_row.get("cagr_5y"),
                beta,
            )
            market_records.append((beta, alpha, fk, row["date_key"]))
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE dbo.Fact_Returns SET beta=?, alpha=? WHERE fund_key=? AND date_key=?",
                market_records,
            )
        conn.commit()
    counts["market_updates"] = len(market_records)
    log.info(f"Fact_Returns: {len(market_records)} rows updated (beta/alpha)")

    # ── Pass 4: Sharpe / Sortino / Treynor ───────────────────────────────────
    existing = load_existing_metrics(conn)
    ra_records: list[tuple] = []
    for fk, (sc, series) in nav_data.items():
        if sc not in existing:
            continue
        row = existing[sc]
        m   = compute_risk_adjusted(series, row["cagr_1y"], row["beta"])
        ra_records.append((
            m.get("sharpe_ratio"), m.get("sortino_ratio"), m.get("treynor_ratio"),
            fk, row["date_key"],
        ))
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE dbo.Fact_Returns "
            "SET sharpe_ratio=?, sortino_ratio=?, treynor_ratio=? "
            "WHERE fund_key=? AND date_key=?",
            ra_records,
        )
    conn.commit()
    counts["risk_adj_updates"] = len(ra_records)
    log.info(f"Fact_Returns: {len(ra_records)} rows updated (Sharpe/Sortino/Treynor)")

    return counts
