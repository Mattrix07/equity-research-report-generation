"""Main report-generation workflow."""
from __future__ import annotations

from pathlib import Path

from src.agents.assumption_derivation_agent import assumptions_to_scenario_assumptions, derive_dynamic_assumptions
from src.agents.company_classifier_agent import classify_company
from src.agents.evidence_agent import build_company_evidence_pack
from src.agents.financial_model_planner_agent import build_financial_model_plan
from src.agents.llm_committee import run_llm_committee_sync
from src.agents.peer_selector_agent import select_dynamic_peer_tickers
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
from src.data.yfinance_client import (
    fetch_historical_financials,
    fetch_market_snapshot,
    fetch_peer_snapshot,
    fetch_price_history,
)
from src.engines.chart_engine import chart_forecast_revenue, chart_margin_forecast, chart_price_technicals
from src.engines.comps_engine import run_comps
from src.engines.dcf_engine import run_dcf
from src.engines.dynamic_valuation_engine import run_dynamic_valuation
from src.engines.forecast_engine import build_default_assumptions, run_forecast
from src.engines.sensitivity_engine import growth_margin_sensitivity, wacc_terminal_growth_sensitivity
from src.engines.technical_engine import run_technical_analysis
from src.report.dcf_led_excel_exporter import export_excel_model
from src.report.evidence_excel_overlay import apply_evidence_overlay
from src.report.renderer import render_report
from src.schemas import CompanyEvidencePack, DynamicValuationResult, FullReport, LLMCommitteeOutput, ReportRequest, SectionOutput


def _recommendation(current_price: float | None, target_price: float | None) -> tuple[str, float | None]:
    if current_price is None or not current_price or target_price is None:
        return "REVIEW", None
    upside = (target_price / current_price) - 1
    if upside >= 0.15:
        return "BUY", upside
    if upside <= -0.10:
        return "SELL", upside
    return "HOLD", upside


def _llm_committee_section(llm_committee: LLMCommitteeOutput) -> SectionOutput:
    if not llm_committee.enabled:
        return SectionOutput(
            title="LLM investment committee",
            narrative=(
                "The LLM committee is disabled. Set ENABLE_LLM_COMMITTEE=true and provide an OpenAI-compatible API key "
                "to activate parallel bull, bear and valuation agents plus a sequential committee-chair synthesis."
            ),
        )

    opinion_rows = []
    for op in llm_committee.opinions:
        opinion_rows.append({
            "agent": op.agent_name,
            "model": op.model,
            "recommendation": op.recommendation,
            "confidence": op.confidence,
            "target_price": op.target_price,
            "implied_upside": op.implied_upside,
            "error": op.error,
        })

    bullets = []
    if llm_committee.final_recommendation:
        bullets.append(f"Committee recommendation: {llm_committee.final_recommendation}")
    if llm_committee.final_target_price:
        bullets.append(f"Committee target price: {llm_committee.final_target_price:,.2f}")
    if llm_committee.final_confidence is not None:
        bullets.append(f"Committee confidence: {llm_committee.final_confidence}/100")
    bullets.extend([f"Risk: {risk}" for risk in llm_committee.final_risks[:5]])
    bullets.extend([f"Evidence gap: {gap}" for gap in llm_committee.final_evidence_gaps[:5]])
    if llm_committee.synthesis_error:
        bullets.append(f"Committee synthesis error: {llm_committee.synthesis_error}")

    return SectionOutput(
        title="LLM investment committee",
        narrative=llm_committee.final_thesis or (
            "The LLM committee generated individual agent views, but no final synthesis was produced. Review the agent table below."
        ),
        bullets=bullets,
        tables=[{"name": "LLM agent opinions", "rows": opinion_rows}],
    )


def _dynamic_valuation_section(dynamic: DynamicValuationResult) -> SectionOutput:
    outputs = []
    for method, output in dynamic.valuation_outputs.items():
        if isinstance(output, dict):
            outputs.append({"method": method, "output": str(output)[:1200]})

    return SectionOutput(
        title="12-month DCF-led valuation output",
        narrative=dynamic.investment_thesis,
        bullets=[
            f"Primary valuation method: {dynamic.primary_method}",
            f"Selected methods: {', '.join(dynamic.selected_methods)}",
            f"Recommendation: {dynamic.recommendation}",
            f"12-month target price: {dynamic.target_price:,.2f}" if dynamic.target_price else "12-month target price: n/a",
            f"Confidence: {dynamic.confidence}/100",
            f"Valuation rationale: {dynamic.valuation_rationale}",
            *[f"Assumption: {x}" for x in dynamic.key_assumptions[:5]],
            *[f"Evidence gap: {x}" for x in dynamic.evidence_gaps[:6]],
            *[f"Sanity check: {x}" for x in dynamic.sanity_checks[:6]],
        ],
        tables=[{"name": "Valuation workings summary", "rows": outputs}],
    )


def _financial_model_plan_section(model_plan) -> SectionOutput:
    tab_rows = [
        {
            "tab": tab.tab_name,
            "purpose": tab.purpose,
            "key_inputs": "; ".join(tab.key_inputs[:4]),
            "key_outputs": "; ".join(tab.key_outputs[:4]),
        }
        for tab in model_plan.workbook_tabs
    ]
    driver_rows = [
        {
            "driver": driver.driver_name,
            "logic": driver.formula_or_logic,
            "evidence_required": "; ".join(driver.evidence_required[:5]),
            "status": driver.current_status,
        }
        for driver in model_plan.forecast_drivers
    ]
    return SectionOutput(
        title="Foundational financial model plan",
        narrative=model_plan.model_principle,
        bullets=[
            f"Model type: {model_plan.model_type}",
            f"Valuation stack: {', '.join(model_plan.valuation_stack)}",
            f"Sensitivity cases: {', '.join(model_plan.sensitivity_cases)}",
            *[f"Build warning: {warning}" for warning in model_plan.build_warnings[:5]],
        ],
        tables=[
            {"name": "Recommended workbook architecture", "rows": tab_rows},
            {"name": "Forecast driver audit trail", "rows": driver_rows},
        ],
    )


def _company_evidence_section(evidence: CompanyEvidencePack) -> SectionOutput:
    rows = [item.model_dump() for item in evidence.evidence_items[:20]]
    return SectionOutput(
        title="Company-specific source evidence",
        narrative=(
            "This section shows the source evidence available to populate the Excel model and sector-specific tabs. "
            "LLM enrichment is used only when enabled; otherwise the model uses deterministic evidence from market data and flags gaps."
        ),
        bullets=[
            f"Evidence items collected: {len(evidence.evidence_items)}",
            f"Source URLs supplied: {len(evidence.source_urls)}",
            *[f"Evidence gap: {gap}" for gap in evidence.gaps[:6]],
            *[f"Warning: {warning}" for warning in evidence.warnings[:4]],
        ],
        tables=[{"name": "Evidence sample", "rows": rows}],
    )


def generate_report(request: ReportRequest) -> FullReport:
    snapshot = fetch_market_snapshot(request.ticker, request.company_name)
    if request.current_price:
        snapshot.current_price = request.current_price
    if request.sector_hint:
        snapshot.sector = request.sector_hint

    plan = build_report_plan(
        ticker=snapshot.ticker,
        company_name=snapshot.company_name,
        report_type=request.report_type,
        sector=snapshot.sector,
    )

    historicals = fetch_historical_financials(snapshot.ticker)
    price_history = fetch_price_history(snapshot.ticker)
    technicals = run_technical_analysis(price_history)

    company_classification = classify_company(snapshot, historicals)
    dynamic_assumptions = derive_dynamic_assumptions(snapshot, historicals, company_classification)
    financial_model_plan = build_financial_model_plan(snapshot, historicals, company_classification, dynamic_assumptions)
    company_evidence = build_company_evidence_pack(
        snapshot=snapshot,
        historicals=historicals,
        classification=company_classification,
        dynamic_assumptions=dynamic_assumptions,
        model_plan=financial_model_plan,
        source_urls=request.source_urls,
    )

    assumptions = build_default_assumptions(historicals)
    assumptions["base"] = assumptions_to_scenario_assumptions(assumptions["base"], dynamic_assumptions)
    assumptions["bear"].wacc = assumptions["base"].wacc + 0.01
    assumptions["bull"].wacc = max(assumptions["base"].wacc - 0.005, 0.06)
    assumptions["bear"].tax_rate = assumptions["base"].tax_rate
    assumptions["bull"].tax_rate = assumptions["base"].tax_rate
    if dynamic_assumptions.terminal_growth is not None:
        assumptions["bear"].terminal_growth = max(dynamic_assumptions.terminal_growth - 0.005, 0.0)
        assumptions["bull"].terminal_growth = dynamic_assumptions.terminal_growth + 0.005

    forecasts = {scenario: run_forecast(historicals, assumption) for scenario, assumption in assumptions.items()}

    net_debt = snapshot.net_debt or 0.0
    shares = snapshot.shares_outstanding
    dcfs = {
        scenario: run_dcf(scenario, forecasts[scenario], assumptions[scenario], net_debt, shares)
        for scenario in ["bear", "base", "bull"]
    }

    peers = select_dynamic_peer_tickers(snapshot, request.peers, min_peers=4, max_peers=5)
    peer_snapshots = fetch_peer_snapshot(peers) if peers else []
    company_ebitda = snapshot.ebitda
    if not company_ebitda and forecasts.get("base"):
        company_ebitda = forecasts["base"][0].ebitda
    comps = run_comps(peer_snapshots, company_ebitda, net_debt, shares)
    comps["selected_peer_tickers"] = peers

    dynamic_valuation = run_dynamic_valuation(
        snapshot=snapshot,
        historicals=historicals,
        forecasts=forecasts,
        dcfs=dcfs,
        comps=comps,
        classification=company_classification,
        dynamic_assumptions=dynamic_assumptions,
    )

    target_price = dynamic_valuation.target_price
    recommendation = dynamic_valuation.recommendation
    upside = dynamic_valuation.upside_downside

    llm_committee = run_llm_committee_sync(
        snapshot,
        forecasts,
        dcfs,
        technicals,
        comps,
        company_classification,
        dynamic_assumptions,
        dynamic_valuation,
    )
    if llm_committee.enabled and llm_committee.final_recommendation:
        recommendation = llm_committee.final_recommendation
        if llm_committee.final_target_price:
            target_price = llm_committee.final_target_price
            _, upside = _recommendation(snapshot.current_price, target_price)

    sensitivities = [
        wacc_terminal_growth_sensitivity(forecasts["base"], assumptions["base"], net_debt, shares),
        growth_margin_sensitivity(historicals, assumptions["base"], net_debt, shares),
    ]

    sections: list[SectionOutput] = [
        front_page_agent(snapshot, recommendation, target_price, upside),
        executive_summary_agent(snapshot, dcfs["base"], recommendation),
        _financial_model_plan_section(financial_model_plan),
        _company_evidence_section(company_evidence),
        _dynamic_valuation_section(dynamic_valuation),
        _llm_committee_section(llm_committee),
        SectionOutput(
            title="The long view and 12-month risk/reward",
            narrative=(
                "The valuation is now framed as a 12-month DCF-led target price. The base-case DCF is the primary valuation anchor, "
                "with dynamically selected trading comparables and sector-specific methods used as secondary triangulation. The Excel model shows the linked workings for the DCF range, comps, valuation bridge, football field and sensitivity matrix."
            ),
            bullets=[
                f"Bear DCF valuation: {dcfs['bear'].target_price:,.2f}" if dcfs["bear"].target_price else "Bear DCF valuation: n/a",
                f"Base DCF valuation: {dcfs['base'].target_price:,.2f}" if dcfs["base"].target_price else "Base DCF valuation: n/a",
                f"Bull DCF valuation: {dcfs['bull'].target_price:,.2f}" if dcfs["bull"].target_price else "Bull DCF valuation: n/a",
                "DCF carries an 80% weighting in the final target price; dynamic peer comps and sector methods are secondary checks.",
                f"Dynamic peer set: {', '.join(peers) if peers else 'n/a'}",
            ],
        ),
        company_overview_agent(snapshot),
        business_model_agent(snapshot),
        market_agent(snapshot),
        competitive_landscape_agent(snapshot, comps),
        commercial_drivers_agent(snapshot),
        historical_financials_agent(historicals),
        valuation_agent(snapshot, dcfs),
        technical_agent(technicals),
        risk_agent(snapshot, upside),
        qa_agent(plan, snapshot, dcfs),
    ]

    report = FullReport(
        plan=plan,
        snapshot=snapshot,
        historicals=historicals,
        technicals=technicals,
        assumptions=assumptions,  # type: ignore[arg-type]
        forecasts=forecasts,  # type: ignore[arg-type]
        dcf_outputs=dcfs,  # type: ignore[arg-type]
        sensitivities=sensitivities,
        sections=sections,
        recommendation=recommendation,
        target_price=target_price,
        upside_downside=upside,
        company_classification=company_classification,
        dynamic_assumptions=dynamic_assumptions,
        financial_model_plan=financial_model_plan,
        company_evidence=company_evidence,
        peer_comps=comps,
        dynamic_valuation=dynamic_valuation,
        llm_committee=llm_committee,
    )

    output_root = Path("outputs")
    chart_dir = output_root / "charts"
    report_dir = output_root / "reports"
    model_dir = output_root / "models"
    chart_paths = [
        chart_forecast_revenue(forecasts, chart_dir, snapshot.ticker),
        chart_margin_forecast(forecasts, chart_dir, snapshot.ticker),
        chart_price_technicals(price_history, chart_dir, snapshot.ticker),
    ]
    chart_paths = [p for p in chart_paths if p]
    html_path = render_report(report, report_dir, chart_paths=chart_paths)
    report.html_path = html_path
    report.excel_model_path = export_excel_model(report, model_dir)
    report.excel_model_path = apply_evidence_overlay(report, report.excel_model_path)
    return report
