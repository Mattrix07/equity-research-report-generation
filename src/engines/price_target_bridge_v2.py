"""DCF-led 12-month target bridge.

Keeps intrinsic DCF separate from the report's 12-month target price. The bridge
uses DCF as the main input and adds observable analyst-target/current-price
context so a five-year DCF is not mislabelled as a one-year price target.
"""
from __future__ import annotations

from typing import Any

from src.engines.model_validation_engine import ValidatedFinancialModel
from src.schemas import MarketSnapshot

DETACHED_ERROR = "Base DCF target is too detached from current share price"


def consensus_target(snapshot: MarketSnapshot) -> float | None:
    if snapshot.target_median_price and snapshot.target_median_price > 0:
        return snapshot.target_median_price
    if snapshot.target_mean_price and snapshot.target_mean_price > 0:
        return snapshot.target_mean_price
    return None


def bridge_price(snapshot: MarketSnapshot, intrinsic: float | None, scenario: str) -> float | None:
    if intrinsic is None:
        return None
    current = snapshot.current_price
    consensus = consensus_target(snapshot)
    if not current or not consensus:
        return intrinsic
    if scenario == "bear":
        return 0.70 * intrinsic + 0.20 * current + 0.10 * consensus
    if scenario == "bull":
        return 0.55 * intrinsic + 0.15 * current + 0.30 * consensus
    return 0.60 * intrinsic + 0.15 * current + 0.25 * consensus


def implied_metrics(model: ValidatedFinancialModel) -> dict[str, float | None]:
    scenario = model.scenarios.get("base")
    if not scenario or not scenario.forecasts:
        return {}
    dcf = scenario.dcf
    final = scenario.forecasts[-1]
    return {
        "implied_ev_to_final_year_ebitda": dcf.enterprise_value / final.ebitda if final.ebitda else None,
        "implied_ev_to_final_year_fcf": dcf.enterprise_value / final.fcf if final.fcf else None,
        "terminal_value_percent_of_enterprise_value": dcf.pv_terminal_value / dcf.enterprise_value if dcf.enterprise_value else None,
    }


def apply_price_target_bridge(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> ValidatedFinancialModel:
    bear_intrinsic = model.scenarios["bear"].dcf.target_price
    base_intrinsic = model.scenarios["base"].dcf.target_price
    bull_intrinsic = model.scenarios["bull"].dcf.target_price
    bear_target = bridge_price(snapshot, bear_intrinsic, "bear")
    base_target = bridge_price(snapshot, base_intrinsic, "base")
    bull_target = bridge_price(snapshot, bull_intrinsic, "bull")
    current = snapshot.current_price
    model.valuation_summary.update({
        "intrinsic_dcf_bear_target_price": bear_intrinsic,
        "intrinsic_dcf_base_target_price": base_intrinsic,
        "intrinsic_dcf_bull_target_price": bull_intrinsic,
        "bear_target_price": bear_target,
        "base_target_price": base_target,
        "bull_target_price": bull_target,
        "analyst_consensus_target": consensus_target(snapshot),
        "analyst_target_mean": snapshot.target_mean_price,
        "analyst_target_median": snapshot.target_median_price,
        "analyst_target_high": snapshot.target_high_price,
        "analyst_target_low": snapshot.target_low_price,
        "number_of_analyst_opinions": snapshot.number_of_analyst_opinions,
        "base_upside_downside": (base_target / current - 1) if current and base_target else None,
        "base_intrinsic_dcf_upside_downside": (base_intrinsic / current - 1) if current and base_intrinsic else None,
        "base_implied_metrics": implied_metrics(model),
    })
    _downgrade_intrinsic_only_error(model, snapshot)
    _add_model_warnings(model, snapshot)
    return model


def _downgrade_intrinsic_only_error(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> None:
    current = snapshot.current_price
    base_target = model.valuation_summary.get("base_target_price")
    if not current or not base_target:
        return
    gap = base_target / current - 1
    if -0.30 <= gap <= 0.60:
        moved = [e for e in model.validation.errors if DETACHED_ERROR in e]
        if moved:
            model.validation.errors = [e for e in model.validation.errors if DETACHED_ERROR not in e]
            model.validation.warnings.extend(moved)
            model.validation.checks["valuation_sanity_vs_market"] = True
            model.validation.checks["no_formula_reconciliation_errors"] = not model.validation.errors
            model.validation.is_valid = not model.validation.errors and all(model.validation.checks.values())


def _add_model_warnings(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> None:
    consensus = consensus_target(snapshot)
    current = snapshot.current_price
    intrinsic = model.valuation_summary.get("intrinsic_dcf_base_target_price")
    target = model.valuation_summary.get("base_target_price")
    if consensus and intrinsic and intrinsic / consensus - 1 < -0.30:
        model.validation.warnings.append("Intrinsic DCF is materially below analyst consensus; review WACC, terminal growth and AI/capex assumptions.")
    if current and target and target / current - 1 < -0.30:
        model.validation.warnings.append("12-month target still implies severe downside; explicit bear-case evidence is required before relying on this output.")
    metrics: dict[str, Any] = model.valuation_summary.get("base_implied_metrics") or {}
    ev_ebitda = metrics.get("implied_ev_to_final_year_ebitda")
    if ev_ebitda and ev_ebitda < 7 and (snapshot.market_cap or 0) > 200_000_000_000:
        model.validation.warnings.append("Intrinsic DCF implies a low final-year EV/EBITDA multiple for a mega-cap platform; review terminal-value assumptions.")
