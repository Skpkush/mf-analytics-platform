"""
Generate Page 1 Visual Build Guide PDF
Mutual Fund Analytics Platform - Power BI Dashboard
"""

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pathlib import Path

# Replace every character outside latin-1 so Helvetica doesn't choke
_REPLACEMENTS = {
    "-": "-",   # em dash
    "-": "-",   # en dash
    "*": "*",   # middle dot
    "x": "x",   # times sign
    "->": "->",  # right arrow
    "<-": "<-",  # left arrow
    "^": "^",   # up arrow
    "v": "v",   # down arrow
    ">=": ">=",  # >=
    "<=": "<=",  # <=
    "!=": "!=",  # not equal
    "[x]": "[x]", # check mark
    "[x]": "[x]", # heavy check
    "-": "-",   # bullet
    "'": "'",   # right single quote
    "'": "'",   # left single quote
    """: '"',   # left double quote
    """: '"',   # right double quote
    # box-drawing
    "┌": "+", "┐": "+", "└": "+", "┘": "+",
    "├": "+", "┤": "+", "┬": "+", "┴": "+",
    "┼": "+", "─": "-", "│": "|", "┤": "+",
    "═": "=", "║": "|",
}

def clean(text: str) -> str:
    for ch, rep in _REPLACEMENTS.items():
        text = text.replace(ch, rep)
    # Hard-encode: replace any remaining non-latin-1 chars with '?'
    return text.encode("latin-1", errors="replace").decode("latin-1")

# ── Colour palette ──────────────────────────────────────────────────────────
BLUE       = (0,   120, 212)   # #0078D4
DARK_BLUE  = (0,   90,  158)   # #005A9E
GREEN      = (16,  124, 16)    # #107C10
AMBER      = (133, 100, 0)     # #856400
RED        = (164, 38,  44)    # #A4262C
WHITE      = (255, 255, 255)
NEAR_BLACK = (37,  36,  35)    # #252423
GREY       = (96,  94,  92)    # #605E5C
LIGHT_GREY = (225, 225, 225)   # #E1E1E1
BG_GREY    = (240, 242, 245)   # #F0F2F5
BG_GREEN   = (232, 245, 233)   # #E8F5E9
BG_AMBER   = (255, 248, 225)   # #FFF8E1
BG_BLUE    = (235, 243, 251)   # #EBF3FB
BG_RED     = (255, 235, 238)   # #FFEBEE
CODE_BG    = (248, 249, 250)   # code block bg

OUTPUT_PATH = Path("docs/powerbi/Page1_Visual_Build_Guide.pdf")


class DashboardPDF(FPDF):

    def header(self):
        self.set_fill_color(*BLUE)
        self.rect(0, 0, 210, 14, style="F")
        self.set_xy(8, 3)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*WHITE)
        self.cell(130, 8, "Mutual Fund Analytics Platform", align="L")
        self.set_font("Helvetica", "", 8)
        self.set_xy(140, 3)
        self.cell(62, 8, "Page 1 - Executive Visual Build Guide", align="R")
        self.set_text_color(*NEAR_BLACK)
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*LIGHT_GREY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GREY)
        self.cell(0, 6,
                  f"mf_analytics_dashboard.pbix * Power BI Desktop * Page {self.page_no()} of {{nb}}",
                  align="C")

    # ── helpers ─────────────────────────────────────────────────────────────

    def section_title(self, step_num: str, title: str, color=BLUE):
        self.ln(3)
        # coloured left bar + step badge
        x, y = self.get_x(), self.get_y()
        self.set_fill_color(*color)
        self.rect(10, y, 3, 8, style="F")
        self.set_xy(14, y)
        # step badge
        self.set_fill_color(*color)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 8)
        self.cell(22, 8, f" Step {step_num}", fill=True, border=0)
        # title
        self.set_text_color(*color)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, clean(f"  {title}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*NEAR_BLACK)
        self.ln(1)

    def sub_heading(self, text: str, color=GREY):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*color)
        self.cell(0, 6, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*NEAR_BLACK)

    def body(self, text: str, indent: int = 0):
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*NEAR_BLACK)
        self.set_x(10 + indent)
        self.multi_cell(190 - indent, 5, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullet(self, text: str, indent: int = 4):
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*NEAR_BLACK)
        self.set_x(10 + indent)
        self.cell(4, 5, "-")
        self.set_x(10 + indent + 4)
        self.multi_cell(186 - indent, 5, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def spec_row(self, label: str, value: str, label_color=GREY):
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*label_color)
        self.set_x(14)
        self.cell(38, 5.5, clean(label))
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*NEAR_BLACK)
        self.multi_cell(148, 5.5, clean(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def code_block(self, code: str):
        self.ln(1)
        x, y = 14, self.get_y()
        lines = code.strip().split("\n")
        line_h = 4.5
        block_h = len(lines) * line_h + 6
        self.set_fill_color(*CODE_BG)
        self.set_draw_color(*LIGHT_GREY)
        self.rect(14, y, 182, block_h, style="FD")
        self.set_fill_color(*BLUE)
        self.rect(14, y, 2, block_h, style="F")
        self.set_xy(18, y + 3)
        self.set_font("Courier", "", 7.5)
        self.set_text_color(50, 50, 50)
        for line in lines:
            self.set_x(18)
            self.cell(0, line_h, clean(line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*NEAR_BLACK)
        self.ln(2)

    def info_box(self, text: str, bg=BG_BLUE, border_color=BLUE):
        self.ln(1)
        text = clean(text)
        y = self.get_y()
        self.set_fill_color(*bg)
        self.set_draw_color(*border_color)
        lines_est = max(1, len(text) // 88 + text.count("\n") + 1)
        h = lines_est * 5 + 6
        self.rect(14, y, 182, h, style="FD")
        self.set_fill_color(*border_color)
        self.rect(14, y, 2.5, h, style="F")
        self.set_xy(19, y + 3)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*NEAR_BLACK)
        self.multi_cell(175, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def position_badge(self, w, h, x, y):
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*GREY)
        self.set_x(14)
        self.cell(0, 5, f"  Position & Size:  W={w}  H={h}  X={x}  Y={y}",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*NEAR_BLACK)

    def divider(self):
        self.ln(2)
        self.set_draw_color(*LIGHT_GREY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def col_table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [int(180 / len(headers))] * len(headers)
        # header row
        self.set_fill_color(*BLUE)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 8)
        self.set_x(14)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, clean(h), border=1, fill=True, align="C")
        self.ln()
        self.set_text_color(*NEAR_BLACK)
        for ri, row in enumerate(rows):
            self.set_fill_color(248, 249, 250) if ri % 2 == 0 else self.set_fill_color(255, 255, 255)
            self.set_font("Helvetica", "", 7.5)
            self.set_x(14)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 5.5, clean(str(cell)), border=1, fill=True, align="C" if i > 0 else "L")
            self.ln()
        self.ln(2)


# ── Build PDF ────────────────────────────────────────────────────────────────

def build_pdf():
    pdf = DashboardPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.alias_nb_pages()

    # ── PAGE 1: Cover + Setup ────────────────────────────────────────────────
    pdf.add_page()

    # Hero band
    pdf.set_fill_color(*BLUE)
    pdf.rect(0, 14, 210, 52, style="F")
    pdf.set_fill_color(*DARK_BLUE)
    pdf.rect(0, 50, 210, 16, style="F")

    pdf.set_xy(10, 20)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 10, "Power BI Dashboard - Page 1", align="L")

    pdf.set_xy(10, 33)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Executive Overview  |  Visual Build Guide", align="L")

    pdf.set_xy(10, 44)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(191, 230, 255)
    pdf.cell(0, 6, "Mutual Fund Analytics Platform  *  mf_analytics_dashboard.pbix  *  Azure SQL  *  2026-06-01")

    pdf.set_xy(10, 52)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*WHITE)
    pdf.cell(90, 6, "10 Steps  *  10 Visuals  *  38 DAX Measures pre-built")
    pdf.set_x(110)
    pdf.cell(90, 6, "Canvas: 1280 x 800 px  *  Import Mode", align="R")

    pdf.set_text_color(*NEAR_BLACK)
    pdf.set_y(72)

    # What's on this page overview table
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*BLUE)
    pdf.cell(0, 7, "What gets built on Page 1 - Executive", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEAR_BLACK)

    overview = [
        ("Step 0", "Page & Canvas Setup",           "Before adding any visuals"),
        ("Step 1", "Header Bar",                     "Blue gradient title bar (top)"),
        ("Step 2", "Toolbar Strip + Asset Slicer",   "White bar with class filter tiles"),
        ("Step 3", "3 x KPI Cards",             "AUM * Beating Nifty * Best Risk-Adjusted"),
        ("Step 4", "MetricSelector Slicer",          "CAGR 1Y / 3Y / 5Y / Sharpe / Alpha tiles"),
        ("Step 5", "Fund Ranking Bar Chart",         "Horizontal bars, dynamic sort by metric"),
        ("Step 6", "Risk vs Return Scatter",         "Signature 4-quadrant scatter chart"),
        ("Step 7", "Needs Attention Table",          "Worst Sharpe + high drawdown funds"),
        ("Step 8", "Asset Class Mix Donut",          "Equity / Index / Gold / Liquid split"),
        ("Step 9", "Fund Performance Matrix",        "Full-width table, colour-coded all metrics"),
        ("Step 10","Footer Bar",                     "Page indicator + pipeline status"),
    ]
    pdf.col_table(
        ["Step", "Visual", "Description"],
        overview,
        col_widths=[18, 60, 102]
    )

    pdf.info_box(
        "PRE-REQUISITES before building visuals:\n"
        "1. All 38 DAX measures already deployed to Executive_measures table via PowerBI MCP.\n"
        "2. Apply theme: View -> Themes -> Browse -> powerbi/theme_mf_analytics.json\n"
        "3. Set canvas: File -> Options -> Report settings -> Custom -> 1280 x 800 px\n"
        "4. Rename page tab to 'Executive' and set tab color #0078D4.",
        bg=BG_BLUE, border_color=BLUE
    )

    # ── PAGE 2: Step 0 + Step 1 + Step 2 ─────────────────────────────────────
    pdf.add_page()

    pdf.section_title("0", "Page & Canvas Setup")
    pdf.spec_row("Page name",   "Executive")
    pdf.spec_row("Tab color",   "#0078D4")
    pdf.spec_row("Canvas",      "Custom  1280 x 800 px  -  File -> Options -> Report settings")
    pdf.spec_row("Theme",       "View -> Themes -> Browse for themes -> powerbi/theme_mf_analytics.json")
    pdf.spec_row("Page view",   "View -> Page view -> Actual size  (so pixel positions are exact)")
    pdf.divider()

    pdf.section_title("1", "Header Bar")
    pdf.sub_heading("Insert -> Shapes -> Rectangle")
    pdf.spec_row("Size & pos",  "W: 1280  H: 44  X: 0  Y: 0")
    pdf.spec_row("Fill",        "Gradient - Direction: Left-to-Right  |  Stop 1: #0078D4  |  Stop 2: #005A9E")
    pdf.spec_row("Border",      "OFF")
    pdf.spec_row("Shadow",      "OFF")

    pdf.ln(2)
    pdf.sub_heading("Insert -> Text box  (main title, over the rectangle)")
    pdf.spec_row("Text",        "Mutual Fund Analytics Platform")
    pdf.spec_row("Font",        "Segoe UI  14pt  Bold  White")
    pdf.spec_row("Position",    "X: 52  Y: 12")

    pdf.ln(2)
    pdf.sub_heading("Insert -> Text box  (subtitle line)")
    pdf.spec_row("Text",        "Azure SQL * 11 Funds * 500 Investors * Last refresh: 01 Jun 2026, 07:30 IST")
    pdf.spec_row("Font",        "Segoe UI  9pt  Regular  #BFE6FF")
    pdf.spec_row("Position",    "X: 52  Y: 28")

    pdf.info_box(
        "TIP: Lock the header rectangle so you don't accidentally move it.\n"
        "Right-click the rectangle -> Lock  (or use the Selection pane: View -> Selection).",
        bg=BG_AMBER, border_color=(255, 185, 0)
    )
    pdf.divider()

    pdf.section_title("2", "Toolbar Strip + Asset Class Slicer")
    pdf.sub_heading("Insert -> Shapes -> Rectangle  (toolbar background)")
    pdf.spec_row("Size & pos",  "W: 1280  H: 30  X: 0  Y: 44")
    pdf.spec_row("Fill",        "White")
    pdf.spec_row("Border",      "Bottom border only  -  color #E1E1E1  -  0.5 px")

    pdf.ln(2)
    pdf.sub_heading("Visualizations -> Slicer  (asset class filter)")
    pdf.spec_row("Field",       "vw_fund_performance[asset_class]")
    pdf.spec_row("Style",       "Format -> Slicer settings -> Style: Tile")
    pdf.spec_row("Orientation", "Format -> Slicer settings -> Orientation: Horizontal")
    pdf.spec_row("Selection",   "Multi-select with Ctrl: OFF  |  Show 'Select all': ON")
    pdf.spec_row("Font",        "Segoe UI  9pt")
    pdf.spec_row("Size & pos",  "W: 550  H: 24  X: 80  Y: 48")
    pdf.spec_row("Tile colors", "Default: bg #F5F5F5  |  Selected: bg #0078D4 text White")

    pdf.ln(2)
    pdf.sub_heading("Insert -> Text box  (right side of toolbar)")
    pdf.spec_row("Text",        "Auto-refresh: Daily 07:30 IST  *  ADF Pipeline Active")
    pdf.spec_row("Font",        "Segoe UI  9pt  #A0A0A0")
    pdf.spec_row("Position",    "X: 980  Y: 53")

    # ── PAGE 3: Step 3 - KPI Cards ────────────────────────────────────────────
    pdf.add_page()

    pdf.section_title("3", "Three KPI Cards", color=GREEN)

    pdf.info_box(
        "Use the NEW Card visual (not the legacy Card). Click Visualizations -> Card (new).\n"
        "All three cards sit in a row below the toolbar. The top accent bar is added as a\n"
        "3px top border in Format -> Visual border.",
        bg=BG_GREEN, border_color=GREEN
    )

    # Card 1
    pdf.ln(1)
    pdf.set_fill_color(*BG_BLUE)
    pdf.set_draw_color(*BLUE)
    self_x = 14
    pdf.set_x(self_x)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*BLUE)
    pdf.cell(182, 6, "  Card 1 - Portfolio AUM  (Blue)", border="LTR", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEAR_BLACK)
    pdf.set_fill_color(*BG_BLUE)
    pdf.set_x(14)
    pdf.set_font("Helvetica", "", 1)
    pdf.cell(182, 1, "", border="LR", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.spec_row("Callout value",    "[Total AUM (Formatted)]  -> Segoe UI  22pt  Bold  #252423")
    pdf.spec_row("Category label",   "Portfolio AUM  -> 10pt  #605E5C")
    pdf.spec_row("Reference label",  "[AUM YoY %]  -> 9pt  #107C10")
    pdf.spec_row("Top border",       "Color #0078D4  |  Width 3px  |  Top side only")
    pdf.spec_row("Background",       "White  |  Border #E8E8E8 0.5px  |  Rounded 8px")
    pdf.position_badge(390, 90, 14, 82)
    pdf.set_fill_color(*BG_BLUE)
    pdf.set_x(14)
    pdf.set_font("Helvetica", "", 1)
    pdf.cell(182, 1, "", border="LBR", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Card 2
    pdf.set_fill_color(*BG_GREEN)
    pdf.set_draw_color(*GREEN)
    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*GREEN)
    pdf.cell(182, 6, "  Card 2 - Beating Nifty 50  (Green)", border="LTR", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEAR_BLACK)

    pdf.ln(1)
    pdf.sub_heading("Create this helper measure first (New measure in Executive_measures):")
    pdf.code_block(
        'Beating KPI Label =\n'
        '[Funds Beating Benchmark] & " / " & [Total Funds Count]'
    )
    pdf.spec_row("Callout value",   "[Beating KPI Label]  -> 22pt  Bold")
    pdf.spec_row("Category label",  "Beating Nifty 50  -> 10pt  #605E5C")
    pdf.spec_row("Reference label", "[Funds Beating Benchmark %]  -> 9pt  #107C10")
    pdf.spec_row("Top border",      "Color #107C10  |  Width 3px")
    pdf.position_badge(390, 90, 412, 82)
    pdf.ln(2)

    # Card 3
    pdf.set_fill_color(*BG_AMBER)
    pdf.set_draw_color((255, 185, 0))
    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*AMBER)
    pdf.cell(182, 6, "  Card 3 - Best Risk-Adjusted  (Amber)", border="LTR", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEAR_BLACK)

    pdf.ln(1)
    pdf.sub_heading("Create this helper measure first:")
    pdf.code_block(
        'Best Sharpe Label =\n'
        '"Sharpe: " & FORMAT([Best Sharpe Ratio], "0.00")\n'
        '    & "  *  Beta: " & FORMAT([Best Sharpe Beta], "0.00")'
    )
    pdf.spec_row("Callout value",   "[Best Sharpe Fund]  -> 15pt  Bold  (fund name is long)")
    pdf.spec_row("Category label",  "Best Risk-Adjusted  -> 10pt  #605E5C")
    pdf.spec_row("Reference label", "[Best Sharpe Label]  -> 9pt  #605E5C")
    pdf.spec_row("Top border",      "Color #FFB900  |  Width 3px")
    pdf.position_badge(390, 90, 814, 82)

    # ── PAGE 4: Steps 4 + 5 ───────────────────────────────────────────────────
    pdf.add_page()

    pdf.section_title("4", "MetricSelector Slicer  (Dynamic Bar Chart Switch)")
    pdf.body(
        "This slicer drives the Fund Ranking bar chart. When the user clicks a tile, "
        "[Selected Metric Value] switches to that column from vw_fund_performance, and "
        "[Fund Rank] re-ranks automatically."
    )
    pdf.ln(1)
    pdf.sub_heading("Visualizations -> Slicer")
    pdf.spec_row("Field",         "MetricSelector[Metric Name]")
    pdf.spec_row("Style",         "Format -> Slicer settings -> Style: Tile")
    pdf.spec_row("Selection",     "Single select  (only one metric at a time)")
    pdf.spec_row("Default",       "Click 'CAGR 5Y' tile before saving")
    pdf.spec_row("Tile colors",   "Unselected: bg #F5F5F5  text #605E5C  |  Selected: bg #0078D4  text White")
    pdf.spec_row("Font",          "Segoe UI  8pt")
    pdf.position_badge(450, 26, 14, 182)

    pdf.info_box(
        "MetricSelector table must have these 5 rows (verify in Data view):\n"
        "  Order 1 - CAGR 1Y      Order 2 - CAGR 3Y      Order 3 - CAGR 5Y\n"
        "  Order 4 - Sharpe Ratio      Order 5 - Alpha\n\n"
        "If the table is empty, add rows manually: Enter data -> type rows above.",
        bg=BG_AMBER, border_color=(255, 185, 0)
    )

    pdf.info_box(
        "Edit interactions: After placing this slicer, click it -> Format -> Edit interactions.\n"
        "Set it to FILTER only the bar chart (Step 5). Set it to NONE for all other visuals on the page\n"
        "so that clicking Sharpe doesn't change the KPI cards or scatter.",
        bg=BG_BLUE, border_color=BLUE
    )
    pdf.divider()

    pdf.section_title("5", "Fund Ranking Bar Chart", color=GREEN)
    pdf.sub_heading("Visualizations -> Clustered bar chart  (horizontal)")
    pdf.spec_row("Y-axis (rows)",   "vw_fund_performance[base_fund_name]")
    pdf.spec_row("X-axis (values)", "[Selected Metric Value]")
    pdf.spec_row("Filters pane",    "Add filter -> vw_fund_performance[is_benchmark]  -> is False")
    pdf.spec_row("Sort",            "Click … on visual -> Sort by -> [Fund Rank] -> Ascending")

    pdf.ln(2)
    pdf.sub_heading("Format settings:")
    pdf.spec_row("X-axis",         "OFF  (hide to keep chart clean)")
    pdf.spec_row("Y-axis",         "Font Segoe UI  9pt  Color #252423")
    pdf.spec_row("Data labels",    "ON  |  Font 8pt  White  |  Position: Inside end")
    pdf.spec_row("Title text",     "Fund Ranking  |  11pt  Bold  #252423")
    pdf.spec_row("Chart badge",    "Add text box overlay: 'Dynamic'  bg #EBF3FB  text #0078D4  8pt")
    pdf.spec_row("Background",     "White  |  Border #E8E8E8 0.5px  |  Rounded corners 8px")
    pdf.position_badge(450, 280, 14, 210)

    pdf.ln(2)
    pdf.sub_heading("Conditional bar color (Format -> Data colors -> fx -> Rules):")
    pdf.col_table(
        ["Condition", "Color", "Hex"],
        [
            ("Value >= 0.15  (15%)", "Green",   "#107C10"),
            ("0.08 <= Value < 0.15", "Amber",   "#FFB900"),
            ("Value < 0.08  (8%)",       "Red",     "#E74856"),
        ],
        col_widths=[70, 50, 60]
    )

    # ── PAGE 5: Steps 6 + 7 ───────────────────────────────────────────────────
    pdf.add_page()

    pdf.section_title("6", "Risk vs Return Scatter Chart  (Signature Visual)")
    pdf.body(
        "This is the headline visual of the dashboard. Each bubble is one fund, positioned "
        "by its volatility (X) and CAGR 5Y (Y). Two dashed reference lines from the "
        "benchmark divide the canvas into 4 labelled quadrants."
    )
    pdf.ln(1)
    pdf.sub_heading("Visualizations -> Scatter chart")
    pdf.spec_row("X-axis",         "vw_fund_performance[std_dev_1y]  -> label 'Volatility (Std Dev %)'")
    pdf.spec_row("Y-axis",         "vw_fund_performance[cagr_5y]  -> label 'CAGR 5Y %'")
    pdf.spec_row("Details",        "vw_fund_performance[base_fund_name]  (one bubble per fund)")
    pdf.spec_row("Size",           "vw_fund_performance[sharpe_ratio]  (bubble sized by Sharpe)")
    pdf.spec_row("Tooltips",       "Add [Quadrant Label] measure  +  alpha  +  max_drawdown")
    pdf.spec_row("Filters pane",   "vw_fund_performance[is_benchmark]  -> is False")

    pdf.ln(2)
    pdf.sub_heading("Reference lines (Analytics pane -> Constant line):")

    pdf.col_table(
        ["Line", "Value", "Label", "Color", "Style"],
        [
            ("Horizontal (Y)", "11.67", "Nifty 5Y Return",  "#A4262C", "Dashed 1.5px"),
            ("Vertical (X)",   "21.85", "Nifty Volatility", "#A4262C", "Dashed 1.5px"),
        ],
        col_widths=[30, 22, 48, 28, 52]
    )

    pdf.sub_heading("Quadrant text boxes  (Insert -> Text box, placed manually inside scatter area):")
    pdf.col_table(
        ["Position",    "Text",              "Text color", "Fill color"],
        [
            ("Top-left",    "EFFICIENT",         "#107C10",    "#E8F5E9"),
            ("Top-right",   "HIGH RISK",         "#856400",    "#FFF8E1"),
            ("Bottom-left", "DEFENSIVE",         "#0078D4",    "#EBF3FB"),
            ("Bottom-right","AVOID",             "#A4262C",    "#FFEBEE"),
        ],
        col_widths=[30, 38, 34, 78]
    )
    pdf.spec_row("Legend",         "Format -> Legend -> ON  |  Position: Bottom  |  8pt")
    pdf.spec_row("Legend colors",  "Efficient #107C10  |  High Risk #FFB900  |  Defensive #0078D4  |  Avoid #A4262C")
    pdf.spec_row("Background",     "White  |  Border #E8E8E8  |  Rounded 8px")
    pdf.position_badge(310, 280, 476, 182)

    pdf.info_box(
        "The reference line values (11.67 and 21.85) are live values from [Benchmark Return] and\n"
        "[Benchmark Volatility] measures. If the data refreshes, update these constant line values\n"
        "by re-running the DAX query:  EVALUATE ROW(\"R\", [Benchmark Return], \"V\", [Benchmark Volatility])",
        bg=BG_BLUE, border_color=BLUE
    )
    pdf.divider()

    pdf.section_title("7", "Needs Attention Table")
    pdf.sub_heading("Visualizations -> Table")
    pdf.spec_row("Columns",        "base_fund_name  -> sharpe_ratio  -> max_drawdown  -> cagr_1y")
    pdf.spec_row("Column labels",  "Fund  -> Sharpe  -> Max DD  -> 1Y Ret")
    pdf.spec_row("Formats",        "Sharpe: 0.00  |  Max DD: 0.0%  |  1Y Ret: 0.0%")
    pdf.spec_row("Filter",         "sharpe_ratio < 0  OR  max_drawdown < -20  (use Filters pane on visual)")
    pdf.spec_row("Sort",           "sharpe_ratio  Ascending  (worst Sharpe at top)")
    pdf.spec_row("Header",         "bg #0078D4  |  text White  |  Bold  9pt")
    pdf.spec_row("Grid lines",     "#F5F5F5  0.5px  |  Row highlight on hover: #F8F9FA")
    pdf.spec_row("Background",     "White  |  Border #E8E8E8  |  Rounded 8px")
    pdf.position_badge(390, 140, 798, 182)

    pdf.ln(1)
    pdf.sub_heading("Conditional font color rules:")
    pdf.col_table(
        ["Column",   "Condition",      "Font color"],
        [
            ("Sharpe",   "> 1.0",           "#107C10 (green)"),
            ("Sharpe",   "0 to 1",          "#856400 (amber)"),
            ("Sharpe",   "< 0",             "#A4262C (red)"),
            ("Max DD",   "> -15%",          "#107C10 (green)"),
            ("Max DD",   "-25% to -15%",    "#856400 (amber)"),
            ("Max DD",   "< -25%",          "#A4262C (red)"),
            ("1Y Ret",   "< 0%",            "#A4262C (red)"),
        ],
        col_widths=[30, 50, 100]
    )

    # ── PAGE 6: Steps 8 + 9 ───────────────────────────────────────────────────
    pdf.add_page()

    pdf.section_title("8", "Asset Class Mix Donut Chart")
    pdf.sub_heading("Visualizations -> Donut chart")
    pdf.spec_row("Legend",         "vw_fund_performance[asset_class]")
    pdf.spec_row("Values",         "Count of vw_fund_performance[base_fund_name]")
    pdf.spec_row("Filter",         "vw_fund_performance[is_benchmark] = False")
    pdf.spec_row("Inner radius",   "50%  (Format -> Slices -> Inner radius)")
    pdf.spec_row("Detail labels",  "OFF")
    pdf.spec_row("Legend",         "Position: Bottom  |  Font 8pt  |  Show value %")
    pdf.spec_row("Background",     "White  |  Border #E8E8E8  |  Rounded 8px")
    pdf.position_badge(390, 140, 798, 324)

    pdf.ln(1)
    pdf.sub_heading("Slice colors  (Format -> Colors -> assign manually):")
    pdf.col_table(
        ["Asset Class",   "Color name", "Hex"],
        [
            ("Equity ETF",    "Blue",       "#0078D4"),
            ("Index Fund",    "Teal",       "#00B294"),
            ("Gold",          "Amber",      "#FFB900"),
            ("Liquid",        "Red",        "#E74856"),
            ("Other / Debt",  "Grey",       "#8A8886"),
        ],
        col_widths=[55, 55, 70]
    )
    pdf.divider()

    pdf.section_title("9", "Fund Performance Matrix  (Full-Width Bottom Table)")
    pdf.body(
        "This is the most data-rich visual on the page. It shows all 11 funds with every "
        "metric in one heat-mapped table. Place it spanning the full width at the bottom of the canvas."
    )
    pdf.ln(1)
    pdf.sub_heading("Visualizations -> Table")
    pdf.spec_row("Filter",         "vw_fund_performance[is_benchmark] = False")
    pdf.spec_row("Sort",           "cagr_5y  Descending")
    pdf.spec_row("Header",         "bg #0078D4  |  White Bold  9pt")
    pdf.spec_row("Values font",    "Segoe UI  8.5pt")
    pdf.spec_row("Row grid",       "#F5F5F5  0.5px  |  Hover: #F8F9FA")
    pdf.spec_row("Background",     "White  |  Border #E8E8E8  |  Rounded 8px")
    pdf.position_badge(1252, 155, 14, 508)

    pdf.ln(2)
    pdf.sub_heading("Columns - add in this order:")
    pdf.col_table(
        ["#", "Display name", "Field",                              "Format"],
        [
            ("1",  "Fund Name",  "vw_fund_performance[base_fund_name]",  "Text"),
            ("2",  "CAGR 1Y",   "vw_fund_performance[cagr_1y]",          "0.0%"),
            ("3",  "CAGR 3Y",   "vw_fund_performance[cagr_3y]",          "0.0%"),
            ("4",  "CAGR 5Y",   "vw_fund_performance[cagr_5y]",          "0.0%"),
            ("5",  "Sharpe",    "vw_fund_performance[sharpe_ratio]",      "0.00"),
            ("6",  "Sortino",   "vw_fund_performance[sortino_ratio]",     "0.00"),
            ("7",  "Beta",      "vw_fund_performance[beta]",              "0.00"),
            ("8",  "Alpha",     "vw_fund_performance[alpha]",             "0.0%"),
            ("9",  "Max DD%",   "vw_fund_performance[max_drawdown]",      "0.0%"),
        ],
        col_widths=[10, 28, 90, 52]
    )

    pdf.ln(1)
    pdf.sub_heading("Conditional formatting  (Format -> Cell elements -> Background color -> Rules):")
    pdf.col_table(
        ["Column",        "Green (#E8F5E9)",    "Amber (#FFF8E1)",      "Red (#FFEBEE)"],
        [
            ("CAGR 1/3/5Y",   "> 15%",             "5% - 15%",         "< 5%"),
            ("Sharpe",         "> 1.0",             "0 - 1.0",          "< 0"),
            ("Sortino",        "> 1.0",             "0 - 1.0",          "< 0"),
            ("Alpha",          "> 10%",             "0 - 10%",          "< 0%"),
            ("Beta",           "< 0.7",             "0.7 - 1.0",        "> 1.0"),
            ("Max DD%",        "> −15%",        "−25% to −15%","< −25%"),
        ],
        col_widths=[32, 48, 52, 48]
    )

    # ── PAGE 7: Step 10 + Final Layout ────────────────────────────────────────
    pdf.add_page()

    pdf.section_title("10", "Footer Bar")
    pdf.sub_heading("Insert -> Shapes -> Rectangle  (footer background)")
    pdf.spec_row("Size & pos",  "W: 1280  H: 22  X: 0  Y: 778")
    pdf.spec_row("Fill",        "White  |  Top border #E1E1E1  0.5px")

    pdf.ln(1)
    pdf.sub_heading("Insert -> Text box  (page indicator, left)")
    pdf.spec_row("Text",        "Page 1 of 4")
    pdf.spec_row("Style",       "Three small rectangles as tab indicators (draw manually as tiny shapes)")
    pdf.spec_row("Position",    "X: 14  Y: 783")

    pdf.ln(1)
    pdf.sub_heading("Insert -> Text box  (info text, right)")
    pdf.spec_row("Text",        "mf_analytics_dashboard.pbix  *  Azure SQL: mf-analytics-db")
    pdf.spec_row("Font",        "Segoe UI  8pt  #A0A0A0")
    pdf.spec_row("Position",    "X: 900  Y: 783")

    pdf.divider()

    # Final layout diagram (text-art)
    pdf.sub_heading("Page 1 Canvas Layout Diagram  (1280 x 800 px):", color=BLUE)
    pdf.ln(1)
    pdf.set_fill_color(*CODE_BG)
    pdf.set_draw_color(*LIGHT_GREY)
    layout_text = (
        "+" + "-"*88 + "+\n"
        "|  HEADER (gradient #0078D4 -> #005A9E)  title + subtitle              44px |\n"
        "+" + "-"*88 + "+\n"
        "|  TOOLBAR (white)  [Asset Class Slicer tiles]  Auto-refresh text       30px |\n"
        "+" + "-"*88 + "+\n"
        "|  [KPI: AUM -- 390px]    [KPI: Beating -- 390px]   [KPI: Best Sharpe -- 390px]  |\n"
        "|                                                                        90px |\n"
        "+" + "-"*26 + "+" + "-"*28 + "+" + "-"*32 + "+\n"
        "| [MetricSelector]   |                      |                                  |\n"
        "| [Fund Ranking      |  Risk vs Return      |  Needs Attention table           |\n"
        "|  Bar Chart         |  Scatter Chart       |  Asset Class Mix donut           |\n"
        "|  450 x 280px]      |  310 x 280px]        |  390 x 280px]                   |\n"
        "+" + "-"*88 + "+\n"
        "|  Fund Performance Matrix (full width 1252px)                         155px |\n"
        "|  Fund | CAGR1Y | CAGR3Y | CAGR5Y | Sharpe | Sortino | Beta | Alpha | MaxDD |\n"
        "+" + "-"*88 + "+\n"
        "|  FOOTER  Page 1 of 4 * mf_analytics_dashboard.pbix * Azure SQL        22px |\n"
        "+" + "-"*88 + "+"
    )
    y_box = pdf.get_y()
    h_box = layout_text.count("\n") * 4.2 + 6
    pdf.rect(14, y_box, 182, h_box, style="FD")
    pdf.set_xy(16, y_box + 3)
    pdf.set_font("Courier", "", 6.8)
    pdf.set_text_color(50, 50, 50)
    for line in layout_text.split("\n"):
        pdf.set_x(16)
        pdf.cell(0, 4.2, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEAR_BLACK)
    pdf.ln(4)

    pdf.info_box(
        "FINAL CHECKLIST before moving to Page 2:\n"
        "[x]  File -> Save (Ctrl+S)\n"
        "[x]  Click MetricSelector slicer -> select 'CAGR 5Y' as default\n"
        "[x]  Verify bar chart sorts correctly with CAGR 5Y selected\n"
        "[x]  Verify scatter shows 11 dots with reference lines crossing\n"
        "[x]  Verify matrix shows all 11 funds with colour-coded cells\n"
        "[x]  Lock header + footer rectangles (Selection pane -> lock icon)",
        bg=BG_GREEN, border_color=GREEN
    )

    # ── Save ─────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT_PATH))
    print(f"PDF saved -> {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    build_pdf()
