"""
Build Page 3 visuals for mf_analytics_dashboard.pbix — Investor Analytics.

Creates a NEW third report page (registered in pages.json) covering
investor segmentation, SIP trends, retention, and geography.

All bindings verified live via the Power BI modeling MCP:
  - vw_investor_segmentation is a STANDALONE table (0 relationships), so we
    slice by Dim_Investor (related to the facts via investor_key) instead.
  - Measures on MF (folder '4. Investor'): Total Investors, Investors with
    Active SIP, Total SIP Inflow, Avg Investment per Investor, Redemption
    Rate %, Cumulative SIP Invested.  Total SIP Inflow = SUM(Fact_Transactions
    [amount]) filtered to SIP — time-aware via Fact_Transactions -> Dim_Date.
  - Dim_Investor columns: investor_segment, risk_profile, age_group, state.
  - Dim_Date[full_date] for the monthly SIP trend.

Canvas: 1440 x 900 (matches Pages 1 & 2).
Layout:
  Row 1 (y=0-54)    : Header bar + title
  Row 2 (y=58-188)  : 6 KPI cards
  Row 3 (y=205-505) : Left slicers (3) + SIP trend line + segment donut + age column
  Row 4 (y=515-735) : SIP-by-risk column + Top states bar + redemption-by-segment column
  Row 5 (y=748-900) : Investor segment x risk matrix

Run:  python scripts/etl/build_page3_visuals.py
Then: pwsh scripts/etl/repack_pbix_page3.ps1
"""
from __future__ import annotations
import json, shutil, uuid, zipfile
from pathlib import Path

PBIX        = Path("powerbi/mf_analytics_dashboard.pbix")   # source (Pages 1 & 2 + full DataModel)
SCHEMA      = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.8.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
INV_TBL  = "Dim_Investor"
DATE_TBL = "Dim_Date"
MEAS_TBL = "Measures on MF"
NAVY      = "#1B3A6B"
CANVAS_BG = "#F4F7FB"
STAGE    = Path("powerbi/_p3_stage")
PAGE3_ID = uuid.uuid4().hex[:20]   # brand-new page


# ── helpers (mirror build_page2_visuals.py) ─────────────────────────────────
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


def c_proj(entity: str, prop: str, active: bool = True) -> dict:
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
            "Investor Analytics  |  Segmentation · SIP Trends · Retention · Geography  |  500 Investors  ·  ₹28.98 Cr Invested"
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
        "Values": {"projections": [c_proj(INV_TBL, prop)]}
    }, objects=obj)


def sip_trend_line(name: str) -> dict:
    """Monthly SIP inflow over time (Fact_Transactions -> Dim_Date)."""
    return visual(name, "lineChart", 205, 205, 700, 300, 30, query_state={
        "Category": {"projections": [c_proj(DATE_TBL, "full_date")]},
        "Y": {"projections": [m_proj("Total SIP Inflow")]},
        "Tooltips": {"projections": [m_proj("Cumulative SIP Invested", False),
                                     m_proj("Investors with Active SIP", False)]},
    })


def segment_donut(name: str) -> dict:
    """Investor count by segment."""
    return visual(name, "donutChart", 915, 205, 260, 300, 31, query_state={
        "Category": {"projections": [c_proj(INV_TBL, "investor_segment")]},
        "Y": {"projections": [m_proj("Total Investors")]},
    })


def age_column(name: str) -> dict:
    """Investor count by age group."""
    return visual(name, "clusteredColumnChart", 1185, 205, 250, 300, 32, query_state={
        "Category": {"projections": [c_proj(INV_TBL, "age_group")]},
        "Y": {"projections": [m_proj("Total Investors")]},
        "Tooltips": {"projections": [m_proj("Avg Investment per Investor", False)]},
    })


def sip_by_risk_column(name: str) -> dict:
    """SIP inflow by risk profile."""
    return visual(name, "clusteredColumnChart", 205, 515, 430, 220, 33, query_state={
        "Category": {"projections": [c_proj(INV_TBL, "risk_profile")]},
        "Y": {"projections": [m_proj("Total SIP Inflow")]},
        "Tooltips": {"projections": [m_proj("Total Investors", False),
                                     m_proj("Cumulative SIP Invested", False)]},
    })


def top_states_bar(name: str) -> dict:
    """Top 10 states by SIP inflow."""
    return visual(name, "clusteredBarChart", 645, 515, 430, 220, 34, query_state={
        "Category": {"projections": [c_proj(INV_TBL, "state")]},
        "Y": {"projections": [m_proj("Total SIP Inflow")]},
        "Tooltips": {"projections": [m_proj("Total Investors", False)]},
    }, filter_cfg={"filters": [topn_filter(INV_TBL, "state", "Total SIP Inflow", 10)]})


def redemption_by_segment_column(name: str) -> dict:
    """Retention proxy: redemption rate by segment."""
    return visual(name, "clusteredColumnChart", 1085, 515, 350, 220, 35, query_state={
        "Category": {"projections": [c_proj(INV_TBL, "investor_segment")]},
        "Y": {"projections": [m_proj("Redemption Rate %")]},
        "Tooltips": {"projections": [m_proj("Total Investors", False)]},
    })


def investor_matrix(name: str) -> dict:
    """Segment x risk breakdown."""
    return visual(name, "pivotTable", 0, 748, 1440, 152, 20, query_state={
        "Rows": {"projections": [
            c_proj(INV_TBL, "investor_segment"),
            c_proj(INV_TBL, "risk_profile", False),
        ]},
        "Values": {"projections": [
            m_proj("Total Investors"),
            m_proj("Total SIP Inflow", False),
            m_proj("Cumulative SIP Invested", False),
            m_proj("Avg Investment per Investor", False),
            m_proj("Redemption Rate %", False),
        ]},
    })


def page_json() -> dict:
    bg = [{"properties": {"color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{CANVAS_BG}'"}}}}}}}]
    return {
        "$schema": PAGE_SCHEMA,
        "name": PAGE3_ID,
        "displayName": "Investor Analytics",
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
        ("Total Investors",            20),
        ("Investors with Active SIP",  240),
        ("Total SIP Inflow",           460),
        ("Cumulative SIP Invested",    680),
        ("Avg Investment per Investor", 900),
        ("Redemption Rate %",          1120),
    ]

    new_visuals: dict[str, dict] = {}

    hdr, ttl = vid(), vid()
    new_visuals[hdr] = header_shape(hdr)
    new_visuals[ttl] = title_textbox(ttl)

    for idx, (m_name, x) in enumerate(KPI_CARDS):
        c_id = vid()
        new_visuals[c_id] = kpi_card(c_id, m_name, float(x), 10 + idx)

    s1, s2, s3 = vid(), vid(), vid()
    new_visuals[s1] = slicer(s1, "investor_segment", 0, 205, 195, 200, 40)
    new_visuals[s2] = slicer(s2, "risk_profile",     0, 415, 195, 100, 41, horizontal=True)
    new_visuals[s3] = slicer(s3, "state",            0, 525, 195, 210, 42)

    ln, dn, age, risk, st, red, mat = vid(), vid(), vid(), vid(), vid(), vid(), vid()
    new_visuals[ln]   = sip_trend_line(ln)
    new_visuals[dn]   = segment_donut(dn)
    new_visuals[age]  = age_column(age)
    new_visuals[risk] = sip_by_risk_column(risk)
    new_visuals[st]   = top_states_bar(st)
    new_visuals[red]  = redemption_by_segment_column(red)
    new_visuals[mat]  = investor_matrix(mat)

    # stage visuals
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for v_id, v_data in new_visuals.items():
        vdir = STAGE / v_id
        vdir.mkdir()
        (vdir / "visual.json").write_text(json.dumps(v_data, indent=2), encoding="utf-8")

    # stage page.json + updated pages.json
    (STAGE / "page.json").write_text(json.dumps(page_json(), indent=2), encoding="utf-8")
    if PAGE3_ID not in pages["pageOrder"]:
        pages["pageOrder"].append(PAGE3_ID)
    (STAGE / "pages.json").write_text(json.dumps(pages, indent=2), encoding="utf-8")

    # patched [Content_Types].xml (drop signed SecurityBindings override)
    ctypes = ctypes.replace('<Override PartName="/SecurityBindings" ContentType="" />', "")
    (STAGE / "content_types.xml").write_bytes(b"\xef\xbb\xbf" + ctypes.encode("utf-8"))

    (STAGE / "_new_ids.txt").write_text("\n".join(new_visuals.keys()), encoding="utf-8")
    (STAGE / "_page_id.txt").write_text(PAGE3_ID, encoding="utf-8")

    print(f"New page id: {PAGE3_ID}  (Investor Analytics)")
    print(f"Staged {len(new_visuals)} visuals -> {STAGE}")
    print("Now run: pwsh scripts/etl/repack_pbix_page3.ps1")


if __name__ == "__main__":
    build()
