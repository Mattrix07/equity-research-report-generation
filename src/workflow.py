"""Main report-generation workflow.

The workflow is now model-first:
1. collect market and financial data;
2. build and validate a bear/base/bull DCF financial model;
3. stop if the model is invalid;
4. generate Excel from the validated model;
5. generate the written report from the validated model outputs.
"""
from __future__ import annotations

from pathlib import Path

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
from src.engines.dynamic_valuation_engine import run_dynamic_valuation
from src.engines.model_validation_engine import build_validated_financial_model, raise_if_model_invalid
from src.engines.sensitivity_engine import growth_margin_sensitivity, wacc_terminal_growth_sensitivity
from src.engines.technical_engine import run_technical_analysis
from src.report.validated_model_excel_exporter import export_excel_model
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
        title="Validated 12-month DCF-led valuation output",
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


def _financial_model_validation_section(validated_model) -> SectionOutput:
    summary = validated_model.valuation_summary
    check_rows = [
        {"check": key, "passed": value}
        for key, value in validated_model.validation.checks.items()
    ]
    message_rows = (
        [{"type": "error", "message": msg} for msg in validated_model.validation.errors]
        + [{"type": "warning", "message": msg} for msg in validated_model.validation.warnings]
    )
    return SectionOutput(
        title="Financial model validation gate",
        narrative=(
            "The report is generated only after the financial model passes validation. The validated model creates the bear, base and bull DCF target prices before the report narrative is written."
        ),
        bullets=[
            f"Model valid: {validated_model.validation.is_valid}",
            f"Historical years available: {validated_model.data_quality.historical_years_available}/5",
            f"Bear target: {summary.get('bear_target_price'):,.2f}" if summary.get("bear_target_price") else "Bear target: n/a",
            f"Base target: {summary.get('base_target_price'):,.2f}" if summary.get("base_target_price") else "Base target: n/a",
            f"Bull target: {summary.get('bull_target_price'):,.2f}" if summary.get("bull_target_price") else "Bull target: n/a",
        ],
        tables=[
            {"name": "Validation checks", "rows": check_rows},
            {"name": "Validation messages", "rows": message_rows},
        ],
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
        title="Model-first workflow architecture",
        narrative=(
            "The workflow now builds and validates the financial model before writing the report. Excel is an interpretable output layer. The Python validation engine is the source of truth for forecast math and bear/base/bull DCF target prices."
        ),
        bullets=[
            f"Model type: {model_plan.model_type}",
            "Report generation is blocked if the financial model validation gate fails",
            "Forecast horizon: five historical years where available and five forecast years",
            "Valuation output: validated bear/base/bull DCF target prices",
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
            "This section shows the source evidence available to support the model assumptions. The current data layer uses yfinance; for greater reliability the next data upgrade should add SEC company facts, Financial Modeling Prep, FactSet, CapIQ or another audited fundamentals feed."
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

    # MODEL-FIRST VALIDATION GATE
    validated_model = build_validated_financial_model(snapshot, historicals)
    raise_if_model_invalid(validated_model)

    # Use the validated model as the report source of truth.
    assumptions = {
        "bear": validated_model.scenarios["bear"].assumptions,
        "base": validated_model.scenarios["base"].assumptions,
        "bull": validated_model.scenarios["bull"].assumptions,
    }
    forecasts = {
        "bear": validated_model.scenarios["bear"].forecasts,
        "base": validated_model.scenarios["base"].forecasts,
        "bull": validated_model.scenarios["bull"].forecasts,
    }
    dcfs = {
        "bear": validated_model.scenarios["bear"].dcf,
        "base": validated_model.scenarios["base"].dcf,
        "bull": validated_model.scenarios["bull"].dcf,
    }

    price_history = fetch_price_history(snapshot.ticker)
    technicals = run_technical_analysis(price_history)

    company_classification = classify_company(snapshot, historicals)
    # Keep these agents for planning/evidence, but they no longer override the validated model.
    dynamic_assumptions = None
    from src.agents.assumption_derivation_agent import derive_dynamic_assumptions
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

    peers = select_dynamic_peer_tickers(snapshot, request.peers, min_peers=4, max_peers=5)
    peer_snapshots = fetch_peer_snapshot(peers) if peers else []
    company_ebitda = snapshot.ebitda or forecasts["base"][0].ebitda
    net_debt = snapshot.net_debt or 0.0
    shares = snapshot.shares_outstanding
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

    target_price = validated_model.valuation_summary.get("base_target_price")
    recommendation, upside = _recommendation(snapshot.current_price, target_price)
    dynamic_valuation.target_price = target_price
    dynamic_valuation.recommendation = recommendation
    dynamic_valuation.upside_downside = upside
    dynamic_valuation.valuation_outputs["validated_model"] = validated_model.model_dump()

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
        # LLM can influence narrative, but the validated model remains the price source of truth.
        recommendation = llm_committee.final_recommendation

    sensitivities = [
        wacc_terminal_growth_sensitivity(forecasts["base"], assumptions["base"], net_debt, shares),
        growth_margin_sensitivity(historicals, assumptions["base"], net_debt, shares),
    ]

    sections: list[SectionOutput] = [
        front_page_agent(snapshot, recommendation, target_price, upside),
        executive_summary_agent(snapshot, dcfs["base"], recommendation),
        _financial_model_validation_section(validated_model),
        _financial_model_plan_section(financial_model_plan),
        _company_evidence_section(company_evidence),
        _dynamic_valuation_section(dynamic_valuation),
        _llm_committee_section(llm_committee),
        SectionOutput(
            title="Validated 12-month risk/reward",
            narrative=(
                "The report is now underpinned by a validated financial model. Bear, base and bull target prices are derived first through the Python DCF validation engine, then streamed into Excel and the written report."
            ),
            bullets=[
                f"Bear DCF valuation: {validated_model.valuation_summary.get('bear_target_price'):,.2f}" if validated_model.valuation_summary.get("bear_target_price") else "Bear DCF valuation: n/a",
                f"Base DCF valuation: {validated_model.valuation_summary.get('base_target_price'):,.2f}" if validated_model.valuation_summary.get("base_target_price") else "Base DCF valuation: n/a",
                f"Bull DCF valuation: {validated_model.valuation_summary.get('bull_target_price'):,.2f}" if validated_model.valuation_summary.get("bull_target_price") else "Bull DCF valuation: n/a",
                "The validated base DCF is the report target price. Dynamic peer comps are shown as a secondary context check, not the source of the final price.",
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
        target_price=target_price,  # type: ignore[arg-type]
        upside_downside=upside,
        company_classification=company_classification,
        dynamic_assumptions=dynamic_assumptions,
        financial_model_plan=financial_model_plan,
        company_evidence=company_evidence,
        peer_comps=comps,
        dynamic_valuation=dynamic_valuation,
        validated_model=validated_model,
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
    report.html_path = render_report(report, report_dir, chart_paths=chart_paths)
    report.excel_model_path = export_excel_model(report, model_dir)
    return report
