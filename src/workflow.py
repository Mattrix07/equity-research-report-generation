"""Main report-generation workflow."""
from __future__ import annotations

from pathlib import Path

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
from src.engines.forecast_engine import build_default_assumptions, run_forecast
from src.engines.sensitivity_engine import growth_margin_sensitivity, wacc_terminal_growth_sensitivity
from src.engines.technical_engine import run_technical_analysis
from src.report.renderer import render_report
from src.schemas import FullReport, ReportRequest, SectionOutput

DEFAULT_PEERS = {
    "Technology": ["MSFT", "GOOGL", "META", "ORCL"],
    "Healthcare": ["JNJ", "PFE", "MRK", "ABBV"],
    "Financial Services": ["JPM", "BAC", "WFC", "MS"],
    "Consumer Cyclical": ["AMZN", "HD", "MCD", "NKE"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS"],
}


def _recommendation(current_price: float | None, target_price: float | None) -> tuple[str, float | None]:
    if current_price is None or not current_price or target_price is None:
        return "REVIEW", None
    upside = (target_price / current_price) - 1
    if upside >= 0.15:
        return "BUY", upside
    if upside <= -0.10:
        return "SELL", upside
    return "HOLD", upside


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

    assumptions = build_default_assumptions(historicals)
    forecasts = {scenario: run_forecast(historicals, assumption) for scenario, assumption in assumptions.items()}

    net_debt = snapshot.net_debt or 0.0
    shares = snapshot.shares_outstanding
    dcfs = {
        scenario: run_dcf(scenario, forecasts[scenario], assumptions[scenario], net_debt, shares)
        for scenario in ["bear", "base", "bull"]
    }

    target_price = dcfs["base"].target_price
    recommendation, upside = _recommendation(snapshot.current_price, target_price)

    peers = request.peers or DEFAULT_PEERS.get(snapshot.sector, [])
    peer_snapshots = fetch_peer_snapshot(peers) if peers else []
    company_ebitda = snapshot.ebitda
    if not company_ebitda and forecasts.get("base"):
        company_ebitda = forecasts["base"][0].ebitda
    comps = run_comps(peer_snapshots, company_ebitda, net_debt, shares)

    sensitivities = [
        wacc_terminal_growth_sensitivity(forecasts["base"], assumptions["base"], net_debt, shares),
        growth_margin_sensitivity(historicals, assumptions["base"], net_debt, shares),
    ]

    sections: list[SectionOutput] = [
        front_page_agent(snapshot, recommendation, target_price, upside),
        executive_summary_agent(snapshot, dcfs["base"], recommendation),
        SectionOutput(
            title="The long view and risk/reward",
            narrative=(
                "The long-view thesis is framed through bear, base and bull cases. The base case reflects the most balanced "
                "view of revenue growth, operating leverage and cash conversion. The bull case assumes stronger growth and margin "
                "expansion, while the bear case captures slower adoption, weaker margins and a higher discount rate."
            ),
            bullets=[
                f"Bear target price: {dcfs['bear'].target_price:,.2f}" if dcfs["bear"].target_price else "Bear target price: n/a",
                f"Base target price: {dcfs['base'].target_price:,.2f}" if dcfs["base"].target_price else "Base target price: n/a",
                f"Bull target price: {dcfs['bull'].target_price:,.2f}" if dcfs["bull"].target_price else "Bull target price: n/a",
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
    )

    output_root = Path("outputs")
    chart_dir = output_root / "charts"
    report_dir = output_root / "reports"
    chart_paths = [
        chart_forecast_revenue(forecasts, chart_dir, snapshot.ticker),
        chart_margin_forecast(forecasts, chart_dir, snapshot.ticker),
        chart_price_technicals(price_history, chart_dir, snapshot.ticker),
    ]
    chart_paths = [p for p in chart_paths if p]
    html_path = render_report(report, report_dir, chart_paths=chart_paths)
    report.html_path = html_path
    return report
