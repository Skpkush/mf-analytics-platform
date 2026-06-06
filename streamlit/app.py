"""
================================================================
Streamlit App: NAV Forecasting Dashboard
================================================================
Client-facing front-end for the Mutual Fund Analytics Platform.
Reads live from the analytics database (PostgreSQL locally /
Azure SQL in the cloud) and serves Prophet NAV forecasts with
30 / 60 / 90-day horizons and confidence-interval bands.

Run locally:
    streamlit run streamlit/app.py

Deploy (Hostinger VPS, Docker + Traefik):
    see streamlit/README.md
================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make the repo importable so we can reuse the forecasting module.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ml.forecast_nav import (  # noqa: E402
    FORECAST_HORIZONS,
    FundRef,
    generate_forecast,
    get_connection,
    list_forecastable_funds,
    load_nav_series,
)

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
HISTORY_TAIL_DAYS = 365          # actuals shown behind the forecast
INTERVAL_CHOICES = {"80%": 0.80, "90%": 0.90, "95%": 0.95}
BRAND_COLOR = "#0078D4"          # Azure blue (matches Power BI theme)
FORECAST_COLOR = "#F2C811"       # Power BI yellow
CACHE_TTL_SECONDS = 3600

# Pre-computed metrics surfaced alongside the forecast.
_METRICS_QUERY = """
    SELECT fr.cagr_1y, fr.cagr_3y, fr.cagr_5y,
           fr.std_dev_1y, fr.max_drawdown,
           fr.sharpe_ratio, fr.beta
    FROM dbo.Fact_Returns fr
    JOIN dbo.Dim_Fund df ON df.fund_key = fr.fund_key
    WHERE df.scheme_code = %s
    ORDER BY fr.date_key DESC
    LIMIT 1
"""


# ----------------------------------------------------------------
# Cached data access
# ----------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_funds() -> list[tuple[str, str, int]]:
    """Return forecastable funds as (scheme_code, fund_name, n_obs) tuples.

    FundRef is unpacked to plain tuples so Streamlit can hash/cache it.
    """
    conn = get_connection()
    try:
        funds: list[FundRef] = list_forecastable_funds(conn)
    finally:
        conn.close()
    return [(f.scheme_code, f.fund_name, f.n_obs) for f in funds]


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_nav_series(scheme_code: str) -> pd.Series:
    """Load a fund's full NAV history (cached per fund)."""
    conn = get_connection()
    try:
        return load_nav_series(conn, scheme_code)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_metrics(scheme_code: str) -> dict[str, float | None] | None:
    """Load the latest pre-computed Fact_Returns metrics for a fund."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_METRICS_QUERY, (scheme_code,))
            row = cur.fetchone()
            cols = [c[0] for c in cur.description]
    finally:
        conn.close()
    if row is None:
        return None
    return {c: (float(v) if v is not None else None) for c, v in zip(cols, row)}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Fitting Prophet model…")
def fetch_forecast(scheme_code: str, interval_width: float) -> tuple[pd.Series, pd.DataFrame]:
    """Fit Prophet and return (history, future-forecast frame), cached."""
    series = fetch_nav_series(scheme_code)
    result = generate_forecast(series, interval_width=interval_width)
    return result.history, result.forecast


# ----------------------------------------------------------------
# Chart
# ----------------------------------------------------------------
def build_chart(
    history: pd.Series,
    forecast: pd.DataFrame,
    interval_width: float,
) -> go.Figure:
    """Plot recent actuals + forecast line + confidence-interval band."""
    recent = history[history.index >= history.index.max() - pd.Timedelta(days=HISTORY_TAIL_DAYS)]

    fig = go.Figure()

    # Confidence band (upper, then lower with fill).
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat_upper"],
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat_lower"],
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(242,200,17,0.25)",
        name=f"{interval_width:.0%} confidence interval",
        hoverinfo="skip",
    ))

    # Actual history.
    fig.add_trace(go.Scatter(
        x=recent.index, y=recent.to_numpy(),
        mode="lines", line=dict(color=BRAND_COLOR, width=2), name="Actual NAV",
    ))

    # Forecast line.
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat"],
        mode="lines", line=dict(color=FORECAST_COLOR, width=2, dash="dash"),
        name="Forecast (Prophet)",
    ))

    fig.update_layout(
        height=460,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None, yaxis_title="NAV (₹)",
        hovermode="x unified",
    )
    return fig


# ----------------------------------------------------------------
# UI
# ----------------------------------------------------------------
def render() -> None:
    st.set_page_config(page_title="MF NAV Forecasting", page_icon="📈", layout="wide")
    st.title("📈 Mutual Fund NAV Forecasting")
    st.caption(
        "Prophet time-series forecasts served live from the analytics database "
        "· Mutual Fund Analytics Platform"
    )

    funds = fetch_funds()
    if not funds:
        st.error("No forecastable funds found. Has the ETL + NAV load run?")
        return

    # ---- Sidebar controls ----
    with st.sidebar:
        st.header("Controls")
        labels = [f"{name}  ({code})" for code, name, _ in funds]
        choice = st.selectbox("Fund", options=range(len(funds)), format_func=lambda i: labels[i])
        scheme_code, fund_name, n_obs = funds[choice]

        horizon = st.radio("Forecast horizon", FORECAST_HORIZONS, format_func=lambda d: f"{d} days", horizontal=True)
        ci_label = st.select_slider("Confidence interval", options=list(INTERVAL_CHOICES.keys()), value="80%")
        interval_width = INTERVAL_CHOICES[ci_label]
        st.caption(f"History: {n_obs:,} trading days")

    # ---- Forecast ----
    history, forecast = fetch_forecast(scheme_code, interval_width)
    last_nav = float(history.iloc[-1])
    last_date = history.index.max()

    horizon_date = last_date + pd.Timedelta(days=horizon)
    window = forecast[forecast["ds"] <= horizon_date]
    point = (window.iloc[-1] if not window.empty else forecast.iloc[-1])
    yhat, lo, hi = float(point["yhat"]), float(point["yhat_lower"]), float(point["yhat_upper"])
    change_pct = (yhat / last_nav - 1) * 100

    # ---- Headline metrics ----
    st.subheader(f"{fund_name}  ·  {scheme_code}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest NAV", f"₹{last_nav:,.2f}", help=f"As of {last_date.date()}")
    c2.metric(f"Forecast (+{horizon}d)", f"₹{yhat:,.2f}", f"{change_pct:+.2f}%")
    c3.metric(f"{ci_label} CI range", f"₹{lo:,.2f} – ₹{hi:,.2f}")
    c4.metric("Forecast date", f"{pd.Timestamp(point['ds']).date()}")

    # ---- Chart ----
    st.plotly_chart(build_chart(history, forecast, interval_width), use_container_width=True)

    # ---- Risk/return context ----
    metrics = fetch_metrics(scheme_code)
    if metrics:
        st.subheader("Risk & Return (pre-computed)")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("CAGR 1Y", _pct(metrics.get("cagr_1y")))
        m2.metric("Sharpe ratio", _num(metrics.get("sharpe_ratio")))
        m3.metric("Beta (vs Nifty 50)", _num(metrics.get("beta")))
        m4.metric("Max drawdown", _pct(metrics.get("max_drawdown")))

    st.caption(
        "⚠️ Forecasts are statistical projections from historical NAV, not "
        "investment advice. Past performance does not guarantee future results."
    )


def _pct(v: float | None) -> str:
    return f"{v:.2f}%" if v is not None else "—"


def _num(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "—"


if __name__ == "__main__":
    render()
