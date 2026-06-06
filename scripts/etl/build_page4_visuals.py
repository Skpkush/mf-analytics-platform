"""
Build Page 4 visuals for mf_analytics_dashboard.pbix — Risk & Volatility.

Creates a NEW fourth report page (registered in pages.json) covering
risk-adjusted performance, drawdown, volatility, and a risk-return scatter.

Sources from mf_analytics_dashboard_p3.pbix (Pages 1-3 + full DataModel).

All bindings verified live via the Power BI modeling MCP:
  - The 'Avg' risk measures aggregate vw_fund_performance (NOT vw_risk_summary,
    which is standalone), so we slice by vw_fund_performance columns.
  - Measures on MF (folder '3. Risk'): Avg Sharpe Ratio, Avg Sortino Ratio,
    Avg Treynor Ratio, Avg Volatility 1Y, Max Drawdown (Worst), Avg max drawdown.
  - vw_fund_performance columns: base_fund_name, amc_short_name,
    asset_class_label, plan_type, std_dev_1y, cagr_1y.

Canvas: 1440 x 900 (matches Pages 1-3).
Layout:
  Row 1 (y=0-54)    : Header bar + title
  Row 2 (y=58-188)  : 6 KPI cards
  Row 3 (y=205-505) : Left slicers (3) + Risk-return scatter + Sharpe heatmap matrix
  Row 4 (y=515-735) : Drawdown column + Volatility column + Sharpe-by-class column
  Row 5 (y=748-900) : Fund risk leaderboard matrix

Run:  python scripts/etl/build_page4_visuals.py
Then: pwsh scripts/etl/repack_pbix_page4.ps1
"""
from __future__ import annotations
import json, shutil, uuid, zipfile
from pathlib import Path

PBIX        = Path("powerbi/mf_analytics_dashboard_p3.pbix")   # source (Pages 1-3 + DataModel)
SCHEMA      = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.8.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
FUND_TBL = "vw_fund_performance"
MEAS_TBL = "Measures on MF"
NAVY      = "#1B3A6B"
CANVAS_BG = "#F4F7FB"
STAGE    = Path("powerbi/_p4_stage")
PAGE4_ID = uuid.uuid4().hex[:20]


# ── helpers ─────────────────────────────────────────────────────────────────
def vid() -> str:
    return uuid.uuid4().hex[:20]


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(prop: str, entity: str = MEAS_TBL) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field: dict, query_ref: str, native_ref: str, active: bool = True) -> dict:
    p: dict = {"field": field, "queryRef": query_ref, "nativeQueryRef": native_ref}
    if active:
        p["active"] = True
    return p


def m_proj(name: str, active: bool = True) -> dict:
    return proj(meas(name), f"{MEAS_TBL}.{name}", name, active)


def c_proj(prop: str, active: bool = True, entity: str = FUND_TBL) -> dict:
    return proj(col(entity, prop), f"{entity}.{prop}", prop, active)


def visual(name: str, vtype: str, x: float, y: float, w: float, h: float,
           z: int, query_state: dict | None = None,
           objects: dict | None = None, filter_cfg: dict | None = None) -> dict:
    v: dict = {
        "$schema": SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": {"visualType": vtype, "drillFilterOtherVisuals": True},
    }
    if query_state:
        v["visual"]["query"] = {"queryState": query_state}
    if objects:
        v["visual"]["objects"] = objects
    if filter_cfg:
        v["filterConfig"] = filter_cfg
    return v


def adv_filter(entity: str, prop: str, kind: int, value: str) -> dict:
    """Numeric advanced filter. kind: 0=Eq 1=GT 2=GTE 3=LT 4=LTE"""
    return {
        "name": vid(),
        "field": col(entity, prop),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": entity, "Type": 0}],
            "Where": [{
                "Condition": {
                    "Comparison": {
                        "ComparisonKind": kind,
                        "Left": {"Column": {"Expression": {"SourceRef": {"Name": "t"}}, "Property": prop}},
                        "Right": {"Literal": {"Value": str(value)}}
                    }
                }
            }]
        }
    }


def title_text(value: str) -> dict:
    return {"properties": {"paragraphs": {"expr": {"Literal": {"Value": json.dumps([{
        "textRuns": [{"value": value,
                      "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt",
                                    "bold": True, "color": "#FFFFFF"}}]
    }])}}}}}


# ── visual builders ─────────────────────────────────────────────────────────
def header_shape(name: str) -> dict:
    return visual(name, "shape", 0, 0, 1440, 54, 5, objects={
        "general": [{"properties": {"shapeType": {"expr": {"Literal": {"Value": "'rectangle'"}}}}}],
        "fill":    [{"properties": {"fillColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{NAVY}'"}}}}}}}],
    })


def title_textbox(name: str) -> dict:
    return visual(name, "textbox", 12, 8, 1100, 38, 6, objects={
        "general": [title_text(
            "Risk & Volatility  |  Sharpe · Sortino · Drawdown · Risk-Return  |  Rf 6.5% (RBI Repo)"
        )]
    })


def kpi_card(name: str, measure_name: str, x: float, z: int) -> dict:
    return visual(name, "cardVisual", x, 58, 210, 130, z, query_state={
        "Data": {"projections": [m_proj(measure_name)]}
    })


def slicer(name: str, prop: str, x: float, y: float, w: float, h: float,
           z: int, horizontal: bool = False) -> dict:
    obj: dict = {
        "data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Basic'"}}}}}],
        "general": [{"properties": {}}],
    }
    if horizontal:
        obj["general"][0]["properties"]["orientation"] = {"expr": {"Literal": {"Value": "1D"}}}
    return visual(name, "slicer", x, y, w, h, z, query_state={
        "Values": {"projections": [c_proj(prop)]}
    }, objects=obj)


def risk_return_scatter(name: str) -> dict:
    """Per-fund volatility vs 1Y return, coloured by asset class.

    Sanity filters keep cash-equivalent / data-artifact outliers off the axes
    (1 < std_dev <= 50, cagr_1y <= 100) — same guardrails as Page 1/2.
    """
    return visual(name, "scatterChart", 205, 205, 700, 300, 30, query_state={
        "X": {"projections": [m_proj("Avg Volatility 1Y")]},
        "Y": {"projections": [m_proj("CAGR 1Y")]},
        "Details": {"projections": [c_proj("base_fund_name")]},
        "Category": {"projections": [c_proj("asset_class_label")]},
        "Tooltips": {"projections": [m_proj("Avg Sharpe Ratio", False),
                                     m_proj("Max Drawdown (Worst)", False)]},
    }, filter_cfg={"filters": [
        adv_filter(FUND_TBL, "std_dev_1y", 1, "1D"),
        adv_filter(FUND_TBL, "std_dev_1y", 4, "50D"),
        adv_filter(FUND_TBL, "cagr_1y", 4, "100D"),
    ]})


def sharpe_heatmap(name: str) -> dict:
    """Sharpe ratio grid: asset class (rows) x plan type (columns)."""
    return visual(name, "pivotTable", 915, 205, 520, 300, 31, query_state={
        "Rows": {"projections": [c_proj("asset_class_label")]},
        "Columns": {"projections": [c_proj("plan_type")]},
        "Values": {"projections": [m_proj("Avg Sharpe Ratio")]},
    })


def drawdown_column(name: str) -> dict:
    """Average max drawdown by asset class (more negative = deeper loss)."""
    return visual(name, "clusteredColumnChart", 205, 515, 430, 220, 32, query_state={
        "Category": {"projections": [c_proj("asset_class_label")]},
        "Y": {"projections": [m_proj("Avg max drawdown")]},
        "Tooltips": {"projections": [m_proj("Max Drawdown (Worst)", False),
                                     m_proj("Scheme Count", False)]},
    })


def volatility_column(name: str) -> dict:
    """Average 1Y volatility by asset class."""
    return visual(name, "clusteredColumnChart", 645, 515, 430, 220, 33, query_state={
        "Category": {"projections": [c_proj("asset_class_label")]},
        "Y": {"projections": [m_proj("Avg Volatility 1Y")]},
        "Tooltips": {"projections": [m_proj("Avg Sharpe Ratio", False)]},
    })


def sharpe_by_class_column(name: str) -> dict:
    """Average Sharpe by asset class."""
    return visual(name, "clusteredColumnChart", 1085, 515, 350, 220, 34, query_state={
        "Category": {"projections": [c_proj("asset_class_label")]},
        "Y": {"projections": [m_proj("Avg Sharpe Ratio")]},
        "Tooltips": {"projections": [m_proj("Avg Sortino Ratio", False)]},
    })


def risk_matrix(name: str) -> dict:
    """Fund risk leaderboard."""
    return visual(name, "pivotTable", 0, 748, 1440, 152, 20, query_state={
        "Rows": {"projections": [
            c_proj("base_fund_name"),
            c_proj("amc_short_name", False),
            c_proj("asset_class_label", False),
        ]},
        "Values": {"projections": [
            m_proj("Avg Sharpe Ratio"),
            m_proj("Avg Sortino Ratio", False),
            m_proj("Avg Treynor Ratio", False),
            m_proj("Avg Volatility 1Y", False),
            m_proj("Max Drawdown (Worst)", False),
            m_proj("Avg Beta", False),
        ]},
    })


def page_json() -> dict:
    bg = [{"properties": {"color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{CANVAS_BG}'"}}}}}}}]
    return {
        "$schema": PAGE_SCHEMA,
        "name": PAGE4_ID,
        "displayName": "Risk & Volatility",
        "displayOption": "FitToPage",
        "height": 900,
        "width": 1440,
        "objects": {"background": bg, "outspace": bg},
    }


# ── main ──────────────────────────────────────────────────────────────────────
def build() -> None:
    with zipfile.ZipFile(PBIX, "r") as src:
        pages = json.loads(src.read("Report/definition/pages/pages.json"))
        ctypes = src.read("[Content_Types].xml").decode("utf-8-sig")
    print(f"Existing pages: {pages['pageOrder']}")

    KPI_CARDS = [
        ("Avg Sharpe Ratio",     20),
        ("Avg Sortino Ratio",    240),
        ("Avg Treynor Ratio",    460),
        ("Avg Volatility 1Y",    680),
        ("Max Drawdown (Worst)", 900),
        ("Avg max drawdown",     1120),
    ]

    new_visuals: dict[str, dict] = {}

    hdr, ttl = vid(), vid()
    new_visuals[hdr] = header_shape(hdr)
    new_visuals[ttl] = title_textbox(ttl)

    for idx, (m_name, x) in enumerate(KPI_CARDS):
        c_id = vid()
        new_visuals[c_id] = kpi_card(c_id, m_name, float(x), 10 + idx)

    s1, s2, s3 = vid(), vid(), vid()
    new_visuals[s1] = slicer(s1, "asset_class_label", 0, 205, 195, 200, 40)
    new_visuals[s2] = slicer(s2, "plan_type",         0, 415, 195, 100, 41, horizontal=True)
    new_visuals[s3] = slicer(s3, "amc_short_name",    0, 525, 195, 210, 42)

    sct, heat, dd, vol, shp, mat = vid(), vid(), vid(), vid(), vid(), vid()
    new_visuals[sct]  = risk_return_scatter(sct)
    new_visuals[heat] = sharpe_heatmap(heat)
    new_visuals[dd]   = drawdown_column(dd)
    new_visuals[vol]  = volatility_column(vol)
    new_visuals[shp]  = sharpe_by_class_column(shp)
    new_visuals[mat]  = risk_matrix(mat)

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for v_id, v_data in new_visuals.items():
        vdir = STAGE / v_id
        vdir.mkdir()
        (vdir / "visual.json").write_text(json.dumps(v_data, indent=2), encoding="utf-8")

    (STAGE / "page.json").write_text(json.dumps(page_json(), indent=2), encoding="utf-8")
    if PAGE4_ID not in pages["pageOrder"]:
        pages["pageOrder"].append(PAGE4_ID)
    (STAGE / "pages.json").write_text(json.dumps(pages, indent=2), encoding="utf-8")

    ctypes = ctypes.replace('<Override PartName="/SecurityBindings" ContentType="" />', "")
    (STAGE / "content_types.xml").write_bytes(b"\xef\xbb\xbf" + ctypes.encode("utf-8"))

    (STAGE / "_new_ids.txt").write_text("\n".join(new_visuals.keys()), encoding="utf-8")
    (STAGE / "_page_id.txt").write_text(PAGE4_ID, encoding="utf-8")

    print(f"New page id: {PAGE4_ID}  (Risk & Volatility)")
    print(f"Staged {len(new_visuals)} visuals -> {STAGE}")
    print("Now run: pwsh scripts/etl/repack_pbix_page4.ps1")


if __name__ == "__main__":
    build()
