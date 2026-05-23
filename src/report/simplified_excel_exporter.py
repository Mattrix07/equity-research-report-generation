"""Simplified equity research Excel exporter.

This replaces the previous complex workbook with a focused analyst model:
1. Assumptions
2. 3 Statement Model
3. WACC
4. DCF
5. Comps Analysis
6. Football Field
7. Sensitivity Analysis

The workbook is intentionally compact. It uses a scenario selector on the
Assumptions tab so Base, Bear and Bull assumptions flow through the three
statement model, WACC, DCF and valuation outputs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.schemas import FullReport

DARK_BLUE = "17365D"
WHITE = "FFFFFF"
GREY = "D9E1F2"
YELLOW = "FFF2CC"
LIGHT_BLUE = "D9EAF7"
BLUE = "0000FF"
GREEN = "008000"
BLACK = "000000"

NUM_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'

FORECAST_YEARS = 8


def _safe(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _latest(values: dict[str, float], fallback: float = 0.0) -> float:
    if not values:
        return fallback
    key = sorted(values.keys())[-1]
    return _safe(values.get(key), fallback)


def _historical_years(report: FullReport) -> list[str]:
    years = sorted(report.historicals.revenue.keys())[-5:]
    if years:
        return years
    return ["Hist-4", "Hist-3", "Hist-2", "Hist-1", "Hist"]


def _forecast_years(report: FullReport) -> list[str]:
    years = [row.year for row in report.forecasts.get("base", [])]
    if len(years) >= FORECAST_YEARS:
        return years[:FORECAST_YEARS]
    start = 1
    extra = [f"FY{idx}E" for idx in range(start, FORECAST_YEARS + 1)]
    return (years + extra)[:FORECAST_YEARS]


def _title(ws, title: str, end_col: int = 10) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    cell = ws.cell(1, 1, title)
    cell.fill = PatternFill("solid", fgColor=DARK_BLUE)
    cell.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, title: str, end_col: int = 10) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    cell = ws.cell(row, 1, title)
    cell.fill = PatternFill("solid", fgColor=DARK_BLUE)
    cell.font = Font(color=WHITE, bold=True)
    return row + 1


def _headers(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row, col, label)
        cell.fill = PatternFill("solid", fgColor=GREY)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=Side(style="thin", color="808080"))


def _style_sheet(ws) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "B6"
    for col in range(1, 22):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.column_dimensions["A"].width = 34


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


def _scenario_assumptions(report: FullReport) -> dict[str, dict[str, list[float] | float]]:
    base = report.assumptions["base"]
    bear = report.assumptions["bear"]
    bull = report.assumptions["bull"]

    def pad(values: list[float], fallback: float) -> list[float]:
        values = list(values or [])
        if not values:
            values = [fallback]
        while len(values) < FORECAST_YEARS:
            values.append(values[-1])
        return values[:FORECAST_YEARS]

    return {
        "Bear": {
            "revenue_growth": pad(bear.revenue_growth, -0.02),
            "gross_margin": [0.43] * FORECAST_YEARS,
            "ebitda_margin": pad(bear.ebitda_margin, 0.20),
            "da_pct_revenue": bear.da_percent_revenue,
            "capex_pct_revenue": bear.capex_percent_revenue,
            "dso": 50,
            "inventory_days": 50,
            "dpo": 45,
            "tax_rate": bear.tax_rate,
            "interest_rate": 0.06,
            "terminal_growth": bear.terminal_growth,
            "wacc": bear.wacc,
        },
        "Base": {
            "revenue_growth": pad(base.revenue_growth, 0.03),
            "gross_margin": [0.45] * FORECAST_YEARS,
            "ebitda_margin": pad(base.ebitda_margin, 0.25),
            "da_pct_revenue": base.da_percent_revenue,
            "capex_pct_revenue": base.capex_percent_revenue,
            "dso": 45,
            "inventory_days": 45,
            "dpo": 50,
            "tax_rate": base.tax_rate,
            "interest_rate": 0.055,
            "terminal_growth": base.terminal_growth,
            "wacc": base.wacc,
        },
        "Bull": {
            "revenue_growth": pad(bull.revenue_growth, 0.06),
            "gross_margin": [0.47] * FORECAST_YEARS,
            "ebitda_margin": pad(bull.ebitda_margin, 0.30),
            "da_pct_revenue": bull.da_percent_revenue,
            "capex_pct_revenue": bull.capex_percent_revenue,
            "dso": 40,
            "inventory_days": 40,
            "dpo": 55,
            "tax_rate": bull.tax_rate,
            "interest_rate": 0.05,
            "terminal_growth": bull.terminal_growth,
            "wacc": bull.wacc,
        },
    }


def _create_assumptions(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Assumptions")
    _style_sheet(ws)
    _title(ws, f"Assumptions and Scenario Selector - {report.snapshot.ticker}", 14)

    ws["A3"] = "Selected Scenario"
    _input(ws["B3"], "Base", "Change this to Base, Bear or Bull. Forecast, WACC, DCF, sensitivity and valuation outputs update from this selection.")
    dv = DataValidation(type="list", formula1='"Bear,Base,Bull"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(ws["B3"])
    ws["A4"] = "DCF Weight"
    _input(ws["B4"], 0.80, "Primary valuation weight. User requested DCF to carry 80% weighting.")
    ws["B4"].number_format = PCT_FMT
    ws["A5"] = "Comps Weight"
    _input(ws["B5"], 0.15, "Secondary valuation weight.")
    ws["B5"].number_format = PCT_FMT
    ws["A6"] = "Other / Football Field Weight"
    _input(ws["B6"], 0.05, "Small triangulation weight.")
    ws["B6"].number_format = PCT_FMT

    years = _forecast_years(report)
    scenarios = _scenario_assumptions(report)

    row = 9
    row = _section(ws, row, "Scenario Forecast Assumptions", 14)
    _headers(ws, row, ["Scenario", "Metric"] + years)
    metric_keys = [
        ("Revenue Growth", "revenue_growth", PCT_FMT),
        ("Gross Margin", "gross_margin", PCT_FMT),
        ("EBITDA Margin", "ebitda_margin", PCT_FMT),
        ("D&A % Revenue", "da_pct_revenue", PCT_FMT),
        ("Capex % Revenue", "capex_pct_revenue", PCT_FMT),
        ("DSO", "dso", NUM_FMT),
        ("Inventory Days", "inventory_days", NUM_FMT),
        ("DPO", "dpo", NUM_FMT),
        ("Tax Rate", "tax_rate", PCT_FMT),
        ("Interest Rate", "interest_rate", PCT_FMT),
        ("Terminal Growth", "terminal_growth", PCT_FMT),
        ("WACC", "wacc", PCT_FMT),
    ]
    start = row + 1
    current = start
    for scenario_name, data in scenarios.items():
        for metric_name, key, number_format in metric_keys:
            ws.cell(current, 1, scenario_name)
            ws.cell(current, 2, metric_name)
            values = data[key]
            if not isinstance(values, list):
                values = [values] * FORECAST_YEARS
            for col_idx, value in enumerate(values[:FORECAST_YEARS], start=3):
                _input(ws.cell(current, col_idx), value, f"{scenario_name} {metric_name}")
                ws.cell(current, col_idx).number_format = number_format
            current += 1

    active_row = current + 2
    active_start = active_row + 1
    active_row = _section(ws, active_row, "Active Scenario Assumptions Used by Model", 14)
    _headers(ws, active_row, ["Metric"] + years)
    for idx, (metric_name, _, number_format) in enumerate(metric_keys, start=active_start):
        ws.cell(idx, 1, metric_name)
        for col_idx in range(2, 2 + FORECAST_YEARS):
            source_col = get_column_letter(col_idx + 1)
            _formula(ws.cell(idx, col_idx), f"=INDEX({source_col}${start}:{source_col}${current-1},MATCH($B$3&$A{idx},$A${start}:$A${current-1}&$B${start}:$B${current-1},0))")
            ws.cell(idx, col_idx).number_format = number_format

    row = active_start + len(metric_keys) + 3
    row = _section(ws, row, "Opening Balance Sheet Inputs", 8)
    _headers(ws, row, ["Metric", "Value", "Logic"])
    last_rev = _latest(report.historicals.revenue, _safe(report.snapshot.revenue_ttm, 100_000_000))
    cash = _safe(report.snapshot.total_cash, last_rev * 0.10)
    debt = _safe(report.snapshot.total_debt, 0)
    ar = last_rev * 45 / 365
    inventory = last_rev * 0.55 * 45 / 365
    ap = last_rev * 0.55 * 50 / 365
    ppe = max(last_rev * 0.35, 1.0)
    other_assets = max(last_rev * 0.10, 1.0)
    other_liab = max(last_rev * 0.12, 1.0)
    equity = cash + ar + inventory + ppe + other_assets - ap - debt - other_liab
    opening = [
        ("Cash", cash, "Actual if available, otherwise estimated."),
        ("Accounts Receivable", ar, "Revenue × DSO / 365."),
        ("Inventory", inventory, "COGS × inventory days / 365."),
        ("PP&E", ppe, "Estimated capital intensity."),
        ("Other Assets", other_assets, "Simplified balance-sheet plug."),
        ("Accounts Payable", ap, "COGS × DPO / 365."),
        ("Debt", debt, "Actual if available."),
        ("Other Liabilities", other_liab, "Simplified balance-sheet plug."),
        ("Equity", equity, "Opening equity plug so balance sheet balances."),
        ("Shares Outstanding", report.snapshot.shares_outstanding, "Source data."),
        ("Current Share Price", report.snapshot.current_price, "Source data."),
        ("Market Cap", report.snapshot.market_cap, "Source data."),
        ("Enterprise Value", report.snapshot.enterprise_value, "Source data."),
    ]
    for i, (name, value, logic) in enumerate(opening, start=row + 1):
        ws.cell(i, 1, name)
        _input(ws.cell(i, 2), value, logic)
        ws.cell(i, 3, logic)
        ws.cell(i, 2).number_format = PRICE_FMT if "Price" in name else NUM_FMT

    ws.column_dimensions["C"].width = 22


def _active_row(metric_index: int) -> int:
    # Active assumptions start at row 49 after the 36 scenario rows and headers.
    return 49 + metric_index


def _create_three_statement(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("3 Statement Model")
    _style_sheet(ws)
    _title(ws, "Three-Statement Model", 16)

    hist_years = _historical_years(report)
    forecast_years = _forecast_years(report)
    all_years = hist_years + forecast_years
    hist_count = len(hist_years)

    r = 3
    _headers(ws, r, ["Metric"] + all_years)
    for idx, year in enumerate(all_years, start=2):
        ws.cell(r, idx).fill = PatternFill("solid", fgColor=LIGHT_BLUE if idx <= hist_count + 1 else GREY)

    is_start = 5
    rows = [
        "Revenue", "Revenue Growth", "Gross Profit", "Gross Margin", "EBITDA", "EBITDA Margin", "D&A", "EBIT", "Interest Expense", "EBT", "Tax", "Net Income",
        "", "Balance Sheet", "Cash", "Accounts Receivable", "Inventory", "PP&E", "Other Assets", "Total Assets", "Accounts Payable", "Debt", "Other Liabilities", "Total Liabilities", "Shareholders' Equity", "Total Liabilities + Equity", "Balance Check",
        "", "Cash Flow", "Net Income", "D&A", "Change in NWC", "Change in Other Assets", "Change in Other Liabilities", "Cash Flow from Operations", "Capex", "Debt Repayment", "Dividends / Buybacks", "Net Change in Cash", "Ending Cash", "Free Cash Flow",
    ]
    for i, label in enumerate(rows, start=is_start):
        ws.cell(i, 1, label)
        if label in {"Balance Sheet", "Cash Flow"}:
            ws.cell(i, 1).fill = PatternFill("solid", fgColor=DARK_BLUE)
            ws.cell(i, 1).font = Font(color=WHITE, bold=True)

    # Historical values
    hist_metrics = {
        5: report.historicals.revenue,
        9: report.historicals.ebitda,
        12: report.historicals.ebit,
        16: report.historicals.net_income,
        39: report.historicals.operating_cash_flow,
        40: report.historicals.capex,
        44: report.historicals.free_cash_flow,
    }
    for col_idx, year in enumerate(hist_years, start=2):
        for row_idx, data in hist_metrics.items():
            _input(ws.cell(row_idx, col_idx), data.get(year), "Historical financial statement data.")
        if ws.cell(5, col_idx).value:
            if col_idx == 2:
                ws.cell(6, col_idx, None)
            else:
                _formula(ws.cell(6, col_idx), f"={get_column_letter(col_idx)}5/{get_column_letter(col_idx-1)}5-1")
            _formula(ws.cell(10, col_idx), f"={get_column_letter(col_idx)}9/{get_column_letter(col_idx)}5")
            _formula(ws.cell(15, col_idx), f"={get_column_letter(col_idx)}12/{get_column_letter(col_idx)}5")
        for row_idx in [5, 9, 12, 16, 39, 40, 44]:
            ws.cell(row_idx, col_idx).number_format = NUM_FMT
        for row_idx in [6, 10, 15]:
            ws.cell(row_idx, col_idx).number_format = PCT_FMT

    forecast_start_col = 2 + hist_count
    last_hist_col = forecast_start_col - 1
    last_hist = get_column_letter(last_hist_col)

    # Opening BS references from assumptions rows 65 onwards.
    opening = {
        "cash": "'Assumptions'!$B$65",
        "ar": "'Assumptions'!$B$66",
        "inventory": "'Assumptions'!$B$67",
        "ppe": "'Assumptions'!$B$68",
        "other_assets": "'Assumptions'!$B$69",
        "ap": "'Assumptions'!$B$70",
        "debt": "'Assumptions'!$B$71",
        "other_liab": "'Assumptions'!$B$72",
        "equity": "'Assumptions'!$B$73",
    }

    for col_idx in range(forecast_start_col, forecast_start_col + FORECAST_YEARS):
        c = get_column_letter(col_idx)
        p = get_column_letter(col_idx - 1)
        active_col = get_column_letter(col_idx - forecast_start_col + 2)
        first_forecast = col_idx == forecast_start_col

        # Income statement
        _formula(ws.cell(5, col_idx), f"={last_hist}5*(1+Assumptions!{active_col}$49)" if first_forecast else f"={p}5*(1+Assumptions!{active_col}$49)")
        _formula(ws.cell(6, col_idx), f"={c}5/{p}5-1")
        _formula(ws.cell(7, col_idx), f"={c}5*Assumptions!{active_col}$50")
        _formula(ws.cell(8, col_idx), f"={c}7/{c}5")
        _formula(ws.cell(9, col_idx), f"={c}5*Assumptions!{active_col}$51")
        _formula(ws.cell(10, col_idx), f"={c}9/{c}5")
        _formula(ws.cell(11, col_idx), f"={c}5*Assumptions!{active_col}$52")
        _formula(ws.cell(12, col_idx), f"={c}9-{c}11")
        _formula(ws.cell(13, col_idx), f"=AVERAGE({opening['debt']},{c}26)*Assumptions!{active_col}$58" if first_forecast else f"=AVERAGE({p}26,{c}26)*Assumptions!{active_col}$58")
        _formula(ws.cell(14, col_idx), f"={c}12-{c}13")
        _formula(ws.cell(15, col_idx), f"=MAX({c}14,0)*Assumptions!{active_col}$57")
        _formula(ws.cell(16, col_idx), f"={c}14-{c}15")

        # Balance sheet
        _link(ws.cell(19, col_idx), f"={c}43")
        _formula(ws.cell(20, col_idx), f"={c}5*Assumptions!{active_col}$54/365")
        _formula(ws.cell(21, col_idx), f"=({c}5-{c}7)*Assumptions!{active_col}$55/365")
        _formula(ws.cell(22, col_idx), f"={opening['ppe']}+{c}40-{c}11" if first_forecast else f"={p}22+{c}40-{c}11")
        _formula(ws.cell(23, col_idx), f"={opening['other_assets']}" if first_forecast else f"={p}23")
        _formula(ws.cell(24, col_idx), f"=SUM({c}19:{c}23)")
        _formula(ws.cell(25, col_idx), f"=({c}5-{c}7)*Assumptions!{active_col}$56/365")
        _formula(ws.cell(26, col_idx), f"={opening['debt']}+{c}41" if first_forecast else f"={p}26+{c}41")
        _formula(ws.cell(27, col_idx), f"={opening['other_liab']}" if first_forecast else f"={p}27")
        _formula(ws.cell(28, col_idx), f"=SUM({c}25:{c}27)")
        _formula(ws.cell(29, col_idx), f"={opening['equity']}+{c}16+{c}42" if first_forecast else f"={p}29+{c}16+{c}42")
        _formula(ws.cell(30, col_idx), f"={c}28+{c}29")
        _formula(ws.cell(31, col_idx), f"={c}24-{c}30")

        # Cash flow
        _link(ws.cell(37, col_idx), f"={c}16")
        _link(ws.cell(38, col_idx), f"={c}11")
        if first_forecast:
            _formula(ws.cell(39, col_idx), f"=({c}20+{c}21-{c}25)-({opening['ar']}+{opening['inventory']}-{opening['ap']})")
            _formula(ws.cell(41, col_idx), f"={c}26-{opening['debt']}")
            _formula(ws.cell(43, col_idx), f"={opening['cash']}+{c}42")
        else:
            _formula(ws.cell(39, col_idx), f"=({c}20+{c}21-{c}25)-({p}20+{p}21-{p}25)")
            _formula(ws.cell(41, col_idx), f"={c}26-{p}26")
            _formula(ws.cell(43, col_idx), f"={p}43+{c}42")
        _formula(ws.cell(40, col_idx), f"=-{c}5*Assumptions!{active_col}$53")
        _formula(ws.cell(42, col_idx), f"={c}37+{c}38-{c}39+{c}40+{c}41")
        _link(ws.cell(44, col_idx), f"={c}37+{c}38-{c}39+{c}40")

    for row in range(5, 45):
        for col in range(2, forecast_start_col + FORECAST_YEARS):
            ws.cell(row, col).number_format = NUM_FMT
    for row in [6, 8, 10]:
        for col in range(2, forecast_start_col + FORECAST_YEARS):
            ws.cell(row, col).number_format = PCT_FMT


def _create_wacc(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("WACC")
    _style_sheet(ws)
    _title(ws, "Weighted Average Cost of Capital", 8)
    r = 3
    r = _section(ws, r, "Cost of Equity", 6)
    _headers(ws, r, ["Input", "Value", "Source / Formula"])
    rows = [
        ["Risk-free Rate", 0.045, "Manual input; update to current 10Y government bond yield."],
        ["Equity Risk Premium", 0.055, "Manual input."],
        ["Beta", report.snapshot.beta or 1.0, "yfinance / manual override."],
        ["Specific Risk Premium", 0.0, "Manual input if analyst wants additional risk premium."],
        ["Cost of Equity", "=B5+B6*B7+B8", "Risk-free rate + beta × ERP + specific risk premium."],
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
    r = _section(ws, r, "WACC Build", 6)
    _headers(ws, r, ["Input", "Value", "Source / Formula"])
    rows = [
        ["Market Cap", "='Assumptions'!B76", "Source data."],
        ["Debt", "='Assumptions'!B71", "Opening debt."],
        ["Total Capital", "=B14+B15", "Market cap + debt."],
        ["Equity Weight", "=B14/B16", "Market cap / total capital."],
        ["Debt Weight", "=B15/B16", "Debt / total capital."],
        ["Pre-tax Cost of Debt", "=Assumptions!B58", "Selected scenario interest rate."],
        ["Tax Rate", "=Assumptions!B57", "Selected scenario tax rate."],
        ["After-tax Cost of Debt", "=B19*(1-B20)", "Pre-tax cost of debt × (1-tax rate)."],
        ["Selected Scenario WACC", "=Assumptions!B60", "Scenario-driven WACC from assumptions."],
        ["Calculated WACC", "=B17*B9+B18*B21", "Equity weight × cost of equity + debt weight × after-tax cost of debt."],
        ["WACC Used in DCF", "=B22", "Uses selected scenario WACC. Analyst can override to calculated WACC if desired."],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        if isinstance(row[1], str) and row[1].startswith("="):
            _link(ws.cell(i, 2), row[1])
        else:
            _input(ws.cell(i, 2), row[1], row[2])
        ws.cell(i, 3, row[2])
    for row in [14, 15, 16]:
        ws.cell(row, 2).number_format = NUM_FMT
    for row in [17, 18, 19, 20, 21, 22, 23, 24]:
        ws.cell(row, 2).number_format = PCT_FMT


def _create_dcf(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("DCF")
    _style_sheet(ws)
    _title(ws, "Discounted Cash Flow Valuation", 14)
    years = _forecast_years(report)
    r = 3
    r = _section(ws, r, "DCF Valuation", 12)
    _headers(ws, r, ["Metric"] + years + ["Terminal"])
    rows = ["Free Cash Flow", "Discount Factor", "PV of FCF", "Terminal Value", "PV of Terminal Value", "Enterprise Value", "Net Debt", "Equity Value", "Shares", "Target Price"]
    for i, label in enumerate(rows, start=r + 1):
        ws.cell(i, 1, label)

    forecast_start_col = 2 + len(_historical_years(report))
    for idx in range(FORECAST_YEARS):
        col = 2 + idx
        c = get_column_letter(col)
        model_col = get_column_letter(forecast_start_col + idx)
        _link(ws.cell(5, col), f"='3 Statement Model'!{model_col}44")
        _formula(ws.cell(6, col), f"=1/(1+WACC!$B$24)^{idx+1}")
        _formula(ws.cell(7, col), f"={c}5*{c}6")
    terminal_col = 2 + FORECAST_YEARS
    term = get_column_letter(terminal_col)
    last = get_column_letter(terminal_col - 1)
    _formula(ws.cell(8, terminal_col), f"={last}5*(1+Assumptions!I59)/(WACC!$B$24-Assumptions!I59)")
    _formula(ws.cell(9, terminal_col), f"={term}8/(1+WACC!$B$24)^{FORECAST_YEARS}")
    _formula(ws.cell(10, terminal_col), f"=SUM(B7:{last}7)+{term}9")
    _link(ws.cell(11, terminal_col), "='Assumptions'!B71-'Assumptions'!B65")
    _formula(ws.cell(12, terminal_col), f"={term}10-{term}11")
    _link(ws.cell(13, terminal_col), "='Assumptions'!B74")
    _formula(ws.cell(14, terminal_col), f"={term}12/{term}13")

    for row in range(5, 15):
        for col in range(2, terminal_col + 1):
            ws.cell(row, col).number_format = PRICE_FMT if row == 14 else NUM_FMT
    ws["A17"] = "Scenario Selected"
    _link(ws["B17"], "=Assumptions!B3")
    ws["A18"] = "DCF Weight"
    _link(ws["B18"], "=Assumptions!B4")
    ws["B18"].number_format = PCT_FMT


def _create_comps(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps Analysis")
    _style_sheet(ws)
    _title(ws, "Trading Comparables", 12)
    r = 3
    r = _section(ws, r, "Dynamic Peer Set", 12)
    _headers(ws, r, ["Company", "Ticker", "Market Cap", "Enterprise Value", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "Forward P/E", "Included?", "Source"])
    peer_rows = report.peer_comps.get("peer_table", []) if report.peer_comps else []
    start = r + 1
    end = start + max(min(len(peer_rows), 5), 1) - 1
    for idx in range(start, end + 1):
        peer = peer_rows[idx - start] if idx - start < len(peer_rows) else {}
        ws.cell(idx, 1, peer.get("company_name", "No peer selected"))
        ws.cell(idx, 2, peer.get("ticker", "n/a"))
        ws.cell(idx, 3, peer.get("market_cap"))
        ws.cell(idx, 4, peer.get("enterprise_value"))
        ws.cell(idx, 5, peer.get("revenue_ttm"))
        ws.cell(idx, 6, peer.get("ebitda"))
        _formula(ws.cell(idx, 7), f"=IFERROR(D{idx}/E{idx},\"n/a\")")
        _formula(ws.cell(idx, 8), f"=IFERROR(D{idx}/F{idx},\"n/a\")")
        ws.cell(idx, 9, peer.get("forward_pe"))
        ws.cell(idx, 10, "Yes" if peer else "No")
        ws.cell(idx, 11, "Dynamic yfinance peer selector" if peer else "n/a")
        for col in range(3, 7):
            ws.cell(idx, col).number_format = NUM_FMT
        for col in [7, 8, 9]:
            ws.cell(idx, col).number_format = MULT_FMT

    summary = end + 3
    summary = _section(ws, summary, "Comps Valuation", 8)
    _headers(ws, summary, ["Metric", "Value", "Formula / Source"])
    rows = [
        ["Median EV/EBITDA", f"=MEDIAN(H{start}:H{end})", "Median of dynamic peer set."],
        ["Subject EBITDA", "='3 Statement Model'!F9", "First forecast year EBITDA from 3-statement model."],
        ["Implied Enterprise Value", f"=B{summary+1}*B{summary+2}", "Median EV/EBITDA × subject EBITDA."],
        ["Less Net Debt", "='Assumptions'!B71-'Assumptions'!B65", "Debt less cash."],
        ["Implied Equity Value", f"=B{summary+3}-B{summary+4}", "EV - net debt."],
        ["Shares", "='Assumptions'!B74", "Shares outstanding."],
        ["Comps Target Price", f"=B{summary+5}/B{summary+6}", "Equity value / shares."],
        ["Comps Weight", "=Assumptions!B5", "Secondary valuation weight."],
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
    ws.cell(summary + 8, 2).number_format = PCT_FMT


def _create_football_field(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Football Field")
    _style_sheet(ws)
    _title(ws, "Football Field Valuation Summary", 10)
    r = 3
    r = _section(ws, r, "Valuation Range", 8)
    _headers(ws, r, ["Method", "Low", "Base", "High", "Weight", "Formula Source"])
    rows = [
        ["DCF", "=DCF!J14*0.90", "=DCF!J14", "=DCF!J14*1.10", "=Assumptions!B4", "DCF tab"],
        ["Comps", "='Comps Analysis'!B16*0.90", "='Comps Analysis'!B16", "='Comps Analysis'!B16*1.10", "=Assumptions!B5", "Comps Analysis tab"],
        ["Other / Current Market", "='Assumptions'!B75*0.95", "='Assumptions'!B75", "='Assumptions'!B75*1.05", "=Assumptions!B6", "Current market reference"],
        ["Weighted Target Price", "=SUMPRODUCT(B5:B7,E5:E7)/SUM(E5:E7)", "=SUMPRODUCT(C5:C7,E5:E7)/SUM(E5:E7)", "=SUMPRODUCT(D5:D7,E5:E7)/SUM(E5:E7)", "=SUM(E5:E7)", "DCF-led weighted target"],
    ]
    for i, row in enumerate(rows, start=r + 1):
        ws.cell(i, 1, row[0])
        for col_idx in range(2, 6):
            if isinstance(row[col_idx - 1], str) and row[col_idx - 1].startswith("="):
                _link(ws.cell(i, col_idx), row[col_idx - 1])
            else:
                _input(ws.cell(i, col_idx), row[col_idx - 1])
        ws.cell(i, 6, row[5])
    for row in range(5, 9):
        for col in [2, 3, 4]:
            ws.cell(row, col).number_format = PRICE_FMT
        ws.cell(row, 5).number_format = PCT_FMT

    chart = BarChart()
    chart.type = "bar"
    chart.title = "Valuation Range"
    data = Reference(ws, min_col=2, max_col=4, min_row=4, max_row=8)
    cats = Reference(ws, min_col=1, min_row=5, max_row=8)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height = 7
    chart.width = 14
    ws.add_chart(chart, "H4")


def _create_sensitivity(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Sensitivity Analysis")
    _style_sheet(ws)
    _title(ws, "DCF Sensitivity Analysis", 10)
    r = 3
    r = _section(ws, r, "WACC vs Terminal Growth", 8)
    ws.cell(r, 1, "WACC / TGR")
    wacc_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    tgr_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    for col_idx, delta in enumerate(tgr_deltas, start=2):
        _formula(ws.cell(r, col_idx), f"=Assumptions!I59+{delta}")
        ws.cell(r, col_idx).number_format = PCT_FMT
    for row_idx, delta in enumerate(wacc_deltas, start=r + 1):
        _formula(ws.cell(row_idx, 1), f"=WACC!$B$24+{delta}")
        ws.cell(row_idx, 1).number_format = PCT_FMT
        for col_idx, tg_delta in enumerate(tgr_deltas, start=2):
            if delta == 0 and tg_delta == 0:
                _link(ws.cell(row_idx, col_idx), "=DCF!J14")
                ws.cell(row_idx, col_idx).fill = PatternFill("solid", fgColor=YELLOW)
            else:
                _formula(ws.cell(row_idx, col_idx), f"=DCF!J14*(1+({tg_delta})*8-({delta})*10)")
            ws.cell(row_idx, col_idx).number_format = PRICE_FMT
    ws["A11"] = "Centre cell links to base selected-scenario DCF target price."


def _format_all(wb: Workbook) -> None:
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
        for col in range(1, min(ws.max_column, 16) + 1):
            width = ws.column_dimensions[get_column_letter(col)].width or 12
            if width < 12:
                ws.column_dimensions[get_column_letter(col)].width = 12


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    _create_assumptions(wb, report)
    _create_three_statement(wb, report)
    _create_wacc(wb, report)
    _create_dcf(wb, report)
    _create_comps(wb, report)
    _create_football_field(wb, report)
    _create_sensitivity(wb, report)
    _format_all(wb)

    path = output_dir / f"{report.snapshot.ticker.lower()}_{report.plan.report_type}_simplified_model.xlsx"
    wb.save(path)
    return str(path)
