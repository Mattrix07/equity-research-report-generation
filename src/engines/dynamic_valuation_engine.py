"""Dynamic valuation engine.

The report is framed around a 12-month target price. DCF is the primary
valuation anchor for operating companies, while trading comparables and
sector-specific methods are used as triangulation checks. Specialist valuation
methods remain available for banks, insurers, mining and pipeline-heavy biotech,
but the output is still reconciled into a one-year target-price framework.
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

DCF_PRIMARY_WEIGHT = 0.80
COMPS_SECONDARY_WEIGHT = 0.15
SECTOR_TERTIARY_WEIGHT = 0.05


def _recommendation(current_price: float | None, target_price: float | None) -> tuple[str, float | None]:
    if not current_price or not target_price:
        return "REVIEW", None
    upside = target_price / current_price - 1
    if upside >= 0.15:
        return "BUY", upside
    if upside <= -0.10:
        return "SELL", upside
    return "HOLD", upside


def _relative_valuation(snapshot: MarketSnapshot, comps: dict[str, Any]) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    implied_price = comps.get("implied_price")
    if implied_price:
        return implied_price, {
            "method": "peer_median_ev_ebitda",
            "implied_price": implied_price,
            "median_ev_ebitda": comps.get("median_ev_ebitda"),
            "median_ev_revenue": comps.get("median_ev_revenue"),
            "peer_count": len(comps.get("peer_table", [])),
        }, warnings

    current = snapshot.current_price
    if not current:
        warnings.append("Current price unavailable; relative valuation could not be anchored.")
        return None, {}, warnings

    if snapshot.forward_pe and snapshot.forward_pe > 0:
        if snapshot.forward_pe < 18:
            adjustment = 1.05
        elif snapshot.forward_pe > 35:
            adjustment = 0.95
        else:
            adjustment = 1.00
    else:
        adjustment = 1.00
        warnings.append("Forward P/E unavailable; relative valuation anchored to current market price with no multiple adjustment.")
    return current * adjustment, {"method": "market_anchor_forward_pe", "adjustment": adjustment}, warnings


def _one_year_dcf_led_valuation(
    snapshot: MarketSnapshot,
    dcfs: dict[str, DCFOutput],
    comps: dict[str, Any],
    sector_price: float | None,
    sanity: list[str],
) -> tuple[float | None, dict[str, Any], list[str]]:
    """Reconcile valuation into a DCF-led 12-month target price."""
    warnings: list[str] = []
    current = snapshot.current_price
    bear_dcf = dcfs.get("bear").target_price if dcfs.get("bear") else None
    base_dcf = dcfs.get("base").target_price if dcfs.get("base") else None
    bull_dcf = dcfs.get("bull").target_price if dcfs.get("bull") else None
    comps_price, comps_output, comps_warnings = _relative_valuation(snapshot, comps)
    warnings.extend(comps_warnings)

    if not base_dcf:
        warnings.append("Base DCF target price is unavailable; valuation cannot be DCF-led.")
        return comps_price or sector_price or current, {
            "bear_dcf": bear_dcf,
            "base_dcf": base_dcf,
            "bull_dcf": bull_dcf,
            "comps": comps_output,
            "sector_price": sector_price,
            "weights": {},
        }, warnings

    if current and (base_dcf > current * 1.75 or base_dcf < current * 0.50):
        sanity.append(
            "Base DCF is materially detached from the current share price. It is preserved as the primary intrinsic valuation output, but the report should explain the assumptions driving the gap."
        )

    components: list[tuple[str, float, float]] = [("DCF base case", base_dcf, DCF_PRIMARY_WEIGHT)]
    if comps_price:
        components.append(("Trading comparables", comps_price, COMPS_SECONDARY_WEIGHT))
    else:
        warnings.append("Trading comps did not produce an implied price; peer data may be incomplete.")
    if sector_price:
        components.append(("Sector-specific method", sector_price, SECTOR_TERTIARY_WEIGHT))

    total_weight = sum(weight for _, _, weight in components)
    target = sum(price * weight for _, price, weight in components) / total_weight if total_weight else base_dcf

    output = {
        "framework": "12-month DCF-led target price",
        "bear_dcf": bear_dcf,
        "base_dcf": base_dcf,
        "bull_dcf": bull_dcf,
        "comps": comps_output,
        "sector_price": sector_price,
        "weights": {name: weight for name, _, weight in components},
        "weighted_components": [{"method": name, "price": price, "weight": weight} for name, price, weight in components],
        "target_price": target,
    }
    return target, output, warnings


def _bank_insurer_valuation(snapshot: MarketSnapshot, comps: dict[str, Any]) -> tuple[float | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    if snapshot.book_value and snapshot.price_to_book and snapshot.current_price:
        current_pb = snapshot.price_to_book
        roe = snapshot.return_on_equity or 0.10
        justified_pb = max(min((roe - 0.03) / 0.08, 2.5), 0.5)
        target = snapshot.book_value * ((current_pb + justified_pb) / 2)
        return target, {"method": "roe_pbv", "current_pb": current_pb, "justified_pb": justified_pb, "roe": roe}, warnings
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
        "Pipeline rNPV is not used as a primary value driver unless pipeline evidence is available.",
    ]
    return None, {"method": "rnpv_required_not_populated"}, warnings


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
        "dcf_scenarios": {k: v.model_dump() for k, v in dcfs.items()},
        "valuation_weights": {
            "dcf_base_case": DCF_PRIMARY_WEIGHT,
            "trading_comps": COMPS_SECONDARY_WEIGHT,
            "sector_method_if_available": SECTOR_TERTIARY_WEIGHT,
        },
    }

    primary = classification.valuation_methods[0] if classification.valuation_methods else "mature_operating_dcf"

    sector_price: float | None = None
    sector_output: dict[str, Any] = {}
    sector_warnings: list[str] = []

    if primary == "bank_insurer_roe_pbv":
        sector_price, sector_output, sector_warnings = _bank_insurer_valuation(snapshot, comps)
    elif primary == "mining_nav":
        sector_price, sector_output, sector_warnings = _mining_nav_placeholder(snapshot)
    elif primary in {"biotech_rnpv", "royalty_healthcare_sotp"}:
        sector_price, sector_output, sector_warnings = _biotech_rnpv_placeholder(snapshot)
    elif primary == "saas_unit_economics":
        sector_price, sector_output, sector_warnings = _relative_valuation(snapshot, comps)
    else:
        sector_output = {"method": "no_separate_sector_price", "comment": "DCF and trading comparables are primary."}

    target, dcf_led_output, warnings = _one_year_dcf_led_valuation(snapshot, dcfs, comps, sector_price, sanity)

    valuation_outputs["dcf_led_12_month_reconciliation"] = dcf_led_output
    valuation_outputs[str(primary)] = sector_output
    evidence_gaps.extend(warnings)
    evidence_gaps.extend(sector_warnings)
    evidence_gaps.extend(dynamic_assumptions.warnings)

    recommendation, upside = _recommendation(snapshot.current_price, target)
    if evidence_gaps and recommendation != "REVIEW":
        sanity.append("Recommendation should be reviewed because key valuation evidence is incomplete.")

    confidence = 65
    if evidence_gaps:
        confidence -= min(len(evidence_gaps) * 4, 25)
    if sanity:
        confidence -= min(len(sanity) * 4, 15)
    confidence = max(confidence, 30)

    return DynamicValuationResult(
        selected_methods=classification.valuation_methods,
        primary_method="mature_operating_dcf" if primary not in {"bank_insurer_roe_pbv", "mining_nav"} else primary,
        recommendation=recommendation,
        target_price=target,
        upside_downside=upside,
        confidence=confidence,
        method_weighting={
            "DCF base case": DCF_PRIMARY_WEIGHT,
            "Trading comparables": COMPS_SECONDARY_WEIGHT,
            "Sector-specific method when supported": SECTOR_TERTIARY_WEIGHT,
        },
        valuation_outputs=valuation_outputs,
        investment_thesis=(
            "The valuation is framed as a 12-month target price and is led by the base-case DCF. "
            "Trading comparables and sector-specific methods are used to triangulate the valuation range, not to replace the DCF unless the company is a bank, insurer, finite-life resource asset or unsupported pipeline case."
        ),
        valuation_rationale=classification.rationale,
        key_assumptions=dynamic_assumptions.sources_and_evidence,
        key_risks=[
            "DCF outputs are highly sensitive to terminal growth, WACC and margin assumptions.",
            "Trading comparables can be distorted by peer selection, one-off earnings and cycle timing.",
            "Pipeline rNPV, NAV or ROE/PBV outputs require source evidence before being used as primary valuation methods.",
        ],
        evidence_gaps=evidence_gaps,
        sanity_checks=sanity,
    )
