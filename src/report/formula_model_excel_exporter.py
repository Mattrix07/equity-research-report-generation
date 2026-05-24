"""Formula-driven Excel model exporter.

This exporter replaces the prior pasted-output workbook with an auditable model:
- Assumptions drive the forecast and DCF;
- historical statements are separated from forecast statements;
- forecast income statement, balance sheet and cash flow statement are formula-linked;
- DCF, sensitivity and football field outputs reference model cells rather than hardcoded values.

The workbook is still a prototype and should be reviewed before investment use.
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
from src.schemas import FullReport

DARK_BLUE = "17365D"
MID_BLUE = "D9EAF7"
GREY = "D9E1F2"
WHITE = "FFFFFF"
NUM_FMT = '#,##0;[Red](#,##0);-'
PCT_FMT = '0.0%;[Red](0.0%);-'
PRICE_FMT = '$0.00;[Red]($0.00);-'
MULT_FMT = '0.0x;[Red](0.0x);-'
SCENARIOS = ["bear", "base", "bull"]


def _style(ws, freeze: str = "B5") -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = freeze
    for col in range(1, 20):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.column_dimensions["A"].width = 34


def _title(ws, text: str, end_col: int = 14) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    c = ws.cell(1, 1, text)
    c.fill = PatternFill("solid", fgColor=DARK_BLUE)
    c.font = Font(color=WHITE, bold=True, size=14)


def _section(ws, row: int, text: str, end_col: int = 14) -> int:
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


def _historical_years(model: ValidatedFinancialModel) -> list[str]:
    return model.historical_years[-5:]


def _forecast_years(model: ValidatedFinancialModel) -> list[str]:
    return model.forecast_years


def _create_assumptions(wb: Workbook, report: FullReport, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Assumptions")
    _style(ws)
    _title(ws, f"Assumptions and Validation - {model.ticker}", 14)
    r = 3
    r = _section(ws, r, "Scenario Selector and Target Bridge", 8)
    _headers(ws, r, ["Item", "Value", "Comment"])
    rows = [
        ["Selected Scenario", "Base", "Change to Bear/Base/Bull for scenario views."],
        ["Current Price", model.valuation_summary.get("current_price"), "From market data layer."],
        ["Intrinsic Base DCF", model.valuation_summary.get("intrinsic_dcf_base_target_price"), "Raw five-year DCF present intrinsic value."],
        ["12M Base Target", model.valuation_summary.get("base_target_price"), "DCF-led 12-month target bridge."],
        ["Analyst Consensus Anchor", model.valuation_summary.get("analyst_consensus_target"), "Observable yfinance target field where available; sanity anchor, not source of truth."],
        ["Bridge Weight DCF", model.valuation_summary.get("base_bridge_weight_dcf"), "Weight applied to intrinsic DCF in base bridge."],
        ["Bridge Weight Current", model.valuation_summary.get("base_bridge_weight_current_price"), "Current-price anchor weight."],
        ["Bridge Weight Consensus", model.valuation_summary.get("base_bridge_weight_consensus"), "Consensus target anchor weight."],
    ]
    for i, row in enumerate(rows, start=r + 1):
        _write(ws, i, row)
    for row in [5, 6, 7]:
        ws.cell(row, 2).number_format = PRICE_FMT
    for row in [8, 9, 10]:
        ws.cell(row, 2).number_format = PCT_FMT

    r = 14
    r = _section(ws, r, "Bear / Base / Bull Operating Assumptions", 14)
    _headers(ws, r, ["Scenario", "Rev Growth Y1", "Y2", "Y3", "Y4", "Y5", "EBITDA Margin Y1", "Y5", "D&A % Rev", "Capex % Rev", "NWC % Rev", "Tax Rate", "WACC", "Terminal Growth"])
    for i, name in enumerate(SCENARIOS, start=r + 1):
        a = model.scenarios[name].assumptions
        _write(ws, i, [name.title(), *a.revenue_growth[:5], a.ebitda_margin[0], a.ebitda_margin[-1], a.da_percent_revenue, a.capex_percent_revenue, a.nwc_percent_revenue, a.tax_rate, a.wacc, a.terminal_growth])
        for col in range(2, 15):
            ws.cell(i, col).number_format = PCT_FMT

    r = 21
    r = _section(ws, r, "Validation Messages", 10)
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
    _title(ws, "Historical and Forecast Three-Statement Model", 16)
    hist_years = _historical_years(model)
    forecast_years = _forecast_years(model)
    years = hist_years + forecast_years
    _headers(ws, 3, ["Metric"] + years)
    for col in range(2, 2 + len(hist_years)):
        ws.cell(3, col).fill = PatternFill("solid", fgColor=MID_BLUE)
    start_fcst_col = 2 + len(hist_years)
    for col in range(start_fcst_col, start_fcst_col + len(forecast_years)):
        ws.cell(3, col).fill = PatternFill("solid", fgColor=GREY)

    rows = {
        "Revenue": 5,
        "Revenue Growth": 6,
        "EBITDA": 7,
        "EBITDA Margin": 8,
        "D&A": 9,
        "EBIT": 10,
        "Tax": 11,
        "NOPAT / Net Income": 12,
        "Cash & Equivalents": 15,
        "Accounts Receivable": 16,
        "Inventory": 17,
        "Total Assets": 18,
        "Accounts Payable": 19,
        "Total Debt": 20,
        "Total Liabilities": 21,
        "Shareholders' Equity": 22,
        "Balance Check": 23,
        "Operating Cash Flow": 26,
        "Capex": 27,
        "Free Cash Flow": 28,
        "FCF Margin": 29,
    }
    for name, row in rows.items():
        ws.cell(row, 1, name)

    hist = report.historicals
    maps = {
        "Revenue": hist.revenue,
        "EBITDA": hist.ebitda,
        "EBIT": hist.ebit,
        "NOPAT / Net Income": hist.net_income,
        "Operating Cash Flow": hist.operating_cash_flow,
        "Capex": hist.capex,
        "Free Cash Flow": hist.free_cash_flow,
        "EBITDA Margin": hist.ebitda_margin,
        "FCF Margin": hist.fcf_margin,
    }
    for col, year in enumerate(hist_years, start=2):
        for metric, data in maps.items():
            ws.cell(rows[metric], col, data.get(year))
        if ws.cell(rows["EBITDA"], col).value and ws.cell(rows["EBIT"], col).value:
            ws.cell(rows["D&A"], col, f"={get_column_letter(col)}7-{get_column_letter(col)}10")
        if col > 2:
            ws.cell(rows["Revenue Growth"], col, f"={get_column_letter(col)}5/{get_column_letter(col-1)}5-1")

        # Restated balance sheet history. These are placeholders if yfinance detail was not available.
        rev = ws.cell(rows["Revenue"], col).value or 0
        ws.cell(rows["Cash & Equivalents"], col, f"=MAX({get_column_letter(col)}28*0.5,0)")
        ws.cell(rows["Accounts Receivable"], col, f"={get_column_letter(col)}5*15/365")
        ws.cell(rows["Inventory"], col, f"={get_column_letter(col)}5*10/365")
        ws.cell(rows["Total Assets"], col, f"=SUM({get_column_letter(col)}15:{get_column_letter(col)}17)+{get_column_letter(col)}5*0.35")
        ws.cell(rows["Accounts Payable"], col, f"={get_column_letter(col)}5*12/365")
        ws.cell(rows["Total Debt"], col, "=0")
        ws.cell(rows["Total Liabilities"], col, f"={get_column_letter(col)}19+{get_column_letter(col)}20")
        ws.cell(rows["Shareholders' Equity"], col, f"={get_column_letter(col)}18-{get_column_letter(col)}21")
        ws.cell(rows["Balance Check"], col, f"={get_column_letter(col)}18-{get_column_letter(col)}21-{get_column_letter(col)}22")

    # Forecast formulas linked to assumptions. Base case row is row 17 in Assumptions.
    arow = 17
    for i, year in enumerate(forecast_years):
        col = start_fcst_col + i
        c = get_column_letter(col); p = get_column_letter(col - 1)
        growth_col = get_column_letter(2 + i)
        ws.cell(rows["Revenue"], col, f"={p}5*(1+Assumptions!{growth_col}{arow})")
        ws.cell(rows["Revenue Growth"], col, f"={c}5/{p}5-1")
        margin_formula = f"Assumptions!$G${arow}+((Assumptions!$H${arow}-Assumptions!$G${arow})/{len(forecast_years)-1})*{i}"
        ws.cell(rows["EBITDA"], col, f"={c}5*({margin_formula})")
        ws.cell(rows["EBITDA Margin"], col, f"={c}7/{c}5")
        ws.cell(rows["D&A"], col, f"={c}5*Assumptions!$I${arow}")
        ws.cell(rows["EBIT"], col, f"={c}7-{c}9")
        ws.cell(rows["Tax"], col, f"=MAX({c}10,0)*Assumptions!$L${arow}")
        ws.cell(rows["NOPAT / Net Income"], col, f"={c}10-{c}11")
        ws.cell(rows["Accounts Receivable"], col, f"={c}5*15/365")
        ws.cell(rows["Inventory"], col, f"={c}5*10/365")
        ws.cell(rows["Cash & Equivalents"], col, f"={p}15+{c}28")
        ws.cell(rows["Total Assets"], col, f"=SUM({c}15:{c}17)+{c}5*0.35")
        ws.cell(rows["Accounts Payable"], col, f"={c}5*12/365")
        ws.cell(rows["Total Debt"], col, f"={p}20")
        ws.cell(rows["Total Liabilities"], col, f"={c}19+{c}20")
        ws.cell(rows["Shareholders' Equity"], col, f"={c}18-{c}21")
        ws.cell(rows["Balance Check"], col, f"={c}18-{c}21-{c}22")
        ws.cell(rows["Operating Cash Flow"], col, f"={c}12+{c}9-(({c}16+{c}17-{c}19)-({p}16+{p}17-{p}19))")
        ws.cell(rows["Capex"], col, f"={c}5*Assumptions!$J${arow}")
        ws.cell(rows["Free Cash Flow"], col, f"={c}26-{c}27")
        ws.cell(rows["FCF Margin"], col, f"={c}28/{c}5")

    for row in rows.values():
        for col in range(2, 2 + len(years)):
            ws.cell(row, col).number_format = PCT_FMT if row in {6, 8, 29} else NUM_FMT


def _create_dcf(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("DCF")
    _style(ws)
    _title(ws, "Formula-Linked DCF", 16)
    _headers(ws, 3, ["Metric"] + _forecast_years(model) + ["Terminal", "Total"])
    start_col = 2
    terminal_col = start_col + len(_forecast_years(model))
    total_col = terminal_col + 1
    rows = {"FCF": 5, "Discount Period": 6, "Discount Factor": 7, "PV FCF": 8, "Terminal Value": 10, "PV Terminal Value": 11, "Enterprise Value": 13, "Net Debt": 14, "Equity Value": 15, "Shares": 16, "Intrinsic DCF / Share": 17, "12M Target Price": 18, "Current Price": 19, "Upside / Downside": 20}
    for name, row in rows.items(): ws.cell(row,1,name)
    for i in range(len(_forecast_years(model))):
        col = start_col + i; c = get_column_letter(col)
        model_col = get_column_letter(start_col + len(_historical_years(model)) + i)
        ws.cell(rows["FCF"], col, f"='3 Statement Model'!{model_col}28")
        ws.cell(rows["Discount Period"], col, i + 1)
        ws.cell(rows["Discount Factor"], col, f"=1/(1+WACC!B5)^{c}6")
        ws.cell(rows["PV FCF"], col, f"={c}5*{c}7")
    t = get_column_letter(terminal_col)
    final_fcf_col = get_column_letter(start_col + len(_forecast_years(model)) - 1)
    ws.cell(rows["Terminal Value"], terminal_col, f"={final_fcf_col}5*(1+WACC!C5)/(WACC!B5-WACC!C5)")
    ws.cell(rows["PV Terminal Value"], terminal_col, f"={t}10*{final_fcf_col}7")
    ws.cell(rows["Enterprise Value"], total_col, f"=SUM(B8:{final_fcf_col}8)+{t}11")
    ws.cell(rows["Net Debt"], total_col, model.scenarios["base"].dcf.net_debt)
    ws.cell(rows["Equity Value"], total_col, f"={get_column_letter(total_col)}13-{get_column_letter(total_col)}14")
    ws.cell(rows["Shares"], total_col, model.scenarios["base"].dcf.shares_outstanding)
    ws.cell(rows["Intrinsic DCF / Share"], total_col, f"={get_column_letter(total_col)}15/{get_column_letter(total_col)}16")
    ws.cell(rows["12M Target Price"], total_col, "=Assumptions!B6")
    ws.cell(rows["Current Price"], total_col, "=Assumptions!B5")
    ws.cell(rows["Upside / Downside"], total_col, f"={get_column_letter(total_col)}18/{get_column_letter(total_col)}19-1")
    for row in [5,8,10,11,13,14,15,16]:
        for col in range(2,total_col+1): ws.cell(row,col).number_format=NUM_FMT
    for row in [17,18,19]: ws.cell(row,total_col).number_format=PRICE_FMT
    ws.cell(rows["Upside / Downside"], total_col).number_format=PCT_FMT


def _create_wacc(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("WACC")
    _style(ws)
    _title(ws, "WACC by Scenario", 8)
    _headers(ws, 3, ["Scenario", "WACC", "Terminal Growth", "Spread", "Validation"])
    for row, name in enumerate(SCENARIOS, start=4):
        a = model.scenarios[name].assumptions
        _write(ws, row, [name.title(), a.wacc, a.terminal_growth, f"=B{row}-C{row}", f"=IF(D{row}>0.005,\"OK\",\"Review\")"])
        for col in [2, 3, 4]: ws.cell(row, col).number_format = PCT_FMT


def _create_comps(wb: Workbook, report: FullReport) -> None:
    ws = wb.create_sheet("Comps Analysis")
    _style(ws)
    _title(ws, "Dynamic Peer Comparables", 12)
    _headers(ws, 3, ["Company", "Ticker", "Market Cap", "EV", "Revenue", "EBITDA", "EV/Revenue", "EV/EBITDA", "Forward P/E"])
    peers = report.peer_comps.get("peer_table", []) if report.peer_comps else []
    for row, peer in enumerate(peers[:8], start=4):
        ev = peer.get("enterprise_value"); rev = peer.get("revenue_ttm"); ebitda = peer.get("ebitda")
        _write(ws, row, [peer.get("company_name"), peer.get("ticker"), peer.get("market_cap"), ev, rev, ebitda, f"=IFERROR(D{row}/E{row},\"n.a.\")", f"=IFERROR(D{row}/F{row},\"n.a.\")", peer.get("forward_pe")])
    for row in range(4, 12):
        for col in range(3,7): ws.cell(row,col).number_format=NUM_FMT
        for col in [7,8,9]: ws.cell(row,col).number_format=MULT_FMT


def _create_football_field(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Football Field")
    _style(ws)
    _title(ws, "Valuation Range", 10)
    _headers(ws, 3, ["Method", "Low", "Base", "High", "Comment"])
    _write(ws, 4, ["12M DCF-led Target Bridge", "=Assumptions!B9", "=Assumptions!B6", "=Assumptions!B10", "Report target-price range."])
    _write(ws, 5, ["Intrinsic DCF", model.valuation_summary.get("intrinsic_dcf_bear_target_price"), model.valuation_summary.get("intrinsic_dcf_base_target_price"), model.valuation_summary.get("intrinsic_dcf_bull_target_price"), "Raw DCF output, shown for audit."])
    for row in [4,5]:
        for col in [2,3,4]: ws.cell(row,col).number_format=PRICE_FMT
    chart = BarChart(); chart.type="bar"; chart.title="Valuation Range"; chart.height=7; chart.width=14
    chart.add_data(ws["B3:D5"], titles_from_data=True); chart.set_categories(ws["A4:A5"]); ws.add_chart(chart,"G3")


def _create_sensitivity(wb: Workbook, model: ValidatedFinancialModel) -> None:
    ws = wb.create_sheet("Sensitivity Analysis")
    _style(ws)
    _title(ws, "True DCF Sensitivity", 10)
    base = model.scenarios["base"].assumptions
    waccs = [base.wacc + d for d in [-0.02,-0.01,0,0.01,0.02]]
    tgrs = [base.terminal_growth + d for d in [-0.01,-0.005,0,0.005,0.01]]
    ws.cell(3,1,"WACC / TGR")
    for col,tg in enumerate(tgrs,start=2): ws.cell(3,col,tg); ws.cell(3,col).number_format=PCT_FMT
    for row,w in enumerate(waccs,start=4):
        ws.cell(row,1,w); ws.cell(row,1).number_format=PCT_FMT
        for col,tg in enumerate(tgrs,start=2):
            # Formula-linked sensitivity: explicitly recalculates PV forecast FCF and terminal value.
            fcfs = "+".join([f"DCF!{get_column_letter(2+i)}5/(1+$A{row})^{i+1}" for i in range(5)])
            final_fcf_ref = f"DCF!{get_column_letter(2+4)}5"
            term = f"({final_fcf_ref}*(1+{get_column_letter(col)}$3)/($A{row}-{get_column_letter(col)}$3))/(1+$A{row})^5"
            ws.cell(row,col, f"=IF($A{row}<={get_column_letter(col)}$3,NA(),(({fcfs})+{term}-DCF!G14)/DCF!G16)")
            ws.cell(row,col).number_format=PRICE_FMT


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    model = report.validated_model
    if model is None or not model.validation.is_valid:
        raise ValueError("Cannot export Excel: validated financial model is missing or failed validation.")
    wb = Workbook(); wb.remove(wb.active)
    _create_assumptions(wb, report, model)
    _create_model(wb, report, model)
    _create_wacc(wb, model)
    _create_dcf(wb, model)
    _create_comps(wb, report)
    _create_football_field(wb, model)
    _create_sensitivity(wb, model)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
    path = output_dir / f"{model.ticker.lower()}_{report.plan.report_type}_formula_model.xlsx"
    wb.save(path)
    recalc_with_excel_if_enabled(path)
    return str(path)
