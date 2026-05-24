"""Financial model first-pass construction and validation.

This module is the source of truth for the financial model used in the report.
The report should not be generated until this model has been built and validated.

Design principles:
- derive assumptions from observed company data where available;
- keep the forecast horizon to five years;
- produce explicit bear/base/bull DCF target prices;
- validate data sufficiency, formula logic and valuation sanity before reporting;
- use Excel as an output/audit layer, not as the first place calculations happen.
"""
from __future__ import annotations

from math import isfinite
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.config import settings
from src.schemas import DCFOutput, ForecastRow, HistoricalFinancials, MarketSnapshot, ScenarioAssumptions

FORECAST_YEARS = 5


class ModelDataQuality(BaseModel):
    source: str = "yfinance"
    historical_years_available: int = 0
    target_historical_years: int = 5
    current_price_available: bool = False
    shares_available: bool = False
    revenue_available: bool = False
    fcf_available: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ValidatedScenarioModel(BaseModel):
    scenario: Literal["bear", "base", "bull"]
    assumptions: ScenarioAssumptions
    forecasts: list[ForecastRow]
    dcf: DCFOutput
    key_assumptions: dict[str, float | list[float]] = Field(default_factory=dict)
    assumption_rationale: list[str] = Field(default_factory=list)


class ModelValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


class ValidatedFinancialModel(BaseModel):
    ticker: str
    company_name: str
    currency: str = "USD"
    data_quality: ModelDataQuality
    historical_years: list[str]
    forecast_years: list[str]
    scenarios: dict[str, ValidatedScenarioModel]
    selected_scenario: str = "base"
    valuation_summary: dict[str, float | None] = Field(default_factory=dict)
    validation: ModelValidationResult
    # Optional metadata used by the iterative LLM-assisted workflow. These fields
    # are kept here because iterative_model_validation_engine returns this shared
    # model type.
    iteration_count: int = 0
    llm_assumption_pack: dict[str, Any] = Field(default_factory=dict)


def _safe(value: float | None, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        return value if isfinite(value) else default
    except Exception:
        return default


def _last_value(values: dict[str, float], fallback: float = 0.0) -> float:
    if not values:
        return fallback
    return _safe(values.get(sorted(values.keys())[-1]), fallback)


def _last_years(values: dict[str, float], max_years: int = 5) -> list[str]:
    return sorted(values.keys())[-max_years:]


def _median(values: list[float], fallback: float) -> float:
    cleaned = [v for v in values if v is not None and isfinite(v)]
    if not cleaned:
        return fallback
    return float(median(cleaned))


def _bounded(value: float, low: float, high: float) -> float:
    return max(min(value, high), low)


def _growth_rates(values: dict[str, float]) -> list[float]:
    years = sorted(values.keys())
    out: list[float] = []
    for prev, curr in zip(years, years[1:]):
        prev_value = values.get(prev)
        curr_value = values.get(curr)
        if prev_value and curr_value:
            out.append(curr_value / prev_value - 1)
    return out


def _derive_data_quality(snapshot: MarketSnapshot, historicals: HistoricalFinancials) -> ModelDataQuality:
    years = _last_years(historicals.revenue, 5)
    quality = ModelDataQuality(
        historical_years_available=len(years),
        current_price_available=bool(snapshot.current_price and snapshot.current_price > 0),
        shares_available=bool(snapshot.shares_outstanding and snapshot.shares_outstanding > 0),
        revenue_available=bool(historicals.revenue),
        fcf_available=bool(historicals.free_cash_flow),
    )
    if len(years) < 5:
        quality.warnings.append(
            f"Only {len(years)} annual revenue years were available from yfinance. The model targets five historical years; consider adding an SEC/FMP/FactSet data source for a full audited history."
        )
    if len(years) < 3:
        quality.errors.append("Fewer than three years of revenue history are available; forecast assumptions are not sufficiently grounded.")
    if not quality.current_price_available:
        quality.errors.append("Current share price is missing; 12-month upside/downside cannot be calculated reliably.")
    if not quality.shares_available:
        quality.errors.append("Shares outstanding are missing; per-share valuation cannot be calculated reliably.")
    if not historicals.revenue:
        quality.errors.append("Revenue history is missing; the model cannot forecast from a reliable baseline.")
    if not historicals.free_cash_flow and not historicals.ebit and not historicals.ebitda:
        quality.errors.append("Cash flow and operating earnings history are missing; DCF cannot be validated.")
    return quality


def _derive_wacc(snapshot: MarketSnapshot) -> float:
    """Derive a simple company-specific WACC instead of using a blanket default.

    This fixes a major source of false downside calls for mature cash-generative
    companies. A hard-coded 9.5% WACC was too punitive for large investment-grade
    companies such as Cisco. This still remains a prototype assumption, but it is
    now tied to beta and capital structure instead of a single static default.
    """
    risk_free_rate = 0.04
    equity_risk_premium = 0.045
    beta = _bounded(_safe(snapshot.beta, 1.0), 0.65, 1.40)
    cost_of_equity = risk_free_rate + beta * equity_risk_premium

    market_cap = _safe(snapshot.market_cap, 0.0)
    debt = max(_safe(snapshot.total_debt, 0.0), 0.0)
    total_capital = market_cap + debt
    if total_capital > 0:
        equity_weight = market_cap / total_capital
        debt_weight = debt / total_capital
    else:
        equity_weight = 1.0
        debt_weight = 0.0

    pre_tax_cost_of_debt = 0.055
    after_tax_cost_of_debt = pre_tax_cost_of_debt * (1 - settings.default_tax_rate)
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt

    # Keep the WACC inside a plausible range for mature listed operating companies.
    return _bounded(wacc, 0.065, 0.105)


def _derive_base_assumptions(historicals: HistoricalFinancials, snapshot: MarketSnapshot) -> ScenarioAssumptions:
    revenue_growth_history = _growth_rates(historicals.revenue)
    recent_growth = _median(revenue_growth_history[-3:], 0.03)
    base_growth = _bounded(recent_growth, -0.03, 0.12)

    revenue = historicals.revenue
    recent_fcf_margin = _bounded(_median(list(historicals.fcf_margin.values())[-3:], 0.16), 0.02, 0.35)

    da_pct_candidates: list[float] = []
    for year in set(historicals.ebitda) & set(historicals.ebit) & set(revenue):
        if revenue.get(year):
            da_pct_candidates.append(max((historicals.ebitda[year] - historicals.ebit[year]) / revenue[year], 0.0))
    da_pct = _bounded(_median(da_pct_candidates, 0.035), 0.005, 0.12)

    capex_pct_candidates = [historicals.capex[y] / revenue[y] for y in sorted(set(historicals.capex) & set(revenue)) if revenue.get(y)]
    capex_pct = _bounded(_median(capex_pct_candidates[-3:], 0.025), 0.005, 0.12)

    # Working capital is intentionally conservative because yfinance annual data
    # does not reliably provide detailed current asset/liability fields.
    nwc_pct = 0.005

    tax_rate = settings.default_tax_rate
    if snapshot.profit_margins is not None and snapshot.profit_margins < 0:
        tax_rate = 0.0

    ebitda_margin_history = list(historicals.ebitda_margin.values())[-3:]
    if ebitda_margin_history:
        ebitda_margin = _bounded(_median(ebitda_margin_history, recent_fcf_margin + 0.09), 0.04, 0.60)
    else:
        # If yfinance does not provide EBITDA, do not fall back to a generic 22%.
        # Reconstruct an implied EBITDA margin from observed FCF margin, capex,
        # D&A and tax rate so mature cash generators are not undervalued.
        fcf_nwc_drag = max(base_growth, 0.0) * nwc_pct / (1 + max(base_growth, 0.0))
        ebitda_margin = ((recent_fcf_margin + capex_pct + fcf_nwc_drag - da_pct) / max(1 - tax_rate, 0.01)) + da_pct
        ebitda_margin = _bounded(ebitda_margin, recent_fcf_margin + 0.04, 0.60)

    wacc = _derive_wacc(snapshot)
    terminal_growth = _bounded(settings.default_terminal_growth, 0.0, min(0.035, wacc - 0.02))

    return ScenarioAssumptions(
        revenue_growth=[base_growth, base_growth * 0.80, base_growth * 0.65, base_growth * 0.50, base_growth * 0.35],
        ebitda_margin=[ebitda_margin, ebitda_margin, ebitda_margin, ebitda_margin, ebitda_margin],
        da_percent_revenue=da_pct,
        capex_percent_revenue=capex_pct,
        nwc_percent_revenue=nwc_pct,
        tax_rate=tax_rate,
        wacc=wacc,
        terminal_growth=terminal_growth,
    )


def _scenario_from_base(base: ScenarioAssumptions, scenario: str) -> ScenarioAssumptions:
    if scenario == "bear":
        return ScenarioAssumptions(
            revenue_growth=[g - 0.02 for g in base.revenue_growth],
            ebitda_margin=[max(m - 0.015, 0.0) for m in base.ebitda_margin],
            da_percent_revenue=base.da_percent_revenue,
            capex_percent_revenue=min(base.capex_percent_revenue + 0.005, 0.15),
            nwc_percent_revenue=base.nwc_percent_revenue + 0.003,
            tax_rate=base.tax_rate,
            wacc=min(base.wacc + 0.0075, 0.115),
            terminal_growth=max(base.terminal_growth - 0.005, 0.0),
        )
    if scenario == "bull":
        return ScenarioAssumptions(
            revenue_growth=[g + 0.02 for g in base.revenue_growth],
            ebitda_margin=[m + 0.015 for m in base.ebitda_margin],
            da_percent_revenue=base.da_percent_revenue,
            capex_percent_revenue=max(base.capex_percent_revenue - 0.003, 0.005),
            nwc_percent_revenue=max(base.nwc_percent_revenue - 0.002, 0.0),
            tax_rate=base.tax_rate,
            wacc=max(base.wacc - 0.005, 0.06),
            terminal_growth=min(base.terminal_growth + 0.005, base.wacc - 0.015),
        )
    return base


def _forecast(historicals: HistoricalFinancials, assumptions: ScenarioAssumptions, start_year: int) -> list[ForecastRow]:
    prior_revenue = _last_value(historicals.revenue, 100_000_000.0)
    rows: list[ForecastRow] = []
    revenue = prior_revenue
    for i in range(FORECAST_YEARS):
        growth = assumptions.revenue_growth[min(i, len(assumptions.revenue_growth) - 1)]
        revenue = revenue * (1 + growth)
        margin = assumptions.ebitda_margin[min(i, len(assumptions.ebitda_margin) - 1)]
        ebitda = revenue * margin
        da = revenue * assumptions.da_percent_revenue
        ebit = ebitda - da
        tax = max(ebit, 0.0) * assumptions.tax_rate
        nopat = ebit - tax
        capex = revenue * assumptions.capex_percent_revenue
        change_nwc = (revenue - prior_revenue) * assumptions.nwc_percent_revenue
        fcf = nopat + da - capex - change_nwc
        rows.append(
            ForecastRow(
                year=f"FY{str(start_year + i)[-2:]}E",
                revenue=revenue,
                ebitda=ebitda,
                ebit=ebit,
                tax=tax,
                nopat=nopat,
                da=da,
                capex=capex,
                change_nwc=change_nwc,
                fcf=fcf,
                ebitda_margin=margin,
                fcf_margin=fcf / revenue if revenue else 0.0,
            )
        )
        prior_revenue = revenue
    return rows


def _dcf(scenario: str, forecast: list[ForecastRow], assumptions: ScenarioAssumptions, snapshot: MarketSnapshot) -> DCFOutput:
    net_debt = _safe(snapshot.net_debt, 0.0)
    shares = snapshot.shares_outstanding
    pv_fcf = sum(row.fcf / ((1 + assumptions.wacc) ** i) for i, row in enumerate(forecast, start=1))
    final_fcf = forecast[-1].fcf if forecast else 0.0
    terminal_spread = assumptions.wacc - assumptions.terminal_growth
    terminal_value = final_fcf * (1 + assumptions.terminal_growth) / terminal_spread if terminal_spread > 0 else 0.0
    pv_terminal_value = terminal_value / ((1 + assumptions.wacc) ** max(len(forecast), 1))
    enterprise_value = pv_fcf + pv_terminal_value
    equity_value = enterprise_value - net_debt
    target_price = equity_value / shares if shares else None
    return DCFOutput(
        scenario=scenario,  # type: ignore[arg-type]
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        target_price=target_price,
        pv_fcf=pv_fcf,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal_value,
        net_debt=net_debt,
        shares_outstanding=shares,
        assumptions=assumptions,
    )


def _validate_model(snapshot: MarketSnapshot, quality: ModelDataQuality, scenarios: dict[str, ValidatedScenarioModel]) -> ModelValidationResult:
    errors = list(quality.errors)
    warnings = list(quality.warnings)
    checks: dict[str, bool] = {}

    checks["data_quality_minimum"] = not quality.errors
    checks["three_scenarios_present"] = set(scenarios.keys()) == {"bear", "base", "bull"}
    checks["five_year_forecast"] = all(len(s.forecasts) == FORECAST_YEARS for s in scenarios.values())
    checks["target_prices_present"] = all(s.dcf.target_price is not None and isfinite(s.dcf.target_price) for s in scenarios.values())
    checks["wacc_exceeds_terminal_growth"] = all(s.assumptions.wacc > s.assumptions.terminal_growth + 0.005 for s in scenarios.values())

    for scenario_name, scenario in scenarios.items():
        for idx, row in enumerate(scenario.forecasts):
            expected_fcf = row.nopat + row.da - row.capex - row.change_nwc
            if abs(expected_fcf - row.fcf) > max(abs(row.revenue) * 0.000001, 1.0):
                errors.append(f"{scenario_name} FY{idx+1}: FCF formula does not reconcile to NOPAT + D&A - capex - change NWC.")
            if row.revenue <= 0:
                errors.append(f"{scenario_name} {row.year}: forecast revenue is not positive.")
            if not isfinite(row.fcf):
                errors.append(f"{scenario_name} {row.year}: forecast FCF is not finite.")
        dcf = scenario.dcf
        expected_ev = dcf.pv_fcf + dcf.pv_terminal_value
        if abs(expected_ev - dcf.enterprise_value) > max(abs(expected_ev) * 0.000001, 1.0):
            errors.append(f"{scenario_name}: enterprise value does not reconcile to PV FCF + PV terminal value.")
        expected_equity = dcf.enterprise_value - dcf.net_debt
        if abs(expected_equity - dcf.equity_value) > max(abs(expected_equity) * 0.000001, 1.0):
            errors.append(f"{scenario_name}: equity value does not reconcile to EV - net debt.")
        if dcf.shares_outstanding and dcf.target_price is not None:
            expected_price = dcf.equity_value / dcf.shares_outstanding
            if abs(expected_price - dcf.target_price) > 0.01:
                errors.append(f"{scenario_name}: target price does not reconcile to equity value / shares.")

    bear = scenarios.get("bear").dcf.target_price if scenarios.get("bear") else None
    base = scenarios.get("base").dcf.target_price if scenarios.get("base") else None
    bull = scenarios.get("bull").dcf.target_price if scenarios.get("bull") else None
    if bear is not None and base is not None and bull is not None:
        if not (bear <= base <= bull):
            warnings.append("Bear/base/bull DCF target prices are not ordered as expected; inspect scenario assumptions.")

    valuation_sanity = True
    if snapshot.current_price and base is not None:
        downside_gap = base / snapshot.current_price - 1
        if downside_gap < -0.45 or downside_gap > 0.80:
            valuation_sanity = False
            errors.append(
                "Base DCF target is too detached from current share price for an automated recommendation. "
                "The model requires analyst review of WACC, terminal value, FCF margin, guidance and data quality before report generation."
            )
        elif downside_gap < -0.25 or downside_gap > 0.45:
            warnings.append("Base DCF target is materially detached from current share price; review WACC, terminal value and forecast assumptions.")
    checks["valuation_sanity_vs_market"] = valuation_sanity

    checks["no_formula_reconciliation_errors"] = not errors
    is_valid = not errors and all(checks.values())
    return ModelValidationResult(is_valid=is_valid, errors=errors, warnings=warnings, checks=checks)


def build_validated_financial_model(snapshot: MarketSnapshot, historicals: HistoricalFinancials) -> ValidatedFinancialModel:
    quality = _derive_data_quality(snapshot, historicals)
    historical_years = _last_years(historicals.revenue, 5)
    latest_hist_year = int(historical_years[-1]) if historical_years and historical_years[-1].isdigit() else 2025
    forecast_years = [f"FY{str(latest_hist_year + i)[-2:]}E" for i in range(1, FORECAST_YEARS + 1)]

    base_assumptions = _derive_base_assumptions(historicals, snapshot)
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
                "Revenue growth is based on the recent historical revenue-growth median and scenario-adjusted for bear/base/bull cases.",
                "EBITDA margin is based on recent historical EBITDA margins; if EBITDA is unavailable, it is reconstructed from observed FCF margin, capex, D&A and tax assumptions.",
                "D&A and capex intensity are derived from available historical financial statements where possible.",
                "WACC is derived from beta and capital structure rather than a single hard-coded default.",
                "The validation gate blocks automated recommendations when the DCF output is too detached from the current share price.",
            ],
        )

    validation = _validate_model(snapshot, quality, scenarios)
    model = ValidatedFinancialModel(
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
    )
    return model


def raise_if_model_invalid(model: ValidatedFinancialModel) -> None:
    if model.validation.is_valid:
        return
    details = "\n".join(model.validation.errors[:12])
    raise ValueError(f"Financial model validation failed. Report generation stopped.\n{details}")
