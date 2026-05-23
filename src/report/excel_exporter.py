"""Excel model exporter.

Creates an analyst-style workbook alongside the HTML report. The workbook is
intended to be a transparent model scaffold: inputs are separated from formulas,
assumptions are auditable, and valuation outputs are linked through dedicated
forecast, WACC, DCF, comps, sensitivity and football-field tabs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.schemas import FullReport

BLUE = "0000FF"   # hardcoded inputs
BLACK = "000000"  # formulas
GREEN = "008000"  # links across sheets
WHITE = "FFFFFF"
DARK_BLUE = "17365D"
LIGHT_BLUE = "D9EAF7"
YELLOW = "FFF2CC"
GREY = "D9E1F2"
RED = "FF0000"

NUM_FMT = '#,##0;[Red](#,##0);-'
NUM_1_FMT = '#,##0.0;[Red](#,##0.0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'


def _section(ws, row: int, title: str, end_col: int = 10) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    cell = ws.cell(row=row, column=1, value=title)
    cell.fill = PatternFill("solid", fgColor=DARK_BLUE)
    cell.font = Font(color=WHITE, bold=True)
    cell.alignment = Alignment(horizontal="left")
    return row + 1


def _header_row(ws, row: int, labels: list[str], start_col: int = 1) -> None:
    for idx, label in enumerate(labels, start=start_col):
        c = ws.cell(row=row, column=idx, value=label)
        c.fill = PatternFill("solid", fgColor=GREY)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
        c.border = Border(bottom=Side(style="thin", color="808080"))


def _set_input(cell, value: Any, comment_text: str | None = None) -> None:
    cell.value = value
    cell.font = Font(color=BLUE)
    cell.fill = PatternFill("solid", fgColor=YELLOW)
    if comment_text:
        from openpyxl.comments import Comment
        cell.comment = Comment(comment_text, "Equity Research Agent")


def _set_formula(cell, formula: str) -> None:
    cell.value = formula
    cell.font = Font(color=BLACK)


def _set_link(cell, formula: str) -> None:
    cell.value = formula
    cell.font = Font(color=GREEN)


def _style_sheet(ws) -> None:
    ws.sheet_view.showGridLines = False
    for col in range(1, 16):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions["A"].width = 34
    ws.freeze_panes = "B5"


def _safe(value: Any, default: Any = 0) -> Any:
    return default if value is None else value


def _years(report: FullReport) -> list[str]:
    base = report.forecasts.get("base", [])
    return [row.year for row in base]


def _create_output_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Output")
    _style_sheet(ws)
    ws["A1"] = f"{report.snapshot.company_name} ({report.snapshot.ticker}) - Equity Research Model"
    ws["A1"].font = Font(size=16, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")

    r = 3
    r = _section(ws, r, "Investment Snapshot", 6)
    rows = [
        ["Recommendation", report.recommendation],
        ["Current Price", report.snapshot.current_price],
        ["Target Price", report.target_price],
        ["Upside / Downside", report.upside_downside],
        ["Primary Valuation Method", report.dynamic_valuation.primary_method if report.dynamic_valuation else "n/a"],
        ["Confidence", report.dynamic_valuation.confidence / 100 if report.dynamic_valuation else None],
    ]
    for i, row in enumerate(rows, start=r):
        ws.cell(i, 1, row[0])
        ws.cell(i, 2, row[1])
    ws["B5"].number_format = PRICE_FMT
    ws["B6"].number_format = PRICE_FMT
    ws["B7"].number_format = PCT_FMT
    ws["B9"].number_format = PCT_FMT

    r = 12
    r = _section(ws, r, "Valuation Range / Football Field", 6)
    _header_row(ws, r, ["Method", "Low", "Base", "High", "Weight", "Notes"])
    methods = [
        ["Dynamic Valuation", "='Football Field'!B5", "='Football Field'!C5", "='Football Field'!D5", "='Football Field'!E5", "Router-selected primary valuation"],
        ["Baseline DCF Cross-check", "='Football Field'!B6", "='Football Field'!C6", "='Football Field'!D6", "='Football Field'!E6", "Not final authority"],
        ["Trading Comps", "='Football Field'!B7", "='Football Field'!C7", "='Football Field'!D7", "='Football Field'!E7", "Peer multiple cross-check"],
    ]
    for i, row in enumerate(methods, start=r + 1):
        for j, val in enumerate(row, start=1):
            if isinstance(val, str) and val.startswith("="):
                _set_link(ws.cell(i, j), val)
            else:
                ws.cell(i, j, val)
    for row in ws.iter_rows(min_row=r + 1, max_row=r + 3, min_col=2, max_col=4):
        for c in row:
            c.number_format = PRICE_FMT
    ws[f"E{r+1}"].number_format = PCT_FMT
    ws[f"E{r+2}"].number_format = PCT_FMT
    ws[f"E{r+3}"].number_format = PCT_FMT


def _create_source_data_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Source Data")
    _style_sheet(ws)
    ws["A1"] = "Source Data"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")

    r = 3
    r = _section(ws, r, "Company Snapshot", 4)
    items = [
        ["Ticker", report.snapshot.ticker, "yfinance / user input"],
        ["Company", report.snapshot.company_name, "yfinance / user input"],
        ["Sector", report.snapshot.sector, "yfinance"],
        ["Industry", report.snapshot.industry, "yfinance"],
        ["Current Price", report.snapshot.current_price, "yfinance or user override"],
        ["Market Cap", report.snapshot.market_cap, "yfinance"],
        ["Enterprise Value", report.snapshot.enterprise_value, "yfinance"],
        ["Shares Outstanding", report.snapshot.shares_outstanding, "yfinance"],
        ["Cash", report.snapshot.total_cash, "yfinance"],
        ["Debt", report.snapshot.total_debt, "yfinance"],
        ["Net Debt", report.snapshot.net_debt, "debt - cash"],
        ["Beta", report.snapshot.beta, "yfinance"],
    ]
    _header_row(ws, r, ["Item", "Value", "Source"])
    for i, row in enumerate(items, start=r + 1):
        ws.cell(i, 1, row[0])
        ws.cell(i, 2, row[1])
        ws.cell(i, 3, row[2])
    for row in range(r + 1, r + len(items) + 1):
        ws.cell(row, 2).font = Font(color=BLUE)
    ws["B8"].number_format = NUM_FMT
    ws["B9"].number_format = NUM_FMT
    ws["B10"].number_format = NUM_FMT
    ws["B11"].number_format = NUM_FMT
    ws["B12"].number_format = NUM_FMT
    ws["B13"].number_format = NUM_FMT

    r = 19
    r = _section(ws, r, "Historical Financials", 8)
    years = sorted(report.historicals.revenue.keys())[-5:]
    _header_row(ws, r, ["Metric"] + years)
    metrics = [
        ("Revenue", report.historicals.revenue),
        ("EBITDA", report.historicals.ebitda),
        ("EBIT", report.historicals.ebit),
        ("Net Income", report.historicals.net_income),
        ("Operating Cash Flow", report.historicals.operating_cash_flow),
        ("Capex", report.historicals.capex),
        ("Free Cash Flow", report.historicals.free_cash_flow),
        ("EBITDA Margin", report.historicals.ebitda_margin),
        ("FCF Margin", report.historicals.fcf_margin),
    ]
    for i, (metric, data) in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
        for j, year in enumerate(years, start=2):
            ws.cell(i, j, data.get(year))
            ws.cell(i, j).font = Font(color=BLUE)
    for row in range(r + 1, r + 8):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_FMT
    for row in range(r + 8, r + 10):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT


def _create_assumptions_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Assumptions")
    _style_sheet(ws)
    ws["A1"] = "Operating and Valuation Assumptions"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")

    years = _years(report)
    r = 3
    r = _section(ws, r, "Scenario Assumptions", 8)
    _header_row(ws, r, ["Metric"] + years)
    base = report.assumptions["base"]
    rows = [
        ["Revenue Growth"] + base.revenue_growth,
        ["EBITDA Margin"] + base.ebitda_margin,
        ["D&A % Revenue"] + [base.da_percent_revenue] * len(years),
        ["Capex % Revenue"] + [base.capex_percent_revenue] * len(years),
        ["NWC % Revenue Growth"] + [base.nwc_percent_revenue] * len(years),
        ["Tax Rate"] + [base.tax_rate] * len(years),
        ["WACC"] + [base.wacc] * len(years),
        ["Terminal Growth"] + [base.terminal_growth] * len(years),
    ]
    for i, row in enumerate(rows, start=r + 1):
        for j, val in enumerate(row, start=1):
            _set_input(ws.cell(i, j), val, "Editable assumption generated from the dynamic assumption agent and historical data.")
    for row in range(r + 1, r + 9):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT

    r = 15
    r = _section(ws, r, "Assumption Rationale / Audit Trail", 4)
    _header_row(ws, r, ["Area", "Rationale"])
    rationale = []
    if report.dynamic_assumptions:
        rationale = [
            ["Revenue", report.dynamic_assumptions.revenue_growth_logic],
            ["Margins", report.dynamic_assumptions.margin_logic],
            ["Capital Intensity", report.dynamic_assumptions.capital_intensity_logic],
            ["Risk Adjustment", report.dynamic_assumptions.risk_adjustment_logic],
            ["Evidence", "; ".join(report.dynamic_assumptions.sources_and_evidence)],
        ]
    for i, row in enumerate(rationale, start=r + 1):
        ws.cell(i, 1, row[0])
        ws.cell(i, 2, row[1])
        ws.cell(i, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["B"].width = 80


def _create_forecast_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Forecast")
    _style_sheet(ws)
    ws["A1"] = "Forecast Model"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")

    years = _years(report)
    r = 3
    r = _section(ws, r, "Base Case Forecast", 8)
    _header_row(ws, r, ["Metric"] + years)
    metrics = [
        "Revenue",
        "Revenue Growth",
        "EBITDA",
        "EBITDA Margin",
        "D&A",
        "EBIT",
        "Tax",
        "NOPAT",
        "Capex",
        "Change in NWC",
        "FCF",
        "FCF Margin",
    ]
    for i, metric in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)

    # Link to assumptions and calculate directly in workbook.
    start_row = r + 1
    for col, year in enumerate(years, start=2):
        col_letter = get_column_letter(col)
        prior_col = get_column_letter(col - 1)
        if col == 2:
            last_hist_col = 1 + len(sorted(report.historicals.revenue.keys())[-5:])
            last_hist_letter = get_column_letter(last_hist_col)
            _set_formula(ws.cell(start_row, col), f"='Source Data'!{last_hist_letter}24*(1+Assumptions!{col_letter}5)")
        else:
            _set_formula(ws.cell(start_row, col), f"={prior_col}{start_row}*(1+Assumptions!{col_letter}5)")
        _set_link(ws.cell(start_row + 1, col), f"=Assumptions!{col_letter}5")
        _set_formula(ws.cell(start_row + 2, col), f"={col_letter}{start_row}*Assumptions!{col_letter}6")
        _set_formula(ws.cell(start_row + 3, col), f"={col_letter}{start_row+2}/{col_letter}{start_row}")
        _set_formula(ws.cell(start_row + 4, col), f"={col_letter}{start_row}*Assumptions!{col_letter}7")
        _set_formula(ws.cell(start_row + 5, col), f"={col_letter}{start_row+2}-{col_letter}{start_row+4}")
        _set_formula(ws.cell(start_row + 6, col), f"=MAX({col_letter}{start_row+5},0)*Assumptions!{col_letter}10")
        _set_formula(ws.cell(start_row + 7, col), f"={col_letter}{start_row+5}-{col_letter}{start_row+6}")
        _set_formula(ws.cell(start_row + 8, col), f"={col_letter}{start_row}*Assumptions!{col_letter}8")
        if col == 2:
            _set_formula(ws.cell(start_row + 9, col), f"=MAX({col_letter}{start_row}-'Source Data'!{last_hist_letter}24,0)*Assumptions!{col_letter}9")
        else:
            _set_formula(ws.cell(start_row + 9, col), f"=MAX({col_letter}{start_row}-{prior_col}{start_row},0)*Assumptions!{col_letter}9")
        _set_formula(ws.cell(start_row + 10, col), f"={col_letter}{start_row+7}+{col_letter}{start_row+4}-{col_letter}{start_row+8}-{col_letter}{start_row+9}")
        _set_formula(ws.cell(start_row + 11, col), f"={col_letter}{start_row+10}/{col_letter}{start_row}")

    for row in [start_row, start_row + 2, start_row + 4, start_row + 5, start_row + 6, start_row + 7, start_row + 8, start_row + 9, start_row + 10]:
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_FMT
    for row in [start_row + 1, start_row + 3, start_row + 11]:
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT


def _create_wacc_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("WACC")
    _style_sheet(ws)
    ws["A1"] = "WACC / Cost of Capital"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:H1")

    r = 3
    r = _section(ws, r, "Cost of Equity", 4)
    rows = [
        ["Risk-free rate", 0.045],
        ["Equity risk premium", 0.055],
        ["Beta", report.snapshot.beta or 1.0],
        ["Company-specific risk adjustment", max((report.dynamic_assumptions.cost_of_equity or 0) - (0.045 + (report.snapshot.beta or 1.0) * 0.055), 0) if report.dynamic_assumptions else 0],
        ["Cost of Equity", "=B4+B5*B6+B7"],
    ]
    for i, row in enumerate(rows, start=r):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str):
            _set_formula(ws.cell(i, 2), row[1])
        else:
            _set_input(ws.cell(i, 2), row[1], "Cost of equity input. Review against market data and sector risk.")
        ws.cell(i, 2).number_format = PCT_FMT

    r = 11
    r = _section(ws, r, "Capital Structure and WACC", 5)
    rows = [
        ["Market Cap", report.snapshot.market_cap],
        ["Total Debt", report.snapshot.total_debt],
        ["Total Capital", "=B12+B13"],
        ["Equity Weight", "=B12/B14"],
        ["Debt Weight", "=B13/B14"],
        ["Pre-tax Cost of Debt", 0.055],
        ["Tax Rate", report.dynamic_assumptions.tax_rate if report.dynamic_assumptions and report.dynamic_assumptions.tax_rate else 0.25],
        ["After-tax Cost of Debt", "=B17*(1-B18)"],
        ["WACC", "=B15*B8+B16*B19"],
    ]
    for i, row in enumerate(rows, start=r):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str):
            _set_formula(ws.cell(i, 2), row[1])
        else:
            _set_input(ws.cell(i, 2), row[1], "WACC input derived from market data or dynamic assumption engine.")
    for i in [12, 13, 14]: ws.cell(i, 2).number_format = NUM_FMT
    for i in [15, 16, 17, 18, 19, 20]: ws.cell(i, 2).number_format = PCT_FMT


def _create_dcf_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("DCF")
    _style_sheet(ws)
    ws["A1"] = "Baseline DCF Cross-check"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")
    years = _years(report)
    r = 3
    r = _section(ws, r, "DCF Calculation", 9)
    _header_row(ws, r, ["Metric"] + years + ["Terminal"])
    metrics = ["FCF", "Discount Factor", "PV of FCF", "Terminal Value", "PV of Terminal Value", "Enterprise Value", "Net Debt", "Equity Value", "Shares Outstanding", "Target Price"]
    for i, metric in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
    start = r + 1
    for col, year in enumerate(years, start=2):
        col_letter = get_column_letter(col)
        _set_link(ws.cell(start, col), f"='Forecast'!{col_letter}14")
        _set_formula(ws.cell(start + 1, col), f"=1/(1+WACC!$B$20)^{col-1}")
        _set_formula(ws.cell(start + 2, col), f"={col_letter}{start}*{col_letter}{start+1}")
    term_col = 2 + len(years)
    term_letter = get_column_letter(term_col)
    last_year_letter = get_column_letter(term_col - 1)
    _set_formula(ws.cell(start + 3, term_col), f"={last_year_letter}{start}*(1+Assumptions!{last_year_letter}12)/(WACC!$B$20-Assumptions!{last_year_letter}12)")
    _set_formula(ws.cell(start + 4, term_col), f"={term_letter}{start+3}/(1+WACC!$B$20)^{len(years)}")
    _set_formula(ws.cell(start + 5, term_col), f"=SUM(B{start+2}:{last_year_letter}{start+2})+{term_letter}{start+4}")
    _set_link(ws.cell(start + 6, term_col), "='Source Data'!B13")
    _set_formula(ws.cell(start + 7, term_col), f"={term_letter}{start+5}-{term_letter}{start+6}")
    _set_link(ws.cell(start + 8, term_col), "='Source Data'!B10")
    _set_formula(ws.cell(start + 9, term_col), f"={term_letter}{start+7}/{term_letter}{start+8}")
    for row in range(start, start + 10):
        for col in range(2, term_col + 1):
            ws.cell(row, col).number_format = PRICE_FMT if row == start + 9 else NUM_FMT
    for col in range(2, term_col):
        ws.cell(start + 1, col).number_format = '0.000x'


def _create_comps_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps")
    _style_sheet(ws)
    ws["A1"] = "Trading Comparables"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")
    r = 3
    r = _section(ws, r, "Peer Comps Placeholder", 8)
    _header_row(ws, r, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA"])
    # Leave a clean structure for real peer data. Link company as first row.
    data = [[report.snapshot.company_name, report.snapshot.ticker, report.snapshot.market_cap, report.snapshot.enterprise_value, report.snapshot.revenue_ttm, report.snapshot.ebitda, None, None]]
    for i, row in enumerate(data, start=r + 1):
        for j, val in enumerate(row, start=1):
            ws.cell(i, j, val)
    _set_formula(ws.cell(r + 1, 7), f"=D{r+1}/E{r+1}")
    _set_formula(ws.cell(r + 1, 8), f"=D{r+1}/F{r+1}")
    for col in range(3, 7): ws.cell(r + 1, col).number_format = NUM_FMT
    ws.cell(r + 1, 7).number_format = MULT_FMT
    ws.cell(r + 1, 8).number_format = MULT_FMT


def _create_sensitivity_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Sensitivity")
    _style_sheet(ws)
    ws["A1"] = "Sensitivity Analysis"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:J1")
    if not report.sensitivities:
        ws["A3"] = "No sensitivities available."
        return
    r = 3
    for sens in report.sensitivities[:2]:
        r = _section(ws, r, sens.title, 8)
        ws.cell(r, 1, f"{sens.row_label} / {sens.column_label}")
        for j, colval in enumerate(sens.columns, start=2):
            ws.cell(r, j, colval)
            ws.cell(r, j).number_format = PCT_FMT
        for i, rowval in enumerate(sens.rows, start=r + 1):
            ws.cell(i, 1, rowval)
            ws.cell(i, 1).number_format = PCT_FMT
            values = sens.values[i - r - 1]
            for j, value in enumerate(values, start=2):
                ws.cell(i, j, value)
                ws.cell(i, j).number_format = PRICE_FMT
        r += len(sens.rows) + 3


def _create_football_field_tab(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Football Field")
    _style_sheet(ws)
    ws["A1"] = "Football Field Valuation"
    ws["A1"].font = Font(size=14, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
    ws.merge_cells("A1:H1")
    r = 3
    r = _section(ws, r, "Valuation Range", 7)
    _header_row(ws, r, ["Method", "Low", "Base", "High", "Weight", "Primary?", "Comment"])
    dyn = report.dynamic_valuation
    target = report.target_price or report.snapshot.current_price or 0
    base_dcf = report.dcf_outputs["base"].target_price or target
    rows = [
        ["Dynamic Valuation", target * 0.9, target, target * 1.1, 0.60, "Yes", dyn.primary_method if dyn else "n/a"],
        ["Baseline DCF Cross-check", base_dcf * 0.8, base_dcf, base_dcf * 1.2, 0.25, "No", "Cross-check only"],
        ["Trading Comps", (report.snapshot.current_price or target) * 0.9, report.snapshot.current_price or target, (report.snapshot.current_price or target) * 1.1, 0.15, "No", "Market anchor until peer dataset populated"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        for j, val in enumerate(row, start=1):
            ws.cell(i, j, val)
    for row in range(r + 1, r + 4):
        for col in range(2, 5): ws.cell(row, col).number_format = PRICE_FMT
        ws.cell(row, 5).number_format = PCT_FMT
    chart = BarChart()
    chart.type = "bar"
    chart.style = 10
    chart.title = "Valuation Range"
    chart.y_axis.title = "Method"
    chart.x_axis.title = "Price"
    data = Reference(ws, min_col=2, max_col=4, min_row=r, max_row=r+3)
    cats = Reference(ws, min_col=1, min_row=r+1, max_row=r+3)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height = 7
    chart.width = 14
    ws.add_chart(chart, "I3")


def _create_sector_specific_tabs(wb: Workbook, report: FullReport) -> None:
    plan = report.financial_model_plan
    if not plan:
        return
    sector_tabs = [t for t in plan.workbook_tabs if t.tab_name not in {"Cover / Output", "Source Data", "Operating Assumptions", "Three Statement Model", "WACC / Cost of Capital", "Comps", "Sensitivity", "Football Field"}]
    for tab in sector_tabs:
        safe_name = tab.tab_name[:31]
        ws = wb.create_sheet(safe_name)
        _style_sheet(ws)
        ws["A1"] = tab.tab_name
        ws["A1"].font = Font(size=14, bold=True, color=WHITE)
        ws["A1"].fill = PatternFill("solid", fgColor=DARK_BLUE)
        ws.merge_cells("A1:J1")
        r = 3
        r = _section(ws, r, "Purpose", 5)
        ws.cell(r, 1, tab.purpose)
        ws.cell(r, 1).alignment = Alignment(wrap_text=True)
        r += 3
        r = _section(ws, r, "Inputs / Outputs Needed", 6)
        _header_row(ws, r, ["Type", "Item"])
        row = r + 1
        for item in tab.key_inputs:
            ws.cell(row, 1, "Input")
            _set_input(ws.cell(row, 2), item, "Required sector-specific input for this model tab.")
            row += 1
        for item in tab.key_outputs:
            ws.cell(row, 1, "Output")
            ws.cell(row, 2, item)
            row += 1


def _format_all_sheets(wb: Workbook) -> None:
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
        for col in range(1, min(ws.max_column, 12) + 1):
            letter = get_column_letter(col)
            if ws.column_dimensions[letter].width < 12:
                ws.column_dimensions[letter].width = 12


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    wb.remove(default)

    _create_output_tab(wb, report)
    _create_source_data_tab(wb, report)
    _create_assumptions_tab(wb, report)
    _create_forecast_tab(wb, report)
    _create_wacc_tab(wb, report)
    _create_dcf_tab(wb, report)
    _create_comps_tab(wb, report)
    _create_sensitivity_tab(wb, report)
    _create_football_field_tab(wb, report)
    _create_sector_specific_tabs(wb, report)
    _format_all_sheets(wb)

    path = output_dir / f"{report.snapshot.ticker.lower()}_{report.plan.report_type}_model.xlsx"
    wb.save(path)
    return str(path)
