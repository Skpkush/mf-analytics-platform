"""
SIP Calculator — maturity / wealth-gain / XIRR for a monthly SIP, a
3-scenario comparison, and risk-profile fund picks (from the 16 funds
with computed metrics). Pure-math core lives in utils/metrics.
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
from utils.metrics import NAVY, sip_growth_schedule, sip_projection, sip_xirr  # noqa: E402

st.set_page_config(page_title="SIP Calculator", page_icon="🧮", layout="wide")

# Map an investor risk profile to vw_risk_summary risk_tiers.
RISK_TIER_MAP = {
    "Conservative": ["Very Low", "Low"],
    "Moderate": ["Medium"],
    "Aggressive": ["High", "Very High"],
}


def main() -> None:
    st.markdown(f"<h1 style='color:{NAVY}'>🧮 SIP Calculator</h1>", unsafe_allow_html=True)

    # ---- Inputs ----
    with st.sidebar:
        st.header("SIP inputs")
        monthly = st.number_input("Monthly amount (₹)", 500, 1_000_000, 10_000, step=500)
        years = st.slider("Duration (years)", 1, 40, 15)
        exp_return = st.slider("Expected annual return (%)", 1.0, 25.0, 12.0, 0.5)

    proj = sip_projection(monthly, years, exp_return)
    xirr = sip_xirr(monthly, years, exp_return)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Maturity value", f"₹{proj['maturity']:,.0f}")
    c2.metric("Total invested", f"₹{proj['invested']:,.0f}")
    c3.metric("Wealth gained", f"₹{proj['gain']:,.0f}", f"{proj['multiple']:.2f}× invested")
    c4.metric("XIRR", f"{xirr:.2f}%" if xirr is not None else "—")

    # ---- Growth chart ----
    schedule = sip_growth_schedule(monthly, years, exp_return)
    st.plotly_chart(charts.sip_growth_chart(schedule), width="stretch")

    # ---- 3-scenario comparison ----
    st.markdown("#### Compare scenarios")
    s1, s2, s3 = st.columns(3)
    r_cons = s1.number_input("Conservative return (%)", 1.0, 25.0, 8.0, 0.5)
    r_mod = s2.number_input("Moderate return (%)", 1.0, 25.0, 12.0, 0.5)
    r_agg = s3.number_input("Aggressive return (%)", 1.0, 25.0, 15.0, 0.5)

    rows = []
    for label, r in [("Conservative", r_cons), ("Moderate", r_mod), ("Aggressive", r_agg)]:
        p = sip_projection(monthly, years, r)
        rows.append({
            "label": f"{label}\n({r:.1f}%)", "return_pct": r,
            "invested": p["invested"], "maturity": p["maturity"], "gain": p["gain"],
        })
    scen = pd.DataFrame(rows)
    st.plotly_chart(charts.scenario_compare_chart(scen), width="stretch")
    st.dataframe(
        scen[["label", "return_pct", "invested", "maturity", "gain"]],
        width="stretch", hide_index=True,
    )

    # ---- Risk-profile fund picks ----
    st.markdown("#### Suggested funds by risk profile")
    profile = st.radio("Your risk profile", list(RISK_TIER_MAP.keys()), horizontal=True)
    if not db.check_connection():
        st.info("Fund suggestions need the database — currently unreachable.")
    else:
        risk = db.get_risk_summary()
        tiers = RISK_TIER_MAP[profile]
        picks = (
            risk[risk["risk_tier"].isin(tiers)]
            .sort_values("sharpe_ratio", ascending=False)
            .head(5)
        )
        if picks.empty:
            st.caption(f"No funds in the {profile.lower()} risk tier(s): {', '.join(tiers)}.")
        else:
            st.caption(
                f"Top {len(picks)} of the metric-bearing funds in the {profile.lower()} "
                f"tier(s) ({', '.join(tiers)}), ranked by Sharpe. Not investment advice."
            )
            st.dataframe(
                picks[["fund_name", "scheme_code", "asset_class", "risk_tier",
                       "cagr_1y", "sharpe_ratio", "std_dev_1y", "max_drawdown"]],
                width="stretch", hide_index=True,
            )

    st.download_button(
        "⬇️ Download growth schedule (CSV)",
        schedule.to_csv(index=False).encode("utf-8"),
        file_name="sip_growth_schedule.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
