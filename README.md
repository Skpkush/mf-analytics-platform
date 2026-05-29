# Mutual Fund Analytics Platform

> Production-style, enterprise-grade Mutual Fund Analytics Platform demonstrating end-to-end Data Engineering, Advanced Analytics, Cloud Architecture, and Executive BI Reporting.

**Built by:** Sumit Kumar Prajapat | [GitHub: Skpkush](https://github.com/Skpkush)
**Status:** 🚧 In Active Development (Week 1 of 4)

---

## 🎯 Business Problem

Asset Management Companies, Wealth Advisors, and FinTech firms need a unified analytics platform that ingests multi-source mutual fund data, computes risk-adjusted performance metrics, segments investors, forecasts NAV trends, and surfaces executive-level insights — all in a scalable cloud architecture.

This platform delivers exactly that.

---

## 🏗️ Architecture (High-Level)

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Data Sources   │───▶│   Azure Blob    │───▶│  Azure Data     │
│  Yahoo Finance  │    │   (Raw Layer)   │    │   Factory       │
│  AMFI India     │    └─────────────────┘    └─────────────────┘
│  Kaggle         │                                     │
└─────────────────┘                                     ▼
                                              ┌─────────────────┐
┌─────────────────┐    ┌─────────────────┐    │  Azure SQL DB   │
│  Streamlit App  │◀───│  Power BI       │◀───│  Star Schema    │
│  (Hostinger VPS)│    │  Dashboard      │    │  Fact + Dim     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        ▲                                              │
        │                                              ▼
        │                                     ┌─────────────────┐
        └─────────────────────────────────────│  Python ML      │
                                              │  Prophet NAV    │
                                              │  Forecasting    │
                                              └─────────────────┘
```

Full diagram: [`docs/architecture/architecture.md`](docs/architecture/architecture.md)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Cloud** | Azure (Blob Storage, SQL Database, Data Factory, Functions, Key Vault) |
| **Database** | Azure SQL Database (primary), PostgreSQL (fallback) |
| **ETL** | Azure Data Factory + Python (pandas, sqlalchemy) |
| **Analytics** | Python (numpy, scipy, statsmodels) |
| **ML** | Prophet (NAV forecasting) |
| **BI** | Power BI Desktop + Power BI Service |
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

**NAV Forecasting (Prophet)** — Predicts 30/60/90-day NAV trajectories with confidence intervals for selected funds.

---

## 🚀 Quick Start

```bash
# Clone repo
git clone https://github.com/Skpkush/mf-analytics-platform.git
cd mf-analytics-platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your Azure / database credentials

# Run data ingestion (Day 1)
python scripts/ingestion/fetch_yahoo_finance.py
python scripts/ingestion/fetch_amfi_nav.py
```

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
│   ├── analytics/        # Financial metric calculations
│   └── ml/               # Prophet forecasting
├── sql/
│   ├── ddl/              # CREATE TABLE scripts (star schema)
│   ├── dml/              # INSERT, UPDATE, MERGE
│   ├── views/            # Analytical views
│   └── procs/            # Stored procedures
├── azure/
│   ├── adf_pipelines/    # ADF JSON pipeline definitions
│   ├── functions/        # Azure Functions code
│   └── arm_templates/    # Infrastructure as code
├── powerbi/              # PBIX file + DAX measures documentation
├── streamlit/            # Streamlit client-facing app
├── docs/
│   ├── architecture/     # Architecture diagrams
│   ├── case_study/       # Final case study PDF
│   └── screenshots/      # Dashboard screenshots
├── notebooks/            # Jupyter notebooks for exploration
├── tests/                # Unit tests
├── PROJECT_PLAN.md       # Week-by-week execution plan
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── README.md
```

---

## 📅 Project Timeline

**Total Duration:** 4 weeks
**Start:** Week 1, Day 1
**Target Completion:** 4 weeks from start

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the detailed day-by-day plan.

---

## 📄 Documentation

- [Architecture](docs/architecture/architecture.md)
- [Project Plan](PROJECT_PLAN.md)
- [Data Dictionary](docs/data_dictionary.md) *(coming Week 2)*
- [KPI Definitions](docs/kpi_definitions.md) *(coming Week 2)*
- [Case Study PDF](docs/case_study/) *(coming Week 4)*

---

## 📜 License

MIT License — see LICENSE file.

---

## 👤 Author

**Sumit Kumar Prajapat**
Data Analyst | Analytics Engineer | Founder, Finonus Capital
📧 sumit@finonuscapital.com
🔗 [GitHub](https://github.com/Skpkush)
