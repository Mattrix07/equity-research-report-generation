"""DCF valuation engine."""
from __future__ import annotations

from src.schemas import DCFOutput, ForecastRow, ScenarioAssumptions


def run_dcf(
    scenario: str,
    forecast: list[ForecastRow],
    assumptions: ScenarioAssumptions,
    net_debt: float = 0.0,
    shares_outstanding: float | None = None,
) -> DCFOutput:
    wacc = assumptions.wacc
    terminal_growth = assumptions.terminal_growth
    pv_fcf = 0.0
    for i, row in enumerate(forecast, start=1):
        pv_fcf += row.fcf / ((1 + wacc) ** i)

    final_fcf = forecast[-1].fcf if forecast else 0.0
    denominator = max(wacc - terminal_growth, 0.001)
    terminal_value = final_fcf * (1 + terminal_growth) / denominator
    pv_terminal_value = terminal_value / ((1 + wacc) ** max(len(forecast), 1))
    enterprise_value = pv_fcf + pv_terminal_value
    equity_value = enterprise_value - net_debt
    target_price = equity_value / shares_outstanding if shares_outstanding else None

    return DCFOutput(
        scenario=scenario,  # type: ignore[arg-type]
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        target_price=target_price,
        pv_fcf=pv_fcf,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal_value,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        assumptions=assumptions,
    )
