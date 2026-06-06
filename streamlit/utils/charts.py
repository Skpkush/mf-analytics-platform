"""
================================================================
Plotly chart builders (navy theme)
================================================================
Every figure here returns a go.Figure with the shared navy/white
look applied via _base_layout(). No Streamlit calls — pages do the
st.plotly_chart(...) themselves so charts stay reusable/testable.
================================================================
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .metrics import AMBER, GREEN, NAVY, RED

CI_FILL = "rgba(27,58,107,0.18)"     # navy @ low alpha for forecast band
GRID = "rgba(0,0,0,0.08)"


def _base_layout(fig: go.Figure, height: int = 420, ytitle: str | None = None) -> go.Figure:
    """Apply the shared navy/white theme to any figure."""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=36, b=10),
        font=dict(family="Segoe UI, Roboto, sans-serif", color="#1f2733"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        colorway=[NAVY, "#3E6DB5", GREEN, AMBER, RED, "#7E57C2"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, title=ytitle)
    return fig


# ----------------------------------------------------------------
# NAV / forecast
# ----------------------------------------------------------------
def nav_line_chart(history: pd.DataFrame, title: str = "") -> go.Figure:
    """5-year NAV line from a [date, nav] DataFrame."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["date"], y=history["nav"], mode="lines",
        line=dict(color=NAVY, width=2), name="NAV",
    ))
    if title:
        fig.update_layout(title=title)
    return _base_layout(fig, ytitle="NAV (₹)")


def forecast_chart(
    history: pd.Series,
    forecast: pd.DataFrame,
    interval_width: float,
    history_tail_days: int = 365,
) -> go.Figure:
    """Actuals (tail) + Prophet forecast line + confidence band."""
    recent = history[history.index >= history.index.max() - pd.Timedelta(days=history_tail_days)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat_upper"], mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat_lower"], mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor=CI_FILL,
        name=f"{interval_width:.0%} confidence", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=recent.index, y=recent.to_numpy(), mode="lines",
        line=dict(color=NAVY, width=2), name="Actual NAV",
    ))
    fig.add_trace(go.Scatter(
        x=forecast["ds"], y=forecast["yhat"], mode="lines",
        line=dict(color=AMBER, width=2, dash="dash"), name="Forecast",
    ))
    return _base_layout(fig, ytitle="NAV (₹)")


# ----------------------------------------------------------------
# Peer comparison
# ----------------------------------------------------------------
def peer_bar(peers: pd.DataFrame, metric: str, highlight: str, label: str) -> go.Figure:
    """Horizontal ranked bar of peers on `metric`, highlighting one fund."""
    d = peers.dropna(subset=[metric]).sort_values(metric)
    colors = [AMBER if c == highlight else "#3E6DB5" for c in d["scheme_code"]]
    fig = go.Figure(go.Bar(
        x=d[metric], y=d["fund_name"], orientation="h",
        marker_color=colors,
        text=[f"{v:.2f}" for v in d[metric]], textposition="auto",
    ))
    fig.update_layout(title=f"Peer ranking — {label}")
    return _base_layout(fig, height=max(260, 40 * len(d)), ytitle=None)


# ----------------------------------------------------------------
# Risk dashboard
# ----------------------------------------------------------------
def risk_return_scatter(df: pd.DataFrame) -> go.Figure:
    """Volatility (x) vs CAGR (y), bubble size by |Sharpe|, colour by asset class."""
    d = df.dropna(subset=["std_dev_1y", "cagr_1y"]).copy()
    fig = go.Figure()
    for ac, grp in d.groupby("asset_class"):
        fig.add_trace(go.Scatter(
            x=grp["std_dev_1y"], y=grp["cagr_1y"], mode="markers+text",
            text=grp["scheme_code"], textposition="top center",
            name=str(ac),
            marker=dict(size=(grp["sharpe_ratio"].abs().fillna(0.5) * 8 + 8)),
            hovertemplate="%{text}<br>Vol %{x:.1f}%<br>CAGR %{y:.1f}%<extra></extra>",
        ))
    fig.update_layout(title="Risk vs Return")
    fig.update_xaxes(title="Volatility (std dev, %)")
    return _base_layout(fig, ytitle="CAGR 1Y (%)")


def sharpe_heatmap(df: pd.DataFrame) -> go.Figure:
    """Sharpe heatmap: asset_class (rows) × fund (cols).

    AMC dimension is intentionally not used — the metric-bearing funds carry
    no AMC, so asset_class × fund is the honest cross-tab.
    """
    d = df.dropna(subset=["sharpe_ratio"]).copy()
    pivot = d.pivot_table(
        index="asset_class", columns="scheme_code",
        values="sharpe_ratio", aggfunc="mean",
    )
    fig = go.Figure(go.Heatmap(
        z=pivot.to_numpy(), x=list(pivot.columns), y=list(pivot.index),
        colorscale=[[0, RED], [0.5, AMBER], [1, GREEN]],
        colorbar=dict(title="Sharpe"),
        hovertemplate="%{y} · %{x}<br>Sharpe %{z:.2f}<extra></extra>",
    ))
    fig.update_layout(title="Sharpe ratio — asset class × fund")
    return _base_layout(fig, height=max(300, 70 * max(1, pivot.shape[0])))


def drawdown_bar(df: pd.DataFrame) -> go.Figure:
    """Max drawdown ranking (most negative first), RAG-coloured."""
    d = df.dropna(subset=["max_drawdown"]).copy()
    d["dd"] = d["max_drawdown"].abs()
    d = d.sort_values("dd", ascending=True)
    colors = [GREEN if v <= 15 else AMBER if v <= 30 else RED for v in d["dd"]]
    fig = go.Figure(go.Bar(
        x=d["dd"], y=d["fund_name"], orientation="h", marker_color=colors,
        text=[f"-{v:.1f}%" for v in d["dd"]], textposition="auto",
    ))
    fig.update_layout(title="Maximum drawdown (lower is better)")
    return _base_layout(fig, height=max(280, 38 * len(d)))


def beta_ladder(df: pd.DataFrame) -> go.Figure:
    """Beta vs the market (β=1 reference line)."""
    d = df.dropna(subset=["beta"]).sort_values("beta")
    colors = [GREEN if abs(v - 1) <= 0.1 else AMBER if abs(v - 1) <= 0.3 else RED for v in d["beta"]]
    fig = go.Figure(go.Bar(
        x=d["beta"], y=d["fund_name"], orientation="h", marker_color=colors,
        text=[f"{v:.2f}" for v in d["beta"]], textposition="auto",
    ))
    fig.add_vline(x=1.0, line=dict(color=NAVY, width=2, dash="dot"),
                  annotation_text="Market β=1", annotation_position="top")
    fig.update_layout(title="Beta ladder (vs Nifty 50)")
    return _base_layout(fig, height=max(280, 38 * len(d)))


# ----------------------------------------------------------------
# SIP
# ----------------------------------------------------------------
def sip_growth_chart(schedule: pd.DataFrame) -> go.Figure:
    """Invested vs portfolio value over time (filled area)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=schedule["year"], y=schedule["invested"], mode="lines",
        line=dict(color="#3E6DB5", width=2), name="Invested",
    ))
    fig.add_trace(go.Scatter(
        x=schedule["year"], y=schedule["value"], mode="lines",
        line=dict(color=GREEN, width=2.5), fill="tonexty",
        fillcolor="rgba(46,125,50,0.15)", name="Portfolio value",
    ))
    fig.update_layout(title="SIP growth over time")
    fig.update_xaxes(title="Years")
    return _base_layout(fig, ytitle="₹")


def scenario_compare_chart(scenarios: pd.DataFrame) -> go.Figure:
    """Grouped bars: maturity vs invested across named scenarios."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=scenarios["label"], y=scenarios["invested"],
                         name="Invested", marker_color="#3E6DB5"))
    fig.add_trace(go.Bar(x=scenarios["label"], y=scenarios["maturity"],
                         name="Maturity", marker_color=GREEN))
    fig.update_layout(title="Scenario comparison", barmode="group")
    return _base_layout(fig, ytitle="₹")


# ----------------------------------------------------------------
# Portfolio
# ----------------------------------------------------------------
def allocation_pie(weights: dict[str, float]) -> go.Figure:
    """Donut of portfolio allocation."""
    fig = go.Figure(go.Pie(
        labels=list(weights.keys()), values=list(weights.values()),
        hole=0.5, textinfo="label+percent",
    ))
    fig.update_layout(title="Allocation")
    return _base_layout(fig, height=360)


def frontier_scatter(
    cloud: pd.DataFrame,
    current: tuple[float, float] | None = None,
) -> go.Figure:
    """Efficient-frontier cloud coloured by Sharpe; mark the current portfolio."""
    fig = go.Figure(go.Scatter(
        x=cloud["vol"], y=cloud["ret"], mode="markers",
        marker=dict(size=5, color=cloud["sharpe"], colorscale="Viridis",
                    colorbar=dict(title="Sharpe"), showscale=True),
        name="Random portfolios",
        hovertemplate="Vol %{x:.1f}%<br>Ret %{y:.1f}%<extra></extra>",
    ))
    if current is not None:
        fig.add_trace(go.Scatter(
            x=[current[1]], y=[current[0]], mode="markers",
            marker=dict(size=16, color=RED, symbol="star"),
            name="Your portfolio",
        ))
    fig.update_layout(title="Efficient frontier (Monte-Carlo)")
    fig.update_xaxes(title="Volatility (%)")
    return _base_layout(fig, ytitle="Expected return (%)")
