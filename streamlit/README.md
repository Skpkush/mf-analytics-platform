# MF Analytics — Streamlit App (multi-page)

Client-facing front-end for the Mutual Fund Analytics Platform. A multi-page
Streamlit app reading live from the analytics database (PostgreSQL locally /
Supabase on the VPS), themed navy `#1B3A6B`.

## Pages

| Page | What it does | Data scope |
|---|---|---|
| **Home** (`app.py`) | KPI cards, top performer, data-freshness | whole DB |
| **🔎 Fund Explorer** | search any fund, metric card, 5Y NAV, peer ranking | **all 14k+ funds** (graceful degrade for AMFI snapshots) |
| **📈 NAV Forecast** | Prophet 30/60/90-day forecast + confidence bands | 16 funds with history |
| **⚠️ Risk Dashboard** | risk-return scatter, Sharpe heatmap, drawdown, beta | 16 funds with metrics |
| **🧮 SIP Calculator** | maturity, XIRR, 3-scenario compare, fund picks | pure math + 16-fund picks |
| **📦 Portfolio Analyzer** | weighted metrics, efficient frontier, diversification | 16 funds with history |

> **Data reality:** only 16 funds (Yahoo ETFs + benchmarks) carry a NAV time
> series and computed metrics; the other ~14k AMFI funds are a single NAV
> snapshot. Analytics pages are scoped accordingly and say so in-app.

## Architecture

```
streamlit/
├── app.py                  # home / entrypoint
├── pages/                  # 01_Fund_Explorer … 05_Portfolio_Analyzer
├── utils/
│   ├── db.py               # SQLAlchemy engine + @st.cache_data queries
│   ├── metrics.py          # SIP/XIRR/portfolio math + RAG colours (pure, testable)
│   └── charts.py           # Plotly builders (navy theme)
└── .streamlit/
    ├── config.toml         # theme + server
    └── secrets.toml.example # DB creds template
```

`pages/02_NAV_Forecast.py` reuses the tested
[`scripts/ml/forecast_nav.generate_forecast`](../scripts/ml/forecast_nav.py).
The DB layer resolves credentials from `st.secrets["postgres"]` first, then
falls back to the repo `.env` (`LOCAL_DB_*`) — so the same code runs locally
and on the VPS.

---

## Run locally

```bash
# from the repo root, with the venv active and .env configured
streamlit run streamlit/app.py        # → http://localhost:8501
```

### Forecast CLI (no UI)

```bash
python scripts/ml/forecast_nav.py --list
python scripts/ml/forecast_nav.py --fund-code NIFTYBEES.NS
```

---

## Deploy on Hostinger VPS

### Database: Supabase (free PostgreSQL)

The app uses `psycopg2`, so it needs a network-reachable **PostgreSQL** (your
local Postgres isn't reachable from the VPS, and Azure SQL is SQL Server — a
different driver). Use a free **Supabase** Postgres project:

1. Create a project at supabase.com and note the **Session pooler** connection
   (host `aws-0-<region>.pooler.supabase.com`, port `5432`, user
   `postgres.<ref>`, db `postgres`). The pooler gives IPv4, which the VPS needs.
2. Migrate the local DB (only ~48 MB) — dumps the whole `dbo` schema:
   ```bash
   pg_dump -h localhost -U postgres -d mf_analytics --schema=dbo \
           --no-owner --no-privileges -f mf_dump.sql
   psql "postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
        -f mf_dump.sql
   ```
3. On the VPS, point the `.env` `LOCAL_DB_*` vars at Supabase (host/port/name/
   user/password). No code change needed.

### Run (current mode: direct port, quick test)

```bash
ssh root@srv973497.hstgr.cloud
cd ~/mf-analytics-platform && git pull origin main
nano .env                                              # Supabase LOCAL_DB_* creds
docker compose -f streamlit/docker-compose.yml up -d --build
```

Reachable at `http://<VPS-IP>:8501` (or `http://srv973497.hstgr.cloud:8501`).
Ensure port **8501** is open in the VPS / Hostinger firewall. Health check:
`curl http://localhost:8501/_stcore/health` → `ok`.

### Later: own domain + HTTPS via Traefik

To serve at e.g. `https://nav.finonuscapital.com`, add a DNS A-record to your
VPS IP, then in `docker-compose.yml` remove the `ports:` block and uncomment the
`networks:` + Traefik `labels:` blocks (the VPS already runs Traefik). Compose
restarts the container on failure (`restart: unless-stopped`).

---

## Notes

- Forecasts are statistical projections from historical NAV — **not investment
  advice**.
- Prophet fits are cached per fund + confidence level for 1 hour
  (`st.cache_data`), so repeat views are instant.
