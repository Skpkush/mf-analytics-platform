# KPI Definitions — Mutual Fund Analytics Platform

This document defines every metric computed in the analytics layer
(`scripts/analytics/`), exposed through the SQL views (`scripts/sql/views/`),
and surfaced in the Power BI dashboard and Streamlit app.

> **Scope note:** time-series metrics (returns, risk, market) are computed on the
> **16-fund Yahoo ETF/benchmark universe** (≥ 200 trading days of history). The
> ~14,384 AMFI schemes carry a single NAV snapshot and are therefore covered for
> directory/AUM purposes only, not for time-series metrics.

---

## Return Metrics

### CAGR (1Y / 3Y / 5Y)
**Compound Annual Growth Rate** — the constant annual rate that grows the
starting NAV to the ending NAV over the period.

```
CAGR = (NAV_end / NAV_start) ^ (1 / years) − 1
```

- **Interpretation:** smooths volatile year-to-year returns into a single
  annualised figure. A 5Y CAGR of 10.19% (e.g. NIFTYBEES) means the fund grew
  ~10.19% per year on average over 5 years.
- **Implementation:** `scripts/analytics/metrics_returns.py`. Uses a
  forward-gap lookup when the exact period-start trading day is missing.

### Rolling Returns (1Y / 3Y / 5Y)
Point-to-point returns measured over a fixed lookback window ending on the
latest available trading day.

```
Return_nY = (NAV_today / NAV_(today − nY)) − 1
```

- **Interpretation:** unlike a single trailing return, rolling windows reduce
  start-date bias and show consistency of performance.

### Absolute Return
Total, non-annualised point-to-point return over the available history.

```
Absolute Return = (NAV_end / NAV_start) − 1
```

- **Interpretation:** raw cumulative gain/loss, not adjusted for time. Useful
  for short horizons (< 1 year) where annualising would distort the figure.

---

## Risk Metrics

### Sharpe Ratio
Excess return (over the risk-free rate) per unit of **total** risk.

```
Sharpe = (R_p − R_f) / σ_p
```

- **R_f = 6.5%** (RBI repo rate); **σ_p** = annualised standard deviation of returns.
- **Thresholds:** `> 1` good · `0–1` acceptable · `< 0` the fund underperformed
  the risk-free rate (poor risk-adjusted outcome).
- **Implementation:** `scripts/analytics/metrics_risk_adjusted.py`.

### Sortino Ratio
Like Sharpe, but penalises only **downside** volatility (it does not punish
upside swings).

```
Sortino = (R_p − R_f) / σ_downside
```

- **σ_downside** = standard deviation of negative returns only.
- **Difference from Sharpe:** Sharpe uses total volatility; Sortino isolates
  harmful (downside) volatility, so it rewards funds whose volatility is mostly
  to the upside. Sortino ≥ Sharpe for the same fund in most cases.

### Treynor Ratio
Excess return per unit of **systematic (market) risk** rather than total risk.

```
Treynor = (R_p − R_f) / β
```

- **Interpretation:** measures reward per unit of non-diversifiable market risk.
  Best compared across funds within the same market exposure. Extreme values for
  near-zero-β cash-equivalent funds (e.g. LIQUIDBEES) are mathematically valid
  but economically meaningless.

### Standard Deviation / Volatility
Annualised dispersion of periodic returns around the mean.

```
σ = stdev(daily returns) × √252
```

- **Interpretation:** higher σ = wider swings = higher total risk. NIFTYBEES
  σ ≈ 12.09% (1Y) is typical for a large-cap equity index ETF.

### Maximum Drawdown
The largest peak-to-trough decline over the period.

```
Max Drawdown = min over t of [ (NAV_t − running_peak_t) / running_peak_t ]
```

- **Interpretation:** worst loss an investor would have suffered if they bought
  at the peak and sold at the trough. Always ≤ 0; closer to 0 is better.
  A −16.11% drawdown means the fund fell 16.11% from its high before recovering.

---

## Market Metrics

### Alpha (Jensen's Alpha)
Return earned **above** what CAPM predicts for the fund's level of market risk.

```
Alpha = R_p − [ R_f + β × (R_m − R_f) ]
```

- **R_m** = benchmark (Nifty 50) return.
- **Interpretation:** positive alpha = manager/strategy added value beyond market
  exposure (e.g. GOLDBEES α ≈ +18.12%); negative alpha = underperformed the
  risk-adjusted expectation (e.g. Nifty IT α ≈ −7.53%).
- **Implementation:** `scripts/analytics/metrics_market.py`.

### Beta (OLS vs Nifty 50)
Sensitivity of fund returns to market (Nifty 50) returns — the OLS regression
slope of fund returns on benchmark returns.

```
β = Cov(R_p, R_m) / Var(R_m)        (OLS slope on common trading days)
```

- **Thresholds:** `β < 1` defensive (moves less than the market) ·
  `β ≈ 1` market-like · `β > 1` aggressive (amplifies market moves).
- **Sanity checks:** `^NSEI` self-beta = 1.0, α = 0.0; NIFTYBEES β ≈ 0.8938;
  LIQUIDBEES β ≈ 0 (no equity-market correlation).

### Information Ratio
Active return over a benchmark per unit of **tracking error** (consistency of
outperformance).

```
Information Ratio = (R_p − R_b) / TrackingError
TrackingError    = stdev(R_p − R_b)
```

- **Interpretation:** how reliably a fund beats its benchmark. Higher = more
  consistent active outperformance, not just a one-off lucky period.

---

## Dashboard KPIs

These are the aggregate cards/measures shown on the Power BI dashboard and the
Streamlit home page.

### Scheme Count
Total number of mutual fund **schemes** ingested into `Dim_Fund`
(plan/option variants counted separately).

```
Scheme Count = COUNT(Dim_Fund rows where is_active)        → 14,384
```

### Unique Funds
Distinct underlying funds after collapsing plan/option variants (Regular/Direct,
Growth/IDCW) to their base name.

```
Unique Funds = DISTINCTCOUNT(Dim_Fund[base_fund_name])
```

- **Why it differs from Scheme Count:** one fund can appear as many schemes
  (Direct-Growth, Regular-IDCW, …); this collapses them to the real fund count.

### Outperforming %
Share of the metric-bearing universe that beat its CAPM expectation
(positive Jensen's alpha).

```
Outperforming % = COUNT(funds where alpha > 0) / COUNT(funds with metrics) × 100
```

### Avg Sharpe
Mean Sharpe ratio across the metric-bearing universe, **capped at ±10** before
averaging to prevent near-zero-volatility cash funds (e.g. LIQUIDBEES,
Sharpe ≈ −578) from distorting the average.

```
Avg Sharpe = AVERAGE( CLAMP(sharpe_ratio, −10, +10) )
```

- **Why the cap:** a handful of cash-equivalent funds produce mathematically
  correct but extreme ratios; clamping keeps the headline KPI representative of
  the equity/ETF universe.

---

## Data Sources

| Source | Use | Detail |
|---|---|---|
| **AMFI India** | Historical/snapshot NAV for all schemes | AMFI NAV endpoint → 14,368 schemes, 51 AMCs |
| **Yahoo Finance** | ETF + benchmark daily time series | 11 ETFs + 5 benchmarks (~1,236 trading days each) — the metric-bearing universe |
| **Risk-free rate** | Sharpe / Sortino / Treynor / Alpha | **RBI repo rate = 6.5%** |
| **Benchmark** | Beta, Alpha, Information Ratio | **Nifty 50 (`^NSEI`)** |

---

_Formulas implemented in `scripts/analytics/`; exposed via
`vw_fund_performance`, `vw_risk_summary`, and `vw_aum_summary`._
