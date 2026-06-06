"""
Fund Explorer — search the full ~14k fund universe, inspect a fund's
metrics + 5Y NAV + peer ranking. Degrades gracefully for AMFI funds
that hold only a single NAV snapshot (no time series / metrics).
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
from utils.metrics import GREY, NAVY, rag_color  # noqa: E402

st.set_page_config(page_title="Fund Explorer", page_icon="🔎", layout="wide")


def _metric_card(col, label: str, value, metric: str, suffix: str = "") -> None:
    """Render a RAG-coloured metric card via HTML."""
    if value is None or (isinstance(value, float) and value != value):
        disp, color = "—", GREY
    else:
        disp, color = f"{value:.2f}{suffix}", rag_color(value, metric)
    col.markdown(
        f"<div style='border:1px solid #e6e9ef;border-radius:10px;padding:10px 12px'>"
        f"<div style='font-size:0.78rem;color:#5a6473'>{label}</div>"
        f"<div style='font-size:1.35rem;font-weight:700;color:{color}'>{disp}</div></div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.markdown(f"<h1 style='color:{NAVY}'>🔎 Fund Explorer</h1>", unsafe_allow_html=True)

    if not db.check_connection():
        st.error("⚠️ Database unreachable — check `.streamlit/secrets.toml` / `.env`.")
        st.stop()

    directory = db.get_fund_directory()
    perf = db.get_fund_performance()

    # ---- Search ----
    term = st.text_input("Search by fund name or AMC", placeholder="e.g. Nifty, HDFC, Gold…").strip()
    filtered = directory
    if term:
        mask = (
            directory["fund_name"].str.contains(term, case=False, na=False)
            | directory["amc"].fillna("").str.contains(term, case=False, na=False)
        )
        filtered = directory[mask]

    st.caption(f"{len(filtered):,} of {len(directory):,} funds match.")
    if filtered.empty:
        st.info("No funds match your search.")
        st.stop()

    # Bias the dropdown toward funds that actually have history.
    filtered = filtered.sort_values(["n_obs", "fund_name"], ascending=[False, True])
    options = filtered["scheme_code"].tolist()
    labels = {
        r.scheme_code: f"{r.fund_name}  ({r.scheme_code})"
        + ("  ⭐ full history" if r.n_obs > 1 else "")
        for r in filtered.itertuples()
    }
    code = st.selectbox("Select a fund", options, format_func=lambda c: labels[c])
    row = filtered[filtered["scheme_code"] == code].iloc[0]

    # ---- Header ----
    st.subheader(f"{row['fund_name']}")
    meta = " · ".join(
        str(x) for x in [row["amc"], row["asset_class"], row["sub_category"], row["plan_type"]]
        if x and str(x) != "None"
    )
    st.caption(f"`{code}` · {meta}")

    has_history = row["n_obs"] > 1
    if not has_history:
        # ---- Graceful degradation (AMFI snapshot) ----
        st.warning(
            "This fund has a **single NAV snapshot** (AMFI publishes one EOD NAV "
            "with no historical series in this dataset), so time-series metrics, "
            "the 5Y chart and peer ranking are unavailable.",
            icon="⚠️",
        )
        c1, c2 = st.columns(2)
        c1.metric("Latest NAV", f"₹{float(row['latest_nav']):,.4f}" if row["latest_nav"] is not None else "—")
        c2.metric("As of", str(row["latest_nav_date"]) if row["latest_nav_date"] is not None else "—")
        _export(directory, "fund_directory")
        return

    # ---- Metric card (funds with full history) ----
    prow = perf[perf["scheme_code"] == code]
    if prow.empty:
        st.info("History exists but computed metrics are not available for this fund.")
    else:
        m = prow.iloc[0]
        st.markdown("#### Performance & risk")
        r1 = st.columns(4)
        _metric_card(r1[0], "CAGR 1Y", m["cagr_1y"], "cagr", "%")
        _metric_card(r1[1], "CAGR 3Y", m["cagr_3y"], "cagr", "%")
        _metric_card(r1[2], "CAGR 5Y", m["cagr_5y"], "cagr", "%")
        _metric_card(r1[3], "Sharpe", m["sharpe_ratio"], "sharpe")
        r2 = st.columns(4)
        _metric_card(r2[0], "Beta", m["beta"], "beta")
        _metric_card(r2[1], "Alpha", m["alpha"], "alpha", "%")
        _metric_card(r2[2], "Max Drawdown", m["max_drawdown"], "drawdown", "%")
        _metric_card(r2[3], "Volatility", m["std_dev_1y"], "volatility", "%")

    # ---- 5Y NAV chart ----
    st.markdown("#### NAV history")
    with st.spinner("Loading NAV history…"):
        hist = db.get_nav_history(code)
    if hist.empty:
        st.info("No NAV history rows found.")
    else:
        st.plotly_chart(charts.nav_line_chart(hist), width="stretch")

    # ---- Peer comparison ----
    if not prow.empty:
        asset_class = prow.iloc[0]["asset_class"]
        peers = perf[perf["asset_class"] == asset_class]
        st.markdown(f"#### Peers — {asset_class} ({len(peers)} funds)")
        if len(peers) > 1:
            st.plotly_chart(
                charts.peer_bar(peers, "cagr_1y", code, "CAGR 1Y"),
                width="stretch",
            )
            st.dataframe(
                peers[["fund_name", "scheme_code", "cagr_1y", "sharpe_ratio", "beta", "max_drawdown"]]
                .sort_values("cagr_1y", ascending=False),
                width="stretch", hide_index=True,
            )
        else:
            st.caption("Only one fund in this asset class — no peers to rank.")

    _export(perf, "fund_performance")


def _export(df, name: str) -> None:
    st.download_button(
        "⬇️ Download data (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
