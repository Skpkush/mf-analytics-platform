# 🚀 DAY 1 — Tomorrow Morning Action Plan

**Goal:** Get real data flowing into your project. End of Day 1, you should have raw parquet files for all funds + benchmarks.

---

## ⏰ Recommended Schedule (6 hours)

| Time | Task | Duration |
|---|---|---|
| 06:00 - 06:30 | Repo setup, venv, dependencies | 30 min |
| 06:30 - 08:00 | Run ingestion scripts, verify data | 90 min |
| 08:00 - 09:00 | **Break — applications (10 today)** | 60 min |
| 09:00 - 11:00 | Explore data in notebook, identify quality issues | 120 min |
| 11:00 - 12:00 | Commit + push + Day 1 standup log | 60 min |

---

## Step-by-Step Commands

### 1. Clone & Setup (5 min)

```bash
# Navigate to your projects folder
cd ~/Projects   # or wherever you keep work

# Create GitHub repo on github.com first (name: mf-analytics-platform)
# Then:
git clone https://github.com/Skpkush/mf-analytics-platform.git
cd mf-analytics-platform

# OR: copy the local folder I just built and init git
# cp -r /path/to/mf-analytics-platform .
# cd mf-analytics-platform
# git init
# git remote add origin https://github.com/Skpkush/mf-analytics-platform.git
```

### 2. Create Virtual Environment (5 min)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies (10 min)

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Run AMFI Ingestion (5 min) — START HERE

```bash
python scripts/ingestion/fetch_amfi_nav.py
```

**Expected output:** ~14,000 schemes from all 51 AMCs, saved to `data/raw/amfi_nav_current_<date>.parquet` (~530 KB).

### 5. Run Yahoo Finance Ingestion (10 min)

```bash
# Default: last 5 years of ETFs + benchmarks
python scripts/ingestion/fetch_yahoo_finance.py

# Or specific date range
python scripts/ingestion/fetch_yahoo_finance.py --start 2020-01-01 --end 2026-05-23
```

**Expected output:**
- `data/raw/yahoo_funds_<date>.parquet` — 16 ETFs × ~1,250 trading days
- `data/raw/yahoo_benchmark_<date>.parquet` — 5 benchmarks × ~1,250 trading days

### 6. Quick Data Exploration (30 min)

```bash
jupyter notebook notebooks/01_data_exploration.ipynb
```

Or run inline:
```bash
python -c "
import pandas as pd
amfi = pd.read_parquet('data/raw/amfi_nav_current_20260523.parquet')
yahoo = pd.read_parquet('data/raw/yahoo_benchmark_20260523.parquet')
print('AMFI schemes:', amfi['scheme_code'].nunique())
print('AMFI AMCs:', amfi['amc'].nunique())
print('Yahoo tickers:', yahoo['ticker'].nunique())
print('Yahoo date range:', yahoo['date'].min(), '->', yahoo['date'].max())
"
```

### 7. Commit & Push (15 min)

```bash
git add .
git commit -m "feat: Day 1 - data ingestion (AMFI + Yahoo Finance)

- AMFI scraper fetching 14k+ Indian MF schemes
- Yahoo Finance ETF + benchmark ingestion
- Star schema folder structure
- Architecture documentation
- 4-week project plan"

git push -u origin main
```

---

## ✅ Day 1 Done When

- [ ] GitHub repo public, README visible
- [ ] Virtual environment working, all deps installed
- [ ] `data/raw/amfi_nav_current_*.parquet` exists with 14k+ rows
- [ ] `data/raw/yahoo_funds_*.parquet` exists with 5-year history
- [ ] `data/raw/yahoo_benchmark_*.parquet` exists with 5-year history
- [ ] First commit pushed to GitHub
- [ ] **10 job applications submitted today**
- [ ] Daily log committed in `docs/daily_log.md`

---

## 🚨 Troubleshooting

**Yahoo Finance returns empty data:**
- Yahoo throttles rapid requests. Add `time.sleep(2)` between tickers if needed.
- Some Indian ETF tickers may have changed — check on yahoo finance website manually.

**AMFI 403 or timeout:**
- AMFI sometimes blocks data center IPs. Use a VPN if blocked.
- If parsing fails, check `logs/amfi_ingestion.log` — format may have changed.

**Prophet install fails:**
- On Windows: needs Visual C++ Build Tools.
- Defer Prophet install to Day 15 if it's a problem now.

---

## Day 1 Standup Log Template

Add this to `docs/daily_log.md` at end of day:

```markdown
## Day 1 — 2026-05-24

**Completed:**
- Repo set up, GitHub pushed
- AMFI ingestion working (14,363 schemes)
- Yahoo Finance ingestion working (16 ETFs + 5 benchmarks)
- 5 years of historical data secured

**Applications submitted:** 10/10 ✓

**Blockers:** None / [describe any]

**Tomorrow (Day 2):**
- Data cleaning + validation framework
- Schema enforcement
- Outlier detection
```
