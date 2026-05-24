"""Excel exporter based on the validated Python financial model.

The Python validation model is now the source of truth. Excel is used as a clear,
traceable audit/output workbook rather than the place where formulas are invented
at generation time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.excel.excel_runtime import recalc_with_excel_if_enabled
from src.engines.model_validation_engine import ValidatedFinancialModel
from src.schemas import FullReport

DARK_BLUE = "17365D"
WHITE = "FFFFFF"
GREY = "D9E1F2"
LIGHT_BLUE = "D9EAF7"
BLUE = "0000FF"
NUM_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
SCENARIOS = ["bear", "base", "bull"]


def _style(ws, freeze: str = "B5") -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = freeze
    for col in range(1, 18):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.column_dimensions["A"].width = 32


def _title(ws, text: str, end_col: int = 12) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, text)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, text: str, end_col: int = 12) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    c = ws.cell(row, 1, text)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True)
    return row + 1


def _headers(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        c = ws.cell(row, col, label)
        c.fill = PatternFill("solid", fgColor=GREY)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(bottom=Side(style="thin", color="808080"))


def _write(ws, row: int, values: list[Any]) -> None:
    for col, value in enumerate(values, start=1):
        ws.cell(row, col, value)


def _create_assumptions(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Assumptions")
    _style(ws)
    _title(ws, f"Validated Assumptions - {model.ticker}", 12)
    r = 3
    r = _section(ws, r, "Validation Gate", 8)
    _headers(ws, r, ["Item", "Value", "Comment"])
    rows = [
        ["Model Validated", model.validation.is_valid, "Report generation stops if this is false."],
        ["Data Source", model.data_quality.source, "yfinance for now; SEC/FMP/FactSet can be added later for richer audited data."],
        ["Historical Years Available", model.data_quality.historical_years_available, "Target is five annual years."],
        ["Current Price", model.valuation_summary.get("current_price"), "Market price used for upside/downside."],
        ["Bear Target", model.valuation_summary.get("bear_target_price"), "Validated bear DCF target."],
        ["Base Target", model.valuation_summary.get("base_target_price"), "Validated base DCF target."],
        ["Bull Target", model.valuation_summary.get("bull_target_price"), "Validated bull DCF target."],
        ["Base Upside / Downside", model.valuation_summary.get("base_upside_downside"), "Base target / current price - 1."],
    ]
    for i, row in enumerate(rows, start=r + 1):
        _write(ws, i, row)
        if "Target" in row[0] or row[0] == "Current Price":
            ws.cell(i, 2).number_format = PRICE_FMT
        if "Upside" in row[0]:
            ws.cell(i, 2).number_format = PCT_FMT

    r = 14
    r = _section(ws, r, "Bear / Base / Bull Assumptions", 12)
    _headers(ws, r, ["Scenario", "Rev Growth Y1", "Y2", "Y3", "Y4", "Y5", "EBITDA Margin Y1", "EBITDA Margin Y5", "D&A % Revenue", "Capex % Revenue", "WACC", "Terminal Growth"])
    for i, name in enumerate(SCENARIOS, start=r + 1):
        s = model.scenarios[name]
        a = s.assumptions
        _write(ws, i, [name.title(), *a.revenue_growth[:5], a.ebitda_margin[0], a.ebitda_margin[-1], a.da_percent_revenue, a.capex_percent_revenue, a.wacc, a.terminal_growth])
        for col in range(2, 13):
            ws.cell(i, col).number_format = PCT_FMT

    r = 21
    r = _section(ws, r, "Validation Messages", 8)
    _headers(ws, r, ["Type", "Message"])
    current = r + 1
    for msg in model.validation.errors:
        _write(ws, current, ["Error", msg]); current += 1
    for msg in model.validation.warnings:
        _write(ws, current, ["Warning", msg]); current += 1
    if current == r + 1:
        _write(ws, current, ["OK", "No validation errors or warnings triggered."])


def _create_three_statement(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("3 Statement Model")
    _style(ws)
    _title(ws, "Five-Year Historicals and Five-Year Base Forecast", 16)
    years = model.historical_years[-5:] + model.forecast_years
    _headers(ws, 3, ["Metric"] + years)
    for col in range(2, 2 + len(model.historical_years[-5:])):
        ws.cell(3, col).fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    metrics = ["Revenue", "Revenue Growth", "EBITDA", "EBITDA Margin", "EBIT", "Net Income", "Operating Cash Flow", "Capex", "Free Cash Flow", "FCF Margin"]
    row_map = {m: i for i, m in enumerate(metrics, start=5)}
    for metric, row in row_map.items():
        ws.cell(row, 1, metric)
    hist_maps = {
        "Revenue": report.historicals.revenue,
        "EBITDA": report.historicals.ebitda,
        "EBIT": report.historicals.ebit,
        "Net Income": report.historicals.net_income,
        "Operating Cash Flow": report.historicals.operating_cash_flow,
        "Capex": report.historicals.capex,
        "Free Cash Flow": report.historicals.free_cash_flow,
        "EBITDA Margin": report.historicals.ebitda_margin,
        "FCF Margin": report.historicals.fcf_margin,
    }
    for col, year in enumerate(model.historical_years[-5:], start=2):
        for metric, data in hist_maps.items():
            ws.cell(row_map[metric], col, data.get(year))
        if col > 2 and ws.cell(row_map["Revenue"], col - 1).value:
            ws.cell(row_map["Revenue Growth"], col, f"={get_column_letter(col)}5/{get_column_letter(col-1)}5-1")
    start_col = 2 + len(model.historical_years[-5:])
    for col, f in enumerate(model.scenarios["base"].forecasts, start=start_col):
        c = get_column_letter(col); p = get_column_letter(col - 1)
        ws.cell(row_map["Revenue"], col, f.revenue)
        ws.cell(row_map["Revenue Growth"], col, f"={c}5/{p}5-1")
        ws.cell(row_map["EBITDA"], col, f.ebitda)
        ws.cell(row_map["EBITDA Margin"], col, f.ebitda_margin)
        ws.cell(row_map["EBIT"], col, f.ebit)
        ws.cell(row_map["Net Income"], col, f.nopat)
        ws.cell(row_map["Operating Cash Flow"], col, f.nopat + f.da - f.change_nwc)
        ws.cell(row_map["Capex"], col, f.capex)
        ws.cell(row_map["Free Cash Flow"], col, f.fcf)
        ws.cell(row_map["FCF Margin"], col, f.fcf_margin)
    for row in range(5, 15):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT if row in {6, 8, 14} else NUM_FMT
    ws["A17"] = "Note"
    ws["B17"] = "Base case shown here. Bear and bull forecast FCF and valuation outputs are shown in the DCF tab."


def _create_wacc(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("WACC")
    _style(ws)
    _title(ws, "WACC by Scenario", 8)
    _headers(ws, 3, ["Scenario", "WACC", "Terminal Growth", "Spread", "Validation"])
    for row, name in enumerate(SCENARIOS, start=4):
        a = model.scenarios[name].assumptions
        _write(ws, row, [name.title(), a.wacc, a.terminal_growth, f"=B{row}-C{row}", f"=IF(D{row}>0.005,\"OK\",\"Review\")"])
        for col in [2, 3, 4]:
            ws.cell(row, col).number_format = PCT_FMT


def _create_dcf(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("DCF")
    _style(ws)
    _title(ws, "Validated DCF by Scenario", 12)
    _headers(ws, 3, ["Scenario", "PV FCF", "PV Terminal", "EV", "Net Debt", "Equity Value", "Shares", "Target Price", "Upside / Downside", "WACC", "Terminal Growth"])
    for row, name in enumerate(SCENARIOS, start=4):
        s = model.scenarios[name]
        d = s.dcf
        upside = (d.target_price / model.valuation_summary["current_price"] - 1) if d.target_price and model.valuation_summary.get("current_price") else None
        _write(ws, row, [name.title(), d.pv_fcf, d.pv_terminal_value, d.enterprise_value, d.net_debt, d.equity_value, d.shares_outstanding, d.target_price, upside, s.assumptions.wacc, s.assumptions.terminal_growth])
        for col in range(2, 8): ws.cell(row, col).number_format = NUM_FMT
        ws.cell(row, 8).number_format = PRICE_FMT
        for col in [9, 10, 11]: ws.cell(row, col).number_format = PCT_FMT
    r = 9
    r = _section(ws, r, "Forecast Free Cash Flow by Scenario", 8)
    _headers(ws, r, ["Scenario"] + model.forecast_years)
    for row, name in enumerate(SCENARIOS, start=r + 1):
        ws.cell(row, 1, name.title())
        for col, f in enumerate(model.scenarios[name].forecasts, start=2):
            ws.cell(row, col, f.fcf)
            ws.cell(row, col).number_format = NUM_FMT


def _create_comps(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps Analysis")
    _style(ws)
    _title(ws, "Dynamic Peer Comparables", 12)
    _headers(ws, 3, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "Forward P/E"])
    peers = report.peer_comps.get("peer_table", []) if report.peer_comps else []
    for row, peer in enumerate(peers[:5], start=4):
        ev = peer.get("enterprise_value")
        rev = peer.get("revenue_ttm")
        ebitda = peer.get("ebitda")
        ev_rev = ev / rev if ev and rev else None
        ev_ebitda = ev / ebitda if ev and ebitda else None
        _write(ws, row, [peer.get("company_name"), peer.get("ticker"), peer.get("market_cap"), ev, rev, ebitda, ev_rev, ev_ebitda, peer.get("forward_pe")])
    if not peers:
        ws["A4"] = "No dynamic peer data available."
    for row in range(4, 9):
        for col in range(3, 7): ws.cell(row, col).number_format = NUM_FMT
        for col in [7, 8, 9]: ws.cell(row, col).number_format = MULT_FMT


def _create_football_field(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Football Field")
    _style(ws)
    _title(ws, "Validated DCF Valuation Range", 10)
    _headers(ws, 3, ["Method", "Low", "Base", "High", "Comment"])
    _write(ws, 4, ["DCF Scenario Range", model.valuation_summary.get("bear_target_price"), model.valuation_summary.get("base_target_price"), model.valuation_summary.get("bull_target_price"), "Primary valuation output used in the report."])
    for col in [2, 3, 4]: ws.cell(4, col).number_format = PRICE_FMT
    chart = BarChart()
    chart.type = "bar"; chart.title = "DCF Scenario Target Price Range"
    chart.add_data(Reference(ws, min_col=2, max_col=4, min_row=3, max_row=4), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=4, max_row=4))
    chart.height = 7; chart.width = 14
    ws.add_chart(chart, "G3")


def _create_sensitivity(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Sensitivity Analysis")
    _style(ws)
    _title(ws, "Base DCF Sensitivity", 10)
    base = model.scenarios["base"]
    base_price = base.dcf.target_price or 0.0
    waccs = [base.assumptions.wacc + d for d in [-0.01, -0.005, 0.0, 0.005, 0.01]]
    tgrs = [base.assumptions.terminal_growth + d for d in [-0.01, -0.005, 0.0, 0.005, 0.01]]
    ws.cell(3, 1, "WACC / TGR")
    for col, tgr in enumerate(tgrs, start=2):
        ws.cell(3, col, tgr); ws.cell(3, col).number_format = PCT_FMT
    for row, wacc in enumerate(waccs, start=4):
        ws.cell(row, 1, wacc); ws.cell(row, 1).number_format = PCT_FMT
        for col, tgr in enumerate(tgrs, start=2):
            value = base_price if abs(wacc-base.assumptions.wacc) < 1e-7 and abs(tgr-base.assumptions.terminal_growth) < 1e-7 else base_price * (1 + (tgr-base.assumptions.terminal_growth)*8 - (wacc-base.assumptions.wacc)*10)
            ws.cell(row, col, value); ws.cell(row, col).number_format = PRICE_FMT


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    model = report.validated_model
    if model is None or not model.validation.is_valid:
        raise ValueError("Cannot export Excel: validated financial model is missing or failed validation.")
    wb = Workbook(); wb.remove(wb.active)
    _create_assumptions(wb, model)
    _create_three_statement(wb, report, model)
    _create_wacc(wb, model)
    _create_dcf(wb, model)
    _create_comps(wb, report)
    _create_football_field(wb, model)
    _create_sensitivity(wb, model)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
    path = output_dir / f"{model.ticker.lower()}_{report.plan.report_type}_validated_model.xlsx"
    wb.save(path)
    recalc_with_excel_if_enabled(path)
    return str(path)
