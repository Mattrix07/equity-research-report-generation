"""Balanced Excel model exporter.

This exporter replaces the earlier workbook scaffold with a formula structure that
is designed to be acyclic and to balance through the three statements before the
Excel file is written.

Key design choices:
- cash is driven from the cash-flow statement and linked to the balance sheet;
- debt is driven from an explicit debt repayment schedule, not from cash;
- other assets and liabilities are included in cash flow, so balance-sheet
  movements reconcile;
- free cash flow and ending cash are kept on separate rows to avoid row-linking
  errors;
- a formula dependency scan runs before save and fails fast if circular links are
  introduced by future code changes.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.schemas import FullReport

BLUE = "0000FF"
BLACK = "000000"
GREEN = "008000"
WHITE = "FFFFFF"
DARK_BLUE = "17365D"
GREY = "D9E1F2"
YELLOW = "FFF2CC"

NUM_FMT = '#,##0;[Red](#,##0);-'
NUM_1_FMT = '#,##0.0;[Red](#,##0.0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'

CELL_REF_RE = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_ ]*))!)?\$?([A-Z]{1,3})\$?(\d+)")


def _style_sheet(ws, freeze: str = "B5") -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = freeze
    for col in range(1, 18):
        ws.column_dimensions[get_column_letter(col)].width = 15
    ws.column_dimensions["A"].width = 36


def _title(ws, title: str, end_col: int = 12) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, title)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, title: str, end_col: int = 12) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    c = ws.cell(row, 1, title)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True)
    return row + 1


def _headers(ws, row: int, labels: list[str]) -> None:
    for idx, label in enumerate(labels, start=1):
        c = ws.cell(row, idx, label)
        c.fill = PatternFill("solid", fgColor=GREY)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(bottom=Side(style="thin", color="808080"))


def _input(cell, value: Any, comment: str | None = None) -> None:
    cell.value = value
    cell.font = Font(color=BLUE)
    cell.fill = PatternFill("solid", fgColor=YELLOW)
    if comment:
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


def _last_value(data: dict[str, float], fallback: float = 0.0) -> float:
    if not data:
        return fallback
    return _safe(data.get(sorted(data.keys())[-1]), fallback)


def _hist_years(report: FullReport) -> list[str]:
    return sorted(report.historicals.revenue.keys())[-3:] or ["Hist"]


def _forecast_years(report: FullReport) -> list[str]:
    base = report.forecasts.get("base", [])
    return [row.year for row in base] or ["FY1E", "FY2E", "FY3E", "FY4E", "FY5E"]


def _source_last_revenue_ref(report: FullReport) -> str:
    return f"'Source Data'!{get_column_letter(1 + len(_hist_years(report)))}24"


def _create_output(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Output")
    _style_sheet(ws)
    _title(ws, f"{report.snapshot.company_name} ({report.snapshot.ticker}) - Equity Research Model", 10)

    r = 3
    r = _section(ws, r, "Investment Snapshot", 6)
    items = [
        ("Recommendation", report.recommendation),
        ("Current price", report.snapshot.current_price),
        ("Target price", report.target_price),
        ("Upside / downside", report.upside_downside),
        ("Primary method", report.dynamic_valuation.primary_method if report.dynamic_valuation else "n/a"),
        ("Model type", report.financial_model_plan.model_type if report.financial_model_plan else "n/a"),
        ("Confidence", (report.dynamic_valuation.confidence / 100) if report.dynamic_valuation else None),
    ]
    for i, (label, value) in enumerate(items, start=r):
        ws.cell(i, 1, label)
        ws.cell(i, 2, value)
    ws["B5"].number_format = PRICE_FMT
    ws["B6"].number_format = PRICE_FMT
    ws["B7"].number_format = PCT_FMT
    ws["B10"].number_format = PCT_FMT

    r = 13
    r = _section(ws, r, "Football Field Summary", 7)
    _headers(ws, r, ["Method", "Low", "Base", "High", "Weight", "Primary", "Comment"])
    rows = [
        ["Dynamic valuation", "='Football Field'!B5", "='Football Field'!C5", "='Football Field'!D5", "='Football Field'!E5", "='Football Field'!F5", "='Football Field'!G5"],
        ["DCF cross-check", "='Football Field'!B6", "='Football Field'!C6", "='Football Field'!D6", "='Football Field'!E6", "='Football Field'!F6", "='Football Field'!G6"],
        ["Trading comps", "='Football Field'!B7", "='Football Field'!C7", "='Football Field'!D7", "='Football Field'!E7", "='Football Field'!F7", "='Football Field'!G7"],
        ["Sector engine", "='Football Field'!B8", "='Football Field'!C8", "='Football Field'!D8", "='Football Field'!E8", "='Football Field'!F8", "='Football Field'!G8"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        for j, value in enumerate(row, start=1):
            if isinstance(value, str) and value.startswith("="):
                _link(ws.cell(i, j), value)
            else:
                ws.cell(i, j, value)
    for row in range(r + 1, r + 5):
        for col in range(2, 5):
            ws.cell(row, col).number_format = PRICE_FMT
        ws.cell(row, 5).number_format = PCT_FMT


def _create_source_data(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Source Data")
    _style_sheet(ws)
    _title(ws, "Source Data and Opening Balance Sheet", 12)

    r = 3
    r = _section(ws, r, "Company Snapshot", 4)
    _headers(ws, r, ["Item", "Value", "Source / Comment"])
    items = [
        ("Ticker", report.snapshot.ticker, "user input / yfinance"),
        ("Company", report.snapshot.company_name, "user input / yfinance"),
        ("Sector", report.snapshot.sector, "yfinance"),
        ("Industry", report.snapshot.industry, "yfinance"),
        ("Current Price", report.snapshot.current_price, "yfinance or user override"),
        ("Market Cap", report.snapshot.market_cap, "yfinance"),
        ("Enterprise Value", report.snapshot.enterprise_value, "yfinance"),
        ("Shares Outstanding", report.snapshot.shares_outstanding, "yfinance"),
        ("Cash", report.snapshot.total_cash, "yfinance"),
        ("Debt", report.snapshot.total_debt, "yfinance"),
        ("Net Debt", report.snapshot.net_debt, "debt minus cash"),
        ("Beta", report.snapshot.beta, "yfinance"),
        ("Book Value / Share", report.snapshot.book_value, "yfinance where available"),
        ("P/B", report.snapshot.price_to_book, "yfinance where available"),
        ("ROE", report.snapshot.return_on_equity, "yfinance where available"),
    ]
    for i, row in enumerate(items, start=r + 1):
        ws.cell(i, 1, row[0])
        _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
    for row in range(r + 1, r + len(items) + 1):
        ws.cell(row, 2).number_format = NUM_FMT
    ws["B9"].number_format = PRICE_FMT
    ws["B19"].number_format = PCT_FMT

    r = 22
    r = _section(ws, r, "Historical Income Statement and Cash Flow", 8)
    years = _hist_years(report)
    _headers(ws, r, ["Metric"] + years)
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
    for i, (metric, values) in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
        for j, year in enumerate(years, start=2):
            _input(ws.cell(i, j), values.get(year), f"Historical {metric}; source review required")
    for row in range(r + 1, r + 8):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_FMT
    for row in range(r + 8, r + 10):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT

    r = 36
    r = _section(ws, r, "Opening Balance Sheet Inputs", 8)
    _headers(ws, r, ["Metric", "Value", "Source / Logic"])
    last_rev = _last_value(report.historicals.revenue, _safe(report.snapshot.revenue_ttm, 100_000_000))
    opening_cash = _safe(report.snapshot.total_cash, max(last_rev * 0.10, 1.0))
    opening_debt = _safe(report.snapshot.total_debt, 0)
    opening_ar = last_rev * 45 / 365
    opening_inventory = max(last_rev * 0.20 * 45 / 365, 0)
    opening_ap = max(last_rev * 0.20 * 50 / 365, 0)
    opening_ppe = max(last_rev * 0.35, 1.0)
    opening_other_assets = max(last_rev * 0.10, 1.0)
    opening_other_liab = max(last_rev * 0.12, 1.0)
    opening_equity = opening_cash + opening_ar + opening_inventory + opening_ppe + opening_other_assets - opening_ap - opening_debt - opening_other_liab
    bs_rows = [
        ("Cash", opening_cash, "actual cash if available; otherwise estimated"),
        ("Accounts Receivable", opening_ar, "estimated from revenue and DSO"),
        ("Inventory", opening_inventory, "estimated from COGS and inventory days"),
        ("PP&E", opening_ppe, "estimated from revenue/capital intensity"),
        ("Other Assets", opening_other_assets, "estimated placeholder"),
        ("Accounts Payable", opening_ap, "estimated from COGS and payable days"),
        ("Debt", opening_debt, "actual debt if available"),
        ("Other Liabilities", opening_other_liab, "estimated placeholder"),
        ("Equity", opening_equity, "opening plug so balance sheet balances"),
    ]
    for i, row in enumerate(bs_rows, start=r + 1):
        ws.cell(i, 1, row[0])
        _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
        ws.cell(i, 2).number_format = NUM_FMT


def _create_assumptions(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Assumptions")
    _style_sheet(ws)
    _title(ws, "Assumptions and Audit Trail", 12)
    years = _forecast_years(report)
    base = report.assumptions["base"]
    r = 3
    r = _section(ws, r, "Core Operating Assumptions", 8)
    _headers(ws, r, ["Metric"] + years)
    rows = [
        ["Revenue Growth"] + list(base.revenue_growth),
        ["Gross Margin"] + [0.45] * len(years),
        ["EBITDA Margin"] + list(base.ebitda_margin),
        ["D&A % Revenue"] + [base.da_percent_revenue] * len(years),
        ["Capex % Revenue"] + [base.capex_percent_revenue] * len(years),
        ["DSO"] + [45] * len(years),
        ["Inventory Days"] + [45] * len(years),
        ["DPO"] + [50] * len(years),
        ["Other Assets Growth"] + [0.0] * len(years),
        ["Other Liabilities Growth"] + [0.0] * len(years),
        ["Tax Rate"] + [base.tax_rate] * len(years),
        ["Interest Rate on Debt"] + [0.055] * len(years),
        ["Debt Repayment % Opening Debt"] + [0.0] * len(years),
        ["Dividend Payout Ratio"] + [0.0] * len(years),
        ["WACC"] + [base.wacc] * len(years),
        ["Terminal Growth"] + [base.terminal_growth] * len(years),
        ["Exit EBITDA Multiple"] + [12.0] * len(years),
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        for j, val in enumerate(row[1:], start=2):
            _input(ws.cell(i, j), val, f"Editable forecast assumption: {row[0]}")
    pct_rows = [5, 6, 7, 8, 9, 13, 14, 15, 16, 17, 18, 19, 20]
    for row in pct_rows:
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT
    for row in [10, 11, 12]:
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_1_FMT
    for col in range(2, 2 + len(years)):
        ws.cell(21, col).number_format = MULT_FMT

    r = 24
    r = _section(ws, r, "Assumption Rationale", 6)
    _headers(ws, r, ["Area", "Rationale"])
    dyn = report.dynamic_assumptions
    rationale = [
        ("Revenue", dyn.revenue_growth_logic if dyn else "Review revenue drivers."),
        ("Margin", dyn.margin_logic if dyn else "Review margin drivers."),
        ("Capital intensity", dyn.capital_intensity_logic if dyn else "Review capex and working capital."),
        ("Risk adjustment", dyn.risk_adjustment_logic if dyn else "Review risk adjustment."),
        ("Evidence", "; ".join(dyn.sources_and_evidence) if dyn else "n/a"),
    ]
    for i, (area, text) in enumerate(rationale, start=r + 1):
        ws.cell(i, 1, area)
        ws.cell(i, 2, text)
        ws.cell(i, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["B"].width = 80


def _create_operating_schedules(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Operating Schedules")
    _style_sheet(ws)
    _title(ws, "Operating Schedules", 12)
    years = _forecast_years(report)
    r = 3
    r = _section(ws, r, "Working Capital, PP&E, Other Assets / Liabilities", 9)
    _headers(ws, r, ["Metric"] + years)
    metrics = [
        "Revenue", "COGS", "Accounts Receivable", "Inventory", "Accounts Payable", "Net Working Capital", "Change in NWC",
        "Opening PP&E", "Capex", "D&A", "Closing PP&E", "Other Assets", "Change in Other Assets", "Other Liabilities", "Change in Other Liabilities",
    ]
    for i, metric in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
    start = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        p = get_column_letter(col - 1)
        _link(ws.cell(start, col), f"='3 Statement Model'!{c}5")
        _formula(ws.cell(start + 1, col), f"={c}{start}*(1-Assumptions!{c}$6)")
        _formula(ws.cell(start + 2, col), f"={c}{start}*Assumptions!{c}$10/365")
        _formula(ws.cell(start + 3, col), f"={c}{start+1}*Assumptions!{c}$11/365")
        _formula(ws.cell(start + 4, col), f"={c}{start+1}*Assumptions!{c}$12/365")
        _formula(ws.cell(start + 5, col), f"={c}{start+2}+{c}{start+3}-{c}{start+4}")
        if col == 2:
            _formula(ws.cell(start + 6, col), f"={c}{start+5}-('Source Data'!$B$39+'Source Data'!$B$40-'Source Data'!$B$43)")
            _link(ws.cell(start + 7, col), "='Source Data'!$B$41")
            _formula(ws.cell(start + 11, col), "='Source Data'!$B$42*(1+Assumptions!B$13)")
            _formula(ws.cell(start + 12, col), f"={c}{start+11}-'Source Data'!$B$42")
            _formula(ws.cell(start + 13, col), "='Source Data'!$B$45*(1+Assumptions!B$14)")
            _formula(ws.cell(start + 14, col), f"={c}{start+13}-'Source Data'!$B$45")
        else:
            _formula(ws.cell(start + 6, col), f"={c}{start+5}-{p}{start+5}")
            _formula(ws.cell(start + 7, col), f"={p}{start+10}")
            _formula(ws.cell(start + 11, col), f"={p}{start+11}*(1+Assumptions!{c}$13)")
            _formula(ws.cell(start + 12, col), f"={c}{start+11}-{p}{start+11}")
            _formula(ws.cell(start + 13, col), f"={p}{start+13}*(1+Assumptions!{c}$14)")
            _formula(ws.cell(start + 14, col), f"={c}{start+13}-{p}{start+13}")
        _formula(ws.cell(start + 8, col), f"={c}{start}*Assumptions!{c}$9")
        _link(ws.cell(start + 9, col), f"='3 Statement Model'!{c}11")
        _formula(ws.cell(start + 10, col), f"={c}{start+7}+{c}{start+8}-{c}{start+9}")
    for row in range(start, start + len(metrics)):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_FMT


def _create_three_statement(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("3 Statement Model")
    _style_sheet(ws)
    _title(ws, "Linked Three-Statement Model", 12)
    years = _forecast_years(report)

    r = 3
    r = _section(ws, r, "Income Statement", 9)
    _headers(ws, r, ["Metric"] + years)
    is_rows = ["Revenue", "Revenue Growth", "Gross Profit", "Gross Margin", "EBITDA", "EBITDA Margin", "D&A", "EBIT", "Interest Expense", "EBT", "Tax", "Net Income"]
    for i, label in enumerate(is_rows, start=r + 1):
        ws.cell(i, 1, label)
    is_start = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        p = get_column_letter(col - 1)
        if col == 2:
            _formula(ws.cell(is_start, col), f"={_source_last_revenue_ref(report)}*(1+Assumptions!{c}$5)")
        else:
            _formula(ws.cell(is_start, col), f"={p}{is_start}*(1+Assumptions!{c}$5)")
        _link(ws.cell(is_start + 1, col), f"=Assumptions!{c}$5")
        _formula(ws.cell(is_start + 2, col), f"={c}{is_start}*Assumptions!{c}$6")
        _formula(ws.cell(is_start + 3, col), f"={c}{is_start+2}/{c}{is_start}")
        _formula(ws.cell(is_start + 4, col), f"={c}{is_start}*Assumptions!{c}$7")
        _formula(ws.cell(is_start + 5, col), f"={c}{is_start+4}/{c}{is_start}")
        _formula(ws.cell(is_start + 6, col), f"={c}{is_start}*Assumptions!{c}$8")
        _formula(ws.cell(is_start + 7, col), f"={c}{is_start+4}-{c}{is_start+6}")
        if col == 2:
            _formula(ws.cell(is_start + 8, col), f"=AVERAGE('Source Data'!$B$44,{c}28)*Assumptions!{c}$16")
        else:
            _formula(ws.cell(is_start + 8, col), f"=AVERAGE({p}28,{c}28)*Assumptions!{c}$16")
        _formula(ws.cell(is_start + 9, col), f"={c}{is_start+7}-{c}{is_start+8}")
        _formula(ws.cell(is_start + 10, col), f"=MAX({c}{is_start+9},0)*Assumptions!{c}$15")
        _formula(ws.cell(is_start + 11, col), f"={c}{is_start+9}-{c}{is_start+10}")

    r = 19
    r = _section(ws, r, "Balance Sheet", 9)
    _headers(ws, r, ["Metric"] + years)
    bs_rows = ["Cash", "Accounts Receivable", "Inventory", "PP&E", "Other Assets", "Total Assets", "Accounts Payable", "Debt", "Other Liabilities", "Total Liabilities", "Shareholders' Equity", "Total Liabilities + Equity", "Balance Check"]
    for i, label in enumerate(bs_rows, start=r + 1):
        ws.cell(i, 1, label)
    bs = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        p = get_column_letter(col - 1)
        _link(ws.cell(bs, col), f"={c}48")
        _link(ws.cell(bs + 1, col), f"='Operating Schedules'!{c}7")
        _link(ws.cell(bs + 2, col), f"='Operating Schedules'!{c}8")
        _link(ws.cell(bs + 3, col), f"='Operating Schedules'!{c}15")
        _link(ws.cell(bs + 4, col), f"='Operating Schedules'!{c}16")
        _formula(ws.cell(bs + 5, col), f"=SUM({c}{bs}:{c}{bs+4})")
        _link(ws.cell(bs + 6, col), f"='Operating Schedules'!{c}9")
        if col == 2:
            _formula(ws.cell(bs + 7, col), f"='Source Data'!$B$44*(1-Assumptions!{c}$17)")
        else:
            _formula(ws.cell(bs + 7, col), f"={p}{bs+7}*(1-Assumptions!{c}$17)")
        _link(ws.cell(bs + 8, col), f"='Operating Schedules'!{c}18")
        _formula(ws.cell(bs + 9, col), f"=SUM({c}{bs+6}:{c}{bs+8})")
        if col == 2:
            _formula(ws.cell(bs + 10, col), f"='Source Data'!$B$46+{c}{is_start+11}+{c}46")
        else:
            _formula(ws.cell(bs + 10, col), f"={p}{bs+10}+{c}{is_start+11}+{c}46")
        _formula(ws.cell(bs + 11, col), f"={c}{bs+9}+{c}{bs+10}")
        _formula(ws.cell(bs + 12, col), f"={c}{bs+5}-{c}{bs+11}")

    r = 36
    r = _section(ws, r, "Cash Flow Statement", 9)
    _headers(ws, r, ["Metric"] + years)
    cf_rows = ["Net Income", "D&A", "Change in NWC", "Change in Other Assets", "Change in Other Liabilities", "Cash Flow from Operations", "Capex", "Debt Repayment", "Dividends / Buybacks", "Net Change in Cash", "Ending Cash", "Free Cash Flow"]
    for i, label in enumerate(cf_rows, start=r + 1):
        ws.cell(i, 1, label)
    cf = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        p = get_column_letter(col - 1)
        _link(ws.cell(cf, col), f"={c}{is_start+11}")
        _link(ws.cell(cf + 1, col), f"={c}{is_start+6}")
        _link(ws.cell(cf + 2, col), f"='Operating Schedules'!{c}11")
        _link(ws.cell(cf + 3, col), f"='Operating Schedules'!{c}17")
        _link(ws.cell(cf + 4, col), f"='Operating Schedules'!{c}19")
        _formula(ws.cell(cf + 5, col), f"={c}{cf}+{c}{cf+1}-{c}{cf+2}-{c}{cf+3}+{c}{cf+4}")
        _formula(ws.cell(cf + 6, col), f"=-'Operating Schedules'!{c}13")
        if col == 2:
            _formula(ws.cell(cf + 7, col), f"={c}{bs+7}-'Source Data'!$B$44")
            _formula(ws.cell(cf + 10, col), f"='Source Data'!$B$38+{c}{cf+9}")
        else:
            _formula(ws.cell(cf + 7, col), f"={c}{bs+7}-{p}{bs+7}")
            _formula(ws.cell(cf + 10, col), f"={p}{cf+10}+{c}{cf+9}")
        _formula(ws.cell(cf + 8, col), f"=-{c}{cf}*Assumptions!{c}$18")
        _formula(ws.cell(cf + 9, col), f"={c}{cf+5}+{c}{cf+6}+{c}{cf+7}+{c}{cf+8}")
        _formula(ws.cell(cf + 11, col), f"={c}{cf+5}+{c}{cf+6}")

    for row in list(range(is_start, is_start + len(is_rows))) + list(range(bs, bs + len(bs_rows))) + list(range(cf, cf + len(cf_rows))):
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = NUM_FMT
    for row in [is_start + 1, is_start + 3, is_start + 5]:
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT


def _create_wacc(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("WACC")
    _style_sheet(ws)
    _title(ws, "WACC / Cost of Capital", 8)
    r = 3
    r = _section(ws, r, "Cost of Equity", 5)
    _headers(ws, r, ["Item", "Value", "Comment"])
    rows = [
        ["Risk-free rate", 0.045, "Input: update to current sovereign yield"],
        ["Equity risk premium", 0.055, "Input: market ERP"],
        ["Beta", report.snapshot.beta or 1.0, "Market beta from yfinance or manual override"],
        ["Specific risk premium", max((report.dynamic_assumptions.cost_of_equity or 0) - (0.045 + (report.snapshot.beta or 1.0) * 0.055), 0) if report.dynamic_assumptions else 0, "Size/sector/company risk premium"],
        ["Cost of Equity", "=B5+B6*B7+B8", "Formula"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str):
            _formula(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
        ws.cell(i, 2).number_format = PCT_FMT

    r = 12
    r = _section(ws, r, "WACC Build", 5)
    _headers(ws, r, ["Item", "Value", "Comment"])
    rows = [
        ["Market Cap", report.snapshot.market_cap, "Source data"],
        ["Total Debt", report.snapshot.total_debt, "Source data"],
        ["Total Capital", "=B14+B15", "Formula"],
        ["Equity Weight", "=B14/B16", "Formula"],
        ["Debt Weight", "=B15/B16", "Formula"],
        ["Pre-tax Cost of Debt", 0.055, "Manual input / debt yield"],
        ["Tax Rate", report.dynamic_assumptions.tax_rate if report.dynamic_assumptions and report.dynamic_assumptions.tax_rate else 0.25, "Dynamic assumption"],
        ["After-tax Cost of Debt", "=B19*(1-B20)", "Formula"],
        ["WACC", "=B17*B9+B18*B21", "Formula"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str):
            _formula(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
    for row in [14, 15, 16]:
        ws.cell(row, 2).number_format = NUM_FMT
    for row in [17, 18, 19, 20, 21, 22]:
        ws.cell(row, 2).number_format = PCT_FMT


def _create_dcf(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("DCF")
    _style_sheet(ws)
    _title(ws, "Baseline DCF Cross-Check", 12)
    years = _forecast_years(report)
    r = 3
    r = _section(ws, r, "DCF Calculation", 10)
    _headers(ws, r, ["Metric"] + years + ["Terminal"])
    rows = ["Free Cash Flow", "Discount Factor", "PV of FCF", "Terminal Value", "PV of Terminal Value", "Enterprise Value", "Net Debt", "Equity Value", "Shares", "Target Price"]
    for i, label in enumerate(rows, start=r + 1):
        ws.cell(i, 1, label)
    start = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        _link(ws.cell(start, col), f"='3 Statement Model'!{c}49")
        _formula(ws.cell(start + 1, col), f"=1/(1+WACC!$B$22)^{col-1}")
        _formula(ws.cell(start + 2, col), f"={c}{start}*{c}{start+1}")
    term_col = 2 + len(years)
    term = get_column_letter(term_col)
    last = get_column_letter(term_col - 1)
    _formula(ws.cell(start + 3, term_col), f"={last}{start}*(1+Assumptions!{last}$20)/(WACC!$B$22-Assumptions!{last}$20)")
    _formula(ws.cell(start + 4, term_col), f"={term}{start+3}/(1+WACC!$B$22)^{len(years)}")
    _formula(ws.cell(start + 5, term_col), f"=SUM(B{start+2}:{last}{start+2})+{term}{start+4}")
    _link(ws.cell(start + 6, term_col), "='Source Data'!$B$15")
    _formula(ws.cell(start + 7, term_col), f"={term}{start+5}-{term}{start+6}")
    _link(ws.cell(start + 8, term_col), "='Source Data'!$B$12")
    _formula(ws.cell(start + 9, term_col), f"={term}{start+7}/{term}{start+8}")
    for row in range(start, start + len(rows)):
        for col in range(2, term_col + 1):
            ws.cell(row, col).number_format = PRICE_FMT if row == start + 9 else NUM_FMT


def _create_comps(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps")
    _style_sheet(ws)
    _title(ws, "Trading Comparables", 10)
    r = 3
    r = _section(ws, r, "Peer Multiples", 10)
    _headers(ws, r, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "P/E", "Notes"])
    row = r + 1
    data = [report.snapshot.company_name, report.snapshot.ticker, report.snapshot.market_cap, report.snapshot.enterprise_value, report.snapshot.revenue_ttm, report.snapshot.ebitda, None, None, report.snapshot.forward_pe, "Subject company"]
    for col, value in enumerate(data, start=1):
        ws.cell(row, col, value)
    _formula(ws.cell(row, 7), f"=D{row}/E{row}")
    _formula(ws.cell(row, 8), f"=D{row}/F{row}")
    for c in range(3, 7):
        ws.cell(row, c).number_format = NUM_FMT
    ws.cell(row, 7).number_format = MULT_FMT
    ws.cell(row, 8).number_format = MULT_FMT
    ws.cell(row, 9).number_format = MULT_FMT


def _create_sensitivity(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Sensitivity")
    _style_sheet(ws)
    _title(ws, "Sensitivity Analysis", 12)
    years = _forecast_years(report)
    last_col = get_column_letter(1 + len(years))
    r = 3
    r = _section(ws, r, "WACC vs Terminal Growth", 8)
    waccs = [0.075, 0.085, 0.095, 0.105, 0.115]
    tgs = [0.01, 0.02, 0.025, 0.03, 0.04]
    ws.cell(r, 1, "WACC / TGR")
    for j, tg in enumerate(tgs, start=2):
        ws.cell(r, j, tg).number_format = PCT_FMT
    for i, w in enumerate(waccs, start=r + 1):
        ws.cell(i, 1, w).number_format = PCT_FMT
        for j, tg in enumerate(tgs, start=2):
            fcf = f"'3 Statement Model'!{last_col}49"
            _formula(ws.cell(i, j), f"=(({fcf}*(1+{tg})/({w}-{tg}))/(1+{w})^{len(years)}+SUM(DCF!B6:{last_col}6)-'Source Data'!$B$15)/'Source Data'!$B$12")
            ws.cell(i, j).number_format = PRICE_FMT

    r = 13
    r = _section(ws, r, "Revenue Growth vs EBITDA Margin Delta", 8)
    growth_deltas = [-0.04, -0.02, 0.0, 0.02, 0.04]
    margin_deltas = [-0.04, -0.02, 0.0, 0.02, 0.04]
    ws.cell(r, 1, "Growth / Margin")
    for j, md in enumerate(margin_deltas, start=2):
        ws.cell(r, j, md).number_format = PCT_FMT
    base_price = report.target_price or report.snapshot.current_price or 0
    for i, gd in enumerate(growth_deltas, start=r + 1):
        ws.cell(i, 1, gd).number_format = PCT_FMT
        for j, md in enumerate(margin_deltas, start=2):
            _formula(ws.cell(i, j), f"={base_price}*(1+{gd}*2+{md}*3)")
            ws.cell(i, j).number_format = PRICE_FMT


def _create_football_field(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Football Field")
    _style_sheet(ws)
    _title(ws, "Football Field Valuation", 10)
    target = report.target_price or report.snapshot.current_price or 0
    dcf = report.dcf_outputs.get("base").target_price if report.dcf_outputs.get("base") else target
    current = report.snapshot.current_price or target
    sector = target or current
    r = 3
    r = _section(ws, r, "Valuation Range", 8)
    _headers(ws, r, ["Method", "Low", "Base", "High", "Weight", "Primary", "Comment"])
    rows = [
        ["Dynamic Valuation", target * 0.9, target, target * 1.1, 0.45, "Yes", report.dynamic_valuation.primary_method if report.dynamic_valuation else "n/a"],
        ["Baseline DCF", dcf * 0.8, dcf, dcf * 1.2, 0.20, "No", "Cross-check only"],
        ["Trading Comps", current * 0.85, current, current * 1.15, 0.20, "No", "Peer multiple cross-check"],
        ["Sector Engine", sector * 0.85, sector, sector * 1.15, 0.15, "No", "Use relevant sector tab"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        for j, value in enumerate(row, start=1):
            ws.cell(i, j, value)
    for row in range(r + 1, r + 5):
        for col in range(2, 5):
            ws.cell(row, col).number_format = PRICE_FMT
        ws.cell(row, 5).number_format = PCT_FMT
    chart = BarChart()
    chart.type = "bar"
    chart.title = "Valuation Range"
    data = Reference(ws, min_col=2, max_col=4, min_row=r, max_row=r + 4)
    cats = Reference(ws, min_col=1, min_row=r + 1, max_row=r + 4)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height = 7
    chart.width = 14
    ws.add_chart(chart, "I3")


def _create_sector_tabs(wb: Workbook, report: FullReport) -> None:
    # Light formula-driven sector engines. Evidence overlay appends company-specific rows after export.
    for name, title in [
        ("Healthcare rNPV", "Healthcare Pipeline rNPV Engine"),
        ("Mining NAV", "Mining NAV Engine"),
        ("SaaS Unit Economics", "SaaS Unit Economics Engine"),
        ("Financials ROE-PBV", "Financials ROE / P-BV Engine"),
    ]:
        ws = wb.create_sheet(name)
        _style_sheet(ws)
        _title(ws, title, 12)
        ws["A3"] = "This tab is formula-ready and is populated with company-specific evidence by the evidence overlay after workbook creation."
        ws["A3"].alignment = Alignment(wrap_text=True)

    ws = wb["Healthcare rNPV"]
    r = 5
    r = _section(ws, r, "Asset-Level Risk-Adjusted Valuation", 12)
    _headers(ws, r, ["Asset", "Indication", "Phase", "PoS", "Launch Year", "Peak Sales", "Royalty / Margin", "Years to Peak", "Discount Rate", "Unrisked NPV", "Risked NPV", "Value / Share"])
    for i in range(r + 1, r + 4):
        for j, value in enumerate(["To be sourced", "To be sourced", "To be sourced", 0.0, "To be sourced", 0, 0.0, 5, 0.12], start=1):
            _input(ws.cell(i, j), value, "Replace with company-specific evidence from filings/presentations/research.")
        _formula(ws.cell(i, 10), f"=F{i}*G{i}/I{i}")
        _formula(ws.cell(i, 11), f"=J{i}*D{i}")
        _formula(ws.cell(i, 12), f"=K{i}/'Source Data'!$B$12")
        for col in [4, 7, 9]:
            ws.cell(i, col).number_format = PCT_FMT
        for col in [10, 11]:
            ws.cell(i, col).number_format = NUM_FMT
        ws.cell(i, 12).number_format = PRICE_FMT

    ws = wb["Mining NAV"]
    r = 5
    r = _section(ws, r, "Finite-Life Mine Cash Flow", 10)
    years = ["Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8"]
    _headers(ws, r, ["Metric"] + years)
    metrics = ["Production", "Commodity Price", "Revenue", "AISC / Unit", "Operating Cost", "Sustaining Capex", "Closure Cost", "Project FCF", "Discount Factor", "PV FCF"]
    for i, metric in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
    start = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        _input(ws.cell(start, col), 100000, "Production assumption; replace with mine plan.")
        _input(ws.cell(start + 1, col), 100, "Commodity price deck input.")
        _formula(ws.cell(start + 2, col), f"={c}{start}*{c}{start+1}")
        _input(ws.cell(start + 3, col), 60, "AISC / unit assumption.")
        _formula(ws.cell(start + 4, col), f"={c}{start}*{c}{start+3}")
        _input(ws.cell(start + 5, col), 5000000, "Sustaining capex assumption.")
        _input(ws.cell(start + 6, col), 0 if col < 2 + len(years) - 1 else 20000000, "Closure cost assumption.")
        _formula(ws.cell(start + 7, col), f"={c}{start+2}-{c}{start+4}-{c}{start+5}-{c}{start+6}")
        _formula(ws.cell(start + 8, col), f"=1/(1+WACC!$B$22)^{col-1}")
        _formula(ws.cell(start + 9, col), f"={c}{start+7}*{c}{start+8}")

    ws = wb["SaaS Unit Economics"]
    r = 5
    r = _section(ws, r, "ARR and Unit Economics", 10)
    years = _forecast_years(report)
    _headers(ws, r, ["Metric"] + years)
    metrics = ["Opening ARR", "New ARR %", "Churn %", "Ending ARR", "ARR Growth", "Revenue", "Gross Margin", "Rule of 40", "EV/ARR Multiple", "Implied Price"]
    for i, metric in enumerate(metrics, start=r + 1):
        ws.cell(i, 1, metric)
    start = r + 1
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        p = get_column_letter(col - 1)
        if col == 2:
            _input(ws.cell(start, col), _safe(report.snapshot.revenue_ttm, 100000000), "Opening ARR proxy; replace with company disclosure.")
        else:
            _formula(ws.cell(start, col), f"={p}{start+3}")
        _input(ws.cell(start + 1, col), 0.25, "New ARR as % opening ARR")
        _input(ws.cell(start + 2, col), 0.08, "Churn as % opening ARR")
        _formula(ws.cell(start + 3, col), f"={c}{start}+{c}{start}*{c}{start+1}-{c}{start}*{c}{start+2}")
        _formula(ws.cell(start + 4, col), f"={c}{start+3}/{c}{start}-1")
        _formula(ws.cell(start + 5, col), f"=AVERAGE({c}{start},{c}{start+3})")
        _input(ws.cell(start + 6, col), 0.75, "Gross margin input")
        _formula(ws.cell(start + 7, col), f"={c}{start+4}+('3 Statement Model'!{c}49/'3 Statement Model'!{c}5)")
        _input(ws.cell(start + 8, col), 8.0, "EV/ARR multiple")
        _formula(ws.cell(start + 9, col), f"={c}{start+3}*{c}{start+8}/'Source Data'!$B$12")

    ws = wb["Financials ROE-PBV"]
    r = 5
    r = _section(ws, r, "Justified P/B Framework", 8)
    _headers(ws, r, ["Metric", "Value", "Comment"])
    rows = [
        ["Book Value / Share", report.snapshot.book_value or report.snapshot.current_price or 1.0, "Input"],
        ["Sustainable ROE", report.snapshot.return_on_equity or 0.12, "Input"],
        ["Cost of Equity", "=WACC!B9", "Formula"],
        ["Long-term Growth", 0.03, "Input"],
        ["Justified P/B", "=(B7-B9)/(B8-B9)", "Formula"],
        ["Target Price", "=B6*B10", "Formula"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str) and row[1].startswith("="):
            _formula(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])


def _create_model_checks(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Model Checks")
    _style_sheet(ws)
    _title(ws, "Model Integrity Checks", 10)
    years = _forecast_years(report)
    r = 3
    r = _section(ws, r, "Balance Sheet Checks", 8)
    _headers(ws, r, ["Check"] + years + ["Status"])
    ws.cell(r + 1, 1, "Balance Check")
    for col in range(2, 2 + len(years)):
        c = get_column_letter(col)
        _link(ws.cell(r + 1, col), f"='3 Statement Model'!{c}33")
        ws.cell(r + 1, col).number_format = NUM_FMT
    status_col = 2 + len(years)
    status_letter = get_column_letter(status_col)
    last_year_letter = get_column_letter(1 + len(years))
    _formula(ws.cell(r + 1, status_col), f"=IF(MAX(ABS(B{r+1}:{last_year_letter}{r+1}))<1,\"OK\",\"ERROR - BS does not balance\")")

    r = 8
    r = _section(ws, r, "Formula Structure Checks", 8)
    checks = [
        ("Cash links to cash-flow ending cash", "='3 Statement Model'!B21='3 Statement Model'!B48"),
        ("DCF links to FCF, not ending cash", "=DCF!B5='3 Statement Model'!B49"),
        ("Net debt source exists", "=ISNUMBER('Source Data'!B15)"),
    ]
    _headers(ws, r, ["Check", "Formula Result"])
    for i, (label, formula) in enumerate(checks, start=r + 1):
        ws.cell(i, 1, label)
        _formula(ws.cell(i, 2), formula)


def _format_all(wb: Workbook) -> None:
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
        for col in range(1, min(ws.max_column, 14) + 1):
            letter = get_column_letter(col)
            if ws.column_dimensions[letter].width < 12:
                ws.column_dimensions[letter].width = 12


def _formula_dependencies(wb: Workbook) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    sheet_names = {ws.title for ws in wb.worksheets}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str) or not cell.value.startswith("="):
                    continue
                node = f"{ws.title}!{cell.coordinate}"
                graph[node]
                for match in CELL_REF_RE.finditer(cell.value):
                    sheet_quoted, sheet_plain, col, row_num = match.groups()
                    sheet_name = sheet_quoted or sheet_plain or ws.title
                    if sheet_name not in sheet_names:
                        continue
                    graph[node].add(f"{sheet_name}!{col}{row_num}")
    return graph


def _assert_no_formula_cycles(wb: Workbook) -> None:
    graph = _formula_dependencies(wb)
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = " -> ".join(path + [node])
            raise ValueError(f"Circular Excel formula dependency detected: {cycle}")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, set()):
            if dep in graph:
                dfs(dep, path + [node])
        visiting.remove(node)
        visited.add(node)

    for node in list(graph.keys()):
        dfs(node, [])


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    _create_output(wb, report)
    _create_source_data(wb, report)
    _create_assumptions(wb, report)
    _create_operating_schedules(wb, report)
    _create_three_statement(wb, report)
    _create_wacc(wb, report)
    _create_dcf(wb, report)
    _create_comps(wb, report)
    _create_sensitivity(wb, report)
    _create_football_field(wb, report)
    _create_sector_tabs(wb, report)
    _create_model_checks(wb, report)
    _format_all(wb)
    _assert_no_formula_cycles(wb)

    path = output_dir / f"{report.snapshot.ticker.lower()}_{report.plan.report_type}_balanced_model.xlsx"
    wb.save(path)
    return str(path)
