# Power BI Dashboard Build Guide
# mf_analytics_dashboard.pbix — 4 Pages

**Reference design:** `mf_analytics_dashboard_v2.html`
**Theme file:** `powerbi/theme_mf_analytics.json`
**All measures:** `Executive_measures` table
**Primary data table for visuals:** `vw_fund_performance`

Apply theme first: View → Themes → Browse → `theme_mf_analytics.json`

---

## Global Setup (do once)

### Canvas size
File → Options → Report Settings → Canvas size → Custom: **1280 × 800 px**

### Header shape (all pages)
Insert → Rectangle → full width, height 44px, top 0
- Fill: gradient — Left #0078D4, Right #005A9E
- Border: none
- Add Text Box over it: "Mutual Fund Analytics Platform" font 14px bold white

### Toolbar strip
Rectangle, height 30px, top 44px, full width
- Fill: white, bottom border #E1E1E1 0.5px

### Footer strip
Rectangle, height 22px, bottom 0, full width
- Fill: white, top border #E1E1E1 0.5px

---

## Page 1 — Executive Overview

**Page name:** `Executive`
**Tab color:** #0078D4

### Slicer — Asset Class (toolbar)
- Visual: **Slicer**
- Field: `vw_fund_performance[asset_class]`
- Style: Horizontal buttons, multi-select
- Position: inside toolbar strip, left side
- Values visible: All Classes / Equity / Debt / Hybrid / Gold / Liquid

### KPI Card 1 — Portfolio AUM (blue)
- Visual: **Card** (new card visual)
- Value: `[Total AUM (Formatted)]`
- Callout: `[Total AUM (Formatted)]`
- Reference label: `[AUM YoY %]`
- Top accent bar color: **#0078D4**
- Size: W=380 H=90, top-left below toolbar

### KPI Card 2 — Beating Nifty 50 (green)
- Visual: **Card**
- Callout value expression:
  ```
  [Funds Beating Benchmark] & " / " & [Total Funds Count]
  ```
- Reference label: `[Funds Beating Benchmark %]`
- Top accent bar color: **#107C10**
- Size: W=380 H=90, same row, middle

### KPI Card 3 — Best Risk-Adjusted (amber)
- Visual: **Card**
- Callout value: `[Best Sharpe Fund]`
- Reference label expression:
  ```
  "Sharpe: " & FORMAT([Best Sharpe Ratio],"0.00") & "  ·  Beta: " & FORMAT([Best Sharpe Beta],"0.00")
  ```
- Top accent bar color: **#FFB900**
- Size: W=380 H=90, same row, right

---

### Fund Ranking Bar Chart (left, large)
- Visual: **Bar chart** (horizontal)
- Y-axis: `vw_fund_performance[base_fund_name]`
- X-axis: `[Selected Metric Value]`
- Sort: by `[Fund Rank]` ascending
- Filter: `vw_fund_performance[is_benchmark] = FALSE`
- Data labels: ON, format as percentage
- Color rules (conditional format on value):
  - ≥ 15% → #107C10 (green)
  - 8–15% → #FFB900 (amber)
  - < 8% → #E74856 (red)
- Size: W=450 H=270, below KPI row, left

**Metric Switcher Slicer (above bar chart):**
- Visual: **Slicer**
- Field: `MetricSelector[Metric Name]`
- Style: Horizontal tiles, single-select
- Default selection: CAGR 5Y

> **How it works:** MetricSelector table has 5 rows (CAGR 1Y / 3Y / 5Y / Sharpe Ratio / Alpha).
> When user clicks a tile, `[Selected Metric Value]` SWITCH returns the matching column from vw_fund_performance.
> `[Fund Rank]` re-ranks accordingly. Bar chart auto-re-sorts.

---

### Risk vs Return Scatter (middle)
- Visual: **Scatter chart**
- X-axis: `vw_fund_performance[std_dev_1y]` — label "Volatility (Std Dev %)"
- Y-axis: `vw_fund_performance[cagr_5y]` — label "CAGR 5Y %"
- Details: `vw_fund_performance[base_fund_name]`
- Legend: `[Quadrant Label]` (measure as legend — place as tooltip field)
- Size (bubble): constant or `vw_fund_performance[sharpe_ratio]`
- Filter: `vw_fund_performance[is_benchmark] = FALSE`
- Reference lines:
  - Y constant line: value = `[Benchmark Return]` (11.67), label "Nifty 5Y", color #A4262C dashed
  - X constant line: value = `[Benchmark Volatility]` (21.85), label "Nifty Vol", color #A4262C dashed
- Legend colors:
  - Efficient → #107C10
  - High Risk/High Reward → #FFB900
  - Defensive → #0078D4
  - Avoid → #A4262C
- Size: W=300 H=270, same row, middle

---

### Needs Attention + Asset Class Mix (right column)
Split this panel into two sections in one chart-card:

**Top section — Needs Attention table:**
- Visual: **Table**
- Columns:
  - `vw_fund_performance[base_fund_name]` → "Fund"
  - `vw_fund_performance[sharpe_ratio]` → "Sharpe" (conditional format: < 0 = red)
  - `vw_fund_performance[max_drawdown]` → "Max DD" (conditional format: < -25% = amber)
  - `vw_fund_performance[cagr_1y]` → "1Y Ret" (conditional format: < 0 = red)
- Filter: show only funds where `sharpe_ratio < 0 OR max_drawdown < -20`
- Sort: by sharpe_ratio ascending (worst first)
- Style: compact, no grid lines, row highlight on hover
- Size: W=300 H=150, right panel top

**Bottom section — Asset Class Mix donut:**
- Visual: **Donut chart**
- Legend: `vw_fund_performance[asset_class]`
- Values: `COUNT(vw_fund_performance[base_fund_name])`
- Filter: `is_benchmark = FALSE`
- Colors: Equity ETF #0078D4, Index Fund #00B294, Gold #FFB900, Liquid #E74856
- Size: W=300 H=110, right panel bottom

---

### Fund Performance Matrix (full width, bottom)
- Visual: **Matrix** or **Table**
- Rows: `vw_fund_performance[base_fund_name]`
- Columns (in order):
  | Column | Field | Format |
  |---|---|---|
  | Fund Name | `vw_fund_performance[base_fund_name]` | text |
  | AMC | `Dim_Fund[short_name]` (via slicer) or `vw_fund_performance[amc_name]` | text |
  | CAGR 1Y | `vw_fund_performance[cagr_1y]` | 0.0% |
  | CAGR 3Y | `vw_fund_performance[cagr_3y]` | 0.0% |
  | CAGR 5Y | `vw_fund_performance[cagr_5y]` | 0.0% |
  | Sharpe | `vw_fund_performance[sharpe_ratio]` | 0.00 |
  | Sortino | `vw_fund_performance[sortino_ratio]` | 0.00 |
  | Beta | `vw_fund_performance[beta]` | 0.00 |
  | Alpha | `vw_fund_performance[alpha]` | 0.0% |
  | Max DD% | `vw_fund_performance[max_drawdown]` | 0.0% |

- **Conditional formatting** (background color by rules):
  - CAGR columns: Top 33% → green (#E8F5E9), Mid → amber (#FFF8E1), Bottom → red (#FFEBEE)
  - Sharpe/Sortino: > 1 → green, 0–1 → amber, < 0 → red
  - Beta: < 0.5 → green, 0.5–1 → neutral, > 1 → red
  - Alpha: > 10% → green, 0–10% → amber, < 0 → red
  - Max DD: > -15% → green, -25% to -15% → amber, < -25% → red
- Sort: CAGR 5Y descending
- Filter: `is_benchmark = FALSE`
- Header background: #0078D4, text white
- Size: full width, H=150, bottom of page

---

## Page 2 — Fund Performance

**Page name:** `Fund Performance`

### KPIs (top row, 4 cards)
1. [Top Performer CAGR] — best CAGR 5Y — green card
2. [CAGR 3Y] — avg 3Y — blue card
3. [Rolling Return 1Y vs Benchmark] — alpha over benchmark — green/red conditional
4. [Avg Alpha] — avg Jensen's alpha — amber card

### Fund vs Benchmark Bar Chart
- Visual: **Clustered bar chart**
- Axis: `vw_fund_performance[base_fund_name]`
- Bars: `vw_fund_performance[cagr_1y]` (Portfolio) + `[Benchmark Return]` (Nifty, constant line)
- Filter: `is_benchmark = FALSE`
- Sort: value descending

### CAGR Trend Line Chart
- Visual: **Line chart**
- X-axis: `Dim_Date[full_date]` (Year/Quarter hierarchy)
- Y-axis: `[CAGR 1Y]`
- Legend: `vw_fund_performance[asset_class]`

### Category Leaderboard Table
- Visual: **Table**
- Columns: Fund Name, sub_category, CAGR 3Y, [Fund Rank by Category], Sharpe, Alpha
- Sort: [Fund Rank by Category] ascending

### Metric Distribution (small multiples)
- Visual: **Bar chart** (small multiples)
- Value: `[Avg Alpha]`
- Small multiple field: `vw_fund_performance[asset_class]`

---

## Page 3 — Investor Analytics

**Page name:** `Investor`

### KPIs (top row, 4 cards)
1. [Total Investors] — 500 — blue card
2. [Investors with Active SIP] — 500 — green card
3. [Redemption Rate %] — 2.27% — amber card (red if > 10%)
4. [Avg Investment per Investor] — ₹5.79L — blue card

### SIP Inflow Trend (area chart)
- Visual: **Area chart**
- X-axis: `Dim_Date[full_date]` (Month level)
- Y-axis: `[Total SIP Inflow]`
- Color: #0078D4 fill, 60% opacity

### Cumulative Investment (area chart)
- Visual: **Area chart**
- X-axis: `Dim_Date[full_date]`
- Y-axis: `[Cumulative SIP Invested]`
- Color: #107C10

### SIP MoM Growth (line chart)
- Visual: **Line chart**
- X-axis: `Dim_Date[full_date]` (Month)
- Y-axis: `[SIP Growth % MoM]`
- Reference line: 0% (constant)
- Color above 0 = green, below 0 = red (conditional color)

### Investor Segmentation Table
- Visual: **Matrix**
- Source: `vw_investor_segmentation`
- Rows: investor segment/tier columns from view
- Values: count, avg investment

### Redemption Gauge
- Visual: **Gauge**
- Value: `[Redemption Rate %]`
- Min: 0, Target: 5, Max: 30
- Color zones: green < 5%, amber 5–15%, red > 15%

---

## Page 4 — Risk

**Page name:** `Risk`

### KPIs (top row, 4 cards)
1. [Avg Sharpe Ratio] — -0.79 — conditional (green > 1, amber 0–1, red < 0)
2. [Avg Volatility 1Y] — 15.31% — amber card
3. [Max Drawdown (Worst)] — -50% — red card
4. [Avg Sortino Ratio] — -1.28 — conditional

### Risk Tier Donut
- Visual: **Donut chart**
- Legend: `vw_risk_summary[risk_tier]`
- Values: `[Risk Tier Distribution]`
- Colors: Low=#107C10, Moderate=#FFB900, High=#E74856, Very High=#A4262C

### Drawdown Bar Chart
- Visual: **Bar chart** (horizontal)
- Axis: `vw_fund_performance[base_fund_name]`
- Value: `vw_fund_performance[max_drawdown]` (negative bars)
- Color: red gradient, sort ascending (worst first)

### Sharpe vs Sortino Scatter
- Visual: **Scatter chart**
- X: `vw_fund_performance[sharpe_ratio]`
- Y: `vw_fund_performance[sortino_ratio]`
- Details: `vw_fund_performance[base_fund_name]`
- Reference line X=0, Y=0 (both dashed red)
- Quadrant labels: "Efficient" (top-right), "Avoid" (bottom-left)

### Risk Metrics Table (full width bottom)
- Visual: **Table**
- Columns: Fund, Sharpe, Sortino, Treynor, Beta, Alpha, Max DD, Std Dev
- All from `vw_fund_performance` direct columns
- Conditional format: same rules as Page 1 matrix

---

## Slicer Sync Settings
After building all 4 pages, set up slicer sync:
- View → Sync Slicers
- `asset_class` slicer: sync visible on all 4 pages
- This allows the asset class filter in the toolbar to filter all pages simultaneously

---

## Conditional Formatting Quick Reference

| Metric | Green | Amber | Red |
|---|---|---|---|
| CAGR | > 15% | 5–15% | < 5% |
| Sharpe | > 1.0 | 0–1.0 | < 0 |
| Sortino | > 1.0 | 0–1.0 | < 0 |
| Alpha | > 10% | 0–10% | < 0 |
| Beta | < 0.7 | 0.7–1.0 | > 1.0 |
| Max DD | > -15% | -25% to -15% | < -25% |
| Redemption | < 5% | 5–15% | > 15% |

Colors: Green = #E8F5E9 / #107C10, Amber = #FFF8E1 / #856400, Red = #FFEBEE / #A4262C

---

*Last updated: 2026-06-01 · All 38 measures deployed via PowerBI MCP*
