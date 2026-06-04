"""
Build Page 2 visuals for mf_analytics_dashboard.pbix — Fund Performance.

Populates the (currently empty) second report page
'1f14492bb3a11526ba5f' with a full Fund Performance layout:
returns, rolling periods (1Y/3Y/5Y), and benchmark comparison.

All visuals bind to EXISTING model objects (verified live via the
Power BI modeling MCP) — no new DAX measures are required:
  - Measures on MF : CAGR 1Y/3Y/5Y, CAGR 1Y Max, Avg Alpha, Avg Beta,
                     Avg Sharpe Ratio, Avg Volatility 1Y, Max Drawdown (Worst),
                     Rolling Return 1Y vs Benchmark, Funds Beating Benchmark %,
                     Scheme Count, Funds with 3Y History
  - vw_fund_performance columns : base_fund_name, amc_short_name,
                     asset_class_label (calc), plan_type, cagr_1y

Canvas: 1440 x 900 (matches Page 1 'Executive' for a consistent report).
Layout:
  Row 1 (y=0-54)    : Header bar + title
  Row 2 (y=58-188)  : 6 KPI cards
  Row 3 (y=205-505) : Left slicers (3) + Rolling-returns bar + Risk-return scatter
  Row 4 (y=515-735) : CAGR-by-asset-class column + Top-AMC-vs-benchmark bar
  Row 5 (y=748-900) : Fund performance leaderboard matrix

Run:  python scripts/etl/build_page2_visuals.py
Then: pwsh scripts/etl/repack_pbix_page2.ps1
"""
from __future__ import annotations
import json, shutil, uuid, zipfile
from pathlib import Path

PBIX     = Path("powerbi/mf_analytics_dashboard.pbix")     # source (has Page 1 + full DataModel)
PAGE2_ID = "1f14492bb3a11526ba5f"
SCHEMA   = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.8.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
FUND_TBL = "vw_fund_performance"
MEAS_TBL = "Measures on MF"
NAVY     = "#1B3A6B"
CANVAS_BG = "#F4F7FB"
STAGE    = Path("powerbi/_p2_stage")


# ── helpers (mirrors build_page1_visuals.py) ───────────────────────────────────
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


def topn_filter(entity: str, prop: str, order_measure: str, count: int) -> dict:
    return {
        "name": vid(),
        "field": col(entity, prop),
        "type": "TopN",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": entity, "Type": 0}],
            "Where": [{
                "Condition": {
                    "TopN": {
                        "Direction": 1,
                        "Count": count,
                        "OrderBy": [{"Ascending": False,
                                     "Expression": {"Measure": {
                                         "Expression": {"SourceRef": {"Name": "t"}},
                                         "Property": order_measure
                                     }}}]
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
            "Fund Performance  |  Returns · Rolling 1Y/3Y/5Y · Benchmark  |  4,961 Schemes  ·  Data: 31-May-2026"
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


def rolling_returns_bar(name: str) -> dict:
    """Top 15 funds — grouped bars for CAGR 1Y / 3Y / 5Y."""
    return visual(name, "clusteredBarChart", 205, 205, 700, 300, 30, query_state={
        "Category": {"projections": [c_proj("base_fund_name")]},
        "Y": {"projections": [m_proj("CAGR 1Y"), m_proj("CAGR 3Y"), m_proj("CAGR 5Y")]},
        "Tooltips": {"projections": [
            c_proj("amc_short_name", False),
            m_proj("Avg Sharpe Ratio", False),
            m_proj("Avg Alpha", False),
        ]},
    }, filter_cfg={"filters": [topn_filter(FUND_TBL, "base_fund_name", "CAGR 1Y", 15)]})


def risk_return_scatter(name: str) -> dict:
    """Per-fund risk (volatility) vs return (CAGR 1Y)."""
    return visual(name, "scatterChart", 915, 205, 520, 300, 31, query_state={
        "X": {"projections": [m_proj("Avg Volatility 1Y")]},
        "Y": {"projections": [m_proj("CAGR 1Y")]},
        "Size": {"projections": [m_proj("Avg Sharpe Ratio")]},
        "Details": {"projections": [c_proj("base_fund_name")]},
        "Category": {"projections": [c_proj("asset_class_label", False)]},
        "Tooltips": {"projections": [m_proj("Avg Beta", False), m_proj("CAGR 3Y", False)]},
    })


def cagr_by_assetclass_column(name: str) -> dict:
    """CAGR 1Y/3Y/5Y grouped by simplified asset class."""
    return visual(name, "clusteredColumnChart", 205, 515, 700, 220, 32, query_state={
        "Category": {"projections": [c_proj("asset_class_label")]},
        "Y": {"projections": [m_proj("CAGR 1Y"), m_proj("CAGR 3Y"), m_proj("CAGR 5Y")]},
        "Tooltips": {"projections": [m_proj("Scheme Count", False),
                                     m_proj("Avg Sharpe Ratio", False)]},
    })


def amc_vs_benchmark_bar(name: str) -> dict:
    """Top 12 AMCs by 1Y return vs benchmark (Nifty 50)."""
    return visual(name, "clusteredBarChart", 915, 515, 520, 220, 33, query_state={
        "Category": {"projections": [c_proj("amc_short_name")]},
        "Y": {"projections": [m_proj("Rolling Return 1Y vs Benchmark")]},
        "Tooltips": {"projections": [m_proj("CAGR 1Y", False),
                                     m_proj("Benchmark Return", False),
                                     m_proj("Scheme Count", False)]},
    }, filter_cfg={"filters": [
        topn_filter(FUND_TBL, "amc_short_name", "Rolling Return 1Y vs Benchmark", 12)
    ]})


def leaderboard_matrix(name: str) -> dict:
    """Full-width fund leaderboard."""
    return visual(name, "pivotTable", 0, 748, 1440, 152, 20, query_state={
        "Rows": {"projections": [
            c_proj("base_fund_name"),
            c_proj("amc_short_name", False),
            c_proj("asset_class_label", False),
            c_proj("plan_type", False),
        ]},
        "Values": {"projections": [
            m_proj("CAGR 1Y Max"),
            m_proj("CAGR 3Y", False),
            m_proj("CAGR 5Y", False),
            m_proj("Avg Sharpe Ratio", False),
            m_proj("Avg Alpha", False),
            m_proj("Avg Beta", False),
            m_proj("Max Drawdown (Worst)", False),
        ]},
    })


def page_json() -> dict:
    """Upgrade Page 2 to 1440x900 with Page-1 styling + a proper name."""
    bg = [{"properties": {"color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{CANVAS_BG}'"}}}}}}}]
    return {
        "$schema": PAGE_SCHEMA,
        "name": PAGE2_ID,
        "displayName": "Fund Performance",
        "displayOption": "FitToPage",
        "height": 900,
        "width": 1440,
        "objects": {"background": bg, "outspace": bg},
    }


# ── main ──────────────────────────────────────────────────────────────────────
def build() -> None:
    page2_prefix = f"Report/definition/pages/{PAGE2_ID}/visuals/"
    with zipfile.ZipFile(PBIX, "r") as src:
        existing = sorted({
            f.split("/")[5] for f in src.namelist()
            if f.startswith(page2_prefix) and f.endswith("visual.json")
        })
    print(f"Existing page-2 visuals (will be dropped): {len(existing)}")

    KPI_CARDS = [
        ("CAGR 1Y",                   20),
        ("CAGR 3Y",                  240),
        ("CAGR 5Y",                  460),
        ("Avg Alpha",                680),
        ("Avg Beta",                 900),
        ("Funds Beating Benchmark %", 1120),
    ]

    new_visuals: dict[str, dict] = {}

    hdr, ttl = vid(), vid()
    new_visuals[hdr] = header_shape(hdr)
    new_visuals[ttl] = title_textbox(ttl)

    for idx, (m_name, x) in enumerate(KPI_CARDS):
        c_id = vid()
        new_visuals[c_id] = kpi_card(c_id, m_name, float(x), 10 + idx)

    s1, s2, s3 = vid(), vid(), vid()
    new_visuals[s1] = slicer(s1, "asset_class_label", 0, 205, 195, 260, 40)
    new_visuals[s2] = slicer(s2, "plan_type",         0, 475, 195,  90, 41, horizontal=True)
    new_visuals[s3] = slicer(s3, "amc_short_name",    0, 575, 195, 160, 42)

    bar, sct, colc, amc, mat = vid(), vid(), vid(), vid(), vid()
    new_visuals[bar]  = rolling_returns_bar(bar)
    new_visuals[sct]  = risk_return_scatter(sct)
    new_visuals[colc] = cagr_by_assetclass_column(colc)
    new_visuals[amc]  = amc_vs_benchmark_bar(amc)
    new_visuals[mat]  = leaderboard_matrix(mat)

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for v_id, v_data in new_visuals.items():
        vdir = STAGE / v_id
        vdir.mkdir()
        (vdir / "visual.json").write_text(json.dumps(v_data, indent=2), encoding="utf-8")

    (STAGE / "_delete_ids.txt").write_text("\n".join(existing), encoding="utf-8")
    (STAGE / "_new_ids.txt").write_text("\n".join(new_visuals.keys()), encoding="utf-8")
    (STAGE / "page.json").write_text(json.dumps(page_json(), indent=2), encoding="utf-8")

    # Modifying the package invalidates the signed SecurityBindings part, so we
    # drop it and remove its Override from [Content_Types].xml. Power BI Desktop
    # then opens the file as unsigned and regenerates the signature on Save.
    with zipfile.ZipFile(PBIX, "r") as src:
        ctypes = src.read("[Content_Types].xml").decode("utf-8-sig")
    ctypes = ctypes.replace('<Override PartName="/SecurityBindings" ContentType="" />', "")
    # write WITH BOM, no trailing newline (matches original encoding)
    (STAGE / "content_types.xml").write_bytes(b"\xef\xbb\xbf" + ctypes.encode("utf-8"))

    print(f"Staged {len(new_visuals)} new visuals -> {STAGE}")
    print("Page.json upgraded to 1440x900 'Fund Performance'")
    print("SecurityBindings will be dropped (repack); patched [Content_Types].xml staged")
    print("Now run: pwsh scripts/etl/repack_pbix_page2.ps1")


if __name__ == "__main__":
    build()
