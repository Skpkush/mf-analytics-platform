# Mutual Fund Analytics Platform

> Production-style, enterprise-grade Mutual Fund Analytics Platform demonstrating end-to-end Data Engineering, Advanced Analytics, Cloud Architecture, and Executive BI Reporting.

**Built by:** Sumit Kumar Prajapat | [GitHub: Skpkush](https://github.com/Skpkush)
**Status:** ✅ Complete — End-to-end pipeline live (ingestion → Azure ADF → Star Schema → Power BI)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/pandas-2.x-150458?logo=pandas&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?logo=postgresql&logoColor=white)
![Azure](https://img.shields.io/badge/Azure-SQL%20%7C%20ADF%20%7C%20Blob-0078D4?logo=microsoftazure&logoColor=white)
![Power BI](https://img.shields.io/badge/Power%20BI-Desktop-F2C811?logo=powerbi&logoColor=black)
![Prophet](https://img.shields.io/badge/Prophet-NAV%20Forecasting-005571)
![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 📊 Key Metrics

| Metric | Value |
|---|---|
| **NAV rows processed** | ~100K NAV observations |
| **Fund schemes covered** | 14,384 |
| **Funds with computed metrics** | 16 (full time-series) |
| **AMCs covered** | 51 |
| **Power BI dashboard pages** | 4 |
| **Cloud ETL** | Azure Data Factory pipeline (✅ Succeeded) |
| **DAX measures authored** | 25+ |
| **Data model** | Star schema — 5 dimension + 4 fact tables |

---

## 🎯 Business Problem

Asset Management Companies, Wealth Advisors, and FinTech firms need a unified analytics platform that ingests multi-source mutual fund data, computes risk-adjusted performance metrics, segments investors, forecasts NAV trends, and surfaces executive-level insights — all in a scalable cloud architecture.

This platform delivers exactly that.

---

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Data Sources   │───▶│   Azure Blob    │───▶│  Azure Data     │
│  Yahoo Finance  │    │   (Raw Layer)   │    │   Factory       │
│  AMFI India     │    └─────────────────┘    │  (✅ Succeeded) │
│  Kaggle         │                           └─────────────────┘
└─────────────────┘                                     │
                                                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Streamlit App  │◀───│  Power BI       │◀───│  Azure SQL DB   │
│  (Hostinger VPS)│    │  4-Page         │    │  Star Schema    │
└─────────────────┘    │  Dashboard      │    │  5 Dim + 4 Fact │
        ▲              └─────────────────┘    └─────────────────┘
        │                                              │
        │                                              ▼
        │                                     ┌─────────────────┐
        └─────────────────────────────────────│  Python ML      │
                                              │  Prophet NAV    │
                                              │  Forecasting    │
                                              └─────────────────┘
```

**Data flow:** Raw multi-source data lands in Azure Blob → Azure Data Factory orchestrates ingestion → transformation/cleaning in Python → load into a **star schema** (5 dimension + 4 fact tables) on Azure SQL Database (PostgreSQL locally) → 25+ DAX measures power a 4-page Power BI dashboard → Prophet forecasts NAV trajectories → Streamlit surfaces client-facing analytics.

Full diagram: [`docs/architecture/architecture.md`](docs/architecture/architecture.md)

### Star Schema (5 Dim + 4 Fact)

- **Dimensions:** `Dim_Date`, `Dim_AMC`, `Dim_Category`, `Dim_Fund`, `Dim_Investor`
- **Facts:** `Fact_NAV`, `Fact_Transactions`, `Fact_SIP`, `Fact_Returns`

DDL: [`scripts/sql/ddl/`](scripts/sql/ddl/) · Views: [`scripts/sql/views/`](scripts/sql/views/) · Procs: [`scripts/sql/procs/`](scripts/sql/procs/)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Cloud** | Azure (Blob Storage, SQL Database, Data Factory, Functions, Key Vault) |
| **Database** | Azure SQL Database (cloud) + PostgreSQL 15 (local/fallback) |
| **ETL** | Azure Data Factory + Python (pandas 2.x, sqlalchemy) |
| **Analytics** | Python (numpy, scipy, statsmodels) |
| **ML** | Prophet (NAV forecasting) |
| **BI** | Power BI Desktop — 4 pages, 25+ DAX measures |
| **App** | Streamlit (deployed on Hostinger VPS) |
| **Orchestration** | ADF pipelines + Azure Functions |
| **Version Control** | Git + GitHub |

---

## 📊 Dashboard Pages (Power BI)

1. **Executive Overview** — AUM, top funds, market summary, KPIs
2. **Fund Performance Analytics** — CAGR, rolling returns, benchmark comparison
3. **Investor Analytics** — SIP trends, segmentation, retention
4. **Risk & Volatility** — Sharpe heatmaps, drawdown, risk-return scatter

---

## 🖼️ Dashboard Screenshots

**Page 1 — Executive Overview**
![Executive Overview](docs/screenshots/page1_executive.png)

**Page 2 — Fund Performance Analytics**
![Fund Performance](docs/screenshots/page2_performance.png)

**Page 3 — Investor Analytics**
![Investor Analytics](docs/screenshots/page3_investor.png)

**Page 4 — Risk & Volatility**
![Risk & Volatility](docs/screenshots/page4_risk.png)

**Azure Data Factory Pipeline — Succeeded**
![Azure ADF Pipeline — Succeeded](docs/screenshots/Pipeline%20success.png)

---

## 📈 Financial Metrics Implemented

- CAGR (Compound Annual Growth Rate)
- Rolling Returns (1Y, 3Y, 5Y)
- Alpha, Beta (vs Nifty 50 benchmark)
- Sharpe Ratio, Sortino Ratio, Treynor Ratio
- Standard Deviation, Volatility
- Maximum Drawdown
- Information Ratio

---

## 🤖 ML Module

**NAV Forecasting (Prophet)** — Forecasts 30/60/90-day NAV trajectories with confidence-interval bands for the Yahoo ETF/benchmark universe (≥ 200 trading days of history). Implemented in [`scripts/ml/forecast_nav.py`](scripts/ml/forecast_nav.py) and served live through the **Streamlit app** ([`streamlit/`](streamlit/)), deployable on the Hostinger VPS behind Traefik (`streamlit/docker-compose.yml`).

```bash
python scripts/ml/forecast_nav.py --fund-code NIFTYBEES.NS   # CLI forecast
streamlit run streamlit/app.py                               # interactive app
```

---

## ▶️ How to Run

### 1. Setup

```bash
# Clone repo
git clone https://github.com/Skpkush/mf-analytics-platform.git
cd mf-analytics-platform

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env            # Windows: copy .env.example .env
# Edit .env with your Azure / PostgreSQL credentials
```

### 2. Ingest data

```bash
python scripts/ingestion/fetch_yahoo_finance.py
python scripts/ingestion/fetch_amfi_nav.py
```

### 3. Transform & load (build the star schema)

```bash
# Clean and validate NAV / transaction history
python scripts/transformation/clean_nav.py
python scripts/transformation/clean_transactions.py

# Create the schema (DDL), then load dimensions and facts
python scripts/etl/run_ddl.py
python scripts/etl/load_dimensions.py
python scripts/etl/load_facts.py
```

### 4. Compute analytics

```bash
python scripts/analytics/metrics_returns.py        # CAGR, rolling returns
python scripts/analytics/metrics_risk.py           # volatility, drawdown
python scripts/analytics/metrics_risk_adjusted.py  # Sharpe, Sortino, Treynor, alpha/beta
python scripts/analytics/metrics_market.py         # market/AUM aggregates
```

### 5. Forecast NAV (Prophet)

```bash
python scripts/ml/forecast_nav.py --list                  # forecastable funds
python scripts/ml/forecast_nav.py --fund-code NIFTYBEES.NS # 30/60/90-day forecast
```

### 6. Explore the dashboard & app

- **Power BI:** open `powerbi/mf_analytics_dashboard_p4.pbix` (apply theme `powerbi/theme_mf_analytics.json`).
- **Streamlit:** `streamlit run streamlit/app.py` → open `http://localhost:8501` (interactive NAV forecasting; deploy notes in [`streamlit/README.md`](streamlit/README.md)).

> Cloud path: the Azure Data Factory pipeline orchestrates the ingestion → blob → SQL load in the cloud (pipeline run **Succeeded** — see screenshot above). Run the cloud ETL via `scripts/etl/run_azure_etl.py` / `scripts/etl/trigger_adf_pipeline.py`.

---

## 📁 Project Structure

```
mf-analytics-platform/
├── data/
│   ├── raw/              # Raw ingested data
│   ├── processed/        # Cleaned, transformed data
│   └── external/         # Benchmark, risk-free rate data
├── scripts/
│   ├── ingestion/        # Data acquisition (Yahoo, AMFI, Kaggle)
│   ├── transformation/   # Cleaning, validation, feature engineering
│   ├── etl/              # DDL run, dimension/fact load, Azure ETL, ADF trigger
│   ├── analytics/        # Financial metric calculations
│   ├── ml/               # Prophet NAV forecasting
│   └── sql/              # SQL layer:
│       ├── ddl/          #   CREATE TABLE scripts (star schema)
│       ├── views/        #   Analytical views
│       └── procs/        #   Stored procedures
├── azure/
│   ├── adf_pipelines/    # ADF JSON pipeline definitions
│   ├── functions/        # Azure Functions code
│   └── arm_templates/    # Infrastructure as code
├── powerbi/              # PBIX file + theme + DAX measures documentation
├── streamlit/            # Streamlit client-facing app
├── docs/
│   ├── architecture/     # Architecture diagrams
│   ├── case_study/       # Final case study PDF
│   └── screenshots/      # Dashboard + pipeline screenshots
├── notebooks/            # Jupyter notebooks for exploration
├── tests/                # Unit tests
├── PROJECT_PLAN.md       # Week-by-week execution plan
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── README.md
```

---

## 📄 Documentation

- [Architecture](docs/architecture/architecture.md)
- [Project Plan](PROJECT_PLAN.md)
- [Data Dictionary](docs/data_dictionary.md)
- [KPI Definitions](docs/kpi_definitions.md)
- [Case Study PDF](docs/case_study/)

---

## 📜 License

MIT License — see LICENSE file.

---

## 👤 Author

**Sumit Kumar Prajapat**
Data Analyst | Analytics Engineer | Founder, Finonus Capital
📧 sumit@finonuscapital.com
🔗 [GitHub](https://github.com/Skpkush)

---

_Last updated: June 2026_
