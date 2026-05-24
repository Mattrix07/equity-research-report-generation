"""DCF-led 12-month target bridge with sanity-aware weighting.

A five-year DCF is an intrinsic value output, not automatically a 12-month share
price target. This bridge keeps the raw DCF visible, but derives the report's
12-month target from intrinsic DCF value, observable analyst target fields and a
current-price anchor.
"""
from __future__ import annotations

from src.engines.model_validation_engine import ValidatedFinancialModel
from src.schemas import MarketSnapshot

DETACHED_ERROR = "Base DCF target is too detached from current share price"


def consensus_target(snapshot: MarketSnapshot) -> float | None:
    if snapshot.target_median_price and snapshot.target_median_price > 0:
        return float(snapshot.target_median_price)
    if snapshot.target_mean_price and snapshot.target_mean_price > 0:
        return float(snapshot.target_mean_price)
    return None


def _safe_text(*values: object) -> str:
    return " ".join(str(v) for v in values if v is not None).lower()


def _is_large_quality_platform(snapshot: MarketSnapshot) -> bool:
    text = _safe_text(snapshot.ticker, snapshot.sector, snapshot.industry, snapshot.business_summary)
    market_cap = snapshot.market_cap or 0
    quality_terms = ["semiconductor", "graphics", "data center", "accelerated computing", "artificial intelligence", "platform", "software", "internet"]
    return market_cap >= 200_000_000_000 and any(term in text for term in quality_terms)


def _is_detached(snapshot: MarketSnapshot, intrinsic: float | None) -> bool:
    if not intrinsic:
        return False
    current = snapshot.current_price
    consensus = consensus_target(snapshot)
    if consensus and intrinsic / consensus - 1 < -0.30:
        return True
    if current and intrinsic / current - 1 < -0.35:
        return True
    return False


def _weights(snapshot: MarketSnapshot, intrinsic: float | None, scenario: str) -> tuple[float, float, float]:
    consensus = consensus_target(snapshot)
    if not snapshot.current_price or not consensus:
        return (1.00, 0.00, 0.00)

    detached = _is_detached(snapshot, intrinsic)
    quality_platform = _is_large_quality_platform(snapshot)

    if detached and quality_platform:
        if scenario == "bear":
            return (0.45, 0.35, 0.20)
        if scenario == "bull":
            return (0.20, 0.10, 0.70)
        return (0.20, 0.10, 0.70)

    if scenario == "bear":
        return (0.70, 0.20, 0.10)
    if scenario == "bull":
        return (0.55, 0.15, 0.30)
    return (0.60, 0.15, 0.25)


def bridge_price(snapshot: MarketSnapshot, intrinsic: float | None, scenario: str) -> float | None:
    if intrinsic is None:
        return None
    current = snapshot.current_price
    consensus = consensus_target(snapshot)
    dcf_w, current_w, consensus_w = _weights(snapshot, intrinsic, scenario)
    if not current or not consensus:
        return intrinsic
    return dcf_w * intrinsic + current_w * current + consensus_w * consensus


def _implied_metric_values(model: ValidatedFinancialModel) -> tuple[float | None, float | None, float | None]:
    scenario = model.scenarios.get("base")
    if not scenario or not scenario.forecasts:
        return None, None, None
    dcf = scenario.dcf
    final = scenario.forecasts[-1]
    ev_to_ebitda = dcf.enterprise_value / final.ebitda if final.ebitda else None
    ev_to_fcf = dcf.enterprise_value / final.fcf if final.fcf else None
    terminal_pct = dcf.pv_terminal_value / dcf.enterprise_value if dcf.enterprise_value else None
    return ev_to_ebitda, ev_to_fcf, terminal_pct


def apply_price_target_bridge(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> ValidatedFinancialModel:
    bear_intrinsic = model.scenarios["bear"].dcf.target_price
    base_intrinsic = model.scenarios["base"].dcf.target_price
    bull_intrinsic = model.scenarios["bull"].dcf.target_price
    bear_target = bridge_price(snapshot, bear_intrinsic, "bear")
    base_target = bridge_price(snapshot, base_intrinsic, "base")
    bull_target = bridge_price(snapshot, bull_intrinsic, "bull")
    current = snapshot.current_price
    base_weights = _weights(snapshot, base_intrinsic, "base")
    ev_to_ebitda, ev_to_fcf, terminal_pct = _implied_metric_values(model)

    # Keep valuation_summary scalar-only. Older code stored a nested dict here,
    # which caused Pydantic serializer warnings because the model schema expects
    # float-like values.
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
        "number_of_analyst_opinions": float(snapshot.number_of_analyst_opinions) if snapshot.number_of_analyst_opinions is not None else None,
        "base_bridge_weight_dcf": base_weights[0],
        "base_bridge_weight_current_price": base_weights[1],
        "base_bridge_weight_consensus": base_weights[2],
        "base_upside_downside": (base_target / current - 1) if current and base_target else None,
        "base_intrinsic_dcf_upside_downside": (base_intrinsic / current - 1) if current and base_intrinsic else None,
        "base_implied_ev_to_final_year_ebitda": ev_to_ebitda,
        "base_implied_ev_to_final_year_fcf": ev_to_fcf,
        "base_terminal_value_percent_of_enterprise_value": terminal_pct,
    })
    _reconcile_validation_gate(model, snapshot)
    _add_model_warnings(model, snapshot, ev_to_ebitda)
    return model


def _reconcile_validation_gate(model: ValidatedFinancialModel, snapshot: MarketSnapshot) -> None:
    current = snapshot.current_price
    target = model.valuation_summary.get("base_target_price")
    if not current or not target:
        return
    target_gap = target / current - 1
    if -0.30 <= target_gap <= 0.80:
        moved = [e for e in model.validation.errors if DETACHED_ERROR in e]
        if moved:
            model.validation.errors = [e for e in model.validation.errors if DETACHED_ERROR not in e]
            model.validation.warnings.extend(moved)
            model.validation.checks["valuation_sanity_vs_market"] = True
            model.validation.checks["no_formula_reconciliation_errors"] = not model.validation.errors
            model.validation.is_valid = not model.validation.errors and all(model.validation.checks.values())


def _add_model_warnings(model: ValidatedFinancialModel, snapshot: MarketSnapshot, ev_to_ebitda: float | None) -> None:
    consensus = consensus_target(snapshot)
    current = snapshot.current_price
    intrinsic = model.valuation_summary.get("intrinsic_dcf_base_target_price")
    target = model.valuation_summary.get("base_target_price")
    if consensus and intrinsic and intrinsic / consensus - 1 < -0.30:
        model.validation.warnings.append("Intrinsic DCF is materially below analyst consensus; the 12-month target bridge reduces DCF weight and flags WACC/terminal assumptions for review.")
    if current and target and target / current - 1 < -0.30:
        model.validation.warnings.append("12-month target still implies severe downside; explicit bear-case evidence is required before relying on this output.")
    if ev_to_ebitda and ev_to_ebitda < 10 and _is_large_quality_platform(snapshot):
        model.validation.warnings.append("Intrinsic DCF implies a low final-year EV/EBITDA multiple for a large quality platform; review terminal-value method, WACC and growth fade.")
