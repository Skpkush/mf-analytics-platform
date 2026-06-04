"""
Build Page 1 visuals for mf_analytics_dashboard.pbix.

Replaces all existing visuals on the 'Executive' page (b5a4a9ec836108a694af)
with a fully configured Fund Performance Dashboard layout.

Canvas: 1440 x 900
Layout:
  Row 1 (y=0-54)    : Header bar + title
  Row 2 (y=58-195)  : 6 KPI cards
  Row 3 (y=205-740) : Left slicers (3) + Bar chart + Donut + Scatter + Column
  Row 4 (y=748-900) : Fund Leaderboard matrix

Run: python scripts/etl/build_page1_visuals.py
"""
from __future__ import annotations
import json, shutil, uuid, zipfile
from pathlib import Path

PBIX    = Path("powerbi/mf_analytics_dashboard.pbix")
OUT     = Path("powerbi/mf_analytics_dashboard_p1.pbix")   # write here (PBI has original locked)
BACKUP  = PBIX.with_suffix(".bak.pbix")
PAGE1_ID = "b5a4a9ec836108a694af"
SCHEMA   = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.8.0/schema.json"
FUND_TBL = "vw_fund_performance"
MEAS_TBL = "Measures on MF"


# ── helpers ───────────────────────────────────────────────────────────────────
def vid() -> str:
    return uuid.uuid4().hex[:20]


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(prop: str, entity: str = MEAS_TBL) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def agg(entity: str, prop: str, fn: int) -> dict:
    """fn: 0=Sum 1=Avg 2=Min 3=Max 4=Count 5=CountDistinct"""
    return {"Aggregation": {"Expression": col(entity, prop), "Function": fn}}


def proj(field: dict, query_ref: str, native_ref: str, active: bool = True) -> dict:
    p: dict = {"field": field, "queryRef": query_ref, "nativeQueryRef": native_ref}
    if active:
        p["active"] = True
    return p


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


def adv_filter(name: str, entity: str, prop: str, kind: int, value: str) -> dict:
    """Numeric advanced filter. kind: 0=Eq 1=GT 2=GTE 3=LT 4=LTE"""
    return {
        "name": name,
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


# ── visual definitions ────────────────────────────────────────────────────────
def make_header_shape(name: str) -> dict:
    return visual(name, "shape", 0, 0, 1440, 54, 5,
                  objects={
                      "general": [{"properties": {"shapeType": {"expr": {"Literal": {"Value": "'rectangle'"}}}}}],
                      "fill":    [{"properties": {"fillColor": {"solid": {"color": {"expr": {"Literal": {"Value": "'#1B3A6B'"}}}}}}}],
                  })


def make_title_textbox(name: str) -> dict:
    return visual(name, "textbox", 12, 8, 900, 38, 6,
                  objects={
                      "general": [{"properties": {"paragraphs": {"expr": {"Literal": {"Value": json.dumps([{
                          "textRuns": [{
                              "value": "Mutual Fund Performance Dashboard  |  Fund Universe: 4,956 Schemes  |  Data: 31-May-2026",
                              "textStyle": {"fontFamily": "Segoe UI", "fontSize": "14pt", "bold": True, "color": "#FFFFFF"}
                          }]
                      }])}}}}}]
                  })


def make_kpi_card(name: str, measure_name: str, x: float, z: int) -> dict:
    return visual(name, "cardVisual", x, 58, 210, 130, z,
                  query_state={
                      "Data": {"projections": [proj(meas(measure_name), f"{MEAS_TBL}.{measure_name}", measure_name)]}
                  })


def make_slicer_column(name: str, entity: str, prop: str, x: float, y: float,
                       w: float, h: float, z: int, orientation: str = "vertical") -> dict:
    obj: dict = {
        "data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Basic'"}}}}}],
        "general": [{"properties": {}}]
    }
    if orientation == "horizontal":
        obj["general"][0]["properties"]["orientation"] = {"expr": {"Literal": {"Value": "1D"}}}
    return visual(name, "slicer", x, y, w, h, z,
                  query_state={
                      "Values": {"projections": [proj(col(entity, prop),
                                                      f"{entity}.{prop}", prop)]}
                  }, objects=obj)


def make_bar_chart(name: str) -> dict:
    """Horizontal bar: Top 20 funds by CAGR 1Y (cagr_1y <= 100 filter)."""
    return visual(
        name, "clusteredBarChart", 205, 205, 680, 260, 30,
        query_state={
            "Category": {"projections": [proj(col(FUND_TBL, "base_fund_name"),
                                              f"{FUND_TBL}.base_fund_name", "base_fund_name")]},
            "Y":        {"projections": [proj(meas("CAGR 1Y Max"),
                                              f"{MEAS_TBL}.CAGR 1Y Max", "CAGR 1Y Max")]},
            "Series":   {"projections": [proj(col(FUND_TBL, "asset_class_label"),
                                              f"{FUND_TBL}.asset_class_label", "asset_class_label")]},
            "Tooltips": {"projections": [
                proj(col(FUND_TBL, "amc_short_name"), f"{FUND_TBL}.amc_short_name", "amc_short_name", False),
                proj(meas("CAGR 3Y"),   f"{MEAS_TBL}.CAGR 3Y",   "CAGR 3Y",   False),
                proj(meas("Avg Sharpe Ratio"), f"{MEAS_TBL}.Avg Sharpe Ratio", "Avg Sharpe Ratio", False),
                proj(meas("Avg Volatility 1Y"), f"{MEAS_TBL}.Avg Volatility 1Y", "Avg Volatility 1Y", False),
            ]},
        },
        filter_cfg={"filters": [
            adv_filter(vid(), FUND_TBL, "cagr_1y", 4, "100D"),   # cagr_1y <= 100
            {
                "name": vid(),
                "field": col(FUND_TBL, "base_fund_name"),
                "type": "TopN",
                "filter": {
                    "Version": 2,
                    "From": [{"Name": "t", "Entity": FUND_TBL, "Type": 0}],
                    "Where": [{
                        "Condition": {
                            "TopN": {
                                "Direction": 1,
                                "Count": 20,
                                "OrderBy": [{"Ascending": False,
                                             "Expression": {"Measure": {
                                                 "Expression": {"SourceRef": {"Name": "t"}},
                                                 "Property": "CAGR 1Y Max"
                                             }}}]
                            }
                        }
                    }]
                }
            }
        ]}
    )


def make_donut_chart(name: str) -> dict:
    """Donut: fund count by asset_class_label."""
    return visual(
        name, "donutChart", 895, 205, 280, 260, 31,
        query_state={
            "Category": {"projections": [proj(col(FUND_TBL, "asset_class_label"),
                                              f"{FUND_TBL}.asset_class_label", "asset_class_label")]},
            "Y":        {"projections": [proj(meas("Scheme Count"),
                                              f"{MEAS_TBL}.Scheme Count", "Scheme Count")]},
        }
    )


def make_scatter_chart(name: str) -> dict:
    """Scatter: risk vs return by asset class (one bubble per category)."""
    return visual(
        name, "scatterChart", 1185, 205, 250, 260, 32,
        query_state={
            "X":       {"projections": [proj(meas("Avg Volatility 1Y"),
                                             f"{MEAS_TBL}.Avg Volatility 1Y", "Avg Volatility 1Y")]},
            "Y":       {"projections": [proj(meas("Avg CAGR 1Y (Clean)"),
                                             f"{MEAS_TBL}.Avg CAGR 1Y (Clean)", "Avg CAGR 1Y (Clean)")]},
            "Size":    {"projections": [proj(meas("Scheme Count"),
                                             f"{MEAS_TBL}.Scheme Count", "Scheme Count")]},
            "Details": {"projections": [proj(col(FUND_TBL, "asset_class_label"),
                                             f"{FUND_TBL}.asset_class_label", "asset_class_label")]},
        },
        filter_cfg={"filters": [
            adv_filter(vid(), FUND_TBL, "std_dev_1y", 1, "1D"),   # std_dev > 1
            adv_filter(vid(), FUND_TBL, "std_dev_1y", 4, "50D"),  # std_dev <= 50
        ]}
    )


def make_column_chart(name: str) -> dict:
    """Clustered column: Top 10 AMCs by Avg CAGR 1Y (Clean)."""
    return visual(
        name, "clusteredColumnChart", 205, 475, 930, 260, 33,
        query_state={
            "Category": {"projections": [proj(col(FUND_TBL, "amc_short_name"),
                                              f"{FUND_TBL}.amc_short_name", "amc_short_name")]},
            "Y":        {"projections": [proj(meas("Avg CAGR 1Y (Clean)"),
                                              f"{MEAS_TBL}.Avg CAGR 1Y (Clean)", "Avg CAGR 1Y (Clean)")]},
            "Tooltips": {"projections": [
                proj(meas("Scheme Count"),        f"{MEAS_TBL}.Scheme Count", "Scheme Count", False),
                proj(meas("Avg Sharpe Ratio"),    f"{MEAS_TBL}.Avg Sharpe Ratio", "Avg Sharpe Ratio", False),
                proj(meas("% Alpha Positive"),    f"{MEAS_TBL}.% Alpha Positive", "% Alpha Positive", False),
                proj(meas("Funds with 3Y History"), f"{MEAS_TBL}.Funds with 3Y History", "Funds with 3Y History", False),
            ]},
        },
        filter_cfg={"filters": [
            adv_filter(vid(), FUND_TBL, "cagr_1y", 4, "100D"),
            {
                "name": vid(),
                "field": col(FUND_TBL, "amc_short_name"),
                "type": "TopN",
                "filter": {
                    "Version": 2,
                    "From": [{"Name": "t", "Entity": FUND_TBL, "Type": 0}],
                    "Where": [{
                        "Condition": {
                            "TopN": {
                                "Direction": 1,
                                "Count": 10,
                                "OrderBy": [{"Ascending": False,
                                             "Expression": {"Measure": {
                                                 "Expression": {"SourceRef": {"Name": "t"}},
                                                 "Property": "Avg CAGR 1Y (Clean)"
                                             }}}]
                            }
                        }
                    }]
                }
            }
        ]}
    )


def make_matrix(name: str) -> dict:
    """Fund leaderboard: top 50 by CAGR 1Y."""
    return visual(
        name, "pivotTable", 0, 748, 1440, 152, 20,
        query_state={
            "Rows": {"projections": [
                proj(col(FUND_TBL, "base_fund_name"),   f"{FUND_TBL}.base_fund_name",   "base_fund_name"),
                proj(col(FUND_TBL, "amc_short_name"),   f"{FUND_TBL}.amc_short_name",   "amc_short_name", False),
                proj(col(FUND_TBL, "asset_class_label"), f"{FUND_TBL}.asset_class_label", "asset_class_label", False),
                proj(col(FUND_TBL, "plan_type"),         f"{FUND_TBL}.plan_type",         "plan_type", False),
            ]},
            "Values": {"projections": [
                proj(meas("CAGR 1Y Max"),        f"{MEAS_TBL}.CAGR 1Y Max",        "CAGR 1Y Max"),
                proj(meas("CAGR 3Y"),            f"{MEAS_TBL}.CAGR 3Y",            "CAGR 3Y", False),
                proj(meas("Avg Sharpe Ratio"),   f"{MEAS_TBL}.Avg Sharpe Ratio",   "Avg Sharpe Ratio", False),
                proj(meas("Avg Volatility 1Y"),  f"{MEAS_TBL}.Avg Volatility 1Y",  "Avg Volatility 1Y", False),
                proj(meas("Max Drawdown (Worst)", ), f"{MEAS_TBL}.Max Drawdown (Worst)", "Max Drawdown (Worst)", False),
            ]},
        },
        filter_cfg={"filters": [
            adv_filter(vid(), FUND_TBL, "cagr_1y", 4, "100D"),
        ]}
    )


STAGE = Path("powerbi/_p1_stage")   # staging dir for new visual JSONs


# ── main ──────────────────────────────────────────────────────────────────────
def build() -> None:
    # Read existing page-1 visual IDs (to delete) directly from the backup/source
    src_pbix = BACKUP if BACKUP.exists() else PBIX
    page1_vis_prefix = f"Report/definition/pages/{PAGE1_ID}/visuals/"
    with zipfile.ZipFile(src_pbix, "r") as src:
        old_ids = sorted({
            f.split("/")[5] for f in src.namelist()
            if f.startswith(page1_vis_prefix) and f.endswith("visual.json")
        })
    print(f"Existing page-1 visuals to remove: {len(old_ids)}")

    # Build new visuals
    KPI_CARDS = [
        ("Scheme Count",           20),
        ("Active Funds",          240),
        ("Avg CAGR 1Y (Clean)",   460),
        ("Median CAGR 1Y",        680),
        ("% Alpha Positive",      900),
        ("Latest Data Date",     1120),
    ]

    new_visuals: dict[str, dict] = {}

    hdr_id = vid(); ttl_id = vid()
    new_visuals[hdr_id] = make_header_shape(hdr_id)
    new_visuals[ttl_id] = make_title_textbox(ttl_id)

    for idx, (m_name, x) in enumerate(KPI_CARDS):
        c_id = vid()
        new_visuals[c_id] = make_kpi_card(c_id, m_name, float(x), 10 + idx)

    sl1 = vid(); sl2 = vid(); sl3 = vid()
    new_visuals[sl1] = make_slicer_column(sl1, FUND_TBL, "asset_class_label", 0, 205, 195, 260, 40)
    new_visuals[sl2] = make_slicer_column(sl2, FUND_TBL, "plan_type",         0, 475, 195,  90, 41, "horizontal")
    new_visuals[sl3] = make_slicer_column(sl3, FUND_TBL, "amc_short_name",    0, 575, 195,  80, 42)

    bar_id = vid(); don_id = vid(); sct_id = vid(); col_id = vid(); mat_id = vid()
    new_visuals[bar_id] = make_bar_chart(bar_id)
    new_visuals[don_id] = make_donut_chart(don_id)
    new_visuals[sct_id] = make_scatter_chart(sct_id)
    new_visuals[col_id] = make_column_chart(col_id)
    new_visuals[mat_id] = make_matrix(mat_id)

    # Emit to staging dir (one folder per visual id) + manifest of old ids to delete
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for v_id, v_data in new_visuals.items():
        vdir = STAGE / v_id
        vdir.mkdir()
        (vdir / "visual.json").write_text(json.dumps(v_data, indent=2), encoding="utf-8")

    (STAGE / "_delete_ids.txt").write_text("\n".join(old_ids), encoding="utf-8")
    (STAGE / "_new_ids.txt").write_text("\n".join(new_visuals.keys()), encoding="utf-8")

    print(f"Staged {len(new_visuals)} new visuals -> {STAGE}")
    print(f"Delete manifest: {len(old_ids)} old ids")
    print("Now run the .NET repack (PowerShell).")


if __name__ == "__main__":
    build()
