# NAV Forecasting App (Streamlit)

Client-facing front-end for the Mutual Fund Analytics Platform. Serves
**Prophet** NAV forecasts (30 / 60 / 90-day horizons with confidence-interval
bands) live from the analytics database, alongside pre-computed risk/return
metrics (CAGR, Sharpe, Beta, Max Drawdown) from `Fact_Returns`.

The forecasting logic lives in [`scripts/ml/forecast_nav.py`](../scripts/ml/forecast_nav.py);
this app is the presentation layer on top of it.

---

## Run locally

```bash
# from the repo root, with the venv active and .env configured
streamlit run streamlit/app.py
# → http://localhost:8501
```

The app reads DB credentials from the repo `.env` (`LOCAL_DB_*` for
PostgreSQL). It only lists funds that have ≥ 200 trading days of NAV
history (the Yahoo ETF/benchmark universe), since Prophet needs a real
time series to forecast.

### CLI (no UI)

```bash
python scripts/ml/forecast_nav.py --list                 # forecastable funds
python scripts/ml/forecast_nav.py --fund-code NIFTYBEES.NS
python scripts/ml/forecast_nav.py --fund-code GOLDBEES.NS --interval-width 0.90 --save
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
