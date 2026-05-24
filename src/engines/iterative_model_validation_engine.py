"""Iterative LLM-assisted financial model validation engine.

This wraps the deterministic validation engine with a bounded LLM assumption
layer. LLM agents propose peers, forecast assumptions, WACC and terminal value;
Python remains the calculation engine; the validation gate decides whether the
model can be used in the report.
"""
from __future__ import annotations

from typing import Any

from src.engines.model_validation_engine import (
    FORECAST_YEARS,
    ModelValidationResult,
    ValidatedFinancialModel,
    ValidatedScenarioModel,
    _dcf,
    _derive_base_assumptions,
    _derive_data_quality,
    _forecast,
    _last_years,
    _scenario_from_base,
    _safe,
    _validate_model,
    raise_if_model_invalid,
)
from src.schemas import HistoricalFinancials, MarketSnapshot, ScenarioAssumptions


def _float_list(values: Any, length: int = FORECAST_YEARS) -> list[float] | None:
    if not isinstance(values, list) or len(values) < length:
        return None
    out: list[float] = []
    for value in values[:length]:
        try:
            out.append(float(value))
        except Exception:
            return None
    return out


def _bounded(value: float, low: float, high: float) -> float:
    return max(min(value, high), low)


def _apply_llm_inputs(base: ScenarioAssumptions, llm_inputs: dict[str, Any] | None) -> tuple[ScenarioAssumptions, list[str]]:
    if not llm_inputs:
        return base, []
    forecast = llm_inputs.get("forecast", {}) or {}
    wacc = llm_inputs.get("wacc", {}) or {}
    terminal = llm_inputs.get("terminal_value", {}) or {}
    revision = llm_inputs.get("validation_revision", {}) or {}
    merged = {**forecast, **wacc, **terminal, **revision}
    notes: list[str] = []

    revenue_growth = _float_list(merged.get("revenue_growth")) or base.revenue_growth
    ebitda_margin = _float_list(merged.get("ebitda_margin")) or base.ebitda_margin
    if revenue_growth != base.revenue_growth:
        notes.append("LLM Forecast Assumption Agent supplied the revenue growth path within guardrails.")
    if ebitda_margin != base.ebitda_margin:
        notes.append("LLM Forecast Assumption Agent supplied the EBITDA margin path within guardrails.")

    out = ScenarioAssumptions(
        revenue_growth=[_bounded(x, -0.10, 0.20) for x in revenue_growth],
        ebitda_margin=[_bounded(x, 0.00, 0.65) for x in ebitda_margin],
        da_percent_revenue=_bounded(_safe(merged.get("da_percent_revenue"), base.da_percent_revenue), 0.0, 0.15),
        capex_percent_revenue=_bounded(_safe(merged.get("capex_percent_revenue"), base.capex_percent_revenue), 0.0, 0.20),
        nwc_percent_revenue=_bounded(_safe(merged.get("nwc_percent_revenue"), base.nwc_percent_revenue), -0.02, 0.05),
        tax_rate=_bounded(_safe(merged.get("tax_rate"), base.tax_rate), 0.0, 0.35),
        wacc=_bounded(_safe(merged.get("wacc"), base.wacc), 0.05, 0.14),
        terminal_growth=_bounded(_safe(merged.get("terminal_growth"), base.terminal_growth), 0.0, 0.045),
    )
    if out.wacc <= out.terminal_growth + 0.01:
        out.terminal_growth = max(0.0, out.wacc - 0.02)
        notes.append("Terminal growth was adjusted so WACC remains safely above terminal growth.")
    if "wacc" in merged:
        notes.append("LLM WACC Agent supplied the WACC, bounded by model guardrails.")
    if "terminal_growth" in merged:
        notes.append("LLM Terminal Value Agent supplied terminal growth, bounded by model guardrails.")
    if revision:
        notes.append("LLM Validation Revision Agent supplied a revised assumption set after validation feedback.")
    return out, notes


def build_model_with_assumptions(snapshot: MarketSnapshot, historicals: HistoricalFinancials, llm_inputs: dict[str, Any] | None = None, iteration_count: int = 0) -> ValidatedFinancialModel:
    quality = _derive_data_quality(snapshot, historicals)
    historical_years = _last_years(historicals.revenue, 5)
    latest_hist_year = int(historical_years[-1]) if historical_years and historical_years[-1].isdigit() else 2025
    forecast_years = [f"FY{str(latest_hist_year + i)[-2:]}E" for i in range(1, FORECAST_YEARS + 1)]

    base_assumptions, llm_notes = _apply_llm_inputs(_derive_base_assumptions(historicals, snapshot), llm_inputs)
    scenarios: dict[str, ValidatedScenarioModel] = {}
    for scenario_name in ["bear", "base", "bull"]:
        assumptions = _scenario_from_base(base_assumptions, scenario_name)
        forecasts = _forecast(historicals, assumptions, latest_hist_year + 1)
        dcf = _dcf(scenario_name, forecasts, assumptions, snapshot)
        scenarios[scenario_name] = ValidatedScenarioModel(
            scenario=scenario_name,  # type: ignore[arg-type]
            assumptions=assumptions,
            forecasts=forecasts,
            dcf=dcf,
            key_assumptions={
                "revenue_growth": assumptions.revenue_growth,
                "ebitda_margin": assumptions.ebitda_margin,
                "da_percent_revenue": assumptions.da_percent_revenue,
                "capex_percent_revenue": assumptions.capex_percent_revenue,
                "nwc_percent_revenue": assumptions.nwc_percent_revenue,
                "tax_rate": assumptions.tax_rate,
                "wacc": assumptions.wacc,
                "terminal_growth": assumptions.terminal_growth,
            },
            assumption_rationale=[
                "Python performs the calculation; LLM agents can only adjust bounded assumptions.",
                "Forecast, WACC and terminal assumptions are derived from available data and challenged by the LLM layer when enabled.",
                "The validation gate blocks automated recommendations when the model is mathematically inconsistent or commercially detached.",
                *llm_notes,
            ],
        )

    validation = _validate_model(snapshot, quality, scenarios)
    return ValidatedFinancialModel(
        ticker=snapshot.ticker,
        company_name=snapshot.company_name,
        currency=snapshot.currency,
        data_quality=quality,
        historical_years=historical_years,
        forecast_years=forecast_years,
        scenarios=scenarios,
        valuation_summary={
            "bear_target_price": scenarios["bear"].dcf.target_price,
            "base_target_price": scenarios["base"].dcf.target_price,
            "bull_target_price": scenarios["bull"].dcf.target_price,
            "current_price": snapshot.current_price,
            "base_upside_downside": (scenarios["base"].dcf.target_price / snapshot.current_price - 1) if snapshot.current_price and scenarios["base"].dcf.target_price else None,
        },
        validation=validation,
        llm_assumption_pack=llm_inputs or {},
        iteration_count=iteration_count,
    )


__all__ = ["build_model_with_assumptions", "raise_if_model_invalid"]
