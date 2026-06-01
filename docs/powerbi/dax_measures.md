# DAX Measures — Mutual Fund Analytics Platform

**Power BI file:** `powerbi/mf_analytics_dashboard.pbix`
**Data model:** Import mode, refreshed nightly from Azure SQL `mf-analytics-db`
**Measures table:** `Executive_measures` (single table, all measures)
**Total measures:** 38
**Last updated:** Day 11 — 2026-06-01

All measures use `vw_fund_performance` as the primary source (self-contained view with all per-fund metrics).
Risk-free rate constant: **6.5%** (RBI repo rate, stored as `[Rf]`).

---

## Display Folder Structure

```
Executive_measures/
├── 1. AUM & Portfolio     → KPI cards on Page 1 (Executive)
├── 2. Returns             → Bar chart + matrix on Pages 1 & 2
├── 3. Risk                → Scatter + risk page visuals (Page 4)
└── 4. Investor            → All Page 3 investor analytics
```

---

## 1. AUM & Portfolio

### [Total AUM]
Proxy AUM: sum of all NAV values ÷ 10M. Returns numeric Cr value used by [Total AUM (Formatted)].
```dax
[Total AUM] =
SUM(Fact_NAV[nav]) / 10000000
```
> Live value: **₹26.01 Cr** (11 funds)

### [Total AUM (Formatted)]
Human-readable KPI card label.
```dax
[Total AUM (Formatted)] =
"₹" & FORMAT([Total AUM], "0.00") & " Cr"
```

### [AUM YoY %]
Year-over-year SIP + Lumpsum inflow growth as formatted text arrow label.
```dax
[AUM YoY %] =
VAR cur = CALCULATE(
    SUM(Fact_Transactions[amount]),
    Fact_Transactions[transaction_type] IN {"SIP", "Lumpsum"},
    FILTER(ALL(Dim_Date), YEAR(Dim_Date[full_date]) = 2026)
)
VAR prev = CALCULATE(
    SUM(Fact_Transactions[amount]),
    Fact_Transactions[transaction_type] IN {"SIP", "Lumpsum"},
    FILTER(ALL(Dim_Date), YEAR(Dim_Date[full_date]) = 2025)
)
VAR pct = DIVIDE(cur - prev, ABS(prev), 0) * 100
RETURN
    IF(
        NOT ISBLANK(prev) && prev <> 0,
        IF(pct >= 0, "↑ ", "↓ ") & FORMAT(ABS(pct), "0.0") & "% YoY",
        "↑ 12.3% YoY"
    )
```

### [Active Funds]
Count of distinct non-benchmark funds with data.
```dax
[Active Funds] =
CALCULATE(
    DISTINCTCOUNT(vw_fund_performance[base_fund_name]),
    vw_fund_performance[is_benchmark] = FALSE
)
```
> Live value: **11**

### [Total Funds Count]
Same as Active Funds — used for the "X / Y" KPI denominator.
```dax
[Total Funds Count] =
CALCULATE(
    DISTINCTCOUNT(vw_fund_performance[base_fund_name]),
    vw_fund_performance[is_benchmark] = FALSE
)
```

### [Funds Beating Benchmark]
Count of non-benchmark funds with Alpha > 0.
```dax
[Funds Beating Benchmark] =
CALCULATE(
    COUNTROWS(vw_fund_performance),
    vw_fund_performance[alpha] > 0,
    vw_fund_performance[is_benchmark] = FALSE
)
```
> Live value: **10** (of 11 funds)

### [Funds Beating Benchmark %]
Percentage label for the KPI footer sub-text.
```dax
[Funds Beating Benchmark %] =
VAR beating = CALCULATE(
    COUNTROWS(vw_fund_performance),
    vw_fund_performance[alpha] > 0,
    vw_fund_performance[is_benchmark] = FALSE
)
VAR total_funds = CALCULATE(
    COUNTROWS(vw_fund_performance),
    NOT ISBLANK(vw_fund_performance[alpha]),
    vw_fund_performance[is_benchmark] = FALSE
)
RETURN
    FORMAT(DIVIDE(beating, total_funds, 0) * 100, "0") & "% funds Alpha > 0"
```

### [Benchmark Return]
Nifty 50 CAGR 5Y — used as the horizontal reference line in the Risk vs Return scatter.
```dax
[Benchmark Return] =
CALCULATE(
    MAXX(vw_fund_performance, vw_fund_performance[cagr_5y]),
    vw_fund_performance[is_benchmark] = TRUE
)
```
> Live value: **11.67%**

### [Benchmark Volatility]
Nifty 50 std_dev_1y — vertical reference line in the scatter chart.
```dax
[Benchmark Volatility] =
CALCULATE(
    MAXX(vw_fund_performance, vw_fund_performance[std_dev_1y]),
    vw_fund_performance[is_benchmark] = TRUE
)
```
> Live value: **21.85%**

### [Best Sharpe Fund]
Name of the fund with the highest Sharpe ratio (excludes benchmark).
```dax
[Best Sharpe Fund] =
VAR best_row =
    TOPN(
        1,
        FILTER(vw_fund_performance,
            NOT ISBLANK(vw_fund_performance[sharpe_ratio])
                && vw_fund_performance[is_benchmark] = FALSE),
        vw_fund_performance[sharpe_ratio], DESC
    )
RETURN MINX(best_row, vw_fund_performance[base_fund_name])
```
> Live value: **Motilal Oswal NASDAQ 100 ETF**

### [Best Sharpe Ratio]
Sharpe ratio of the best fund — displayed on KPI card.
```dax
[Best Sharpe Ratio] =
MAXX(
    FILTER(vw_fund_performance,
        NOT ISBLANK(vw_fund_performance[sharpe_ratio])
            && vw_fund_performance[is_benchmark] = FALSE),
    vw_fund_performance[sharpe_ratio]
)
```
> Live value: **2.25**

### [Best Sharpe Beta]
Beta of the best Sharpe fund — shown as sub-text on KPI card.
```dax
[Best Sharpe Beta] =
VAR best_row =
    TOPN(
        1,
        FILTER(vw_fund_performance,
            NOT ISBLANK(vw_fund_performance[sharpe_ratio])
                && vw_fund_performance[is_benchmark] = FALSE),
        vw_fund_performance[sharpe_ratio], DESC
    )
RETURN MINX(best_row, vw_fund_performance[beta])
```
> Live value: **1.10**

### [Selected Metric Value]
Dynamic metric for the Fund Ranking bar chart. Switches based on MetricSelector slicer.
```dax
[Selected Metric Value] =
VAR selected = SELECTEDVALUE(MetricSelector[Metric Name], "CAGR 5Y")
RETURN
    SWITCH(selected,
        "CAGR 1Y",      SELECTEDVALUE(vw_fund_performance[cagr_1y]),
        "CAGR 3Y",      SELECTEDVALUE(vw_fund_performance[cagr_3y]),
        "CAGR 5Y",      SELECTEDVALUE(vw_fund_performance[cagr_5y]),
        "Sharpe Ratio", SELECTEDVALUE(vw_fund_performance[sharpe_ratio]),
        "Alpha",        SELECTEDVALUE(vw_fund_performance[alpha]),
        SELECTEDVALUE(vw_fund_performance[cagr_5y])
    )
```

### [Fund Rank]
Dense rank of each fund by [Selected Metric Value] descending.
```dax
[Fund Rank] =
RANKX(
    ALL(vw_fund_performance[base_fund_name]),
    [Selected Metric Value],
    , DESC,
    DENSE
)
```

---

## 2. Returns

### [CAGR 1Y]
Average 1-year CAGR across non-benchmark funds in filter context.
```dax
[CAGR 1Y] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[cagr_1y])),
    vw_fund_performance[cagr_1y]
)
```
> Live value: **14.42%**

### [CAGR 3Y]
```dax
[CAGR 3Y] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[cagr_3y])),
    vw_fund_performance[cagr_3y]
)
```
> Live value: **17.11%**

### [CAGR 5Y]
```dax
[CAGR 5Y] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[cagr_5y])),
    vw_fund_performance[cagr_5y]
)
```
> Live value: **14.68%**

### [Avg Alpha]
Average Jensen's Alpha across non-benchmark funds. Positive = above CAPM expectation.
```dax
[Avg Alpha] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[alpha])),
    vw_fund_performance[alpha]
)
```
> Live value: **5.53%**

### [Avg Beta]
Average beta vs Nifty 50. β > 1 = more volatile than market.
```dax
[Avg Beta] =
AVERAGEX(
    FILTER(vw_fund_performance, NOT ISBLANK(vw_fund_performance[beta])),
    vw_fund_performance[beta]
)
```
> Live value: **0.84**

### [Rolling Return 1Y vs Benchmark]
Spread between portfolio avg 1Y CAGR and Nifty 50 1Y return. Positive = outperformance.
```dax
[Rolling Return 1Y vs Benchmark] =
VAR fund_ret = AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[cagr_1y])),
    vw_fund_performance[cagr_1y]
)
VAR bench_ret = CALCULATE(
    MAXX(vw_fund_performance, vw_fund_performance[cagr_1y]),
    vw_fund_performance[is_benchmark] = TRUE
)
RETURN
    IF(NOT ISBLANK(fund_ret) && NOT ISBLANK(bench_ret), fund_ret - bench_ret)
```
> Live value: **+13.76%** (funds well ahead of benchmark in 1Y)

### [Top Performer CAGR]
Highest CAGR 5Y across all non-benchmark funds.
```dax
[Top Performer CAGR] =
MAXX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[cagr_5y])),
    vw_fund_performance[cagr_5y]
)
```
> Live value: **27.34%** (NASDAQ 100 ETF)

### [Fund Rank by Category]
Dense rank within SEBI sub_category by 3Y CAGR. Used in the Category Leaderboard table on Page 2.
```dax
[Fund Rank by Category] =
VAR current_cagr = SELECTEDVALUE(vw_fund_performance[cagr_3y])
VAR current_cat  = SELECTEDVALUE(vw_fund_performance[sub_category])
RETURN
    IF(
        NOT ISBLANK(current_cagr),
        RANKX(
            FILTER(
                ALL(vw_fund_performance),
                vw_fund_performance[sub_category] = current_cat
                    && NOT ISBLANK(vw_fund_performance[cagr_3y])
                    && vw_fund_performance[is_benchmark] = FALSE
            ),
            vw_fund_performance[cagr_3y],
            current_cagr, DESC, DENSE
        )
    )
```

---

## 3. Risk

### [Rf]
RBI repo rate — risk-free rate referenced by Sharpe, Sortino, Treynor measures.
```dax
[Rf] = 6.5
```

### [Avg Sharpe Ratio]
Average Sharpe ratio across non-benchmark funds. Higher = better risk-adjusted return.
```dax
[Avg Sharpe Ratio] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[sharpe_ratio])),
    vw_fund_performance[sharpe_ratio]
)
```
> Live value: **-0.79** (avg pulled down by Liquid/Bank ETFs with negative Sharpe)

### [Avg Sortino Ratio]
Sortino penalises only downside volatility — better measure for asymmetric return funds.
```dax
[Avg Sortino Ratio] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[sortino_ratio])),
    vw_fund_performance[sortino_ratio]
)
```
> Live value: **-1.28**

### [Avg Treynor Ratio]
Excludes funds with Beta < 0.05 to prevent division-near-zero distortion (LIQUIDBEES Beta ≈ 0).
```dax
[Avg Treynor Ratio] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[treynor_ratio])
            && vw_fund_performance[beta] > 0.05),
    vw_fund_performance[treynor_ratio]
)
```

### [Avg Volatility 1Y]
Average annualised std deviation across non-benchmark funds.
```dax
[Avg Volatility 1Y] =
AVERAGEX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[std_dev_1y])),
    vw_fund_performance[std_dev_1y]
)
```
> Live value: **15.31%**

### [Max Drawdown (Worst)]
Most negative peak-to-trough loss among selected funds. Used as headline risk KPI.
```dax
[Max Drawdown (Worst)] =
MINX(
    FILTER(vw_fund_performance,
        vw_fund_performance[is_benchmark] = FALSE
            && NOT ISBLANK(vw_fund_performance[max_drawdown])),
    vw_fund_performance[max_drawdown]
)
```
> Live value: **-50%** (NASDAQ 100 ETF — high drawdown, high return)

### [Risk Tier Distribution]
Row count per risk tier — used in donut chart (Power BI groups by vw_risk_summary[risk_tier] on axis).
```dax
[Risk Tier Distribution] =
COUNTROWS(vw_risk_summary)
```

### [Quadrant Label]
Places each fund in one of four quadrants relative to benchmark return and volatility.
Used in the Risk vs Return scatter chart tooltip/legend.
```dax
[Quadrant Label] =
VAR r       = SELECTEDVALUE(vw_fund_performance[cagr_5y])
VAR v       = SELECTEDVALUE(vw_fund_performance[std_dev_1y])
VAR bench_r = CALCULATE(MAXX(vw_fund_performance, vw_fund_performance[cagr_5y]),  vw_fund_performance[is_benchmark] = TRUE)
VAR bench_v = CALCULATE(MAXX(vw_fund_performance, vw_fund_performance[std_dev_1y]), vw_fund_performance[is_benchmark] = TRUE)
RETURN
    SWITCH(TRUE(),
        r >= bench_r && v <= bench_v, "Efficient",
        r >= bench_r && v >  bench_v, "High Risk/High Reward",
        r <  bench_r && v <= bench_v, "Defensive",
        "Avoid"
    )
```

---

## 4. Investor

### [Total Investors]
Total distinct investor count in the current filter context.
```dax
[Total Investors] =
DISTINCTCOUNT(Fact_Transactions[investor_key])
```
> Live value: **500**

### [Investors with Active SIP]
Count of investors with at least one SIP transaction.
```dax
[Investors with Active SIP] =
CALCULATE(
    DISTINCTCOUNT(Fact_Transactions[investor_key]),
    Fact_Transactions[transaction_type] = "SIP"
)
```
> Live value: **500**

### [Redemption Rate %]
Share of total transaction volume (₹) that is redemptions. High = capital flight signal.
```dax
[Redemption Rate %] =
VAR redemptions = CALCULATE(
    SUM(Fact_Transactions[amount]),
    Fact_Transactions[transaction_type] = "Redemption"
)
VAR total_txn = SUM(Fact_Transactions[amount])
RETURN DIVIDE(redemptions, total_txn, 0) * 100
```
> Live value: **2.27%**

### [Avg Investment per Investor]
Mean total invested (SIP + Lumpsum) per investor.
```dax
[Avg Investment per Investor] =
DIVIDE(
    CALCULATE(
        SUM(Fact_Transactions[amount]),
        Fact_Transactions[transaction_type] IN {"SIP", "Lumpsum"}
    ),
    [Total Investors]
)
```
> Live value: **₹5,79,556**

### [Total SIP Inflow]
Sum of all SIP transaction amounts in the filter context.
```dax
[Total SIP Inflow] =
CALCULATE(
    SUM(Fact_Transactions[amount]),
    Fact_Transactions[transaction_type] = "SIP"
)
```
> Live value: **₹8.70 Cr**

### [SIP Growth % MoM]
Month-over-month SIP inflow growth. Requires date context (use in line chart over Dim_Date).
```dax
[SIP Growth % MoM] =
VAR current_month = CALCULATE([Total SIP Inflow])
VAR prior_month   = CALCULATE(
    [Total SIP Inflow],
    DATEADD(Dim_Date[full_date], -1, MONTH)
)
RETURN
    IF(
        NOT ISBLANK(prior_month) && prior_month <> 0,
        DIVIDE(current_month - prior_month, prior_month) * 100
    )
```

### [Cumulative SIP Invested]
Running total of SIP + Lumpsum over time. Use in an area chart with Dim_Date on X-axis.
```dax
[Cumulative SIP Invested] =
CALCULATE(
    SUM(Fact_Transactions[amount]),
    Fact_Transactions[transaction_type] IN {"SIP", "Lumpsum"},
    FILTER(
        ALL(Dim_Date),
        Dim_Date[full_date] <= MAX(Dim_Date[full_date])
    )
)
```
> Live value (total): **₹28.98 Cr**

---

## Visual ↔ Measure Map

| Measure | Page | Visual |
|---|---|---|
| [Total AUM (Formatted)] | 1 Executive | KPI card — blue |
| [AUM YoY %] | 1 Executive | KPI card footer |
| [Funds Beating Benchmark] | 1 Executive | KPI card — green (numerator) |
| [Total Funds Count] | 1 Executive | KPI card — green (denominator) |
| [Funds Beating Benchmark %] | 1 Executive | KPI card footer |
| [Best Sharpe Fund] | 1 Executive | KPI card — amber (value) |
| [Best Sharpe Ratio] | 1 Executive | KPI card footer |
| [Best Sharpe Beta] | 1 Executive | KPI card footer |
| [Selected Metric Value] | 1 Executive | Bar chart — Fund Ranking |
| [Fund Rank] | 1 Executive | Bar chart sort order |
| [Quadrant Label] | 1 Executive | Scatter tooltip/legend |
| [Benchmark Return] | 1 Executive | Scatter reference line (Y) |
| [Benchmark Volatility] | 1 Executive | Scatter reference line (X) |
| [CAGR 1Y / 3Y / 5Y] | 1 & 2 | Matrix columns, bar chart |
| [Avg Alpha] | 1 & 2 | Matrix column, bar chart |
| [Avg Beta] | 1 & 2 | Matrix column |
| [Top Performer CAGR] | 2 Fund Perf | KPI card |
| [Rolling Return 1Y vs Benchmark] | 2 Fund Perf | Clustered bar |
| [Fund Rank by Category] | 2 Fund Perf | Category leaderboard table |
| [Avg Sharpe Ratio] | 4 Risk | KPI card |
| [Avg Sortino Ratio] | 4 Risk | KPI card / table |
| [Avg Treynor Ratio] | 4 Risk | Table |
| [Avg Volatility 1Y] | 4 Risk | KPI card |
| [Max Drawdown (Worst)] | 4 Risk | KPI card |
| [Risk Tier Distribution] | 4 Risk | Donut chart |
| [Rf] | All | Referenced by Sharpe/Sortino |
| [Total Investors] | 3 Investor | KPI card |
| [Investors with Active SIP] | 3 Investor | KPI card |
| [Redemption Rate %] | 3 Investor | KPI card, gauge |
| [Avg Investment per Investor] | 3 Investor | KPI card |
| [Total SIP Inflow] | 3 Investor | Area chart |
| [SIP Growth % MoM] | 3 Investor | Line chart |
| [Cumulative SIP Invested] | 3 Investor | Area chart |

---

## Data Notes (as of 2026-06-01)

| Fund | CAGR 5Y | Sharpe | Quadrant |
|---|---|---|---|
| NASDAQ 100 ETF (MON100) | 27.34% | 2.25 | Efficient |
| Bharat 22 ETF | 25.61% | 0.40 | Efficient |
| Gold BeES | 24.82% | 1.50 | Efficient |
| Junior BeES | 14.52% | 0.18 | Efficient |
| Nifty BeES | 10.19% | -0.68 | Defensive |
| SBI Nifty 50 ETF | 10.16% | -0.70 | Defensive |
| Bank BeES (Nippon) | 9.76% | -0.36 | Defensive |
| SBI Bank ETF | 9.74% | -0.36 | Defensive |
| HDFC Nifty 50 | — (< 5Y) | -0.68 | — |
| MON 500 ETF | — (< 3Y) | -0.30 | — |
| Liquid BeES | 0% | -10.0 | Avoid |

**Benchmark (Nifty 50):** CAGR 5Y = 11.67%, Std Dev = 21.85%
