"""
Portfolio Analyzer — combine funds with allocation weights, compute
weighted metrics, plot the efficient frontier (Monte-Carlo) with the
current portfolio marked, score diversification and surface rule-based
rebalancing suggestions. Scoped to the 16 funds with NAV history.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils import charts, db, metrics  # noqa: E402
from utils.metrics import NAVY  # noqa: E402

st.set_page_config(page_title="Portfolio Analyzer", page_icon="📦", layout="wide")
CONCENTRATION_LIMIT = 40.0  # % single-fund weight that triggers a trim suggestion


def main() -> None:
    st.markdown(f"<h1 style='color:{NAVY}'>📦 Portfolio Analyzer</h1>", unsafe_allow_html=True)

    if not db.check_connection():
        st.error("⚠️ Database unreachable — check `.streamlit/secrets.toml` / `.env`.")
        st.stop()

    funds = db.get_forecastable_funds()
    perf = db.get_fund_performance()
    if funds.empty:
        st.warning("No funds with usable history.")
        st.stop()

    st.info(
        f"Portfolio construction uses the **{len(funds)} funds** with full NAV history "
        "(the only funds where covariance / frontier math is valid).",
        icon="ℹ️",
    )

    codes = funds["scheme_code"].tolist()
    labels = {r.scheme_code: f"{r.fund_name} ({r.scheme_code})" for r in funds.itertuples()}
    chosen = st.multiselect(
        "Select funds (2+ for a frontier)", codes,
        default=codes[:3], format_func=lambda c: labels[c],
    )
    if not chosen:
        st.info("Pick at least one fund.")
        st.stop()

    # ---- Allocation inputs ----
    st.markdown("#### Allocation")
    cols = st.columns(min(len(chosen), 4))
    raw_weights: dict[str, float] = {}
    for idx, c in enumerate(chosen):
        raw_weights[c] = cols[idx % len(cols)].number_input(
            f"{c} (%)", 0.0, 100.0, round(100 / len(chosen), 1), step=5.0, key=f"w_{c}",
        )
    total = sum(raw_weights.values())
    if total <= 0:
        st.warning("Total allocation is 0% — assign some weights.")
        st.stop()
    weights = {c: w / total for c, w in raw_weights.items()}  # normalise to 1.0
    if abs(total - 100) > 0.1:
        st.caption(f"⚖️ Weights sum to {total:.1f}% — normalised to 100% for all calculations.")

    a, b = st.columns([1, 2])
    with a:
        st.plotly_chart(charts.allocation_pie({c: round(w * 100, 1) for c, w in weights.items()}),
                        width="stretch")

    # ---- Weighted metrics ----
    wm = metrics.weighted_portfolio_metrics(perf, weights)
    with b:
        st.markdown("#### Weighted portfolio metrics")
        m = st.columns(5)
        m[0].metric("CAGR 1Y", _fmt(wm.get("cagr_1y"), "%"))
        m[1].metric("Sharpe", _fmt(wm.get("sharpe_ratio")))
        m[2].metric("Beta", _fmt(wm.get("beta")))
        m[3].metric("Volatility", _fmt(wm.get("std_dev_1y"), "%"))
        m[4].metric("Max DD", _fmt(wm.get("max_drawdown"), "%"))

    # ---- Frontier + diversification (need >= 2 funds) ----
    if len(chosen) >= 2:
        with st.spinner("Computing efficient frontier…"):
            prices = db.get_price_matrix(tuple(chosen))
        if prices.shape[1] >= 2 and not prices.empty:
            mean, cov = metrics.annualised_stats(prices)
            w_vec = np.array([weights[c] for c in prices.columns])
            cur_ret, cur_vol = metrics.portfolio_risk_return(w_vec, mean, cov)
            cloud = metrics.efficient_frontier(prices)
            div = metrics.diversification_score(prices)

            f1, f2 = st.columns([2, 1])
            with f1:
                st.plotly_chart(charts.frontier_scatter(cloud, current=(cur_ret, cur_vol)),
                                width="stretch")
            with f2:
                st.metric("Diversification score", f"{div:.0f}/100" if div is not None else "—",
                          help="Higher = lower average pairwise correlation.")
                st.metric("Portfolio return (ann.)", f"{cur_ret:.2f}%")
                st.metric("Portfolio volatility (ann.)", f"{cur_vol:.2f}%")
        else:
            st.caption("Not enough overlapping price history for a frontier.")
    else:
        st.caption("Select 2+ funds to see the efficient frontier and diversification score.")

    # ---- Rebalancing suggestions ----
    st.markdown("#### Rebalancing suggestions")
    for s in _suggestions(weights, wm):
        st.markdown(f"- {s}")

    st.download_button(
        "⬇️ Download portfolio metrics (CSV)",
        perf[perf["scheme_code"].isin(chosen)].to_csv(index=False).encode("utf-8"),
        file_name="portfolio_funds.csv",
        mime="text/csv",
    )


def _fmt(v, suffix: str = "") -> str:
    return f"{v:.2f}{suffix}" if v is not None else "—"


def _suggestions(weights: dict[str, float], wm: dict) -> list[str]:
    """Simple rule-based (not advice) rebalancing hints."""
    out: list[str] = []
    for c, w in weights.items():
        if w * 100 > CONCENTRATION_LIMIT:
            out.append(f"⚠️ **{c}** is {w*100:.0f}% of the portfolio — consider trimming "
                       f"below {CONCENTRATION_LIMIT:.0f}% to reduce concentration risk.")
    beta = wm.get("beta")
    if beta is not None and beta > 1.2:
        out.append(f"📈 Weighted beta is **{beta:.2f}** (> 1.2) — adding lower-beta or "
                   "debt/gold exposure would dampen market sensitivity.")
    sharpe = wm.get("sharpe_ratio")
    if sharpe is not None and sharpe < 0.5:
        out.append(f"🔻 Weighted Sharpe is **{sharpe:.2f}** — reweighting toward "
                   "higher-Sharpe holdings could improve risk-adjusted return.")
    if len(weights) < 3:
        out.append("🧩 Holding fewer than 3 funds limits diversification — consider "
                   "adding an uncorrelated asset class (e.g. gold or debt).")
    if not out:
        out.append("✅ No obvious concentration or risk flags. Portfolio looks balanced.")
    return out


if __name__ == "__main__":
    main()
