"""
================================================================
Financial calculations + conditional formatting
================================================================
Pure functions (no DB, no Streamlit) so they are unit-testable:
    - SIP maturity / wealth-gain projection
    - XIRR (Newton-Raphson, with bisection fallback)
    - Portfolio weighted metrics + risk/return + diversification
    - Efficient-frontier sampling
    - RAG (red/amber/green) colour thresholds for the UI
================================================================
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---- Brand palette -------------------------------------------------
NAVY = "#1B3A6B"
GREEN = "#2E7D32"
AMBER = "#F9A825"
RED = "#C62828"
GREY = "#9E9E9E"

TRADING_DAYS = 252
RISK_FREE_RATE = 6.5  # % — RBI repo, matches Fact_Returns Sharpe basis


# ----------------------------------------------------------------
# Conditional colour coding
# ----------------------------------------------------------------
def rag_color(value: float | None, metric: str) -> str:
    """Return a hex colour (green/amber/red) for a metric value.

    Thresholds are deliberately simple and documented so the UI legend
    can explain them. Higher-is-better for most; drawdown/volatility/beta
    are lower-is-better.

    Args:
        value: The metric value (None -> grey).
        metric: One of 'sharpe', 'cagr', 'beta', 'drawdown', 'volatility',
            'alpha', 'sortino'.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return GREY

    higher_better = {
        "sharpe": (1.0, 0.5),
        "sortino": (1.5, 0.7),
        "cagr": (12.0, 7.0),
        "alpha": (2.0, 0.0),
    }
    lower_better = {
        "drawdown": (15.0, 30.0),   # abs(%) — smaller is better
        "volatility": (12.0, 20.0),
        "beta": (0.9, 1.1),         # near/below 1 green, well above amber/red
    }

    if metric in higher_better:
        good, ok = higher_better[metric]
        if value >= good:
            return GREEN
        return AMBER if value >= ok else RED

    if metric in lower_better:
        good, ok = lower_better[metric]
        v = abs(value)
        if v <= good:
            return GREEN
        return AMBER if v <= ok else RED

    return GREY


def rag_emoji(value: float | None, metric: str) -> str:
    """🟢/🟡/🔴/⚪ badge matching rag_color — handy in markdown."""
    return {GREEN: "🟢", AMBER: "🟡", RED: "🔴", GREY: "⚪"}[rag_color(value, metric)]


# ----------------------------------------------------------------
# SIP projection
# ----------------------------------------------------------------
def sip_projection(
    monthly_amount: float,
    years: int,
    annual_return_pct: float,
) -> dict[str, float]:
    """Future value of a monthly SIP using the standard annuity formula.

    FV = P * [((1+i)^n - 1) / i] * (1+i),  i = monthly rate, n = months.
    Returns maturity value, total invested, and wealth gained.
    """
    n = int(years * 12)
    invested = monthly_amount * n
    i = (annual_return_pct / 100.0) / 12.0
    if i == 0:
        maturity = float(invested)
    else:
        maturity = monthly_amount * (((1 + i) ** n - 1) / i) * (1 + i)
    return {
        "maturity": round(maturity, 2),
        "invested": round(invested, 2),
        "gain": round(maturity - invested, 2),
        "multiple": round(maturity / invested, 2) if invested else 0.0,
    }


def sip_growth_schedule(
    monthly_amount: float,
    years: int,
    annual_return_pct: float,
) -> pd.DataFrame:
    """Month-by-month invested vs portfolio value (for the growth chart)."""
    n = int(years * 12)
    i = (annual_return_pct / 100.0) / 12.0
    rows = []
    value = 0.0
    for m in range(1, n + 1):
        value = (value + monthly_amount) * (1 + i)
        rows.append({
            "month": m,
            "year": round(m / 12.0, 2),
            "invested": monthly_amount * m,
            "value": round(value, 2),
        })
    return pd.DataFrame(rows)


def xirr(cashflows: list[tuple[pd.Timestamp, float]], guess: float = 0.1) -> float | None:
    """Annualised IRR for dated cashflows (outflows negative, inflows positive).

    Newton-Raphson with a bisection fallback for robustness. Returns the
    annualised rate as a percentage, or None if it fails to converge.
    """
    if len(cashflows) < 2:
        return None
    dates = [pd.Timestamp(d) for d, _ in cashflows]
    amounts = np.array([a for _, a in cashflows], dtype=float)
    t0 = min(dates)
    years = np.array([(d - t0).days / 365.0 for d in dates])

    def npv(rate: float) -> float:
        return float(np.sum(amounts / (1 + rate) ** years))

    # Newton-Raphson
    rate = guess
    for _ in range(100):
        f = npv(rate)
        # numerical derivative
        df = (npv(rate + 1e-6) - f) / 1e-6
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if not np.isfinite(new_rate):
            break
        if abs(new_rate - rate) < 1e-8:
            return round(new_rate * 100, 4)
        rate = new_rate

    # Bisection fallback on a sane bracket
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return round(mid * 100, 4)
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return round(((lo + hi) / 2) * 100, 4)


def sip_xirr(monthly_amount: float, years: int, annual_return_pct: float) -> float | None:
    """XIRR of a SIP: monthly outflows + a single terminal inflow (maturity)."""
    n = int(years * 12)
    proj = sip_projection(monthly_amount, years, annual_return_pct)
    start = pd.Timestamp.today().normalize()
    flows: list[tuple[pd.Timestamp, float]] = [
        (start + pd.DateOffset(months=m), -monthly_amount) for m in range(n)
    ]
    flows.append((start + pd.DateOffset(months=n), proj["maturity"]))
    return xirr(flows)


# ----------------------------------------------------------------
# Portfolio analytics
# ----------------------------------------------------------------
def weighted_portfolio_metrics(
    perf: pd.DataFrame,
    weights: dict[str, float],
) -> dict[str, float | None]:
    """Allocation-weighted CAGR / Sharpe / Beta / Volatility / Drawdown.

    Args:
        perf: rows from vw_fund_performance (must include scheme_code +
            cagr_1y, sharpe_ratio, beta, std_dev_1y, max_drawdown).
        weights: {scheme_code: weight_fraction} summing to ~1.0.
    """
    sub = perf[perf["scheme_code"].isin(weights)].copy()
    if sub.empty:
        return {}
    sub["w"] = sub["scheme_code"].map(weights)
    sub["w"] = sub["w"] / sub["w"].sum()  # normalise

    def wavg(col: str) -> float | None:
        s = sub[[col, "w"]].dropna()
        if s.empty:
            return None
        return round(float((s[col] * s["w"]).sum() / s["w"].sum()), 4)

    return {
        "cagr_1y": wavg("cagr_1y"),
        "sharpe_ratio": wavg("sharpe_ratio"),
        "beta": wavg("beta"),
        "std_dev_1y": wavg("std_dev_1y"),
        "max_drawdown": wavg("max_drawdown"),
    }


def annualised_stats(prices: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Annualised mean daily return vector and covariance matrix from prices."""
    rets = prices.pct_change().dropna()
    mean = rets.mean() * TRADING_DAYS
    cov = rets.cov() * TRADING_DAYS
    return mean, cov


def portfolio_risk_return(
    weights: np.ndarray,
    mean: pd.Series,
    cov: pd.DataFrame,
) -> tuple[float, float]:
    """Return (annualised return %, annualised volatility %) for a weight vector."""
    ret = float(np.dot(weights, mean.to_numpy()) * 100)
    vol = float(np.sqrt(weights @ cov.to_numpy() @ weights) * 100)
    return ret, vol


def efficient_frontier(
    prices: pd.DataFrame,
    n_samples: int = 3000,
    seed: int = 42,
) -> pd.DataFrame:
    """Monte-Carlo random portfolios → (return, volatility, sharpe) cloud.

    Needs >= 2 funds with aligned price history. Sharpe uses RISK_FREE_RATE.
    """
    if prices.shape[1] < 2 or prices.empty:
        return pd.DataFrame()
    mean, cov = annualised_stats(prices)
    rng = np.random.default_rng(seed)
    n_assets = prices.shape[1]
    out = []
    for _ in range(n_samples):
        w = rng.random(n_assets)
        w /= w.sum()
        ret, vol = portfolio_risk_return(w, mean, cov)
        sharpe = (ret - RISK_FREE_RATE) / vol if vol else 0.0
        out.append({"ret": ret, "vol": vol, "sharpe": round(sharpe, 3)})
    return pd.DataFrame(out)


def diversification_score(prices: pd.DataFrame) -> float | None:
    """0–100 score: lower average pairwise correlation = better diversified.

    score = (1 - avg_offdiag_corr) * 100, clamped to [0, 100].
    """
    if prices.shape[1] < 2:
        return None
    corr = prices.pct_change().dropna().corr().to_numpy()
    n = corr.shape[0]
    off = (corr.sum() - np.trace(corr)) / (n * n - n)
    return round(float(max(0.0, min(1.0, 1 - off)) * 100), 1)
