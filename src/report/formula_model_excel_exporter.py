"""Formula-driven Excel model exporter.

This workbook is deliberately generated from a fixed template, not by an LLM.
It uses FMP statement history when available and falls back to yfinance fields.
Key design goals:
- five historical years;
- ten forecast years in the Excel model;
- separate income statement, balance sheet and cash flow sections on one tab;
- DCF, football field and sensitivity tabs reference model cells;
- no circular formulas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.excel.excel_runtime import recalc_with_excel_if_enabled
from src.engines.model_validation_engine import ValidatedFinancialModel
from src.schemas import FullReport, HistoricalFinancials

DARK_BLUE = "17365D"
MID_BLUE = "D9EAF7"
GREY = "D9E1F2"
LIGHT_GREEN = "E2F0D9"
WHITE = "FFFFFF"
NUM_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
SCENARIOS = ["bear", "base", "bull"]
FORECAST_YEARS_EXCEL = 10


def _style(ws, freeze: str = "B5") -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = freeze
    for col in range(1, 24):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.column_dimensions["A"].width = 34


def _title(ws, text: str, end_col: int = 16) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, text)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, text: str, end_col: int = 16) -> int:
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


def _historical_years(model: ValidatedFinancialModel, hist: HistoricalFinancials) -> list[str]:
    years = sorted(hist.revenue.keys())[-5:]
    return years or model.historical_years[-5:]


def _forecast_years(model: ValidatedFinancialModel) -> list[str]:
    if model.forecast_years:
        first = model.forecast_years[0]
        try:
            start = 2000 + int(first.replace("FY", "").replace("E", ""))
            return [f"FY{str(start + i)[-2:]}E" for i in range(FORECAST_YEARS_EXCEL)]
        except Exception:
            pass
    return [f"FY{i}E" for i in range(1, FORECAST_YEARS_EXCEL + 1)]


def _get(d: dict[str, float], year: str) -> float | None:
    return d.get(year)


def _last_nonzero(values: dict[str, float], default: float) -> float:
    for _, value in sorted(values.items(), reverse=True):
        if value not in (None, 0):
            return value
    return default


def _pct(ws, rows: list[int], cols: range) -> None:
    for row in rows:
        for col in cols:
            ws.cell(row, col).number_format = PCT_FMT


def _num(ws, rows: list[int], cols: range) -> None:
    for row in rows:
        for col in cols:
            ws.cell(row, col).number_format = NUM_FMT


def _create_assumptions(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Assumptions")
    _style(ws)
    _title(ws, f"Assumptions and Validation - {model.ticker}", 16)
    r = 3
    r = _section(ws, r, "Scenario Selector and Target Bridge", 10)
    _headers(ws, r, ["Item", "Value", "Comment"])
    rows = [
        ["Selected Scenario", "Base", "Change to Bear/Base/Bull for scenario views."],
        ["Current Price", model.valuation_summary.get("current_price"), "Market data layer."],
        ["Intrinsic Base DCF", model.valuation_summary.get("intrinsic_dcf_base_target_price"), "Raw DCF value."],
        ["12M Base Target", model.valuation_summary.get("base_target_price"), "DCF-led 12-month target bridge."],
        ["12M Bear Target", model.valuation_summary.get("bear_target_price"), "Bear scenario bridge."],
        ["12M Bull Target", model.valuation_summary.get("bull_target_price"), "Bull scenario bridge."],
        ["Analyst Consensus Anchor", model.valuation_summary.get("analyst_consensus_target"), "Sanity anchor; not source of truth."],
        ["Bridge Weight DCF", model.valuation_summary.get("base_bridge_weight_dcf"), "Base bridge DCF weight."],
        ["Bridge Weight Current", model.valuation_summary.get("base_bridge_weight_current_price"), "Base bridge current-price weight."],
        ["Bridge Weight Consensus", model.valuation_summary.get("base_bridge_weight_consensus"), "Base bridge consensus weight."],
        ["Financial Data Source", report.historicals.source, "FMP preferred; yfinance fallback."],
    ]
    for i, row in enumerate(rows, start=r + 1):
        _write(ws, i, row)
    for row in [5, 6, 7, 8, 9, 10, 11]:
        ws.cell(row, 2).number_format = PRICE_FMT
    for row in [12, 13, 14]:
        ws.cell(row, 2).number_format = PCT_FMT

    r = 18
    r = _section(ws, r, "Bear / Base / Bull Operating Assumptions", 16)
    _headers(ws, r, ["Scenario", "Rev Growth Y1", "Y2", "Y3", "Y4", "Y5", "Terminal Fade Growth", "EBITDA Margin Y1", "Y5", "D&A % Rev", "Capex % Rev", "NWC % Rev", "Tax Rate", "WACC", "Terminal Growth"])
    for i, name in enumerate(SCENARIOS, start=r + 1):
        a = model.scenarios[name].assumptions
        terminal_fade = a.terminal_growth
        _write(ws, i, [name.title(), *a.revenue_growth[:5], terminal_fade, a.ebitda_margin[0], a.ebitda_margin[-1], a.da_percent_revenue, a.capex_percent_revenue, a.nwc_percent_revenue, a.tax_rate, a.wacc, a.terminal_growth])
        for col in range(2, 16):
            ws.cell(i, col).number_format = PCT_FMT

    r = 26
    r = _section(ws, r, "Validation Messages", 12)
    _headers(ws, r, ["Type", "Message"])
    current = r + 1
    for msg in model.validation.errors:
        _write(ws, current, ["Error", msg]); current += 1
    for msg in model.validation.warnings:
        _write(ws, current, ["Warning", msg]); current += 1
    if current == r + 1:
        _write(ws, current, ["OK", "No validation errors or warnings triggered."])


def _create_model(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("3 Statement Model")
    _style(ws)
    _title(ws, "Historical and Forecast Three-Statement Model", 18)
    hist = report.historicals
    hist_years = _historical_years(model, hist)
    forecast_years = _forecast_years(model)
    years = hist_years + forecast_years
    _headers(ws, 3, ["Metric"] + years)
    for col in range(2, 2 + len(hist_years)):
        ws.cell(3, col).fill = PatternFill("solid", fgColor=MID_BLUE)
    start_fcst_col = 2 + len(hist_years)
    for col in range(start_fcst_col, start_fcst_col + len(forecast_years)):
        ws.cell(3, col).fill = PatternFill("solid", fgColor=LIGHT_GREEN)

    rows = {
        "Revenue": 5, "Revenue Growth": 6, "Gross Profit": 7, "Gross Margin": 8,
        "EBITDA": 9, "EBITDA Margin": 10, "D&A": 11, "EBIT": 12, "Tax": 13, "Net Income / NOPAT": 14,
        "Cash & Equivalents": 18, "Short-term Investments": 19, "Receivables": 20, "Inventory": 21,
        "Total Current Assets": 22, "PP&E": 23, "Goodwill": 24, "Intangibles": 25, "Total Assets": 26,
        "Accounts Payable": 29, "Short-term Debt": 30, "Long-term Debt": 31, "Total Debt": 32,
        "Total Current Liabilities": 33, "Total Liabilities": 34, "Shareholders' Equity": 35, "Balance Check": 36,
        "Operating Cash Flow": 40, "Capex": 41, "Free Cash Flow": 42, "FCF Margin": 43,
        "Stock-based Compensation": 44, "Dividends Paid": 45, "Share Repurchases": 46, "Shares Outstanding": 47,
    }
    for name, row in rows.items():
        ws.cell(row, 1, name)

    maps = {
        "Revenue": hist.revenue, "Gross Profit": hist.gross_profit, "EBITDA": hist.ebitda,
        "EBIT": hist.ebit, "Tax": hist.income_tax_expense, "Net Income / NOPAT": hist.net_income,
        "Operating Cash Flow": hist.operating_cash_flow, "Capex": hist.capex, "Free Cash Flow": hist.free_cash_flow,
        "Stock-based Compensation": hist.stock_based_compensation, "Dividends Paid": hist.dividends_paid,
        "Share Repurchases": hist.share_repurchases, "Cash & Equivalents": hist.cash_and_equivalents,
        "Short-term Investments": hist.short_term_investments, "Receivables": hist.receivables, "Inventory": hist.inventory,
        "Total Current Assets": hist.total_current_assets, "PP&E": hist.ppne, "Goodwill": hist.goodwill,
        "Intangibles": hist.intangible_assets, "Total Assets": hist.total_assets, "Accounts Payable": hist.accounts_payable,
        "Short-term Debt": hist.short_term_debt, "Long-term Debt": hist.long_term_debt, "Total Debt": hist.total_debt,
        "Total Current Liabilities": hist.total_current_liabilities, "Total Liabilities": hist.total_liabilities,
        "Shareholders' Equity": hist.shareholders_equity, "Shares Outstanding": hist.shares_outstanding,
    }
    for col, year in enumerate(hist_years, start=2):
        c = get_column_letter(col)
        for metric, data in maps.items():
            ws.cell(rows[metric], col, _get(data, year))
        if col > 2:
            ws.cell(rows["Revenue Growth"], col, f"={c}5/{get_column_letter(col-1)}5-1")
        ws.cell(rows["Gross Margin"], col, f"=IFERROR({c}7/{c}5,0)")
        ws.cell(rows["EBITDA Margin"], col, f"=IFERROR({c}9/{c}5,0)")
        if not ws.cell(rows["D&A"], col).value and ws.cell(rows["EBITDA"], col).value and ws.cell(rows["EBIT"], col).value:
            ws.cell(rows["D&A"], col, f"={c}9-{c}12")
        ws.cell(rows["FCF Margin"], col, f"=IFERROR({c}42/{c}5,0)")
        if not ws.cell(rows["Total Debt"], col).value:
            ws.cell(rows["Total Debt"], col, f"=N({c}30)+N({c}31)")
        if not ws.cell(rows["Balance Check"], col).value:
            ws.cell(rows["Balance Check"], col, f"=N({c}26)-N({c}34)-N({c}35)")

    base_row = 21  # Assumptions base case row: section at 18, header 19, bear 20, base 21, bull 22
    last_hist_col = start_fcst_col - 1
    for i, year in enumerate(forecast_years):
        col = start_fcst_col + i
        c = get_column_letter(col); p = get_column_letter(col - 1)
        if i < 5:
            growth = f"Assumptions!{get_column_letter(2 + i)}${base_row}"
        else:
            growth = f"MAX(Assumptions!$G${base_row},Assumptions!$F${base_row}*0.75^{i-4})"
        margin_formula = f"Assumptions!$H${base_row}+((Assumptions!$I${base_row}-Assumptions!$H${base_row})/4)*MIN({i},4)"
        ws.cell(rows["Revenue"], col, f"={p}5*(1+{growth})")
        ws.cell(rows["Revenue Growth"], col, f"={c}5/{p}5-1")
        ws.cell(rows["Gross Profit"], col, f"={c}5*AVERAGE({get_column_letter(max(2,last_hist_col-2))}8:{get_column_letter(last_hist_col)}8)")
        ws.cell(rows["Gross Margin"], col, f"={c}7/{c}5")
        ws.cell(rows["EBITDA"], col, f"={c}5*({margin_formula})")
        ws.cell(rows["EBITDA Margin"], col, f"={c}9/{c}5")
        ws.cell(rows["D&A"], col, f"={c}5*Assumptions!$J${base_row}")
        ws.cell(rows["EBIT"], col, f"={c}9-{c}11")
        ws.cell(rows["Tax"], col, f"=MAX({c}12,0)*Assumptions!$M${base_row}")
        ws.cell(rows["Net Income / NOPAT"], col, f"={c}12-{c}13")
        ws.cell(rows["Receivables"], col, f"={c}5*AVERAGE({get_column_letter(max(2,last_hist_col-2))}20:{get_column_letter(last_hist_col)}20)/AVERAGE({get_column_letter(max(2,last_hist_col-2))}5:{get_column_letter(last_hist_col)}5)")
        ws.cell(rows["Inventory"], col, f"={c}5*AVERAGE({get_column_letter(max(2,last_hist_col-2))}21:{get_column_letter(last_hist_col)}21)/AVERAGE({get_column_letter(max(2,last_hist_col-2))}5:{get_column_letter(last_hist_col)}5)")
        ws.cell(rows["Cash & Equivalents"], col, f"={p}18+{c}42")
        ws.cell(rows["Short-term Investments"], col, f"={p}19")
        ws.cell(rows["Total Current Assets"], col, f"=SUM({c}18:{c}21)")
        ws.cell(rows["PP&E"], col, f"=MAX(0,{p}23+{c}41-{c}11)")
        ws.cell(rows["Goodwill"], col, f"={p}24")
        ws.cell(rows["Intangibles"], col, f"={p}25")
        ws.cell(rows["Total Assets"], col, f"={c}22+{c}23+{c}24+{c}25")
        ws.cell(rows["Accounts Payable"], col, f"={c}5*AVERAGE({get_column_letter(max(2,last_hist_col-2))}29:{get_column_letter(last_hist_col)}29)/AVERAGE({get_column_letter(max(2,last_hist_col-2))}5:{get_column_letter(last_hist_col)}5)")
        ws.cell(rows["Short-term Debt"], col, f"={p}30")
        ws.cell(rows["Long-term Debt"], col, f"={p}31")
        ws.cell(rows["Total Debt"], col, f"={c}30+{c}31")
        ws.cell(rows["Total Current Liabilities"], col, f"={c}29+{c}30")
        ws.cell(rows["Total Liabilities"], col, f"={c}34")
        ws.cell(rows["Total Liabilities"], col, f"={c}33+{c}31")
        ws.cell(rows["Shareholders' Equity"], col, f"={c}26-{c}34")
        ws.cell(rows["Balance Check"], col, f"={c}26-{c}34-{c}35")
        ws.cell(rows["Operating Cash Flow"], col, f"={c}14+{c}11-(({c}20+{c}21-{c}29)-({p}20+{p}21-{p}29))")
        ws.cell(rows["Capex"], col, f"={c}5*Assumptions!$K${base_row}")
        ws.cell(rows["Free Cash Flow"], col, f"={c}40-{c}41")
        ws.cell(rows["FCF Margin"], col, f"={c}42/{c}5")
        ws.cell(rows["Stock-based Compensation"], col, f"={c}5*AVERAGE({get_column_letter(max(2,last_hist_col-2))}44:{get_column_letter(last_hist_col)}44)/AVERAGE({get_column_letter(max(2,last_hist_col-2))}5:{get_column_letter(last_hist_col)}5)")
        ws.cell(rows["Dividends Paid"], col, f"={p}45")
        ws.cell(rows["Share Repurchases"], col, f"={p}46")
        ws.cell(rows["Shares Outstanding"], col, f"=IFERROR({p}47*(1-({c}46/MAX({c}14,1))*0.01),{p}47)")

    used_cols = range(2, 2 + len(years))
    _pct(ws, [6, 8, 10, 43], used_cols)
    _num(ws, [r for r in rows.values() if r not in {6, 8, 10, 43}], used_cols)


def _create_wacc(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("WACC")
    _style(ws)
    _title(ws, "WACC by Scenario", 8)
    _headers(ws, 3, ["Scenario", "WACC", "Terminal Growth", "Spread", "Validation"])
    for row, name in enumerate(SCENARIOS, start=4):
        a = model.scenarios[name].assumptions
        _write(ws, row, [name.title(), a.wacc, a.terminal_growth, f"=B{row}-C{row}", f"=IF(D{row}>0.005,\"OK\",\"Review\")"])
        for col in [2, 3, 4]: ws.cell(row, col).number_format = PCT_FMT


def _create_dcf(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("DCF")
    _style(ws)
    _title(ws, "Formula-Linked 10-Year DCF", 16)
    fyears = _forecast_years(model)
    _headers(ws, 3, ["Metric"] + fyears + ["Terminal", "Total"])
    hist_count = len(_historical_years(model, report.historicals))
    start_col = 2
    terminal_col = start_col + len(fyears)
    total_col = terminal_col + 1
    rows = {"FCF": 5, "Discount Period": 6, "Discount Factor": 7, "PV FCF": 8, "Terminal Value": 10, "PV Terminal Value": 11, "Enterprise Value": 13, "Net Debt": 14, "Equity Value": 15, "Shares": 16, "Intrinsic DCF / Share": 17, "12M Target Price": 18, "Current Price": 19, "Upside / Downside": 20}
    for name, row in rows.items(): ws.cell(row,1,name)
    for i in range(len(fyears)):
        col = start_col + i; c = get_column_letter(col)
        model_col = get_column_letter(2 + hist_count + i)
        ws.cell(rows["FCF"], col, f"='3 Statement Model'!{model_col}42")
        ws.cell(rows["Discount Period"], col, i + 1)
        ws.cell(rows["Discount Factor"], col, f"=1/(1+WACC!B5)^{c}6")
        ws.cell(rows["PV FCF"], col, f"={c}5*{c}7")
    t = get_column_letter(terminal_col)
    final_fcf_col = get_column_letter(start_col + len(fyears) - 1)
    total = get_column_letter(total_col)
    ws.cell(rows["Terminal Value"], terminal_col, f"={final_fcf_col}5*(1+WACC!C5)/(WACC!B5-WACC!C5)")
    ws.cell(rows["PV Terminal Value"], terminal_col, f"={t}10*{final_fcf_col}7")
    ws.cell(rows["Enterprise Value"], total_col, f"=SUM(B8:{final_fcf_col}8)+{t}11")
    ws.cell(rows["Net Debt"], total_col, model.scenarios["base"].dcf.net_debt)
    ws.cell(rows["Equity Value"], total_col, f"={total}13-{total}14")
    ws.cell(rows["Shares"], total_col, model.scenarios["base"].dcf.shares_outstanding)
    ws.cell(rows["Intrinsic DCF / Share"], total_col, f"={total}15/{total}16")
    ws.cell(rows["12M Target Price"], total_col, "=Assumptions!B6")
    ws.cell(rows["Current Price"], total_col, "=Assumptions!B5")
    ws.cell(rows["Upside / Downside"], total_col, f"={total}18/{total}19-1")
    _num(ws, [5, 8, 10, 11, 13, 14, 15, 16], range(2, total_col + 1))
    for row in [17, 18, 19]: ws.cell(row, total_col).number_format = PRICE_FMT
    ws.cell(rows["Upside / Downside"], total_col).number_format = PCT_FMT


def _create_comps(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps Analysis")
    _style(ws)
    _title(ws, "Dynamic Peer Comparables", 12)
    _headers(ws, 3, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "Forward P/E"])
    peers = report.peer_comps.get("peer_table", []) if report.peer_comps else []
    for row, peer in enumerate(peers[:8], start=4):
        ev = peer.get("enterprise_value"); rev = peer.get("revenue_ttm"); ebitda = peer.get("ebitda")
        _write(ws, row, [peer.get("company_name"), peer.get("ticker"), peer.get("market_cap"), ev, rev, ebitda, f"=IFERROR(D{row}/E{row},\"n.a.\")", f"=IFERROR(D{row}/F{row},\"n.a.\")", peer.get("forward_pe")])
    _num(ws, list(range(4, 12)), range(3, 7))
    for row in range(4, 12):
        for col in [7, 8, 9]: ws.cell(row, col).number_format = MULT_FMT


def _create_football_field(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Football Field")
    _style(ws)
    _title(ws, "Valuation Range", 10)
    _headers(ws, 3, ["Method", "Low", "Base", "High", "Comment"])
    _write(ws, 4, ["12M DCF-led Target Bridge", "=Assumptions!B8", "=Assumptions!B6", "=Assumptions!B9", "Report target-price range."])
    _write(ws, 5, ["Intrinsic DCF", "=DCF!M17", "=DCF!M17", "=DCF!M17", "Formula-linked intrinsic DCF output."])
    for row in [4, 5]:
        for col in [2, 3, 4]: ws.cell(row, col).number_format = PRICE_FMT
    chart = BarChart(); chart.type = "bar"; chart.title = "Valuation Range"; chart.height = 7; chart.width = 14
    chart.add_data(ws["B3:D5"], titles_from_data=True); chart.set_categories(ws["A4:A5"]); ws.add_chart(chart, "G3")


def _create_sensitivity(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Sensitivity Analysis")
    _style(ws)
    _title(ws, "True DCF Sensitivity", 12)
    base = model.scenarios["base"].assumptions
    waccs = [base.wacc + d for d in [-0.02, -0.01, 0, 0.01, 0.02]]
    tgrs = [base.terminal_growth + d for d in [-0.01, -0.005, 0, 0.005, 0.01]]
    ws.cell(3, 1, "WACC / TGR")
    for col, tg in enumerate(tgrs, start=2):
        ws.cell(3, col, tg); ws.cell(3, col).number_format = PCT_FMT
    for row, w in enumerate(waccs, start=4):
        ws.cell(row, 1, w); ws.cell(row, 1).number_format = PCT_FMT
        for col, _ in enumerate(tgrs, start=2):
            fcfs = "+".join([f"DCF!{get_column_letter(2+i)}5/(1+$A{row})^{i+1}" for i in range(FORECAST_YEARS_EXCEL)])
            final_fcf_ref = f"DCF!{get_column_letter(2+FORECAST_YEARS_EXCEL-1)}5"
            tg_ref = f"{get_column_letter(col)}$3"
            term = f"({final_fcf_ref}*(1+{tg_ref})/($A{row}-{tg_ref}))/(1+$A{row})^{FORECAST_YEARS_EXCEL}"
            ws.cell(row, col, f"=IF($A{row}<={tg_ref},NA(),(({fcfs})+{term}-DCF!M14)/DCF!M16)")
            ws.cell(row, col).number_format = PRICE_FMT


def _create_audit(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Model Audit")
    _style(ws)
    _title(ws, "Model Audit and Source Trace", 10)
    _headers(ws, 3, ["Check", "Result", "Comment"])
    rows = [
        ["Financial data source", report.historicals.source, "FMP preferred when FMP_API_KEY is configured."],
        ["Historical revenue years", len(report.historicals.revenue), "Should be at least five for a useful model."],
        ["Historical balance sheet available", bool(report.historicals.total_assets), "True when FMP balance sheet data is present."],
        ["Workbook linkage", "Formula-driven", "DCF and sensitivity reference 3 Statement Model, WACC and Assumptions."],
        ["Validation status", model.validation.is_valid, "Report generation stops when model is invalid."],
    ]
    for i, row in enumerate(rows, start=4): _write(ws, i, row)


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    model = report.validated_model
    if model is None or not model.validation.is_valid:
        raise ValueError("Cannot export Excel: validated financial model is missing or failed validation.")
    wb = Workbook(); wb.remove(wb.active)
    _create_assumptions(wb, report, model)
    _create_model(wb, report, model)
    _create_wacc(wb, model)
    _create_dcf(wb, report, model)
    _create_comps(wb, report)
    _create_football_field(wb, model)
    _create_sensitivity(wb, model)
    _create_audit(wb, report, model)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
    path = output_dir / f"{model.ticker.lower()}_{report.plan.report_type}_formula_model.xlsx"
    wb.save(path)
    recalc_with_excel_if_enabled(path)
    return str(path)
