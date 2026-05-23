"""Financial Model Planner Agent.

Builds a foundational modelling plan before valuation is attempted. The design
is inspired by investment-banking style models with separate tabs for inputs,
operating assumptions, three-statement forecasts, WACC, DCF, comparables,
sensitivity analysis and football-field outputs.
"""
from __future__ import annotations

from src.schemas import (
    CompanyClassification,
    DynamicAssumptions,
    FinancialModelPlan,
    ForecastDriver,
    HistoricalFinancials,
    MarketSnapshot,
    ModelTabPlan,
)


def _standard_tabs() -> list[ModelTabPlan]:
    return [
        ModelTabPlan(
            tab_name="Cover / Output",
            purpose="Summarise recommendation, target price, valuation range, key assumptions and report status.",
            key_outputs=["Recommendation", "Target price", "Upside/downside", "Valuation range", "Key evidence gaps"],
            linked_to=["Football Field", "Valuation Summary"],
        ),
        ModelTabPlan(
            tab_name="Source Data",
            purpose="Store raw historical data, company filings, market data and source references.",
            key_inputs=["Historical income statement", "Balance sheet", "Cash flow", "share count", "net debt", "source URLs"],
            key_outputs=["Normalised historical dataset"],
        ),
        ModelTabPlan(
            tab_name="Operating Assumptions",
            purpose="Separate hardcoded assumptions from formulas and provide an audit trail for each driver.",
            key_inputs=["Revenue drivers", "margin assumptions", "tax", "capex", "working capital", "scenario toggles"],
            key_outputs=["Base/bull/bear operating assumptions"],
            linked_to=["Three Statement Model", "Valuation Summary"],
        ),
        ModelTabPlan(
            tab_name="Three Statement Model",
            purpose="Forecast income statement, balance sheet and cash flow with linked formulas.",
            key_outputs=["Revenue", "EBITDA", "EBIT", "NPAT", "EPS", "FCF", "net debt", "shares"],
            linked_to=["DCF", "Comps", "Sensitivity"],
        ),
        ModelTabPlan(
            tab_name="WACC / Cost of Capital",
            purpose="Derive company-specific discount rate using beta, capital structure, cost of debt, tax and risk adjustments.",
            key_inputs=["risk-free rate", "equity risk premium", "beta", "debt/equity weights", "cost of debt", "tax rate"],
            key_outputs=["Cost of equity", "after-tax cost of debt", "WACC", "discount rate rationale"],
        ),
        ModelTabPlan(
            tab_name="Comps",
            purpose="Benchmark valuation against relevant peers and sector-specific multiples.",
            key_inputs=["peer set", "EV", "market cap", "revenue", "EBITDA", "EPS", "book value", "growth", "margins"],
            key_outputs=["median multiples", "implied valuation range", "premium/discount"],
        ),
        ModelTabPlan(
            tab_name="Sensitivity",
            purpose="Show how valuation changes under key assumption ranges.",
            key_outputs=["WACC vs terminal value", "growth vs margin", "method-specific sensitivities"],
        ),
        ModelTabPlan(
            tab_name="Football Field",
            purpose="Triangulate all valuation methods into a low/base/high valuation range.",
            key_outputs=["DCF range", "comps range", "SOTP/NAV/rNPV range", "final valuation range"],
        ),
    ]


def _generic_forecast_drivers() -> list[ForecastDriver]:
    return [
        ForecastDriver(
            driver_name="Revenue growth",
            formula_or_logic="Driven by historical growth, market growth, pricing, volume, share gain/loss and management guidance.",
            evidence_required=["historical revenue", "segment disclosure", "guidance", "market growth", "pricing and volume indicators"],
        ),
        ForecastDriver(
            driver_name="Gross / EBITDA margin",
            formula_or_logic="Forecast margin from historical margin, cost inflation, mix shift, operating leverage and peer benchmarks.",
            evidence_required=["historical margins", "cost structure", "mix", "management commentary", "peer margins"],
        ),
        ForecastDriver(
            driver_name="Capital intensity",
            formula_or_logic="Forecast capex as maintenance plus growth capex, linked to asset base, expansion plans and historical capex/revenue.",
            evidence_required=["historical capex", "management capex guidance", "asset base", "capacity expansion plans"],
        ),
        ForecastDriver(
            driver_name="Working capital",
            formula_or_logic="Forecast using days sales outstanding, inventory days, payables days or change in NWC as percentage of sales growth.",
            evidence_required=["receivables", "inventory", "payables", "sales growth", "cash conversion"],
        ),
        ForecastDriver(
            driver_name="Share count / capital returns",
            formula_or_logic="Forecast diluted shares, buybacks, dividends and equity issuance where relevant.",
            evidence_required=["shares outstanding", "buyback authorisation", "dividend policy", "option dilution"],
        ),
    ]


def build_financial_model_plan(
    snapshot: MarketSnapshot,
    historicals: HistoricalFinancials,
    classification: CompanyClassification,
    dynamic_assumptions: DynamicAssumptions,
) -> FinancialModelPlan:
    tabs = _standard_tabs()
    drivers = _generic_forecast_drivers()
    valuation_stack: list[str] = []
    sensitivity_cases: list[str] = []
    warnings: list[str] = list(classification.warnings) + list(dynamic_assumptions.warnings)

    if classification.primary_type == "healthcare_pipeline_or_royalty":
        tabs.extend([
            ModelTabPlan(
                tab_name="Pipeline rNPV",
                purpose="Value each asset using stage, probability of success, launch timing, market size, pricing, penetration and peak sales.",
                key_inputs=["asset", "indication", "clinical stage", "PoS", "launch year", "peak sales", "gross margin", "royalty/milestone terms"],
                key_outputs=["risk-adjusted asset value", "unrisked asset value", "per-share contribution"],
            ),
            ModelTabPlan(
                tab_name="Catalyst Timeline",
                purpose="Track clinical, regulatory and reimbursement events that could change probability, launch timing or peak-sales assumptions.",
                key_outputs=["catalyst", "expected timing", "valuation impact", "risk direction"],
            ),
        ])
        drivers.extend([
            ForecastDriver(
                driver_name="Pipeline asset valuation",
                formula_or_logic="Asset value = risk-adjusted discounted cash flows using clinical-stage probability, launch timing, penetration and peak sales.",
                evidence_required=["clinical phase", "Tufts/DiMasi-style PoS", "TAM", "pricing", "penetration", "trial endpoints", "regulatory timeline"],
            ),
            ForecastDriver(
                driver_name="Royalty / milestone economics",
                formula_or_logic="Revenue equals partner sales multiplied by royalty rate plus milestone timing, probability weighted by asset risk.",
                evidence_required=["licensing agreement", "royalty tiers", "milestone schedule", "partner sales forecast"],
            ),
        ])
        valuation_stack = ["Marketed-product DCF", "Pipeline rNPV", "Royalty/milestone NPV", "Net cash", "Corporate cost adjustment"]
        sensitivity_cases = ["PoS by clinical phase", "peak sales", "launch delay", "penetration", "price/reimbursement", "discount rate"]

    elif classification.primary_type == "resources_or_mining":
        tabs.extend([
            ModelTabPlan(
                tab_name="Mining NAV",
                purpose="Value resources using finite-life project cash flows, commodity price deck, production, costs, capex and closure costs.",
                key_inputs=["reserves/resources", "mine life", "production schedule", "commodity price", "AISC", "sustaining capex", "closure cost"],
                key_outputs=["project NAV", "corporate NAV", "NAV/share"],
            ),
            ModelTabPlan(
                tab_name="Commodity Deck",
                purpose="Document price assumptions and sensitivity ranges by commodity.",
                key_inputs=["spot price", "forward curve", "long-term price", "FX", "inflation"],
            ),
        ])
        drivers.extend([
            ForecastDriver(
                driver_name="Mine-life cash flow",
                formula_or_logic="Project FCF = production volume × realised commodity price - operating costs - sustaining/growth capex - closure costs.",
                evidence_required=["reserve statement", "mine plan", "commodity price deck", "cost guidance", "capex guidance"],
            ),
        ])
        valuation_stack = ["Project NAV", "Exploration/resource option value", "Net debt", "Corporate overhead", "NAV/share"]
        sensitivity_cases = ["commodity price", "production volume", "AISC", "capex", "FX", "project discount rate"]

    elif classification.primary_type in {"bank_or_lender", "insurer"}:
        tabs.extend([
            ModelTabPlan(
                tab_name="ROE / Book Value Model",
                purpose="Value financials through book value, ROE, cost of equity, payout and capital adequacy.",
                key_inputs=["book value", "ROE", "cost of equity", "dividend payout", "capital ratio", "credit loss ratio"],
                key_outputs=["justified P/B", "target book multiple", "valuation range"],
            )
        ])
        drivers.extend([
            ForecastDriver(
                driver_name="ROE versus cost of equity",
                formula_or_logic="P/B justified by sustainable ROE, cost of equity and growth/payout profile.",
                evidence_required=["ROE", "CET1/capital ratio", "NIM", "credit loss ratio", "book value", "payout"],
            )
        ])
        valuation_stack = ["P/B", "P/TBV", "Residual income", "Dividend yield", "Peer financial multiples"]
        sensitivity_cases = ["ROE", "cost of equity", "credit losses", "NIM", "capital ratio", "payout"]

    elif classification.primary_type == "software_or_saas":
        tabs.extend([
            ModelTabPlan(
                tab_name="SaaS Unit Economics",
                purpose="Forecast ARR, retention, churn, CAC efficiency, gross margin, Rule of 40 and free-cash-flow conversion.",
                key_inputs=["ARR", "NRR", "churn", "ARPU", "customers", "CAC", "S&M efficiency"],
                key_outputs=["ARR forecast", "Rule of 40", "LTV/CAC", "EV/ARR implied value"],
            )
        ])
        drivers.extend([
            ForecastDriver(
                driver_name="ARR / retention build",
                formula_or_logic="ARR = prior ARR + new ARR - churned ARR; revenue follows ARR recognition, NRR and ARPU.",
                evidence_required=["ARR", "NRR", "churn", "customers", "ARPU", "sales efficiency"],
            )
        ])
        valuation_stack = ["EV/ARR", "EV/Sales", "Rule of 40 peer screen", "DCF cross-check"]
        sensitivity_cases = ["ARR growth", "NRR", "gross margin", "S&M efficiency", "terminal FCF margin"]

    else:
        valuation_stack = ["Operating DCF", "Trading comparables", "SOTP if segments are material", "Football field"]
        sensitivity_cases = ["WACC", "terminal growth or exit multiple", "revenue growth", "EBITDA margin", "capex", "working capital"]

    return FinancialModelPlan(
        model_type=classification.primary_type,
        model_principle=(
            "Valuation must be built from explicit forecast drivers and a documented assumption audit trail. "
            "Generic DCF outputs are cross-checks only unless the valuation router confirms DCF is the appropriate primary method."
        ),
        workbook_tabs=tabs,
        forecast_drivers=drivers,
        assumption_audit_trail=dynamic_assumptions.sources_and_evidence,
        valuation_stack=valuation_stack,
        sensitivity_cases=sensitivity_cases,
        build_warnings=warnings,
    )
