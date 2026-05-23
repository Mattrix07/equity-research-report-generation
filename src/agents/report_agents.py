"""Deterministic agent-style section builders.

These are intentionally structured as small specialist agents. They can later be
replaced or augmented with LLM calls, but the first version avoids hallucinated
numbers by only narrating from the structured data and model outputs.
"""
from __future__ import annotations

from typing import Any

from src.schemas import (
    DCFOutput,
    HistoricalFinancials,
    MarketSnapshot,
    ReportPlan,
    SectionOutput,
    TechnicalSnapshot,
)


def fmt_money(value: float | None, currency: str = "") -> str:
    if value is None:
        return "n/a"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        return f"{currency}{value / 1_000_000_000:,.1f}bn"
    if abs_v >= 1_000_000:
        return f"{currency}{value / 1_000_000:,.1f}m"
    return f"{currency}{value:,.2f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def build_report_plan(ticker: str, company_name: str, report_type: str, sector: str) -> ReportPlan:
    template = "healthcare_initiation" if "health" in sector.lower() or "bio" in sector.lower() else "initiation"
    sections = [
        "Investment snapshot",
        "Executive summary",
        "The long view",
        "Risk/reward and scenarios",
        "Company overview",
        "Business model",
        "Industry and market analysis",
        "Competitive landscape",
        "Commercial drivers",
        "Historical financial overview",
        "Forecast revenue build",
        "DCF valuation",
        "Trading comparables",
        "Sensitivity analysis",
        "Catalysts",
        "Investment risks",
        "Model QA notes",
    ]
    return ReportPlan(
        ticker=ticker.upper(),
        company_name=company_name,
        report_type=report_type,  # type: ignore[arg-type]
        sector=sector,
        template=template,
        sections=sections,
        valuation_methods=["DCF", "Scenario analysis", "Sensitivity analysis", "Trading comparables"],
        charts=["Revenue forecast", "EBITDA margin forecast", "Price versus moving averages"],
    )


def front_page_agent(snapshot: MarketSnapshot, recommendation: str, target_price: float | None, upside: float | None) -> SectionOutput:
    return SectionOutput(
        title="Investment snapshot",
        bullets=[
            f"Rating: {recommendation}",
            f"Current price: {fmt_money(snapshot.current_price, snapshot.currency + ' ' if snapshot.currency else '')}",
            f"Target price: {fmt_money(target_price, snapshot.currency + ' ' if snapshot.currency else '')}",
            f"Upside/downside to target: {fmt_pct(upside)}",
            f"Market capitalisation: {fmt_money(snapshot.market_cap, snapshot.currency + ' ' if snapshot.currency else '')}",
            f"52-week range: {fmt_money(snapshot.fifty_two_week_low)} to {fmt_money(snapshot.fifty_two_week_high)}",
        ],
        narrative=(
            f"{snapshot.company_name} is analysed using a structured initiation-report framework. "
            "The recommendation is anchored in the base-case DCF, cross-checked against scenario outputs, "
            "technical context and key risks."
        ),
    )


def executive_summary_agent(snapshot: MarketSnapshot, dcf_base: DCFOutput, recommendation: str) -> SectionOutput:
    narrative = (
        f"{snapshot.company_name} operates in {snapshot.industry} within the {snapshot.sector} sector. "
        f"The base-case DCF implies an equity value of {fmt_money(dcf_base.equity_value, snapshot.currency + ' ')} "
        f"and a target price of {fmt_money(dcf_base.target_price, snapshot.currency + ' ')}. "
        f"On this basis, the model-driven recommendation is {recommendation}. "
        "The conclusion should be treated as an analytical starting point rather than investment advice, "
        "with final judgement dependent on source review, company filings and analyst-led assumption checks."
    )
    return SectionOutput(
        title="Executive summary",
        bullets=[
            "The report is structured as an initiation report with a full thesis, forecast model and valuation layer.",
            "The DCF is deterministic and calculated from explicit assumptions rather than generated directly by an LLM.",
            "The risk/reward framework uses bear, base and bull cases to avoid relying on a single-point forecast.",
        ],
        narrative=narrative,
    )


def company_overview_agent(snapshot: MarketSnapshot) -> SectionOutput:
    summary = snapshot.business_summary or (
        f"{snapshot.company_name} is a listed company in the {snapshot.industry} industry. "
        "A fuller company description should be added from filings and investor presentations."
    )
    return SectionOutput(
        title="Company overview",
        narrative=summary,
        bullets=[
            f"Sector: {snapshot.sector}",
            f"Industry: {snapshot.industry}",
            f"Ticker: {snapshot.ticker}",
        ],
    )


def business_model_agent(snapshot: MarketSnapshot) -> SectionOutput:
    return SectionOutput(
        title="Business model",
        narrative=(
            f"The first-pass model treats {snapshot.company_name} as a conventional operating company. "
            "Revenue growth, margin progression, capital intensity and working-capital needs are the key drivers. "
            "For sector-specific reports, this module should be extended into templates such as SaaS, bank, insurer, "
            "medical device, biotech risk-adjusted NPV, resources/NAV or consumer models."
        ),
        bullets=[
            "Revenue driver: forecast growth applied to the latest available reported revenue base.",
            "Margin driver: EBITDA margin progression by scenario.",
            "Cash flow driver: EBIT tax-adjusted to NOPAT, plus D&A, less capex and working capital.",
        ],
    )


def market_agent(snapshot: MarketSnapshot) -> SectionOutput:
    return SectionOutput(
        title="Industry and market analysis",
        narrative=(
            f"The market analysis should connect {snapshot.company_name}'s revenue opportunity to industry size, "
            "penetration, pricing, regulation and competitive intensity. In this prototype, the section is generated "
            "from market classification data and should be expanded with filings, industry reports and primary sources."
        ),
        bullets=[
            f"Sector exposure: {snapshot.sector}",
            f"Industry exposure: {snapshot.industry}",
            "Key analytical gap to fill: TAM, growth rate, penetration and regulatory/market access context.",
        ],
    )


def competitive_landscape_agent(snapshot: MarketSnapshot, comps: dict[str, Any]) -> SectionOutput:
    median_ev_ebitda = comps.get("median_ev_ebitda")
    return SectionOutput(
        title="Competitive landscape and peer valuation",
        narrative=(
            "The competitive section should compare business quality, growth, margins, balance-sheet strength and valuation. "
            "The current prototype uses a simple peer-comps engine and can be extended with a stronger peer-selection agent."
        ),
        bullets=[
            f"Median peer EV/EBITDA: {median_ev_ebitda:.1f}x" if median_ev_ebitda else "Median peer EV/EBITDA: n/a",
            f"Peer-implied price: {fmt_money(comps.get('implied_price'), snapshot.currency + ' ')}",
        ],
        tables=[{"name": "Peer table", "rows": comps.get("peer_table", [])}],
    )


def commercial_drivers_agent(snapshot: MarketSnapshot) -> SectionOutput:
    return SectionOutput(
        title="Commercial drivers",
        narrative=(
            "Commercial drivers translate the thesis into measurable forecast assumptions. For a generic company, "
            "the first-pass drivers are revenue growth, EBITDA margin, capital intensity and working-capital absorption. "
            "For a healthcare report, this should be replaced with patient pool, penetration, price, persistency, launch timing, "
            "probability of success and reimbursement assumptions."
        ),
        bullets=[
            "Volume/penetration driver: captured through scenario revenue growth.",
            "Pricing/mix driver: indirectly captured through revenue and margin assumptions.",
            "Operating leverage driver: captured through EBITDA margin progression.",
        ],
    )


def historical_financials_agent(h: HistoricalFinancials) -> SectionOutput:
    years = sorted(h.revenue.keys())[-5:]
    rows = []
    for year in years:
        rows.append({
            "year": year,
            "revenue": h.revenue.get(year),
            "ebitda": h.ebitda.get(year),
            "net_income": h.net_income.get(year),
            "free_cash_flow": h.free_cash_flow.get(year),
            "ebitda_margin": h.ebitda_margin.get(year),
            "fcf_margin": h.fcf_margin.get(year),
        })
    return SectionOutput(
        title="Historical financial overview",
        narrative=(
            "The historical financial overview is used as the anchor for the forecast. The model prioritises reported revenue, "
            "EBITDA, free cash flow conversion and margins. Where data is missing from yfinance, the report flags the limitation."
        ),
        bullets=[
            "Latest reported revenue is used as the forecast starting point.",
            "Historical EBITDA and FCF margins inform the base-case margin path.",
            "Analyst review is required where one-off items distort reported history.",
        ],
        tables=[{"name": "Historical financial summary", "rows": rows}],
    )


def valuation_agent(snapshot: MarketSnapshot, dcfs: dict[str, DCFOutput]) -> SectionOutput:
    rows = []
    for scenario, dcf in dcfs.items():
        rows.append({
            "scenario": scenario,
            "enterprise_value": dcf.enterprise_value,
            "equity_value": dcf.equity_value,
            "target_price": dcf.target_price,
            "wacc": dcf.assumptions.wacc,
            "terminal_growth": dcf.assumptions.terminal_growth,
        })
    base = dcfs["base"]
    return SectionOutput(
        title="DCF valuation",
        narrative=(
            f"The DCF values forecast free cash flow, terminal value, enterprise value and equity value. "
            f"The base case implies a target price of {fmt_money(base.target_price, snapshot.currency + ' ')}. "
            "The output is most sensitive to WACC, terminal growth, revenue growth and EBITDA margin."
        ),
        bullets=[
            f"Base case enterprise value: {fmt_money(base.enterprise_value, snapshot.currency + ' ')}",
            f"Base case equity value: {fmt_money(base.equity_value, snapshot.currency + ' ')}",
            f"Base case WACC / terminal growth: {fmt_pct(base.assumptions.wacc)} / {fmt_pct(base.assumptions.terminal_growth)}",
        ],
        tables=[{"name": "DCF scenario output", "rows": rows}],
    )


def technical_agent(t: TechnicalSnapshot) -> SectionOutput:
    return SectionOutput(
        title="Technical analysis",
        narrative=t.momentum_comment,
        bullets=[
            f"Last price: {fmt_money(t.last_price)}",
            f"20-day moving average: {fmt_money(t.ma_20)}",
            f"50-day moving average: {fmt_money(t.ma_50)}",
            f"200-day moving average: {fmt_money(t.ma_200)}",
            f"14-day RSI: {t.rsi_14:.1f}" if t.rsi_14 is not None else "14-day RSI: n/a",
        ],
    )


def risk_agent(snapshot: MarketSnapshot, upside: float | None) -> SectionOutput:
    return SectionOutput(
        title="Investment risks",
        narrative=(
            "The risks below are generated as a first-pass checklist. They should be refined using company filings, sector research, "
            "management commentary and primary source evidence."
        ),
        bullets=[
            "Forecast risk: revenue growth or margin expansion may not materialise.",
            "Valuation risk: target price is sensitive to WACC, terminal growth and terminal cash flow assumptions.",
            "Market risk: macro conditions, rates, risk appetite and sector rotation may affect multiples.",
            "Competitive risk: peers or substitutes may pressure growth, pricing or margins.",
            "Data risk: public yfinance data can be incomplete or distorted by one-off items.",
        ],
    )


def qa_agent(plan: ReportPlan, snapshot: MarketSnapshot, dcfs: dict[str, DCFOutput]) -> SectionOutput:
    base = dcfs.get("base")
    checks = [
        "DCF is calculated by Python from explicit assumptions.",
        "Bear/base/bull cases use different revenue growth, margin, WACC and terminal growth assumptions.",
        "The target price is linked to equity value divided by shares outstanding where share count is available.",
        "Any missing financial fields should be reviewed before relying on the report.",
    ]
    if not snapshot.shares_outstanding:
        checks.append("Share count was unavailable, so per-share valuation may be incomplete.")
    if base and base.target_price is None:
        checks.append("Base-case target price could not be calculated because shares outstanding were unavailable.")
    return SectionOutput(
        title="Model QA notes",
        narrative="Quality-control notes identify where the model is robust and where analyst review is required.",
        bullets=checks,
    )
