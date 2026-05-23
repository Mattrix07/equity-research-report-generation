"""Forecasting engine.

Agents create assumptions; this module performs the calculations.
"""
from __future__ import annotations

from datetime import datetime

from src.config import settings
from src.schemas import ForecastRow, HistoricalFinancials, ScenarioAssumptions


def _last_value(values: dict[str, float], fallback: float = 100_000_000.0) -> float:
    if not values:
        return fallback
    latest_key = sorted(values.keys())[-1]
    return float(values[latest_key])


def _median(values: list[float], fallback: float) -> float:
    cleaned = sorted([v for v in values if v is not None])
    if not cleaned:
        return fallback
    mid = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[mid]
    return (cleaned[mid - 1] + cleaned[mid]) / 2


def build_default_assumptions(historicals: HistoricalFinancials) -> dict[str, ScenarioAssumptions]:
    revenue_years = sorted(historicals.revenue.keys())
    growth_rates: list[float] = []
    for prev, curr in zip(revenue_years, revenue_years[1:]):
        if historicals.revenue.get(prev):
            growth_rates.append((historicals.revenue[curr] / historicals.revenue[prev]) - 1)

    base_growth = max(min(_median(growth_rates[-3:], 0.06), 0.25), -0.05)
    margin = max(min(_median(list(historicals.ebitda_margin.values())[-3:], 0.18), 0.45), -0.05)

    base = ScenarioAssumptions(
        revenue_growth=[base_growth, base_growth * 0.9, base_growth * 0.8, base_growth * 0.7, base_growth * 0.6],
        ebitda_margin=[margin, margin + 0.01, margin + 0.015, margin + 0.02, margin + 0.025],
        tax_rate=settings.default_tax_rate,
        wacc=settings.default_wacc,
        terminal_growth=settings.default_terminal_growth,
    )
    bear = ScenarioAssumptions(
        revenue_growth=[g - 0.04 for g in base.revenue_growth],
        ebitda_margin=[max(m - 0.04, -0.10) for m in base.ebitda_margin],
        tax_rate=settings.default_tax_rate,
        wacc=settings.default_wacc + 0.01,
        terminal_growth=max(settings.default_terminal_growth - 0.005, 0.0),
    )
    bull = ScenarioAssumptions(
        revenue_growth=[g + 0.04 for g in base.revenue_growth],
        ebitda_margin=[m + 0.04 for m in base.ebitda_margin],
        tax_rate=settings.default_tax_rate,
        wacc=max(settings.default_wacc - 0.005, 0.06),
        terminal_growth=settings.default_terminal_growth + 0.005,
    )
    return {"bear": bear, "base": base, "bull": bull}


def run_forecast(historicals: HistoricalFinancials, assumptions: ScenarioAssumptions) -> list[ForecastRow]:
    start_revenue = _last_value(historicals.revenue)
    current_year = datetime.now().year
    rows: list[ForecastRow] = []
    revenue = start_revenue
    prior_revenue = start_revenue

    for i, growth in enumerate(assumptions.revenue_growth):
        year = f"FY{str(current_year + i + 1)[-2:]}E"
        revenue = revenue * (1 + growth)
        ebitda_margin = assumptions.ebitda_margin[min(i, len(assumptions.ebitda_margin) - 1)]
        ebitda = revenue * ebitda_margin
        da = revenue * assumptions.da_percent_revenue
        ebit = ebitda - da
        tax = max(ebit, 0) * assumptions.tax_rate
        nopat = ebit - tax
        capex = revenue * assumptions.capex_percent_revenue
        change_nwc = max(revenue - prior_revenue, 0) * assumptions.nwc_percent_revenue
        fcf = nopat + da - capex - change_nwc
        rows.append(
            ForecastRow(
                year=year,
                revenue=revenue,
                ebitda=ebitda,
                ebit=ebit,
                tax=tax,
                nopat=nopat,
                da=da,
                capex=capex,
                change_nwc=change_nwc,
                fcf=fcf,
                ebitda_margin=ebitda_margin,
                fcf_margin=fcf / revenue if revenue else 0.0,
            )
        )
        prior_revenue = revenue
    return rows
