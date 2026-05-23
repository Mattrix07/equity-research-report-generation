"""Sensitivity analysis engine."""
from __future__ import annotations

from copy import deepcopy

from src.engines.dcf_engine import run_dcf
from src.engines.forecast_engine import run_forecast
from src.schemas import ForecastRow, HistoricalFinancials, ScenarioAssumptions, SensitivityTable


def wacc_terminal_growth_sensitivity(
    base_forecast: list[ForecastRow],
    assumptions: ScenarioAssumptions,
    net_debt: float,
    shares_outstanding: float | None,
) -> SensitivityTable:
    waccs = [0.075, 0.085, 0.095, 0.105, 0.115]
    terminal_growths = [0.01, 0.02, 0.025, 0.03, 0.04]
    values: list[list[float | None]] = []
    for wacc in waccs:
        row_values: list[float | None] = []
        for tg in terminal_growths:
            adjusted = deepcopy(assumptions)
            adjusted.wacc = wacc
            adjusted.terminal_growth = tg
            dcf = run_dcf("base", base_forecast, adjusted, net_debt, shares_outstanding)
            row_values.append(dcf.target_price)
        values.append(row_values)
    return SensitivityTable(
        title="DCF sensitivity: WACC vs terminal growth",
        row_label="WACC",
        column_label="Terminal growth",
        rows=waccs,
        columns=terminal_growths,
        values=values,
    )


def growth_margin_sensitivity(
    historicals: HistoricalFinancials,
    assumptions: ScenarioAssumptions,
    net_debt: float,
    shares_outstanding: float | None,
) -> SensitivityTable:
    growth_deltas = [-0.04, -0.02, 0.0, 0.02, 0.04]
    margin_deltas = [-0.04, -0.02, 0.0, 0.02, 0.04]
    values: list[list[float | None]] = []
    for gd in growth_deltas:
        row_values: list[float | None] = []
        for md in margin_deltas:
            adjusted = deepcopy(assumptions)
            adjusted.revenue_growth = [g + gd for g in adjusted.revenue_growth]
            adjusted.ebitda_margin = [m + md for m in adjusted.ebitda_margin]
            forecast = run_forecast(historicals, adjusted)
            dcf = run_dcf("base", forecast, adjusted, net_debt, shares_outstanding)
            row_values.append(dcf.target_price)
        values.append(row_values)
    return SensitivityTable(
        title="Operating sensitivity: revenue growth delta vs EBITDA margin delta",
        row_label="Revenue growth delta",
        column_label="EBITDA margin delta",
        rows=growth_deltas,
        columns=margin_deltas,
        values=values,
    )
