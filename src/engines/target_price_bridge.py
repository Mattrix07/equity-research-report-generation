"""12-month target-price bridge and valuation sanity checks.

The DCF engine produces an intrinsic value. This module converts that intrinsic
value into a DCF-led 12-month target-price range by adding observable analyst
price target context and current-market anchoring. The objective is not to force
consensus, but to stop a single long-term DCF from being mislabelled as a
12-month target without a reconciliation bridge.
"""
from __future__ import annotations

from typing import Any

from src.engines.model_validation_engine import ValidatedFinancialModel
from src.schemas import MarketSnapshot


def consensus_target(snapshot: MarketSnapshot) -> float | None:
    if snapshot.target_median_price and snapshot.target_median_price > 0:
        return snapshot.target_median_price
    if snapshot.target_mean_price and snapshot.target_mean_price > 0:
        return snapshot.target_mean_price
    return None


def _target_12m(snapshot: MarketSnapshot, intrinsic_price: float | None, scenario: str) -> float | None:
    if intrinsic_price is None:
        return None
    current = snapshot.current_price
    consensus = consensus_target(snapshot)
    if not current or not consensus:
        return intrinsic_price
    if scenario == "bear":
        return 0.70 * intrinsic_price + 0.20 * current + 0.10 * consensus
    if scenario == "bull":
        return 0.55 * intrinsic_price + 0.15 * current + 0.30 * consensus
    return 0.60 * intrinsic_price + 0.15 * current + 0.25 * consensus


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


def apply_12m_target_bridge(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> ValidatedFinancialModel:
    """Mutate valuation_summary so report target is a 12-month bridge.

    Preserves the raw intrinsic DCF outputs separately for audit.
    """
    bear_intrinsic = model.scenarios["bear"].dcf.target_price
    base_intrinsic = model.scenarios["base"].dcf.target_price
    bull_intrinsic = model.scenarios["bull"].dcf.target_price
    bear_12m = _target_12m(snapshot, bear_intrinsic, "bear")
    base_12m = _target_12m(snapshot, base_intrinsic, "base")
    bull_12m = _target_12m(snapshot, bull_intrinsic, "bull")
    current = snapshot.current_price
    model.valuation_summary.update({
        "intrinsic_dcf_bear_target_price": bear_intrinsic,
        "intrinsic_dcf_base_target_price": base_intrinsic,
        "intrinsic_dcf_bull_target_price": bull_intrinsic,
        "bear_target_price": bear_12m,
        "base_target_price": base_12m,
        "bull_target_price": bull_12m,
        "analyst_consensus_target": consensus_target(snapshot),
        "analyst_target_mean": snapshot.target_mean_price,
        "analyst_target_median": snapshot.target_median_price,
        "analyst_target_high": snapshot.target_high_price,
        "analyst_target_low": snapshot.target_low_price,
        "number_of_analyst_opinions": snapshot.number_of_analyst_opinions,
        "base_upside_downside": (base_12m / current - 1) if current and base_12m else None,
        "base_intrinsic_dcf_upside_downside": (base_intrinsic / current - 1) if current and base_intrinsic else None,
        "base_implied_metrics": implied_metrics(model),
    })
    _add_warnings(model, snapshot)
    return model


def _add_warnings(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> None:
    consensus = consensus_target(snapshot)
    current = snapshot.current_price
    intrinsic = model.valuation_summary.get("intrinsic_dcf_base_target_price")
    target_12m = model.valuation_summary.get("base_target_price")
    if consensus and intrinsic and intrinsic / consensus - 1 < -0.30:
        model.validation.warnings.append(
            "Intrinsic DCF is more than 30% below analyst consensus. The workbook now separates intrinsic DCF from the DCF-led 12-month target bridge."
        )
    if current and target_12m and target_12m / current - 1 < -0.30:
        model.validation.warnings.append(
            "12-month target still implies severe downside after consensus/current-price triangulation; review assumptions before relying on the output."
        )
    metrics: dict[str, Any] = model.valuation_summary.get("base_implied_metrics") or {}
    ev_ebitda = metrics.get("implied_ev_to_final_year_ebitda")
    if ev_ebitda and ev_ebitda < 7 and (snapshot.market_cap or 0) > 200_000_000_000:
        model.validation.warnings.append(
            "Base DCF implies a low final-year EV/EBITDA multiple for a mega-cap platform; review WACC, terminal growth and terminal-value assumptions."
        )
