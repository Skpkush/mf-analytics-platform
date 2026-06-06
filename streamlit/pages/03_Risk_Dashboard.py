"""
Risk Dashboard — risk-return scatter, Sharpe heatmap (asset_class × fund),
drawdown ranking and beta ladder. Scoped to the 16 funds with full NAV
history (the only funds with computed risk metrics), clearly labelled.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import charts, db  # noqa: E402
from utils.metrics import NAVY  # noqa: E402

st.set_page_config(page_title="Risk Dashboard", page_icon="⚠️", layout="wide")


def main() -> None:
    st.markdown(f"<h1 style='color:{NAVY}'>⚠️ Risk Dashboard</h1>", unsafe_allow_html=True)

    if not db.check_connection():
        st.error("⚠️ Database unreachable — check `.streamlit/secrets.toml` / `.env`.")
        st.stop()

    perf = db.get_fund_performance()
    if perf.empty:
        st.warning("No computed risk metrics available.")
        st.stop()

    st.info(
        f"Scope: **{perf['scheme_code'].nunique()} funds** with full NAV history "
        "(Yahoo ETFs + benchmarks). AMFI funds have no time series, so no risk metrics. "
        "Heatmap is asset-class × fund (the metric-bearing funds carry no AMC).",
        icon="ℹ️",
    )

    # ---- Asset-class filter ----
    classes = sorted(perf["asset_class"].dropna().unique().tolist())
    picked = st.multiselect("Filter asset classes", classes, default=classes)
    view = perf[perf["asset_class"].isin(picked)] if picked else perf
    if view.empty:
        st.info("No funds for the selected asset classes.")
        st.stop()

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.risk_return_scatter(view), width="stretch")
    with c2:
        st.plotly_chart(charts.sharpe_heatmap(view), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(charts.drawdown_bar(view), width="stretch")
    with c4:
        st.plotly_chart(charts.beta_ladder(view), width="stretch")

    st.markdown("#### Risk table")
    cols = ["fund_name", "scheme_code", "asset_class", "cagr_1y", "std_dev_1y",
            "sharpe_ratio", "sortino_ratio", "beta", "alpha", "max_drawdown"]
    table = view[[c for c in cols if c in view.columns]].sort_values("sharpe_ratio", ascending=False)
    st.dataframe(table, width="stretch", hide_index=True)

    st.download_button(
        "⬇️ Download risk data (CSV)",
        table.to_csv(index=False).encode("utf-8"),
        file_name="risk_dashboard.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
