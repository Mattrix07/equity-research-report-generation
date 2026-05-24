"""Iterative LLM-assisted model-first workflow.

This workflow implements the target architecture:
- sequential Manager planning;
- parallel-ready data collection;
- LLM-assisted peer selection;
- parallel LLM assumption agents for forecast, WACC and terminal value;
- deterministic Python DCF calculation;
- validation gate;
- bounded revision loop;
- LLM investment committee;
- report and Excel generation only after the model is validated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.agents.assumption_derivation_agent import derive_dynamic_assumptions
from src.agents.company_classifier_agent import classify_company
from src.agents.evidence_agent import build_company_evidence_pack
from src.agents.financial_model_planner_agent import build_financial_model_plan
from src.agents.llm_committee import run_llm_committee_sync
from src.agents.llm_model_agents import run_llm_model_assumption_agents_sync
from src.agents.llm_peer_selection_agent import select_peers_with_llm_sync
from src.agents.peer_selector_agent import _candidate_shortlist, select_dynamic_peer_tickers
from src.agents.report_agents import (
    build_report_plan,
    business_model_agent,
    commercial_drivers_agent,
    company_overview_agent,
    competitive_landscape_agent,
    executive_summary_agent,
    front_page_agent,
    historical_financials_agent,
    market_agent,
    qa_agent,
    risk_agent,
    technical_agent,
    valuation_agent,
)
from src.data.yfinance_client import fetch_historical_financials, fetch_market_snapshot, fetch_peer_snapshot, fetch_price_history
from src.engines.chart_engine import chart_forecast_revenue, chart_margin_forecast, chart_price_technicals
from src.engines.comps_engine import run_comps
from src.engines.dynamic_valuation_engine import run_dynamic_valuation
from src.engines.iterative_model_validation_engine import build_model_with_assumptions, raise_if_model_invalid
from src.engines.price_target_bridge_v2 import apply_price_target_bridge
from src.engines.sensitivity_engine import growth_margin_sensitivity, wacc_terminal_growth_sensitivity
from src.engines.technical_engine import run_technical_analysis
from src.report.renderer import render_report
from src.report.validated_model_excel_exporter import export_excel_model
from src.schemas import FullReport, LLMCommitteeOutput, ReportRequest, SectionOutput

ProgressCallback = Callable[[dict[str, Any]], None]


def _emit(progress_callback: ProgressCallback | None, *, agent: str, status: str, message: str, phase: str, mode: str = "sequential", group: str | None = None, reasoning_steps: list[str] | None = None, payload: dict[str, Any] | None = None) -> None:
    if progress_callback:
        progress_callback({
            "agent": agent,
            "status": status,
            "message": message,
            "phase": phase,
            "mode": mode,
            "group": group,
            "reasoning_steps": reasoning_steps or [],
            "payload": payload or {},
        })


def _recommendation(current_price: float | None, target_price: float | None) -> tuple[str, float | None]:
    if not current_price or not target_price:
        return "REVIEW", None
    upside = target_price / current_price - 1
    if upside >= 0.15:
        return "BUY", upside
    if upside <= -0.10:
        return "SELL", upside
    return "HOLD", upside


def _validation_section(model) -> SectionOutput:
    summary = model.valuation_summary
    return SectionOutput(
        title="Financial model validation gate",
        narrative=(
            "The report is generated only after the model passes validation. The model now separates intrinsic DCF value from the DCF-led 12-month target bridge."
        ),
        bullets=[
            f"Model valid: {model.validation.is_valid}",
            f"Iteration count: {model.iteration_count}",
            f"Historical years available: {model.data_quality.historical_years_available}/5",
            f"Intrinsic base DCF: {summary.get('intrinsic_dcf_base_target_price'):,.2f}" if summary.get("intrinsic_dcf_base_target_price") else "Intrinsic base DCF: n/a",
            f"12-month base target: {summary.get('base_target_price'):,.2f}" if summary.get("base_target_price") else "12-month base target: n/a",
            f"Analyst consensus anchor: {summary.get('analyst_consensus_target'):,.2f}" if summary.get("analyst_consensus_target") else "Analyst consensus anchor: n/a",
        ],
        tables=[
            {"name": "Validation checks", "rows": [{"check": k, "passed": v} for k, v in model.validation.checks.items()]},
            {"name": "Validation messages", "rows": [{"type": "error", "message": e} for e in model.validation.errors] + [{"type": "warning", "message": w} for w in model.validation.warnings]},
        ],
    )


def _llm_model_section(model, llm_pack, peer_selection) -> SectionOutput:
    rows = []
    if llm_pack:
        rows.extend([
            {"agent": "Forecast Assumption Agent", "output": str(llm_pack.forecast)[:900]},
            {"agent": "WACC Agent", "output": str(llm_pack.wacc)[:900]},
            {"agent": "Terminal Value Agent", "output": str(llm_pack.terminal_value)[:900]},
            {"agent": "Validation Revision Agent", "output": str(llm_pack.validation_revision)[:900]},
        ])
    return SectionOutput(
        title="LLM-assisted model agents",
        narrative=(
            "LLM agents propose peers, forecast assumptions, WACC and terminal value. Python performs valuation calculations and the validation gate decides whether outputs can be used."
        ),
        bullets=[
            f"LLM assumption agents enabled: {bool(llm_pack and llm_pack.enabled)}",
            f"LLM peer selector enabled: {bool(peer_selection and peer_selection.enabled)}",
            f"Peer rationale: {peer_selection.peer_rationale}" if peer_selection and peer_selection.peer_rationale else "Peer rationale: n/a",
            *([f"Warning: {w}" for w in llm_pack.warnings[:4]] if llm_pack else []),
        ],
        tables=[{"name": "LLM model agent outputs", "rows": rows}],
    )


def _llm_committee_section(llm_committee: LLMCommitteeOutput) -> SectionOutput:
    if not llm_committee.enabled:
        return SectionOutput(title="LLM investment committee", narrative="The LLM investment committee is disabled. Set ENABLE_LLM_COMMITTEE=true and provide an OpenAI-compatible API key to activate it.")
    return SectionOutput(
        title="LLM investment committee",
        narrative=llm_committee.final_thesis or "Committee generated agent opinions; review the table for detail.",
        bullets=[
            f"Committee recommendation: {llm_committee.final_recommendation}" if llm_committee.final_recommendation else "Committee recommendation: n/a",
            f"Committee confidence: {llm_committee.final_confidence}/100" if llm_committee.final_confidence is not None else "Committee confidence: n/a",
            *[f"Risk: {risk}" for risk in llm_committee.final_risks[:5]],
            *[f"Evidence gap: {gap}" for gap in llm_committee.final_evidence_gaps[:5]],
        ],
        tables=[{"name": "LLM agent opinions", "rows": [op.model_dump() for op in llm_committee.opinions]}],
    )


def _internet_platform_candidates(snapshot) -> list[str] | None:
    text = f"{snapshot.ticker} {snapshot.sector} {snapshot.industry} {snapshot.business_summary}".lower()
    if snapshot.ticker.upper() in {"META", "GOOGL", "SNAP", "PINS", "RDDT", "TTD"} or any(term in text for term in ["advertising", "social", "family of apps", "internet content", "digital"]):
        return ["GOOGL", "SNAP", "PINS", "RDDT", "TTD", "NFLX", "SPOT", "ROKU", "AMZN", "MSFT", "TCEHY", "BIDU"]
    return None


def _apply_bridge(model, snapshot):
    model = apply_price_target_bridge(model, snapshot)
    return model


def generate_report(request: ReportRequest, progress_callback: ProgressCallback | None = None) -> FullReport:
    _emit(progress_callback, agent="Manager", status="running", phase="planning", message="Planning model-first iterative research workflow.", reasoning_steps=["Confirm ticker and report type.", "Run financial model before report writing.", "Use LLMs for peer and assumption judgement; Python remains calculation engine."])
    snapshot = fetch_market_snapshot(request.ticker, request.company_name)
    if request.current_price:
        snapshot.current_price = request.current_price
    if request.sector_hint:
        snapshot.sector = request.sector_hint
    plan = build_report_plan(snapshot.ticker, snapshot.company_name, request.report_type, snapshot.sector)
    _emit(progress_callback, agent="Manager", status="complete", phase="planning", message=f"Plan created for {snapshot.ticker}.", payload={"ticker": snapshot.ticker, "report_type": request.report_type})

    _emit(progress_callback, agent="Financial Data Agent", status="running", phase="data_collection", mode="parallel-ready", group="Data", message="Fetching financial statements and market data, including yfinance analyst target fields where available.")
    historicals = fetch_historical_financials(snapshot.ticker)
    _emit(progress_callback, agent="Financial Data Agent", status="complete", phase="data_collection", mode="parallel-ready", group="Data", message=f"Collected {len(historicals.revenue)} revenue years.")

    _emit(progress_callback, agent="LLM Peer Selection Agent", status="running", phase="peer_selection", mode="sequential", message="Selecting comparable companies using LLM judgement and Python verification.", reasoning_steps=["Create a candidate shortlist from sector and business description.", "Use an internet-platform shortlist for digital advertising/social media businesses.", "Ask LLM to select most relevant peers and explain exclusions.", "Verify selected tickers through market data before use."])
    if request.peers:
        peer_selection = None
        peers = [p.upper().strip() for p in request.peers if p.strip()][:5]
    else:
        candidate_peers = _internet_platform_candidates(snapshot) or _candidate_shortlist(snapshot, max_candidates=28)
        peer_selection = select_peers_with_llm_sync(snapshot, candidate_peers, max_peers=5)
        peers = peer_selection.selected_tickers[:5] if peer_selection and peer_selection.selected_tickers else []
        if not peers:
            peers = select_dynamic_peer_tickers(snapshot, [], min_peers=4, max_peers=5)
    peer_snapshots = fetch_peer_snapshot(peers) if peers else []
    _emit(progress_callback, agent="LLM Peer Selection Agent", status="complete", phase="peer_selection", message=f"Peer set selected: {', '.join(peers) if peers else 'n/a'}.", payload={"peers": peers, "llm_enabled": bool(peer_selection and peer_selection.enabled), "rationale": peer_selection.peer_rationale if peer_selection else "User supplied peers."})

    _emit(progress_callback, agent="LLM Assumption Agents", status="running", phase="assumption_derivation", mode="parallel", group="Parallel model agents", message="Running Forecast, WACC and Terminal Value agents in parallel.", reasoning_steps=["Forecast agent derives growth and margin assumptions.", "WACC agent derives cost of equity/debt and WACC.", "Terminal value agent derives terminal growth logic."])
    llm_pack = run_llm_model_assumption_agents_sync(snapshot, historicals, peers=peers)
    _emit(progress_callback, agent="LLM Assumption Agents", status="complete", phase="assumption_derivation", mode="parallel", group="Parallel model agents", message="LLM model assumptions collected and bounded for Python calculation.", payload={"enabled": llm_pack.enabled, "warnings": llm_pack.warnings})

    _emit(progress_callback, agent="Model Calculation Agent", status="running", phase="model_validation", message="Calculating intrinsic DCF and DCF-led 12-month target bridge.")
    model = _apply_bridge(build_model_with_assumptions(snapshot, historicals, llm_inputs=llm_pack.model_inputs(), iteration_count=1), snapshot)

    if not model.validation.is_valid:
        _emit(progress_callback, agent="Validation Agent", status="running", phase="model_validation", message="Initial model failed validation. Sending feedback to LLM revision agent for one controlled iteration.", payload={"errors": model.validation.errors, "warnings": model.validation.warnings})
        revision_pack = run_llm_model_assumption_agents_sync(snapshot, historicals, peers=peers, prior_model=model.model_dump(), validation_feedback=model.validation.model_dump())
        merged_inputs = llm_pack.model_inputs()
        if revision_pack.validation_revision:
            merged_inputs["validation_revision"] = revision_pack.validation_revision
        model = _apply_bridge(build_model_with_assumptions(snapshot, historicals, llm_inputs=merged_inputs, iteration_count=2), snapshot)
        if revision_pack.enabled:
            llm_pack.validation_revision = revision_pack.validation_revision
            llm_pack.warnings.extend(revision_pack.warnings)

    raise_if_model_invalid(model)
    _emit(progress_callback, agent="Validation Agent", status="complete", phase="model_validation", message="Model passed validation. Intrinsic DCF and DCF-led 12-month target bridge are approved for report generation.", payload=model.valuation_summary)

    assumptions = {name: model.scenarios[name].assumptions for name in ["bear", "base", "bull"]}
    forecasts = {name: model.scenarios[name].forecasts for name in ["bear", "base", "bull"]}
    dcfs = {name: model.scenarios[name].dcf for name in ["bear", "base", "bull"]}

    _emit(progress_callback, agent="Technical Data Agent", status="running", phase="data_collection", mode="parallel-ready", group="Data", message="Fetching technical price history.")
    price_history = fetch_price_history(snapshot.ticker)
    technicals = run_technical_analysis(price_history)
    _emit(progress_callback, agent="Technical Data Agent", status="complete", phase="data_collection", mode="parallel-ready", group="Data", message="Technical data complete.")

    company_classification = classify_company(snapshot, historicals)
    dynamic_assumptions = derive_dynamic_assumptions(snapshot, historicals, company_classification)
    financial_model_plan = build_financial_model_plan(snapshot, historicals, company_classification, dynamic_assumptions)
    evidence = build_company_evidence_pack(snapshot, historicals, company_classification, dynamic_assumptions, financial_model_plan, request.source_urls)

    net_debt = snapshot.net_debt or 0.0
    shares = snapshot.shares_outstanding
    company_ebitda = snapshot.ebitda or forecasts["base"][0].ebitda
    comps = run_comps(peer_snapshots, company_ebitda, net_debt, shares)
    comps["selected_peer_tickers"] = peers
    if peer_selection:
        comps["llm_peer_selection"] = peer_selection.__dict__

    dynamic_valuation = run_dynamic_valuation(snapshot, historicals, forecasts, dcfs, comps, company_classification, dynamic_assumptions)
    target_price = model.valuation_summary.get("base_target_price")
    recommendation, upside = _recommendation(snapshot.current_price, target_price)
    dynamic_valuation.target_price = target_price
    dynamic_valuation.recommendation = recommendation
    dynamic_valuation.upside_downside = upside
    dynamic_valuation.valuation_outputs["validated_iterative_model"] = model.model_dump()

    _emit(progress_callback, agent="LLM Investment Committee", status="running", phase="investment_committee", mode="parallel", group="Parallel LLM agents", message="Running Bull, Bear and Valuation Analysts in parallel, followed by Committee Chair synthesis.")
    llm_committee = run_llm_committee_sync(snapshot, forecasts, dcfs, technicals, comps, company_classification, dynamic_assumptions, dynamic_valuation)
    if llm_committee.enabled and llm_committee.final_recommendation:
        recommendation = llm_committee.final_recommendation
    _emit(progress_callback, agent="Committee Chair", status="complete" if llm_committee.enabled else "skipped", phase="investment_committee", mode="sequential", group="Sequential synthesis", message="Committee synthesis complete." if llm_committee.enabled else "LLM committee disabled; deterministic model remains source of truth.")

    sensitivities = [wacc_terminal_growth_sensitivity(forecasts["base"], assumptions["base"], net_debt, shares), growth_margin_sensitivity(historicals, assumptions["base"], net_debt, shares)]

    _emit(progress_callback, agent="Report Agents", status="running", phase="report_generation", message="Generating report sections from validated model and committee outputs.")
    sections = [
        front_page_agent(snapshot, recommendation, target_price, upside),
        executive_summary_agent(snapshot, dcfs["base"], recommendation),
        _validation_section(model),
        _llm_model_section(model, llm_pack, peer_selection),
        SectionOutput(title="Validated 12-month risk/reward", narrative="The report separates intrinsic DCF from the DCF-led 12-month target. LLMs inform assumptions and challenge the model; Python performs calculation and validation.", bullets=[f"Intrinsic base DCF: {model.valuation_summary.get('intrinsic_dcf_base_target_price'):,.2f}" if model.valuation_summary.get('intrinsic_dcf_base_target_price') else "Intrinsic base DCF: n/a", f"12-month bear target: {model.valuation_summary.get('bear_target_price'):,.2f}" if model.valuation_summary.get('bear_target_price') else "12-month bear target: n/a", f"12-month base target: {model.valuation_summary.get('base_target_price'):,.2f}" if model.valuation_summary.get('base_target_price') else "12-month base target: n/a", f"12-month bull target: {model.valuation_summary.get('bull_target_price'):,.2f}" if model.valuation_summary.get('bull_target_price') else "12-month bull target: n/a", f"Analyst consensus anchor: {model.valuation_summary.get('analyst_consensus_target'):,.2f}" if model.valuation_summary.get('analyst_consensus_target') else "Analyst consensus anchor: n/a", f"Dynamic peer set: {', '.join(peers) if peers else 'n/a'}"]),
        _llm_committee_section(llm_committee),
        company_overview_agent(snapshot), business_model_agent(snapshot), market_agent(snapshot), competitive_landscape_agent(snapshot, comps), commercial_drivers_agent(snapshot), historical_financials_agent(historicals), valuation_agent(snapshot, dcfs), technical_agent(technicals), risk_agent(snapshot, upside), qa_agent(plan, snapshot, dcfs),
    ]
    _emit(progress_callback, agent="Report Agents", status="complete", phase="report_generation", message="Report sections complete.")

    report = FullReport(plan=plan, snapshot=snapshot, historicals=historicals, technicals=technicals, assumptions=assumptions, forecasts=forecasts, dcf_outputs=dcfs, sensitivities=sensitivities, sections=sections, recommendation=recommendation, target_price=target_price, upside_downside=upside, company_classification=company_classification, dynamic_assumptions=dynamic_assumptions, financial_model_plan=financial_model_plan, company_evidence=evidence, peer_comps=comps, dynamic_valuation=dynamic_valuation, validated_model=model, llm_committee=llm_committee)

    output_root = Path("outputs")
    chart_dir = output_root / "charts"
    report_dir = output_root / "reports"
    model_dir = output_root / "models"
    _emit(progress_callback, agent="Output Renderer", status="running", phase="outputs", message="Rendering charts, HTML report and Excel model.")
    chart_paths = [chart_forecast_revenue(forecasts, chart_dir, snapshot.ticker), chart_margin_forecast(forecasts, chart_dir, snapshot.ticker), chart_price_technicals(price_history, chart_dir, snapshot.ticker)]
    chart_paths = [p for p in chart_paths if p]
    report.html_path = render_report(report, report_dir, chart_paths=chart_paths)
    report.excel_model_path = export_excel_model(report, model_dir)
    _emit(progress_callback, agent="Output Renderer", status="complete", phase="outputs", message="Final outputs generated.", payload={"html_path": report.html_path, "excel_model_path": report.excel_model_path})
    return report
