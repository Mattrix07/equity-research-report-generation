"""Dynamic assumption derivation agent."""
from __future__ import annotations

from statistics import median

from src.schemas import CompanyClassification, DynamicAssumptions, HistoricalFinancials, MarketSnapshot, ScenarioAssumptions


def _safe_median(values: list[float], fallback: float) -> float:
    cleaned = [v for v in values if v is not None]
    return float(median(cleaned)) if cleaned else fallback


def _historical_growth(historicals: HistoricalFinancials) -> list[float]:
    years = sorted(historicals.revenue.keys())
    out: list[float] = []
    for prev, curr in zip(years, years[1:]):
        if historicals.revenue.get(prev):
            out.append(historicals.revenue[curr] / historicals.revenue[prev] - 1)
    return out


def derive_dynamic_assumptions(snapshot: MarketSnapshot, historicals: HistoricalFinancials, classification: CompanyClassification) -> DynamicAssumptions:
    warnings: list[str] = []
    beta = snapshot.beta if snapshot.beta and snapshot.beta > 0 else 1.0
    risk_free_rate = 0.045
    equity_risk_premium = 0.055
    specific_risk = 0.0

    if snapshot.market_cap and snapshot.market_cap < 2_000_000_000:
        specific_risk += 0.015
    if classification.primary_type in {"healthcare_pipeline_or_royalty", "resources_or_mining"}:
        specific_risk += 0.02
    if classification.primary_type in {"bank_or_lender", "insurer"}:
        specific_risk += 0.005

    cost_of_equity = risk_free_rate + beta * equity_risk_premium + specific_risk
    total_debt = snapshot.total_debt or 0.0
    market_cap = snapshot.market_cap or 0.0
    debt_weight = total_debt / (total_debt + market_cap) if (total_debt + market_cap) > 0 else 0.0
    equity_weight = 1 - debt_weight
    tax_rate = 0.21 if snapshot.currency == "USD" else 0.25
    pre_tax_cost_of_debt = 0.055 + (0.015 if debt_weight > 0.4 else 0.0)
    after_tax_cost_of_debt = pre_tax_cost_of_debt * (1 - tax_rate)
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt

    growth_rates = _historical_growth(historicals)
    recent_growth = _safe_median(growth_rates[-3:], 0.04)
    terminal_growth = max(min(recent_growth * 0.25, 0.035), 0.01)
    terminal_method = classification.terminal_value_method
    if terminal_method in {"finite_life", "asset_level_rnpv", "not_applicable"}:
        terminal_growth = None

    if snapshot.profit_margins is not None and snapshot.profit_margins < 0:
        warnings.append("Company has negative profitability; effective tax and steady-state margin assumptions need analyst review.")

    return DynamicAssumptions(
        wacc=wacc,
        cost_of_equity=cost_of_equity,
        after_tax_cost_of_debt=after_tax_cost_of_debt,
        tax_rate=tax_rate,
        terminal_growth=terminal_growth,
        terminal_value_method=terminal_method,
        exit_multiple=12.0 if terminal_method == "exit_multiple" else None,
        revenue_growth_logic="Revenue assumptions are anchored to recent growth, then routed through the selected company-specific valuation framework.",
        margin_logic="Margin assumptions are benchmarked against recent EBITDA and FCF margins, adjusted for maturity, cyclicality and operating leverage.",
        capital_intensity_logic="Capital intensity is based on historical capex and working-capital behaviour unless a sector model overrides it.",
        risk_adjustment_logic="Risk adjustment depends on valuation method, including clinical probability weighting for pipeline companies and finite-life treatment for resources.",
        sources_and_evidence=[
            f"Beta used for cost of equity: {beta:.2f}",
            f"Debt weight estimated from market cap and total debt: {debt_weight:.1%}",
            f"Selected terminal value method: {terminal_method}",
            f"Company classification: {classification.primary_type}",
        ],
        warnings=warnings + classification.warnings,
    )


def assumptions_to_scenario_assumptions(base: ScenarioAssumptions, dynamic: DynamicAssumptions) -> ScenarioAssumptions:
    updated = base.model_copy(deep=True)
    if dynamic.tax_rate is not None:
        updated.tax_rate = dynamic.tax_rate
    if dynamic.wacc is not None:
        updated.wacc = dynamic.wacc
    if dynamic.terminal_growth is not None:
        updated.terminal_growth = dynamic.terminal_growth
    return updated
