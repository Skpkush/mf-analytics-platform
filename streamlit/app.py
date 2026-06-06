"""
================================================================
Mutual Fund Analytics Platform — Streamlit (Home)
================================================================
Multi-page app entrypoint. Streamlit auto-discovers pages/ ;
this file is the landing dashboard: headline KPIs, today's top
performer, data-freshness indicator, and navigation.

Run:   streamlit run streamlit/app.py
Pages: pages/01_Fund_Explorer … 05_Portfolio_Analyzer
================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make repo + utils importable regardless of launch CWD.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import db  # noqa: E402
from utils.metrics import NAVY, rag_emoji  # noqa: E402

st.set_page_config(
    page_title="MF Analytics Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _kpi_card(col, label: str, value: str, help_text: str = "") -> None:
    col.metric(label, value, help=help_text or None)


def main() -> None:
    st.markdown(
        f"<h1 style='color:{NAVY};margin-bottom:0'>📊 Mutual Fund Analytics Platform</h1>"
        "<p style='color:#5a6473;margin-top:4px'>End-to-end fund intelligence — "
        "performance, forecasting, risk, SIP planning and portfolio construction.</p>",
        unsafe_allow_html=True,
    )

    # ---- Graceful DB-down fallback ----
    if not db.check_connection():
        st.error(
            "⚠️ Cannot reach the analytics database. "
            "Check the connection settings (`.streamlit/secrets.toml` or `.env`). "
            "The app stays up; data will load once the DB is reachable."
        )
        st.stop()

    try:
        kpis = db.get_kpis()
        top = db.get_top_performer()
    except Exception as exc:  # pragma: no cover - defensive UI guard
        st.error(f"Failed to load dashboard data: {exc}")
        st.stop()

    # ---- KPI row ----
    st.subheader("Platform at a glance")
    c1, c2, c3, c4, c5 = st.columns(5)
    _kpi_card(c1, "Total funds", f"{int(kpis['total_funds']):,}")
    _kpi_card(c2, "AMCs covered", f"{int(kpis['total_amcs']):,}")
    _kpi_card(c3, "Categories", f"{int(kpis['total_categories']):,}")
    _kpi_card(c4, "NAV rows", f"{int(kpis['total_nav_rows']):,}")
    _kpi_card(
        c5, "Funds w/ full metrics", f"{int(kpis['funds_with_metrics']):,}",
        "Only these have a NAV time series → CAGR/Sharpe/forecast. The rest "
        "are single AMFI snapshots.",
    )

    st.divider()

    # ---- Top performer + freshness ----
    left, right = st.columns([2, 1])
    with left:
        st.subheader("🏆 Top performer (1Y CAGR)")
        if top:
            badge = rag_emoji(top.get("cagr_1y"), "cagr")
            st.markdown(
                f"### {badge} {top['fund_name']}\n"
                f"**{top['cagr_1y']:.2f}%** 1Y CAGR · {top['asset_class']} · "
                f"`{top['scheme_code']}`"
            )
        else:
            st.info("No computed performance metrics available yet.")
    with right:
        st.subheader("🕒 Data freshness")
        latest = kpis.get("latest_nav_date")
        st.metric("Latest NAV date", str(latest) if latest else "—")
        st.caption("Metrics cached for 1 hour (`st.cache_data`).")

    st.divider()

    # ---- Navigation guide ----
    st.subheader("Explore")
    n1, n2, n3 = st.columns(3)
    n1.markdown(
        "**🔎 Fund Explorer**\nSearch any of the 14k+ funds, metric cards, "
        "5Y NAV, peer ranking.\n\n"
        "**📈 NAV Forecast**\nProphet 30/60/90-day projections with confidence bands."
    )
    n2.markdown(
        "**⚠️ Risk Dashboard**\nRisk-return scatter, Sharpe heatmap, drawdown & beta.\n\n"
        "**🧮 SIP Calculator**\nMaturity, XIRR, scenario compare, fund picks."
    )
    n3.markdown(
        "**📦 Portfolio Analyzer**\nMulti-fund allocation, weighted metrics, "
        "efficient frontier, diversification score."
    )
    st.caption("👈 Use the sidebar to switch pages.")

    st.info(
        "ℹ️ **Data scope:** time-series analytics (forecasting, risk, peer ranking, "
        "portfolio) cover the **16 funds** with full NAV history (Yahoo ETFs + "
        "benchmarks). Fund Explorer searches the **entire 14k+ universe** and "
        "degrades gracefully for snapshot-only AMFI funds.",
        icon="ℹ️",
    )


if __name__ == "__main__":
    main()
