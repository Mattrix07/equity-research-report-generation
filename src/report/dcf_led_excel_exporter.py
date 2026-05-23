"""DCF-led Excel exporter overlay.

Builds on the validated balanced model, then rewrites the valuation-facing tabs so
that the workbook is explicitly a 12-month DCF-led target-price model.

The overlay adds transparent workings for:
- one-year share-price and valuation range analysis;
- bear/base/bull DCF scenario values;
- trading comparables using actual peer rows from the comps engine;
- DCF-led valuation bridge with visible weights;
- football field linked to the underlying workings;
- sensitivity matrix where the centre cell links to the base DCF target.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.report.validated_excel_exporter import export_excel_model as export_validated_model
from src.schemas import FullReport

DARK_BLUE = "17365D"
WHITE = "FFFFFF"
GREY = "D9E1F2"
YELLOW = "FFF2CC"
BLUE = "0000FF"
GREEN = "008000"
BLACK = "000000"

NUM_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'


def _reset_sheet(wb, name: str):
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    for col in range(1, 16):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions["A"].width = 34
    return ws


def _title(ws, title: str, end_col: int = 10):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, title)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, title: str, end_col: int = 10) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    c = ws.cell(row, 1, title)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True)
    return row + 1


def _headers(ws, row: int, labels: list[str]) -> None:
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row, i, label)
        c.fill = PatternFill("solid", fgColor=GREY)
        c.font = Font(bold=True)
        c.border = Border(bottom=Side(style="thin", color="808080"))
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _input(cell, value: Any, comment: str | None = None) -> None:
    cell.value = value
    cell.font = Font(color=BLUE)
    cell.fill = PatternFill("solid", fgColor=YELLOW)
    if comment:
        from openpyxl.comments import Comment
        cell.comment = Comment(comment, "Equity Research Agent")


def _formula(cell, formula: str) -> None:
    cell.value = formula
    cell.font = Font(color=BLACK)


def _link(cell, formula: str) -> None:
    cell.value = formula
    cell.font = Font(color=GREEN)


def _safe(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except Exception:
        return default


def _create_one_year_analysis(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "1Y Price Analysis")
    _title(ws, f"12-Month Share Price and Valuation Range - {report.snapshot.ticker}", 9)
    r = 3
    r = _section(ws, r, "Market Context", 6)
    rows = [
        ["Current Price", report.snapshot.current_price, "Source Data / yfinance or user override"],
        ["52-Week Low", report.snapshot.fifty_two_week_low, "yfinance"],
        ["52-Week High", report.snapshot.fifty_two_week_high, "yfinance"],
        ["20-Day Moving Average", report.technicals.ma_20, "technical engine"],
        ["50-Day Moving Average", report.technicals.ma_50, "technical engine"],
        ["200-Day Moving Average", report.technicals.ma_200, "technical engine"],
        ["DCF-led 12M Target Price", "='Valuation Bridge'!B12", "linked to valuation bridge"],
        ["12M Upside / Downside", "=B10/B4-1", "target / current price - 1"],
    ]
    _headers(ws, r, ["Metric", "Value", "Source / Formula"])
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str) and row[1].startswith("="):
            _link(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
    for row in range(4, 11):
        ws.cell(row, 2).number_format = PRICE_FMT
    ws["B11"].number_format = PCT_FMT


def _create_dcf_scenario_workings(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "DCF Scenario Workings")
    _title(ws, "DCF Scenario Workings - Bear / Base / Bull", 10)
    r = 3
    r = _section(ws, r, "Scenario Output from DCF Engine", 10)
    _headers(ws, r, ["Scenario", "PV of FCF", "PV of Terminal Value", "Enterprise Value", "Net Debt", "Equity Value", "Shares", "Target Price", "WACC", "Terminal Growth"])
    scenario_rows = [("bear", 5), ("base", 6), ("bull", 7)]
    for scenario, row in scenario_rows:
        dcf = report.dcf_outputs[scenario]
        ws.cell(row, 1, scenario.title())
        _input(ws.cell(row, 2), dcf.pv_fcf, "Calculated by Python DCF engine from scenario forecast.")
        _input(ws.cell(row, 3), dcf.pv_terminal_value, "Calculated by Python DCF engine from terminal value assumptions.")
        _formula(ws.cell(row, 4), f"=B{row}+C{row}")
        _input(ws.cell(row, 5), dcf.net_debt, "Net debt used in DCF engine.")
        _formula(ws.cell(row, 6), f"=D{row}-E{row}")
        _input(ws.cell(row, 7), dcf.shares_outstanding, "Shares outstanding used in DCF engine.")
        _formula(ws.cell(row, 8), f"=F{row}/G{row}")
        _input(ws.cell(row, 9), dcf.assumptions.wacc, "Scenario WACC.")
        _input(ws.cell(row, 10), dcf.assumptions.terminal_growth, "Scenario terminal growth.")
    for row in range(5, 8):
        for col in range(2, 8):
            ws.cell(row, col).number_format = NUM_FMT
        ws.cell(row, 8).number_format = PRICE_FMT
        ws.cell(row, 9).number_format = PCT_FMT
        ws.cell(row, 10).number_format = PCT_FMT

    r = 10
    r = _section(ws, r, "Visible DCF Range Used in Report", 8)
    _headers(ws, r, ["Range Point", "Linked Target Price", "Formula"])
    rows = [["Bear", "=H5"], ["Base", "=H6"], ["Bull", "=H7"]]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        _link(ws.cell(i, 2), row[1])
        ws.cell(i, 3, row[1])
        ws.cell(i, 2).number_format = PRICE_FMT


def _create_comps(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "Comps")
    _title(ws, "Trading Comparables - Peer Multiples", 11)
    r = 3
    r = _section(ws, r, "Peer Multiples", 11)
    _headers(ws, r, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "Forward P/E", "Included?", "Source"])
    peer_rows = report.peer_comps.get("peer_table", []) if report.peer_comps else []
    # Limit to 5 peers. If the peer data is incomplete, the row is still shown.
    for idx, peer in enumerate(peer_rows[:5], start=r + 1):
        ws.cell(idx, 1, peer.get("company_name"))
        ws.cell(idx, 2, peer.get("ticker"))
        ws.cell(idx, 3, peer.get("market_cap"))
        ws.cell(idx, 4, peer.get("enterprise_value"))
        ws.cell(idx, 5, peer.get("revenue_ttm"))
        ws.cell(idx, 6, peer.get("ebitda"))
        _formula(ws.cell(idx, 7), f"=IFERROR(D{idx}/E{idx},\"n/a\")")
        _formula(ws.cell(idx, 8), f"=IFERROR(D{idx}/F{idx},\"n/a\")")
        ws.cell(idx, 9, peer.get("forward_pe"))
        ws.cell(idx, 10, "Yes")
        ws.cell(idx, 11, "yfinance")
    start = r + 1
    end = max(start, start + min(len(peer_rows), 5) - 1)
    for row in range(start, end + 1):
        for col in range(3, 7):
            ws.cell(row, col).number_format = NUM_FMT
        for col in [7, 8, 9]:
            ws.cell(row, col).number_format = MULT_FMT

    summary = end + 3
    summary = _section(ws, summary, "Comps Valuation Workings", 8)
    _headers(ws, summary, ["Metric", "Value", "Formula / Source"])
    rows = [
        ["Median EV/EBITDA", f"=MEDIAN(H{start}:H{end})" if peer_rows else None, "Median of included peers"],
        ["Subject EBITDA", "='Source Data'!B13", "Current subject EBITDA / yfinance"],
        ["Implied Enterprise Value", f"=B{summary+1}*B{summary+2}", "Median EV/EBITDA × subject EBITDA"],
        ["Less Net Debt", "='Source Data'!B15", "Source Data"],
        ["Implied Equity Value", f"=B{summary+3}-B{summary+4}", "EV - net debt"],
        ["Shares", "='Source Data'!B12", "Source Data"],
        ["Trading Comps Implied Price", f"=B{summary+5}/B{summary+6}", "Equity value / shares"],
    ]
    for i, row in enumerate(rows, start=summary + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str) and row[1].startswith("="):
            _link(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
    ws.cell(summary + 1, 2).number_format = MULT_FMT
    for row in range(summary + 2, summary + 7):
        ws.cell(row, 2).number_format = NUM_FMT
    ws.cell(summary + 7, 2).number_format = PRICE_FMT


def _create_valuation_bridge(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "Valuation Bridge")
    _title(ws, "12-Month DCF-Led Target Price Bridge", 10)
    r = 3
    r = _section(ws, r, "Method Weighting", 8)
    _headers(ws, r, ["Method", "Linked Price", "Weight", "Weighted Contribution", "Source / Working"])
    rows = [
        ["DCF Base Case", "='DCF Scenario Workings'!H6", 0.70, "='DCF Scenario Workings'!H6*C5", "DCF Scenario Workings"],
        ["Trading Comparables", "=Comps!B16", 0.20, "=B6*C6", "Comps valuation workings"],
        ["Sector Engine", "='1Y Price Analysis'!B4", 0.10, "=B7*C7", "Placeholder unless sector tab has sufficient evidence"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        _link(ws.cell(i, 2), row[1])
        _input(ws.cell(i, 3), row[2], "Editable valuation method weight.")
        _formula(ws.cell(i, 4), row[3])
        ws.cell(i, 5, row[4])
    total_row = r + 5
    ws.cell(total_row, 1, "DCF-led 12M Target Price")
    _formula(ws.cell(total_row, 2), f"=SUM(D5:D7)/SUM(C5:C7)")
    ws.cell(total_row + 1, 1, "Current Price")
    _link(ws.cell(total_row + 1, 2), "='1Y Price Analysis'!B4")
    ws.cell(total_row + 2, 1, "Upside / Downside")
    _formula(ws.cell(total_row + 2, 2), f"=B{total_row}/B{total_row+1}-1")
    for row in range(5, 8):
        ws.cell(row, 2).number_format = PRICE_FMT
        ws.cell(row, 3).number_format = PCT_FMT
        ws.cell(row, 4).number_format = PRICE_FMT
    ws.cell(total_row, 2).number_format = PRICE_FMT
    ws.cell(total_row + 1, 2).number_format = PRICE_FMT
    ws.cell(total_row + 2, 2).number_format = PCT_FMT


def _create_football_field(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "Football Field")
    _title(ws, "Football Field - Linked Valuation Range", 10)
    r = 3
    r = _section(ws, r, "Linked Valuation Range", 8)
    _headers(ws, r, ["Method", "Low", "Base", "High", "Weight", "Primary", "Working"])
    rows = [
        ["DCF Scenario Range", "='DCF Scenario Workings'!H5", "='DCF Scenario Workings'!H6", "='DCF Scenario Workings'!H7", 0.70, "Yes", "DCF Scenario Workings"],
        ["Trading Comps", "=Comps!B16*0.9", "=Comps!B16", "=Comps!B16*1.1", 0.20, "No", "Comps"],
        ["Sector Engine", "='1Y Price Analysis'!B4*0.9", "='1Y Price Analysis'!B4", "='1Y Price Analysis'!B4*1.1", 0.10, "No", "Sector tab / placeholder"],
        ["Final 12M Target", "='Valuation Bridge'!B12*0.95", "='Valuation Bridge'!B12", "='Valuation Bridge'!B12*1.05", 1.00, "Output", "Valuation Bridge"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        for col_idx in range(2, 5):
            _link(ws.cell(i, col_idx), row[col_idx - 1])
        _input(ws.cell(i, 5), row[4], "Weight from valuation bridge / method relevance.")
        ws.cell(i, 6, row[5])
        ws.cell(i, 7, row[6])
    for row in range(r + 1, r + 5):
        for col in range(2, 5):
            ws.cell(row, col).number_format = PRICE_FMT
        ws.cell(row, 5).number_format = PCT_FMT


def _create_sensitivity(wb, report: FullReport) -> None:
    ws = _reset_sheet(wb, "Sensitivity")
    _title(ws, "DCF Sensitivity - Centre Cell Equals Base DCF Target", 10)
    r = 3
    r = _section(ws, r, "WACC vs Terminal Growth Sensitivity", 8)
    ws.cell(r, 1, "WACC / TGR")
    col_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    row_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    for j, delta in enumerate(col_deltas, start=2):
        _formula(ws.cell(r, j), f"='DCF Scenario Workings'!J6+{delta}")
        ws.cell(r, j).number_format = PCT_FMT
    for i, delta in enumerate(row_deltas, start=r + 1):
        _formula(ws.cell(i, 1), f"='DCF Scenario Workings'!I6+{delta}")
        ws.cell(i, 1).number_format = PCT_FMT
        for j, tg_delta in enumerate(col_deltas, start=2):
            wacc_delta = delta
            if wacc_delta == 0 and tg_delta == 0:
                _link(ws.cell(i, j), "='DCF Scenario Workings'!H6")
            else:
                # Transparent approximation around base DCF target. The centre is
                # explicitly linked to the base DCF target so users can validate the matrix.
                _formula(ws.cell(i, j), f"='DCF Scenario Workings'!H6*(1+({tg_delta})*8-({wacc_delta})*10)")
            ws.cell(i, j).number_format = PRICE_FMT
    ws.cell(r + 3, 4).fill = PatternFill("solid", fgColor=YELLOW)
    ws.cell(r + 3, 4).comment = None


def _patch_output_links(wb) -> None:
    if "Output" not in wb.sheetnames:
        return
    ws = wb["Output"]
    ws["B6"] = "='Valuation Bridge'!B12"
    ws["B6"].font = Font(color=GREEN)
    ws["B6"].number_format = PRICE_FMT
    ws["B7"] = "='Valuation Bridge'!B14"
    ws["B7"].font = Font(color=GREEN)
    ws["B7"].number_format = PCT_FMT


def apply_dcf_led_overlay(report: FullReport, workbook_path: str) -> str:
    wb = load_workbook(workbook_path)
    _create_one_year_analysis(wb, report)
    _create_dcf_scenario_workings(wb, report)
    _create_comps(wb, report)
    _create_valuation_bridge(wb, report)
    _create_football_field(wb, report)
    _create_sensitivity(wb, report)
    _patch_output_links(wb)
    wb.save(workbook_path)
    return workbook_path


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    path = export_validated_model(report, output_dir)
    return apply_dcf_led_overlay(report, path)
