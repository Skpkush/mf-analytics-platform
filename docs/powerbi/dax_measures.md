# DAX Measures — Mutual Fund Analytics Platform

**Power BI file:** `powerbi/mf_analytics.pbix`
**Data model:** Import mode, refreshed nightly from Azure SQL `mf-analytics-db`
**Total measures:** 25

All measures are defined in a dedicated `_Measures` table to keep the model clean.
Risk-free rate constant: **6.5%** (RBI repo rate, stored as `[Rf]` measure).

---

## Table of Contents

1. [AUM & Portfolio Size](#1-aum--portfolio-size)
2. [Returns & CAGR](#2-returns--cagr)
3. [Risk Metrics](#3-risk-metrics)
4. [Risk-Adjusted Returns](#4-risk-adjusted-returns)
5. [Market Metrics](#5-market-metrics)
6. [Investor Analytics](#6-investor-analytics)
7. [SIP Analytics](#7-sip-analytics)

---

## 1. AUM & Portfolio Size

### [Total AUM]
Total assets under management = sum of (units held × latest NAV) across all investors and funds.
Used on Page 1 Executive KPI card.

```dax
[Total AUM] =
SUMX(
    SUMMARIZE(
        Fact_SIP,
        Fact_SIP[fund_key],
        "@units", SUM( Fact_SIP[current_units_held] )
    ),
    VAR latest_nav =
        CALCULATE(
            LASTNONBLANK( Fact_NAV[nav], 1 ),
            FILTER( Fact_NAV, Fact_NAV[fund_key] = [@fund_key] )
        )
    RETURN [@units] * latest_nav
)
```

### [Total AUM (Formatted)]
Human-readable AUM label for KPI cards (e.g. "₹12.4 Cr").

```dax
[Total AUM (Formatted)] =
VAR aum = [Total AUM]
RETURN
    SWITCH(
        TRUE(),
        aum >= 1e7, FORMAT( aum / 1e7, "₹0.00" ) & " Cr",
        aum >= 1e5, FORMAT( aum / 1e5, "₹0.00" ) & " L",
                    FORMAT( aum,        "₹#,##0" )
    )
```

### [Active Funds Count]
Number of distinct funds that have at least one unit held.

```dax
[Active Funds Count] =
CALCULATE(
    DISTINCTCOUNT( Fact_SIP[fund_key] ),
    Fact_SIP[current_units_held] > 0
)
```

---

## 2. Returns & CAGR

### [CAGR 1Y]
Average 1-year compound annual growth rate across selected funds.
NULL-safe: excludes funds with insufficient history.

```dax
[CAGR 1Y] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[cagr_1y] ) ),
    Fact_Returns[cagr_1y]
)
```

### [CAGR 3Y]
```dax
[CAGR 3Y] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[cagr_3y] ) ),
    Fact_Returns[cagr_3y]
)
```

### [CAGR 5Y]
```dax
[CAGR 5Y] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[cagr_5y] ) ),
    Fact_Returns[cagr_5y]
)
```

### [Best CAGR 5Y Fund]
Name of the fund with the highest 5-year CAGR in the current filter context.
Used in Executive Overview "Top Performer" card.

```dax
[Best CAGR 5Y Fund] =
VAR best_key =
    CALCULATE(
        FIRSTNONBLANK( Fact_Returns[fund_key], 1 ),
        TOPN( 1, Fact_Returns, Fact_Returns[cagr_5y], DESC )
    )
RETURN
    CALCULATE(
        SELECTEDVALUE( Dim_Fund[base_fund_name] ),
        Dim_Fund[fund_key] = best_key
    )
```

### [Rolling Return 1Y vs Benchmark]
Difference between selected fund's 1Y return and Nifty 50 1Y return.
Positive = outperformed benchmark.

```dax
[Rolling Return 1Y vs Benchmark] =
VAR fund_ret =
    CALCULATE( [CAGR 1Y] )
VAR bench_ret =
    CALCULATE(
        SELECTEDVALUE( Fact_Returns[cagr_1y] ),
        Dim_Fund[scheme_code] = "^NSEI"
    )
RETURN
    IF(
        NOT ISBLANK( fund_ret ) && NOT ISBLANK( bench_ret ),
        fund_ret - bench_ret
    )
```

---

## 3. Risk Metrics

### [Avg Volatility 1Y]
Average annualised standard deviation across selected funds (%).

```dax
[Avg Volatility 1Y] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[std_dev_1y] ) ),
    Fact_Returns[std_dev_1y]
)
```

### [Max Drawdown (Worst)]
The largest peak-to-trough loss among selected funds (most negative value = worst).
Used in Risk page headline KPI.

```dax
[Max Drawdown (Worst)] =
MINX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[max_drawdown] ) ),
    Fact_Returns[max_drawdown]
)
```

### [Portfolio Volatility]
Weighted average volatility of the investor's portfolio, weighted by AUM per fund.

```dax
[Portfolio Volatility] =
DIVIDE(
    SUMX(
        FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[std_dev_1y] ) ),
        VAR fund_aum =
            CALCULATE(
                SUMX( Fact_SIP, Fact_SIP[current_units_held] )
                    * LASTNONBLANK( Fact_NAV[nav], 1 ),
                Fact_NAV[fund_key] = Fact_Returns[fund_key]
            )
        RETURN fund_aum * Fact_Returns[std_dev_1y]
    ),
    [Total AUM]
)
```

### [Risk Tier Distribution]
Count of funds per SEBI riskometer tier for the donut chart on the Risk page.

```dax
[Risk Tier Distribution] =
COUNTROWS( FILTER( vw_risk_summary, vw_risk_summary[risk_tier] = SELECTEDVALUE( vw_risk_summary[risk_tier] ) ) )
```

---

## 4. Risk-Adjusted Returns

### [Rf]
Risk-free rate constant (RBI repo rate). Referenced by Sharpe, Sortino, Treynor measures.

```dax
[Rf] = 6.5
```

### [Avg Sharpe Ratio]
Average Sharpe ratio across selected funds. Higher = better risk-adjusted return.

```dax
[Avg Sharpe Ratio] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[sharpe_ratio] ) ),
    Fact_Returns[sharpe_ratio]
)
```

### [Avg Sortino Ratio]
Average Sortino ratio — penalises only downside volatility; better measure for asymmetric returns.

```dax
[Avg Sortino Ratio] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[sortino_ratio] ) ),
    Fact_Returns[sortino_ratio]
)
```

### [Best Sharpe Fund]
Fund name with the highest Sharpe ratio in the current filter context.

```dax
[Best Sharpe Fund] =
VAR best_key =
    CALCULATE(
        FIRSTNONBLANK( Fact_Returns[fund_key], 1 ),
        TOPN( 1, FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[sharpe_ratio] ) ),
              Fact_Returns[sharpe_ratio], DESC )
    )
RETURN
    CALCULATE(
        SELECTEDVALUE( Dim_Fund[base_fund_name] ),
        Dim_Fund[fund_key] = best_key
    )
```

---

## 5. Market Metrics

### [Avg Beta]
Average beta vs Nifty 50 across selected funds. β > 1 = more volatile than market.

```dax
[Avg Beta] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[beta] ) ),
    Fact_Returns[beta]
)
```

### [Avg Alpha]
Average Jensen's Alpha (%). Positive = fund generated returns above CAPM expectation.

```dax
[Avg Alpha] =
AVERAGEX(
    FILTER( Fact_Returns, NOT ISBLANK( Fact_Returns[alpha] ) ),
    Fact_Returns[alpha]
)
```

### [Fund Rank by Category]
Rank of each fund within its SEBI sub_category by selected metric.
Used in the "Category Leaderboard" table visual on Page 2.

```dax
[Fund Rank by Category] =
VAR current_cagr = SELECTEDVALUE( Fact_Returns[cagr_3y] )
VAR current_cat  = SELECTEDVALUE( Dim_Category[sub_category] )
RETURN
    IF(
        NOT ISBLANK( current_cagr ),
        RANKX(
            FILTER(
                ALL( Fact_Returns ),
                CALCULATE(
                    SELECTEDVALUE( Dim_Category[sub_category] ),
                    USERELATIONSHIP( Fact_Returns[fund_key], Dim_Fund[fund_key] )
                ) = current_cat
                    && NOT ISBLANK( Fact_Returns[cagr_3y] )
            ),
            Fact_Returns[cagr_3y],
            current_cagr,
            DESC,
            DENSE
        )
    )
```

---

## 6. Investor Analytics

### [Total Investors]
Total count of investors in the current filter context.

```dax
[Total Investors] =
DISTINCTCOUNT( Dim_Investor[investor_key] )
```

### [Investors with Active SIP]
Count of investors who have at least one SIP transaction in the selected period.

```dax
[Investors with Active SIP] =
CALCULATE(
    DISTINCTCOUNT( Fact_Transactions[investor_key] ),
    Fact_Transactions[transaction_type] = "SIP"
)
```

### [Redemption Rate %]
Proportion of transaction volume (by amount) that is redemptions.
High redemption rate = capital flight signal.

```dax
[Redemption Rate %] =
VAR redemptions =
    CALCULATE(
        SUM( Fact_Transactions[amount] ),
        Fact_Transactions[transaction_type] = "Redemption"
    )
VAR total_txn =
    SUM( Fact_Transactions[amount] )
RETURN
    DIVIDE( redemptions, total_txn, 0 ) * 100
```

### [Avg Investment per Investor]
Mean total invested amount across all investors in the filter context.

```dax
[Avg Investment per Investor] =
DIVIDE(
    CALCULATE( SUM( Fact_Transactions[amount] ),
               Fact_Transactions[transaction_type] IN { "SIP", "Lumpsum" } ),
    [Total Investors]
)
```

---

## 7. SIP Analytics

### [Total SIP Inflow]
Sum of all SIP transaction amounts in the current filter context.

```dax
[Total SIP Inflow] =
CALCULATE(
    SUM( Fact_Transactions[amount] ),
    Fact_Transactions[transaction_type] = "SIP"
)
```

### [SIP Growth % MoM]
Month-over-month growth in total SIP inflow.
Used in the SIP Trend line chart on Page 3.

```dax
[SIP Growth % MoM] =
VAR current_month =
    CALCULATE( [Total SIP Inflow] )
VAR prior_month =
    CALCULATE(
        [Total SIP Inflow],
        DATEADD( Dim_Date[full_date], -1, MONTH )
    )
RETURN
    IF(
        NOT ISBLANK( prior_month ) && prior_month <> 0,
        DIVIDE( current_month - prior_month, prior_month ) * 100
    )
```

### [Cumulative SIP Invested]
Running total of SIP + Lumpsum investments over time.
Used in the investor portfolio value area chart on Page 3.

```dax
[Cumulative SIP Invested] =
CALCULATE(
    SUM( Fact_Transactions[amount] ),
    Fact_Transactions[transaction_type] IN { "SIP", "Lumpsum" },
    FILTER(
        ALL( Dim_Date ),
        Dim_Date[full_date] <= MAX( Dim_Date[full_date] )
    )
)
```

---

## Usage Notes

| Measure | Page | Visual type |
|---|---|---|
| [Total AUM (Formatted)] | Page 1 — Executive | KPI card |
| [CAGR 1Y / 3Y / 5Y] | Page 2 — Fund Performance | Bar chart, table |
| [Best CAGR 5Y Fund] | Page 1 — Executive | Card |
| [Rolling Return 1Y vs Benchmark] | Page 2 — Fund Performance | Clustered bar |
| [Avg Volatility 1Y] | Page 4 — Risk | KPI card |
| [Max Drawdown (Worst)] | Page 4 — Risk | KPI card |
| [Portfolio Volatility] | Page 4 — Risk | Gauge |
| [Avg Sharpe Ratio] | Page 4 — Risk | KPI card |
| [Avg Sortino Ratio] | Page 4 — Risk | Table |
| [Best Sharpe Fund] | Page 1 — Executive | Card |
| [Avg Beta] | Page 2 — Fund Performance | Table |
| [Avg Alpha] | Page 2 — Fund Performance | Table |
| [Fund Rank by Category] | Page 2 — Fund Performance | Table (conditional format) |
| [Total Investors] | Page 3 — Investor Analytics | KPI card |
| [Investors with Active SIP] | Page 3 — Investor Analytics | KPI card |
| [Redemption Rate %] | Page 3 — Investor Analytics | KPI card, gauge |
| [Avg Investment per Investor] | Page 3 — Investor Analytics | KPI card |
| [Total SIP Inflow] | Page 3 — Investor Analytics | Area chart |
| [SIP Growth % MoM] | Page 3 — Investor Analytics | Line chart |
| [Cumulative SIP Invested] | Page 3 — Investor Analytics | Area chart |
| [Risk Tier Distribution] | Page 4 — Risk | Donut chart |
| [Rf] | All pages | Referenced by Sharpe/Sortino/Treynor |
| [Active Funds Count] | Page 1 — Executive | KPI card |
| [Total AUM] | All pages | Base for portfolio calculations |
| [Avg Alpha] | Page 2 — Fund Performance | Bar chart |

---

*Last updated: Day 9 — 2026-05-30*
*Power BI Desktop connection: Azure SQL `mf-analytics-server.database.windows.net` / `mf-analytics-db`*
