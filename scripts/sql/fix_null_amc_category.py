"""
Fix NULL amc_key, category_key, plan_type, option_type in Dim_Fund
for Yahoo ETF funds (source = 'yahoo_etf').

Root cause: Yahoo ETF funds were loaded without AMC/category lookups.
The LEFT JOINs in vw_fund_performance and vw_risk_summary return NULL
for asset_class, sub_category, amc_name, amc_short_name, plan_type,
option_type — making Power BI dashboard columns completely blank.

Fix:
  1. Map each ETF fund to its correct amc_key (from Dim_AMC)
     and category_key (from Dim_Category) based on fund name.
  2. Set plan_type = 'ETF', option_type = 'Growth' for ETF funds.
  3. Verify vw_fund_performance and vw_risk_summary now show values.
"""

import os
import sys
import logging
import pyodbc
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── DB connection ────────────────────────────────────────────────────────────

def get_conn() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={os.environ['AZURE_SQL_DRIVER']};"
        f"SERVER={os.environ['AZURE_SQL_SERVER']};"
        f"DATABASE={os.environ['AZURE_SQL_DATABASE']};"
        f"UID={os.environ['AZURE_SQL_USER']};"
        f"PWD={os.environ['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


# ── Step 1: Inspect current state ───────────────────────────────────────────

INSPECT_SQL = """
SELECT
    df.fund_key,
    df.scheme_code,
    df.fund_name,
    df.base_fund_name,
    df.source,
    df.amc_key,
    df.category_key,
    df.plan_type,
    df.option_type
FROM dbo.Dim_Fund df
WHERE df.source IN ('yahoo_etf', 'yahoo_benchmark')
ORDER BY df.fund_key;
"""

# ── Step 2: Pull existing lookup keys ───────────────────────────────────────

AMC_QUERY   = "SELECT amc_key, amc_name, amc_short_name FROM dbo.Dim_AMC ORDER BY amc_key;"
CAT_QUERY   = "SELECT category_key, asset_class, sub_category FROM dbo.Dim_Category ORDER BY category_key;"


# ── Step 3: Name-based mapping rules ────────────────────────────────────────
# Each tuple: (substring_in_fund_name_lower, amc_key, category_key)
# Rules are tried top-to-bottom; first match wins.

def derive_amc_key(name: str, amc_map: dict) -> int | None:
    n = name.lower()
    if "nippon" in n:            return amc_map.get("Nippon India Mutual Fund")
    if "motilal" in n:           return amc_map.get("Motilal Oswal Mutual Fund")
    if "icici" in n:             return amc_map.get("ICICI Prudential Mutual Fund")
    if "hdfc" in n:              return amc_map.get("HDFC Mutual Fund")
    if "sbi" in n:               return amc_map.get("SBI Mutual Fund")
    if "kotak" in n:             return amc_map.get("Kotak Mahindra Mutual Fund")
    if "aditya birla" in n:      return amc_map.get("Aditya Birla Sun Life Mutual Fund")
    if "dsp" in n:               return amc_map.get("DSP Mutual Fund")
    if "mirae" in n:             return amc_map.get("Mirae Asset Mutual Fund")
    if "uti" in n:               return amc_map.get("UTI Mutual Fund")
    return None  # benchmarks / unmapped


def derive_category_key(name: str, cat_map: dict) -> int | None:
    """
    cat_map: {(asset_class, sub_category): category_key}
    ETF classification per SEBI:
      - Liquid/Overnight    → Debt Scheme, Liquid Fund        (key 12)
      - Gold ETF            → Other Scheme, Gold ETF          (key 46)
      - Broad index (Nifty 50, Nifty 500, Next 50) → Other Scheme, Index Funds (key 47)
      - Sectoral/Thematic ETF (NASDAQ, Bank, Bharat 22) → Other Scheme, Other ETFs (key 48)
    """
    n = name.lower()
    # Liquid/money market
    if "liquid" in n:                                        return cat_map.get(("Debt Scheme", "Liquid Fund"))
    # Gold
    if "gold" in n:                                          return cat_map.get(("Other Scheme", "Gold ETF"))
    # Broad index trackers
    if "nifty 50" in n and "bank" not in n:                  return cat_map.get(("Other Scheme", "Index Funds"))
    if "nifty50" in n:                                       return cat_map.get(("Other Scheme", "Index Funds"))
    if "nifty 500" in n:                                     return cat_map.get(("Other Scheme", "Index Funds"))
    if "nifty next 50" in n or "junior" in n:               return cat_map.get(("Other Scheme", "Index Funds"))
    if "setfnif50" in n.replace(" ", ""):                    return cat_map.get(("Other Scheme", "Index Funds"))
    # Sectoral / thematic ETFs
    if "nasdaq" in n or "n100" in n or "mon100" in n:       return cat_map.get(("Other Scheme", "Other  ETFs"))
    if "bank" in n:                                          return cat_map.get(("Other Scheme", "Other  ETFs"))
    if "bharat 22" in n or "bharat22" in n:                 return cat_map.get(("Other Scheme", "Other  ETFs"))
    if "nifty" in n:                                         return cat_map.get(("Other Scheme", "Other  ETFs"))
    # Benchmarks (indices — no category)
    if "sensex" in n or "^bse" in n or "^nse" in n:         return None
    return cat_map.get(("Other Scheme", "Other  ETFs"))      # fallback for unknown ETFs


# ── Step 4: Build UPDATE statements ─────────────────────────────────────────

UPDATE_SQL = """
UPDATE dbo.Dim_Fund
SET
    amc_key      = ?,
    category_key = ?,
    plan_type    = ?,
    option_type  = ?
WHERE fund_key = ?;
"""


# ── Step 5: Verify views ─────────────────────────────────────────────────────

VERIFY_SQL = """
SELECT
    vfp.base_fund_name,
    vfp.amc_name,
    vfp.amc_short_name,
    vfp.asset_class,
    vfp.sub_category,
    vfp.plan_type,
    vfp.option_type
FROM dbo.vw_fund_performance vfp
WHERE vfp.is_benchmark = 0
ORDER BY vfp.cagr_5y DESC;
"""

VERIFY_RISK_SQL = """
SELECT
    vrs.base_fund_name,
    vrs.amc_name,
    vrs.asset_class,
    vrs.sub_category,
    vrs.risk_tier
FROM dbo.vw_risk_summary vrs
WHERE vrs.is_benchmark = 0
ORDER BY vrs.std_dev_1y DESC;
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Connecting to Azure SQL...")
    conn = get_conn()
    cur  = conn.cursor()

    # --- Load lookup tables ---
    cur.execute(AMC_QUERY)
    amc_rows = cur.fetchall()
    amc_map  = {row.amc_name: row.amc_key for row in amc_rows}
    log.info("Loaded %d AMC records", len(amc_map))

    cur.execute(CAT_QUERY)
    cat_rows = cur.fetchall()
    cat_map  = {(row.asset_class, row.sub_category): row.category_key for row in cat_rows}
    log.info("Loaded %d Category records", len(cat_map))

    # --- Inspect current Yahoo ETF state ---
    cur.execute(INSPECT_SQL)
    etf_funds = cur.fetchall()
    log.info("Found %d Yahoo ETF/benchmark funds in Dim_Fund", len(etf_funds))

    print("\n" + "="*80)
    print("CURRENT STATE  (before fix)")
    print("="*80)
    print(f"{'fund_key':>9}  {'scheme_code':<20}  {'base_fund_name':<45}  {'amc':>6}  {'cat':>5}")
    print("-"*80)
    for r in etf_funds:
        print(f"{r.fund_key:>9}  {str(r.scheme_code):<20}  {str(r.base_fund_name or r.fund_name)[:45]:<45}  "
              f"{str(r.amc_key or 'NULL'):>6}  {str(r.category_key or 'NULL'):>5}")

    # --- Build update params ---
    updates = []
    skipped = []

    for r in etf_funds:
        name = r.base_fund_name or r.fund_name or ""
        is_benchmark = (r.source == "yahoo_benchmark")

        new_amc_key  = None if is_benchmark else derive_amc_key(name, amc_map)
        new_cat_key  = None if is_benchmark else derive_category_key(name, cat_map)
        new_plan     = None if is_benchmark else "ETF"
        new_option   = None if is_benchmark else "Growth"

        if new_amc_key is None and not is_benchmark:
            log.warning("Could not map AMC for: %s", name)
            skipped.append(name)
        if new_cat_key is None and not is_benchmark:
            log.warning("Could not map Category for: %s", name)

        updates.append((new_amc_key, new_cat_key, new_plan, new_option, r.fund_key))

    # --- Show proposed changes ---
    print("\n" + "="*80)
    print("PROPOSED UPDATES")
    print("="*80)
    print(f"{'fund_key':>9}  {'base_fund_name':<45}  {'amc_key':>8}  {'cat_key':>8}  {'plan':<6}")
    print("-"*80)
    for u in updates:
        new_amc, new_cat, new_plan, _, fk = u
        fund_name = next((r.base_fund_name or r.fund_name for r in etf_funds if r.fund_key == fk), "?")
        print(f"{fk:>9}  {str(fund_name)[:45]:<45}  {str(new_amc or 'NULL'):>8}  {str(new_cat or 'NULL'):>8}  {str(new_plan or ''):6}")

    if skipped:
        print(f"\nWARNING: {len(skipped)} funds could not be mapped to an AMC:")
        for s in skipped:
            print(f"  - {s}")

    # --- Apply updates ---
    print("\nApplying updates...")
    changed = 0
    for params in updates:
        cur.execute(UPDATE_SQL, params)
        changed += cur.rowcount

    conn.commit()
    log.info("Committed %d row update(s)", changed)

    # --- Verify views ---
    print("\n" + "="*80)
    print("VERIFICATION  vw_fund_performance  (non-benchmark funds)")
    print("="*80)
    cur.execute(VERIFY_SQL)
    rows = cur.fetchall()
    print(f"{'Fund':<40}  {'AMC':<25}  {'Class':<16}  {'Sub-Cat':<20}  {'Plan'}")
    print("-"*120)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:40]:<40}  "
              f"{str(r.amc_name or 'NULL')[:25]:<25}  "
              f"{str(r.asset_class or 'NULL')[:16]:<16}  "
              f"{str(r.sub_category or 'NULL')[:20]:<20}  "
              f"{str(r.plan_type or 'NULL')}")

    print("\n" + "="*80)
    print("VERIFICATION  vw_risk_summary  (non-benchmark funds)")
    print("="*80)
    cur.execute(VERIFY_RISK_SQL)
    rows = cur.fetchall()
    print(f"{'Fund':<40}  {'AMC':<25}  {'Class':<16}  {'Sub-Cat':<20}  {'Tier'}")
    print("-"*110)
    for r in rows:
        print(f"{str(r.base_fund_name or '')[:40]:<40}  "
              f"{str(r.amc_name or 'NULL')[:25]:<25}  "
              f"{str(r.asset_class or 'NULL')[:16]:<16}  "
              f"{str(r.sub_category or 'NULL')[:20]:<20}  "
              f"{str(r.risk_tier or 'NULL')}")

    cur.close()
    conn.close()
    log.info("Done. Refresh Power BI Desktop to see updated columns.")


if __name__ == "__main__":
    main()
