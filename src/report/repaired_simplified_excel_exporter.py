"""Repaired simplified Excel exporter.

Keeps the seven-tab simplified workbook, then fixes the model formulas before the
file is returned. This addresses the generated workbook issues observed in the
AMGN model: off-by-one assumption links, incorrect opening balance-sheet links,
circular debt/debt-repayment formulas, DCF linking to ending cash instead of FCF,
and football-field/comps links pointing to the wrong cells.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from src.report.simplified_excel_exporter import export_excel_model as export_base_model
from src.schemas import FullReport

FORECAST_YEARS = 8


def _historical_years(report: FullReport) -> list[str]:
    years = sorted(report.historicals.revenue.keys())[-5:]
    return years or ["Hist-4", "Hist-3", "Hist-2", "Hist-1", "Hist"]


def _f(ws, cell: str, formula: str) -> None:
    ws[cell] = formula
    ws[cell].data_type = "f"


def _patch_assumptions(wb) -> None:
    ws = wb["Assumptions"]
    # Active assumption rows are 50:61. Scenario table rows are 11:46.
    # Use SUMIFS to avoid array-style MATCH formulas that can fail in Excel.
    for row in range(50, 62):
        for out_col, source_col in zip("BCDEFGHI", "CDEFGHIJ"):
            _f(ws, f"{out_col}{row}", f'=SUMIFS({source_col}$11:{source_col}$46,$A$11:$A$46,$B$3,$B$11:$B$46,$A{row})')


def _patch_three_statement(wb, report: FullReport) -> None:
    ws = wb["3 Statement Model"]
    hist_count = len(_historical_years(report))
    forecast_start_col = 2 + hist_count
    forecast_cols = [get_column_letter(forecast_start_col + i) for i in range(FORECAST_YEARS)]
    active_cols = [get_column_letter(2 + i) for i in range(FORECAST_YEARS)]

    # Opening BS rows in Assumptions:
    # 67 cash, 68 AR, 69 inventory, 70 PPE, 71 other assets,
    # 72 AP, 73 debt, 74 other liabilities, 75 equity.
    cash = "'Assumptions'!$B$67"
    ar = "'Assumptions'!$B$68"
    inventory = "'Assumptions'!$B$69"
    ppe = "'Assumptions'!$B$70"
    other_assets = "'Assumptions'!$B$71"
    ap = "'Assumptions'!$B$72"
    debt = "'Assumptions'!$B$73"
    other_liabilities = "'Assumptions'!$B$74"
    equity = "'Assumptions'!$B$75"

    ws["A41"] = "Debt Issuance / (Repayment)"
    ws["A42"] = "Dividends / Buybacks"
    ws["A43"] = "Net Change in Cash"
    ws["A44"] = "Ending Cash"
    ws["A45"] = "Free Cash Flow"

    for i, (col, active_col) in enumerate(zip(forecast_cols, active_cols)):
        prev = get_column_letter(forecast_start_col - 1) if i == 0 else forecast_cols[i - 1]
        first = i == 0

        # Active assumption rows: 50 rev growth, 51 gross margin, 52 EBITDA margin,
        # 53 D&A, 54 capex, 55 DSO, 56 inventory days, 57 DPO,
        # 58 tax, 59 interest rate, 60 terminal growth, 61 WACC.
        _f(ws, f"{col}5", f"={prev}5*(1+'Assumptions'!{active_col}$50)")
        _f(ws, f"{col}6", f"={col}5/{prev}5-1")
        _f(ws, f"{col}7", f"={col}5*'Assumptions'!{active_col}$51")
        _f(ws, f"{col}8", f"={col}7/{col}5")
        _f(ws, f"{col}9", f"={col}5*'Assumptions'!{active_col}$52")
        _f(ws, f"{col}10", f"={col}9/{col}5")
        _f(ws, f"{col}11", f"={col}5*'Assumptions'!{active_col}$53")
        _f(ws, f"{col}12", f"={col}9-{col}11")
        _f(ws, f"{col}13", f"=AVERAGE({debt if first else prev+'26'},{col}26)*'Assumptions'!{active_col}$59")
        _f(ws, f"{col}14", f"={col}12-{col}13")
        _f(ws, f"{col}15", f"=MAX({col}14,0)*'Assumptions'!{active_col}$58")
        _f(ws, f"{col}16", f"={col}14-{col}15")

        _f(ws, f"{col}19", f"={col}44")
        _f(ws, f"{col}20", f"={col}5*'Assumptions'!{active_col}$55/365")
        _f(ws, f"{col}21", f"=({col}5-{col}7)*'Assumptions'!{active_col}$56/365")
        _f(ws, f"{col}22", f"={ppe if first else prev+'22'}-{col}40-{col}11")
        _f(ws, f"{col}23", f"={other_assets if first else prev+'23'}")
        _f(ws, f"{col}24", f"=SUM({col}19:{col}23)")
        _f(ws, f"{col}25", f"=({col}5-{col}7)*'Assumptions'!{active_col}$57/365")
        _f(ws, f"{col}26", f"={debt if first else prev+'26'}")
        _f(ws, f"{col}27", f"={other_liabilities if first else prev+'27'}")
        _f(ws, f"{col}28", f"=SUM({col}25:{col}27)")
        _f(ws, f"{col}29", f"={equity if first else prev+'29'}+{col}16+{col}42")
        _f(ws, f"{col}30", f"={col}28+{col}29")
        _f(ws, f"{col}31", f"={col}24-{col}30")

        _f(ws, f"{col}37", f"={col}16")
        _f(ws, f"{col}38", f"={col}11")
        if first:
            _f(ws, f"{col}39", f"=({col}20+{col}21-{col}25)-({ar}+{inventory}-{ap})")
            _f(ws, f"{col}44", f"={cash}+{col}43")
        else:
            _f(ws, f"{col}39", f"=({col}20+{col}21-{col}25)-({prev}20+{prev}21-{prev}25)")
            _f(ws, f"{col}44", f"={prev}44+{col}43")
        _f(ws, f"{col}40", f"=-{col}5*'Assumptions'!{active_col}$54")
        ws[f"{col}41"] = 0
        ws[f"{col}42"] = 0
        _f(ws, f"{col}43", f"={col}37+{col}38-{col}39+{col}40+{col}41+{col}42")
        _f(ws, f"{col}45", f"={col}37+{col}38-{col}39+{col}40")


def _patch_wacc(wb) -> None:
    ws = wb["WACC"]
    _f(ws, "B14", "='Assumptions'!B78")
    _f(ws, "B15", "='Assumptions'!B73")
    _f(ws, "B16", "=B14+B15")
    _f(ws, "B17", "=B14/B16")
    _f(ws, "B18", "=B15/B16")
    _f(ws, "B19", "='Assumptions'!B59")
    _f(ws, "B20", "='Assumptions'!B58")
    _f(ws, "B21", "=B19*(1-B20)")
    _f(ws, "B22", "='Assumptions'!B61")
    _f(ws, "B23", "=B17*B9+B18*B21")
    _f(ws, "B24", "=B22")


def _patch_dcf(wb, report: FullReport) -> None:
    ws = wb["DCF"]
    hist_count = len(_historical_years(report))
    forecast_start_col = 2 + hist_count
    for i in range(FORECAST_YEARS):
        dcf_col = get_column_letter(2 + i)
        model_col = get_column_letter(forecast_start_col + i)
        _f(ws, f"{dcf_col}5", f"='3 Statement Model'!{model_col}45")
        _f(ws, f"{dcf_col}6", f"=1/(1+WACC!$B$24)^{i + 1}")
        _f(ws, f"{dcf_col}7", f"={dcf_col}5*{dcf_col}6")
    _f(ws, "J8", "=I5*(1+'Assumptions'!I60)/(WACC!$B$24-'Assumptions'!I60)")
    _f(ws, "J9", "=J8/(1+WACC!$B$24)^8")
    _f(ws, "J10", "=SUM(B7:I7)+J9")
    _f(ws, "J11", "='Assumptions'!B73-'Assumptions'!B67")
    _f(ws, "J12", "=J10-J11")
    _f(ws, "J13", "='Assumptions'!B76")
    _f(ws, "J14", "=J12/J13")


def _patch_comps_and_outputs(wb) -> None:
    ws = wb["Comps Analysis"]
    _f(ws, "B17", "='Assumptions'!B73-'Assumptions'!B67")
    _f(ws, "B19", "='Assumptions'!B76")
    _f(ws, "B20", "=B18/B19")
    _f(ws, "B21", "='Assumptions'!B5")

    ff = wb["Football Field"]
    _f(ff, "B5", "=DCF!J14*0.90")
    _f(ff, "C5", "=DCF!J14")
    _f(ff, "D5", "=DCF!J14*1.10")
    _f(ff, "E5", "='Assumptions'!B4")
    _f(ff, "B6", "='Comps Analysis'!B20*0.90")
    _f(ff, "C6", "='Comps Analysis'!B20")
    _f(ff, "D6", "='Comps Analysis'!B20*1.10")
    _f(ff, "E6", "='Assumptions'!B5")
    _f(ff, "B7", "='Assumptions'!B77*0.95")
    _f(ff, "C7", "='Assumptions'!B77")
    _f(ff, "D7", "='Assumptions'!B77*1.05")
    _f(ff, "E7", "='Assumptions'!B6")
    _f(ff, "B8", "=SUMPRODUCT(B5:B7,E5:E7)/SUM(E5:E7)")
    _f(ff, "C8", "=SUMPRODUCT(C5:C7,E5:E7)/SUM(E5:E7)")
    _f(ff, "D8", "=SUMPRODUCT(D5:D7,E5:E7)/SUM(E5:E7)")
    _f(ff, "E8", "=SUM(E5:E7)")

    sens = wb["Sensitivity Analysis"]
    tgr_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    wacc_deltas = [-0.01, -0.005, 0.0, 0.005, 0.01]
    for col_idx, tgr_delta in enumerate(tgr_deltas, start=2):
        col = get_column_letter(col_idx)
        _f(sens, f"{col}4", f"='Assumptions'!I60+{tgr_delta}")
    for row_idx, wacc_delta in enumerate(wacc_deltas, start=5):
        _f(sens, f"A{row_idx}", f"=WACC!$B$24+{wacc_delta}")
        for col_idx, tgr_delta in enumerate(tgr_deltas, start=2):
            col = get_column_letter(col_idx)
            if wacc_delta == 0 and tgr_delta == 0:
                _f(sens, f"{col}{row_idx}", "=DCF!J14")
            else:
                _f(sens, f"{col}{row_idx}", f"=DCF!J14*(1+({tgr_delta})*8-({wacc_delta})*10)")


def _assert_no_stale_references(wb) -> None:
    stale_fragments = ["B$49", "$B$65", "B65", "B71-'Assumptions'!B65", "B74"]
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    if "Assumptions" in value and any(fragment in value for fragment in stale_fragments):
                        raise ValueError(f"Stale formula reference in {ws.title}!{cell.coordinate}: {value}")


def export_excel_model(report: FullReport, output_dir: Path) -> str:
    path = export_base_model(report, output_dir)
    wb = load_workbook(path)

    _patch_assumptions(wb)
    _patch_three_statement(wb, report)
    _patch_wacc(wb)
    _patch_dcf(wb, report)
    _patch_comps_and_outputs(wb)
    _assert_no_stale_references(wb)

    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"

    wb.save(path)
    return str(path)
