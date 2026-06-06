"""
NAV Forecast — Prophet 30/60/90-day projections with confidence bands.
Reuses scripts/ml/forecast_nav.generate_forecast (already tested) and
only feeds it a NAV series loaded via utils/db.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import charts, db  # noqa: E402
from utils.metrics import NAVY  # noqa: E402
from scripts.ml.forecast_nav import (  # noqa: E402
    FORECAST_HORIZONS,
    MIN_HISTORY_DAYS,
    generate_forecast,
)

st.set_page_config(page_title="NAV Forecast", page_icon="📈", layout="wide")
INTERVAL_CHOICES = {"80%": 0.80, "90%": 0.90, "95%": 0.95}


@st.cache_data(ttl=3600, show_spinner="Fitting Prophet model…")
def _forecast(scheme_code: str, interval_width: float):
    """Cache a Prophet fit per (fund, CI). Returns (history, forecast_df)."""
    series = db.get_nav_series(scheme_code)
    if len(series) < MIN_HISTORY_DAYS:
        return None
    res = generate_forecast(series, interval_width=interval_width)
    return res.history, res.forecast


def main() -> None:
    st.markdown(f"<h1 style='color:{NAVY}'>📈 NAV Forecast</h1>", unsafe_allow_html=True)
    st.caption("Prophet time-series projections. Forecasts are statistical, **not** advice.")

    if not db.check_connection():
        st.error("⚠️ Database unreachable — check `.streamlit/secrets.toml` / `.env`.")
        st.stop()

    funds = db.get_forecastable_funds()
    if funds.empty:
        st.warning("No funds have enough NAV history to forecast.")
        st.stop()

    codes = funds["scheme_code"].tolist()
    labels = {r.scheme_code: f"{r.fund_name} ({r.scheme_code})" for r in funds.itertuples()}

    c1, c2, c3 = st.columns([2, 1, 1])
    code = c1.selectbox("Fund", codes, format_func=lambda c: labels[c])
    horizon = c2.radio("Horizon", FORECAST_HORIZONS, format_func=lambda d: f"{d} days", horizontal=True)
    ci_label = c3.select_slider("Confidence", list(INTERVAL_CHOICES.keys()), value="80%")
    interval_width = INTERVAL_CHOICES[ci_label]

    result = _forecast(code, interval_width)
    if result is None:
        st.warning(
            f"⚠️ Insufficient history (< {MIN_HISTORY_DAYS} observations) to forecast "
            "this fund reliably.",
            icon="⚠️",
        )
        st.stop()
    history, forecast = result

    last_nav = float(history.iloc[-1])
    last_date = history.index.max()
    horizon_date = last_date + pd.Timedelta(days=horizon)
    window = forecast[forecast["ds"] <= horizon_date]
    point = window.iloc[-1] if not window.empty else forecast.iloc[-1]
    yhat, lo, hi = float(point["yhat"]), float(point["yhat_lower"]), float(point["yhat_upper"])
    change = (yhat / last_nav - 1) * 100

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Latest NAV", f"₹{last_nav:,.2f}", help=f"As of {last_date.date()}")
    k2.metric(f"Forecast (+{horizon}d)", f"₹{yhat:,.2f}", f"{change:+.2f}%")
    k3.metric(f"{ci_label} interval", f"₹{lo:,.2f} – ₹{hi:,.2f}")
    k4.metric("Forecast date", str(pd.Timestamp(point["ds"]).date()))

    st.plotly_chart(
        charts.forecast_chart(history, forecast, interval_width),
        width="stretch",
    )

    exp = forecast.copy()
    exp.insert(0, "scheme_code", code)
    st.download_button(
        "⬇️ Download forecast (CSV)",
        exp.to_csv(index=False).encode("utf-8"),
        file_name=f"forecast_{code.replace('.', '_')}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
