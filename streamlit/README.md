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

## Deploy on Hostinger VPS (Docker + Traefik)

The VPS (`srv973497.hstgr.cloud`) already runs Traefik + Docker. Deploy:

```bash
git pull
docker compose -f streamlit/docker-compose.yml up -d --build
```

This builds the image (see [`Dockerfile`](Dockerfile)), attaches it to the
external `traefik` network, and publishes it at
`https://nav.srv973497.hstgr.cloud` via Traefik labels.

Before first deploy:
1. Point the DB env vars in `.env` at the reachable database (Azure SQL or a
   VPS-hosted PostgreSQL — the app connects over the network).
2. Adjust the Traefik `entrypoints` / `certresolver` / network name in
   `docker-compose.yml` to match your Traefik setup.
3. Create a DNS A-record for the `nav.` subdomain pointing at the VPS.

Health check: the container exposes Streamlit's `/_stcore/health` endpoint and
Compose restarts it on failure (`restart: unless-stopped`).

---

## Notes

- Forecasts are statistical projections from historical NAV — **not investment
  advice**.
- Prophet fits are cached per fund + confidence level for 1 hour
  (`st.cache_data`), so repeat views are instant.
