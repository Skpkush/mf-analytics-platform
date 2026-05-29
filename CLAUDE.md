# CLAUDE.md — Project Context for Claude Code

> This file is automatically read by Claude Code at the start of every session.
> It contains everything Claude Code needs to work effectively in this repo.

---

## 🎯 Project Identity

**Name:** Mutual Fund Analytics Platform
**Owner:** Sumit Kumar Prajapat ([Skpkush on GitHub](https://github.com/Skpkush))
**Type:** Production-grade portfolio project for Senior Data Analyst role (₹9-11 LPA target)
**Deadline:** 4 weeks from project start (hard deadline — November 2026 job window)
**Current Phase:** See `PROJECT_PLAN.md` for current day/week

---

## 📚 MUST READ AT SESSION START

Before doing anything else in a new session, read these files in order:

1. `PROJECT_PLAN.md` — Current day/week, today's tasks
2. `docs/architecture/architecture.md` — System design (do not deviate)
3. `docs/daily_log.md` — What was completed yesterday (if exists)
4. `README.md` — Project overview

---

## 🚨 HARD CONSTRAINTS (DO NOT VIOLATE)

1. **Azure free trial = 15 days only.** Do not provision Azure resources before Day 8 of the plan. Do not provision expensive services (Databricks, Synapse) ever.
2. **Power BI = free tier.** Do not assume Pro features (RLS, deployment pipelines, paginated reports).
3. **Out of scope items** (listed in `PROJECT_PLAN.md`) are **deliberately cut.** Do not add them back even if user asks casually. If user explicitly insists, flag the timeline impact first.
4. **Daily commits required.** Every working day must end with a git commit.
5. **No new dependencies without justification.** `requirements.txt` is the source of truth. If you need a new package, explain why and update the file.

---

## 🛠️ Tech Stack (LOCKED)

| Layer | Tool | Notes |
|---|---|---|
| Language | Python 3.11+ | Use type hints |
| Data | pandas 2.x, numpy | Parquet for raw storage |
| DB (local) | PostgreSQL 15+ | Primary post-trial |
| DB (cloud) | Azure SQL Database (Basic tier) | 15-day window only |
| ETL | Azure Data Factory + Python | ADF for orchestration |
| Cloud | Azure Blob, ADF, SQL DB, Functions, Key Vault | NO Databricks, NO Synapse |
| ML | Prophet | Only 1 ML model — NAV forecasting |
| BI | Power BI Desktop (PBIX file-based) | Service used during trial only |
| App | Streamlit | Deployed on Hostinger VPS |
| Versioning | Git + GitHub | Skpkush org |

---

## 📁 Project Structure Convention

```
mf-analytics-platform/
├── scripts/
│   ├── ingestion/      # Data acquisition (Yahoo, AMFI, Kaggle)
│   ├── transformation/ # Cleaning, validation, feature engineering
│   ├── analytics/      # Financial metric calculations
│   └── ml/             # Prophet forecasting
├── sql/
│   ├── ddl/            # CREATE TABLE
│   ├── dml/            # INSERT, UPDATE, MERGE
│   ├── views/          # Analytical views
│   └── procs/          # Stored procedures
├── azure/              # ADF JSON, Functions, ARM templates
├── powerbi/            # PBIX + DAX docs
├── streamlit/          # Streamlit app
├── docs/               # Architecture, case study, screenshots
├── notebooks/          # Jupyter notebooks (exploratory only)
├── tests/              # pytest
└── data/{raw,processed,external}/
```

**Rule:** New files MUST go into the correct folder. Do not put scripts in root.

---

## 🎨 Code Style Standards

### Python
- **Type hints everywhere.** No `def foo(x):` — always `def foo(x: int) -> str:`
- **Docstrings** on every function — Google style.
- **Logging, not print().** Use the standard `logging` module.
- **Pathlib, not os.path.** Use `Path` objects for all file operations.
- **Error handling.** Every external call (API, DB, file) wrapped in try/except with retry logic.
- **Black formatting.** Line length 100.
- **No magic numbers.** Use named constants at the top of the file.

### SQL
- **Uppercase keywords.** `SELECT`, `FROM`, `JOIN` — not lowercase.
- **CTEs over subqueries.** Readability over cleverness.
- **Indexes documented.** Every index should have a comment explaining why.
- **Schema prefixes.** Always `dbo.Dim_Fund`, not `Dim_Fund`.

### Git
- **Conventional commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`
- **Atomic commits.** One logical change per commit.
- **No "WIP" or "stuff" commits.** Squash before pushing if needed.

---

## ⚠️ KNOWN PATTERN TO WATCH (FROM USER MEMORY)

The user has a documented pattern of using **planning, documentation, and exploration as avoidance of execution.**

If during a session the user:
- Asks to "create another PDF document" instead of writing code
- Asks to "research more options" before executing what's already decided
- Wants to "explore a new approach" mid-week
- Suggests adding scope back that was deliberately cut

**Response protocol:**
1. Acknowledge the request once.
2. Flag the pattern *briefly and only once* — do not lecture.
3. Connect to the current day's deliverable from `PROJECT_PLAN.md`.
4. Ask: "Do you want to do this now, or finish [today's planned task] first?"
5. Respect the user's decision and move on.

Do not bring up this pattern more than once per session. The user has acknowledged it; nagging is counterproductive.

---

## 🗣️ Communication Style

- **Hinglish for casual back-and-forth.** Match the user's register.
- **English for technical code explanations.** Comments in English.
- **No excessive agreement.** If the user's request creates a problem (timeline, scope, architecture), say so directly. The user has explicitly asked for honest pushback in their preferences.
- **Honorifics for deities.** "Bhagwan Krishna," "Shri Hanuman ji" — never just "Krishna" or "Hanuman."
- **Surname:** Prajapat. Not Pushkar.

---

## 🎯 Daily Workflow Template

Every working session should follow this loop:

1. **Read state.** Check `docs/daily_log.md` (last entry) and `PROJECT_PLAN.md` (today's tasks).
2. **Confirm scope.** Tell the user: "Today's plan says X. Confirm or override?"
3. **Execute.** Write code, run tests, fix bugs.
4. **Commit.** After each logical unit of work.
5. **Update log.** Append to `docs/daily_log.md` before session end:
   ```markdown
   ## Day N — YYYY-MM-DD
   **Completed:** ...
   **Applications submitted:** X/10
   **Blockers:** ...
   **Tomorrow:** ...
   ```
6. **Push.** `git push origin main` at end of day.

---

## 🚦 Critical Milestones (DO NOT MISS)

| Day | Milestone | Why |
|---|---|---|
| 7 | Local PostgreSQL + all metrics working | Streamlit fallback ready |
| 8 | Azure activation, 15-day clock starts | Cloud burst begins |
| 14 | Loom video + Azure screenshots captured | LAST DAY of cloud window |
| 21 | Streamlit deployed on Hostinger VPS | Post-Azure life secured |
| 28 | Case study PDF + LinkedIn post + resume bullets | Portfolio launch |

If today's session pushes any of these dates later, flag it immediately.

---

## 🔌 Environment

- **OS:** Windows 11
- **Python:** 3.11+ in venv at `./venv/`
- **DB:** PostgreSQL local at `localhost:5432`, db name `mf_analytics`
- **Hostinger VPS:** `srv973497.hstgr.cloud` (Traefik + Docker already running)
- **Secrets:** `.env` file (gitignored). Template in `.env.example`.

---

## 📞 When in Doubt

- Architecture decision? → `docs/architecture/architecture.md`
- Scope question? → `PROJECT_PLAN.md` "Out of Scope" section
- Style question? → This file, "Code Style Standards" section
- "Should I add this feature?" → Default to NO unless it's in `PROJECT_PLAN.md` for today

---

**Last updated:** Day 0 (project scaffold complete)
**Next milestone:** Day 1 — Data ingestion verification + GitHub repo public
