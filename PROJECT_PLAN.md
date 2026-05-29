# 📅 PROJECT PLAN — Mutual Fund Analytics Platform

**Duration:** 4 weeks
**Daily Commitment:** 6 hours actual project time (8-10 hr available, 2-4 hr buffer for applications + Finonus ops)
**Start Date:** _Day 1_

---

## 🎯 Hard Constraints

| Constraint | Limit | Mitigation |
|---|---|---|
| Azure free credit | 15 days | Cloud burst in Week 2, screenshots + Loom video before expiry |
| Power BI free | 1 month | Capture Power BI Service screenshots in Week 2-3 |
| Job applications | 10/day must continue | Mornings: project, evenings: applications |
| Project deadline | 4 weeks | Aggressive scope cuts (see "Out of Scope" below) |

---

## 🚦 Critical Milestones (DO NOT MISS)

| Day | Milestone | Why Critical |
|---|---|---|
| **Day 7** | Local PostgreSQL star schema fully loaded + all metrics computed | Streamlit fallback ready before Azure activation |
| **Day 8** | Azure subscription activated, 15-day clock starts | Cloud burst window opens |
| **Day 14** | Loom video + all Azure screenshots captured | Last day of cloud window |
| **Day 21** | Streamlit app deployed on Hostinger VPS | Post-Azure life secured |
| **Day 28** | Case study PDF + LinkedIn post + resume bullets | Portfolio launch ready |

---

## 📆 WEEK 1 — Foundation & Data Pipeline (Off-Cloud)

### Day 1 — Data Acquisition
- [ ] Set up Python virtual environment, install dependencies
- [ ] Build `fetch_yahoo_finance.py` — pull NAV data for top 30 Indian MFs + Nifty 50 benchmark
- [ ] Build `fetch_amfi_nav.py` — scrape AMFI historical NAV
- [ ] Download Kaggle SIP/investor dataset
- [ ] Validate row counts, date ranges, schema
- [ ] Commit to GitHub: `feat: data ingestion scripts`

**Deliverable:** Raw data files in `data/raw/`

### Day 2 — Data Cleaning & Validation
- [ ] Build `clean_nav.py` — handle missing dates, outliers, NA values
- [ ] Build `clean_transactions.py` — investor data cleanup
- [ ] Build `data_quality.py` — schema enforcement, anomaly detection
- [ ] Write unit tests for data quality checks
- [ ] Commit: `feat: data cleaning + quality framework`

### Day 3 — Star Schema Design
- [ ] Design dimension tables: Dim_Fund, Dim_Date, Dim_Investor, Dim_AMC, Dim_Category
- [ ] Design fact tables: Fact_NAV, Fact_Transactions, Fact_SIP, Fact_Returns
- [ ] Write DDL scripts in `sql/ddl/`
- [ ] Set up local PostgreSQL, create database `mf_analytics`
- [ ] Run DDL, verify schema
- [ ] Commit: `feat: star schema DDL`

### Day 4 — ETL: Load to Star Schema
- [ ] Build `load_dimensions.py` — populate all Dim tables
- [ ] Build `load_facts.py` — populate Fact tables with proper foreign keys
- [ ] Verify row counts, referential integrity
- [ ] Build `Dim_Date` generator (2015–2026 daily)
- [ ] Commit: `feat: ETL pipeline to star schema`

### Day 5 — Financial Metrics (Part 1)
- [ ] Build `metrics_returns.py` — CAGR, rolling returns (1Y/3Y/5Y)
- [ ] Build `metrics_risk.py` — std dev, volatility, max drawdown
- [ ] Validate against known benchmark values (e.g., HDFC Top 100 published CAGR)
- [ ] Commit: `feat: returns + risk metrics`

### Day 6 — Financial Metrics (Part 2) + SQL Layer
- [ ] Build `metrics_risk_adjusted.py` — Sharpe, Sortino, Treynor
- [ ] Build `metrics_market.py` — Alpha, Beta vs Nifty 50
- [ ] Write SQL views: `vw_fund_performance`, `vw_investor_segmentation`, `vw_risk_summary`
- [ ] Write stored procedures: `sp_compute_aum`, `sp_top_funds_by_category`
- [ ] Commit: `feat: risk-adjusted metrics + SQL analytical layer`

### Day 7 — Week 1 Review & Buffer
- [ ] Run end-to-end local pipeline, verify all metrics
- [ ] Generate exploratory notebook with key visualizations
- [ ] Document data dictionary (`docs/data_dictionary.md`)
- [ ] **Streamlit fallback test:** ensure local Postgres + metrics work standalone
- [ ] Commit: `docs: data dictionary + week 1 wrap-up`

---

## 📆 WEEK 2 — Azure Cloud Burst 🔥 (15-Day Clock Starts)

### Day 8 — Azure Activation & Setup
- [ ] Activate Azure free trial (₹13,300 credit / $200)
- [ ] **Set budget alert at ₹500** (critical)
- [ ] Create Resource Group: `rg-mf-analytics`
- [ ] Provision: Storage Account (Blob), Azure SQL Database (Basic tier), Key Vault
- [ ] Store credentials in Key Vault
- [ ] Commit: `feat: Azure infra provisioned`

### Day 9 — Blob Ingestion + ADF Setup
- [ ] Upload raw data to Blob container `raw/`
- [ ] Create ADF instance, link to Blob + SQL DB
- [ ] Build ADF pipeline: `pl_raw_to_sql` (Copy Activity, parameterized)
- [ ] Test pipeline run
- [ ] Commit: `feat: ADF raw-to-SQL pipeline`

### Day 10 — ADF Transformation Pipeline
- [ ] Build `pl_transform_facts` — orchestrates fact table loads
- [ ] Schedule pipeline (daily trigger)
- [ ] Add monitoring + email alert on failure
- [ ] Commit: `feat: ADF transformation pipeline`

### Day 11 — Azure Function (Light Compute)
- [ ] Build Python Azure Function: `fn_compute_daily_metrics`
- [ ] Trigger: HTTP + scheduled
- [ ] Deploy to Function App
- [ ] Test integration with SQL DB
- [ ] Commit: `feat: Azure Function for daily metrics`

### Day 12 — Power BI Desktop: Pages 1 & 2
- [ ] Connect Power BI Desktop to Azure SQL DB
- [ ] Build data model (relationships, hierarchies)
- [ ] **Page 1:** Executive Overview (AUM, top funds, KPIs, market summary)
- [ ] **Page 2:** Fund Performance (CAGR trends, rolling returns, benchmark comparison)
- [ ] DAX measures: 20+ core measures documented
- [ ] Commit: `feat: Power BI pages 1-2 + DAX measures`

### Day 13 — Power BI Desktop: Pages 3 & 4
- [ ] **Page 3:** Investor Analytics (SIP trends, segmentation, retention, region-wise)
- [ ] **Page 4:** Risk & Volatility (Sharpe heatmap, drawdown, risk-return scatter)
- [ ] Bookmarks + drill-through + tooltips
- [ ] Commit: `feat: Power BI pages 3-4`

### Day 14 — 🚨 PUBLISH + CAPTURE EVERYTHING 🚨
- [ ] Publish PBIX to Power BI Service
- [ ] Configure scheduled refresh
- [ ] **CAPTURE: 20+ high-resolution screenshots** (all pages, all states)
- [ ] **RECORD: 5-7 minute Loom video walkthrough**
- [ ] Save PBIX file to `powerbi/` folder
- [ ] Export architecture screenshots from Azure Portal
- [ ] Commit: `feat: Power BI published + screenshots + loom video`

---

## 📆 WEEK 3 — ML + Streamlit + Polish

### Day 15 — Prophet NAV Forecasting
- [ ] Build `prophet_nav_forecast.py`
- [ ] Train on top 10 funds, forecast 30/60/90 days
- [ ] Generate confidence intervals
- [ ] Save model artifacts
- [ ] Commit: `feat: Prophet NAV forecasting`

### Day 16 — Streamlit App: SIP Planner + Fund Comparison
- [ ] Set up Streamlit project structure
- [ ] **Tab 1:** SIP Planner (input: amount, tenure, expected return → output: maturity, projection chart)
- [ ] **Tab 2:** Fund Comparison (select 2-3 funds, compare CAGR, Sharpe, drawdown)
- [ ] Connect to local Postgres (Azure fallback ready)
- [ ] Commit: `feat: Streamlit SIP planner + comparison`

### Day 17 — Streamlit App: Risk Profiler + Forecast Viewer
- [ ] **Tab 3:** Risk Profiler (questionnaire → portfolio recommendation)
- [ ] **Tab 4:** NAV Forecast Viewer (select fund → Prophet forecast chart)
- [ ] Add download buttons (PDF report export)
- [ ] Commit: `feat: Streamlit risk profiler + forecast`

### Day 18 — Hostinger VPS Deployment
- [ ] Set up Streamlit on existing Hostinger VPS (srv973497.hstgr.cloud)
- [ ] Configure Traefik reverse proxy (already running on VPS)
- [ ] SSL via Let's Encrypt
- [ ] Subdomain: `mf.finonuscapital.com` or similar
- [ ] Test from external network
- [ ] Commit: `chore: deploy Streamlit to VPS`

### Day 19 — End-to-End Testing
- [ ] Run full pipeline (ingestion → SQL → metrics → ML → Streamlit)
- [ ] Fix bugs, edge cases
- [ ] Test on different fund categories
- [ ] Commit: `fix: e2e testing + bug fixes`

### Day 20 — Performance Optimization
- [ ] Add SQL indexes on Fact table joins
- [ ] Cache expensive Streamlit computations
- [ ] Optimize DAX measures (variables, SUMX → SUMMARIZE where possible)
- [ ] Commit: `perf: query + DAX optimization`

### Day 21 — Week 3 Review
- [ ] Full system health check
- [ ] Update README with live links
- [ ] Backup all artifacts
- [ ] Commit: `docs: week 3 progress update`

---

## 📆 WEEK 4 — Documentation & Portfolio Launch

### Day 22 — Architecture Diagram (Polished)
- [ ] Create proper architecture diagram (draw.io or Excalidraw)
- [ ] Export PNG + SVG
- [ ] Embed in README
- [ ] Commit: `docs: polished architecture diagram`

### Day 23 — GitHub README Final Polish
- [ ] Add live demo links (Streamlit URL)
- [ ] Embed Loom video
- [ ] Add screenshots gallery
- [ ] Tech stack badges
- [ ] Commit: `docs: README final polish`

### Day 24 — Case Study PDF
- [ ] Write case study (10-15 pages): problem, architecture, implementation, results, learnings
- [ ] Include screenshots, code samples, KPI definitions
- [ ] Generate PDF via ReportLab
- [ ] Save to `docs/case_study/`
- [ ] Commit: `docs: case study PDF`

### Day 25 — LinkedIn Project Post
- [ ] Draft LinkedIn carousel post (8-10 slides)
- [ ] Generate visuals
- [ ] Schedule for high-engagement time
- [ ] Commit: `docs: LinkedIn post draft`

### Day 26 — Resume Integration
- [ ] Write 3 resume bullets (impact + tech + scale)
- [ ] Update LinkedIn profile project section
- [ ] Update portfolio website (github.com/Skpkush)
- [ ] Commit: `docs: resume + LinkedIn updates`

### Day 27 — Interview Prep Integration
- [ ] Write 10 expected interview questions + answers about this project
- [ ] Practice 5-min project pitch
- [ ] Record practice video, review
- [ ] Commit: `docs: interview prep`

### Day 28 — Buffer & Launch
- [ ] Final review of all deliverables
- [ ] Publish LinkedIn post
- [ ] Send to 5 recruiters as portfolio sample
- [ ] Celebrate 🎉

---

## 🚫 OUT OF SCOPE (Hard Cuts)

These were in the original spec but **deliberately cut** for 4-week feasibility:

| Cut Item | Reason |
|---|---|
| Monte Carlo simulation | 2-3 days debug time, low recruiter ROI |
| Efficient Frontier optimization | Niche, math-heavy |
| Row-Level Security (RLS) | Requires Power BI Pro |
| Azure Databricks | High cost for 15-day window |
| Investor churn ML model | No real investor data, synthetic weakens credibility |
| Calculation groups, field parameters | DAX showmanship, low interview value |
| Deneb / Vega-Lite visuals | Vanity feature |
| Cohort analysis | Mention in case study only |
| Hypothesis testing module | Mention in case study only |

These will be added as **"Future Enhancements"** section in case study PDF.

---

## 📊 Success Criteria

| Metric | Target |
|---|---|
| GitHub stars (3 months) | 20+ |
| LinkedIn post impressions | 5,000+ |
| Resume callback rate (post-project) | 3x current |
| Interview talking points | 10+ specific, technical |
| Live demo URL working | Yes (Streamlit on VPS) |

---

## 🔄 Daily Standup Template

```
**Date:** YYYY-MM-DD
**Day #:** X of 28
**Yesterday:** [what was completed]
**Today:** [what will be done — must align with plan above]
**Blockers:** [any issues]
**Applications submitted today:** [count, target: 10]
```

Commit this daily to `docs/daily_log.md`.
