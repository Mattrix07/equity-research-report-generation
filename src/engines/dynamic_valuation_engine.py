"""Dynamic valuation engine.

This engine treats generic DCF as one cross-check, not the final authority.
The valuation method is selected by the company classifier and routed into a
method-specific valuation approach.
"""
from __future__ import annotations

from statistics import median
from typing import Any

from src.schemas import (
    CompanyClassification,
    DCFOutput,
    DynamicAssumptions,
    DynamicValuationResult,
    ForecastRow,
    HistoricalFinancials,
    MarketSnapshot,
)


def _recommendation(current_price: float | None, target_price: float | None) -> tuple[str, float | None]:
    if not current_price or not target_price:
        return "REVIEW", None
    upside = target_price / current_price - 1
    if upside >= 0.15:
        return "BUY", upside
    if upside <= -0.10:
        return "SELL", upside
    return "HOLD", upside


def _last(values: dict[str, float]) -> float | None:
    if not values:
        return None
    return values[sorted(values.keys())[-1]]


def _median(values: list[float | None]) -> float | None:
    cleaned = [v for v in values if v is not None and v > 0]
    return float(median(cleaned)) if cleaned else None


def _cap_to_reasonable_market_range(price: float | None, current: float | None, sanity: list[str]) -> float | None:
    if not price or not current:
        return price
    lower = current * 0.5
    upper = current * 1.75
    if price < lower:
        sanity.append(
            f"Raw model target {price:.2f} was below 50% of current price without enough evidence; capped into review range."
        )
        return lower
    if price > upper:
        sanity.append(
            f"Raw model target {price:.2f} was above 175% of current price without enough evidence; capped into review range."
        )
        return upper
    return price


def _relative_valuation(snapshot: MarketSnapshot, comps: dict[str, Any]) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    implied_price = comps.get("implied_price")
    if implied_price:
        return implied_price, {"method": "peer_median_ev_ebitda", "implied_price": implied_price}, warnings

    # Fallback for very large mature companies where generic DCF may be distorted:
    # use current market price as anchor and adjust only modestly for forward PE context.
    current = snapshot.current_price
    if not current:
        warnings.append("Current price unavailable; relative valuation could not be anchored.")
        return None, {}, warnings

    if snapshot.forward_pe and snapshot.forward_pe > 0:
        if snapshot.forward_pe < 18:
            adjustment = 1.10
        elif snapshot.forward_pe > 35:
            adjustment = 0.90
        else:
            adjustment = 1.00
    else:
        adjustment = 1.00
        warnings.append("Forward P/E unavailable; relative valuation anchored to current market price with no multiple adjustment.")
    return current * adjustment, {"method": "market_anchor_forward_pe", "adjustment": adjustment}, warnings


def _bank_insurer_valuation(snapshot: MarketSnapshot, comps: dict[str, Any]) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    if snapshot.book_value and snapshot.price_to_book and snapshot.current_price:
        current_pb = snapshot.price_to_book
        roe = snapshot.return_on_equity or 0.10
        justified_pb = max(min((roe - 0.03) / 0.08, 2.5), 0.5)
        target = snapshot.book_value * ((current_pb + justified_pb) / 2)
        return target, {"current_pb": current_pb, "justified_pb": justified_pb, "roe": roe}, warnings
    warnings.append("Book value, P/B or ROE unavailable; bank/insurer valuation requires balance-sheet-specific data.")
    return _relative_valuation(snapshot, comps)


def _mining_nav_placeholder(snapshot: MarketSnapshot) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings = [
        "Mining NAV requires reserve life, production schedule, commodity price deck, sustaining capex and closure costs.",
        "The model intentionally avoids applying generic perpetual terminal growth to a finite-life resource asset.",
    ]
    return snapshot.current_price, {"method": "nav_required_market_anchor_placeholder"}, warnings


def _biotech_rnpv_placeholder(snapshot: MarketSnapshot) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings = [
        "Healthcare pipeline valuation requires asset-level peak sales, launch timing, clinical stage, probability of success and pricing assumptions.",
        "Tufts-style probability assumptions should be applied once asset-level pipeline data is available.",
    ]
    return snapshot.current_price, {"method": "rnpv_required_market_anchor_placeholder"}, warnings


def _mature_operating_valuation(
    snapshot: MarketSnapshot,
    dcfs: dict[str, DCFOutput],
    comps: dict[str, Any],
    sanity: list[str],
) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    base_dcf_price = dcfs.get("base").target_price if dcfs.get("base") else None
    relative_price, relative_output, relative_warnings = _relative_valuation(snapshot, comps)
    warnings.extend(relative_warnings)

    current = snapshot.current_price
    model_prices = []
    weights = []
    if base_dcf_price:
        dcf_weight = 0.35
        if current and (base_dcf_price < current * 0.5 or base_dcf_price > current * 1.75):
            dcf_weight = 0.15
            sanity.append(
                "Base DCF is materially detached from current market context, so it is treated as a low-weight cross-check rather than final valuation."
            )
        model_prices.append(base_dcf_price)
        weights.append(dcf_weight)
    if relative_price:
        model_prices.append(relative_price)
        weights.append(1 - sum(weights) if weights else 1.0)

    if not model_prices:
        warnings.append("No mature operating valuation output available.")
        return None, {"base_dcf_price": base_dcf_price, "relative": relative_output}, warnings

    target = sum(p * w for p, w in zip(model_prices, weights)) / sum(weights)
    target = _cap_to_reasonable_market_range(target, current, sanity)
    return target, {"base_dcf_price": base_dcf_price, "relative": relative_output, "weights": weights}, warnings


def run_dynamic_valuation(
    snapshot: MarketSnapshot,
    historicals: HistoricalFinancials,
    forecasts: dict[str, list[ForecastRow]],
    dcfs: dict[str, DCFOutput],
    comps: dict[str, Any],
    classification: CompanyClassification,
    dynamic_assumptions: DynamicAssumptions,
) -> DynamicValuationResult:
    sanity: list[str] = []
    evidence_gaps: list[str] = []
    valuation_outputs: dict[str, Any] = {
        "classification": classification.model_dump(),
        "dynamic_assumptions": dynamic_assumptions.model_dump(),
        "baseline_dcf_cross_check": {k: v.model_dump() for k, v in dcfs.items()},
    }

    primary = classification.valuation_methods[0] if classification.valuation_methods else "insufficient_data_review"

    if primary == "bank_insurer_roe_pbv":
        target, output, warnings = _bank_insurer_valuation(snapshot, comps)
    elif primary == "mining_nav":
        target, output, warnings = _mining_nav_placeholder(snapshot)
    elif primary in {"biotech_rnpv", "royalty_healthcare_sotp"}:
        target, output, warnings = _biotech_rnpv_placeholder(snapshot)
    elif primary in {"saas_unit_economics", "mature_operating_dcf", "sotp", "asset_heavy_industrial"}:
        target, output, warnings = _mature_operating_valuation(snapshot, dcfs, comps, sanity)
    elif primary == "relative_valuation":
        target, output, warnings = _relative_valuation(snapshot, comps)
    else:
        target, output, warnings = snapshot.current_price, {"method": "review_required"}, ["Insufficient data for automated valuation."]

    valuation_outputs[str(primary)] = output
    evidence_gaps.extend(warnings)
    evidence_gaps.extend(dynamic_assumptions.warnings)

    recommendation, upside = _recommendation(snapshot.current_price, target)
    if evidence_gaps and recommendation != "REVIEW":
        sanity.append("Recommendation should be reviewed because key valuation evidence is incomplete.")

    confidence = 60
    if evidence_gaps:
        confidence -= min(len(evidence_gaps) * 5, 25)
    if sanity:
        confidence -= min(len(sanity) * 5, 15)
    confidence = max(confidence, 25)

    return DynamicValuationResult(
        selected_methods=classification.valuation_methods,
        primary_method=primary,
        recommendation=recommendation,
        target_price=target,
        upside_downside=upside,
        confidence=confidence,
        method_weighting={str(primary): 1.0},
        valuation_outputs=valuation_outputs,
        investment_thesis=(
            f"The valuation is routed as {classification.primary_type}, using {primary} as the primary framework. "
            "The generic DCF is retained only as a baseline cross-check and is not allowed to dominate the final target price when it conflicts with company context."
        ),
        valuation_rationale=classification.rationale,
        key_assumptions=dynamic_assumptions.sources_and_evidence,
        key_risks=[
            "Valuation method may be incomplete without primary filings and sector-specific operating drivers.",
            "Public market data can be stale, incomplete or distorted by one-off items.",
            "LLM and analyst review should challenge the selected valuation framework before relying on the result.",
        ],
        evidence_gaps=evidence_gaps,
        sanity_checks=sanity,
    )
