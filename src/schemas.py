"""Typed data models for the report workflow."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

ReportType = Literal["quick", "update", "initiation", "valuation_only", "healthcare_initiation"]
ScenarioName = Literal["bear", "base", "bull"]
ValuationMethod = Literal[
    "mature_operating_dcf",
    "sotp",
    "bank_insurer_roe_pbv",
    "mining_nav",
    "biotech_rnpv",
    "royalty_healthcare_sotp",
    "saas_unit_economics",
    "asset_heavy_industrial",
    "relative_valuation",
    "insufficient_data_review",
]
TerminalValueMethod = Literal["perpetuity_growth", "exit_multiple", "finite_life", "asset_level_rnpv", "not_applicable"]


class ReportRequest(BaseModel):
    ticker: str = Field(..., examples=["AAPL"])
    company_name: str | None = None
    report_type: ReportType = "initiation"
    sector_hint: str | None = None
    current_price: float | None = None
    peers: list[str] = Field(default_factory=list)


class ReportPlan(BaseModel):
    ticker: str
    company_name: str
    report_type: ReportType
    sector: str
    template: str
    sections: list[str]
    valuation_methods: list[str]
    charts: list[str]


class MarketSnapshot(BaseModel):
    ticker: str
    company_name: str
    sector: str = "Unknown"
    industry: str = "Unknown"
    current_price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    shares_outstanding: float | None = None
    currency: str = "USD"
    beta: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    revenue_ttm: float | None = None
    ebitda: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    net_debt: float | None = None
    book_value: float | None = None
    price_to_book: float | None = None
    return_on_equity: float | None = None
    profit_margins: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    business_summary: str = ""


class HistoricalFinancials(BaseModel):
    revenue: dict[str, float] = Field(default_factory=dict)
    ebitda: dict[str, float] = Field(default_factory=dict)
    ebit: dict[str, float] = Field(default_factory=dict)
    net_income: dict[str, float] = Field(default_factory=dict)
    operating_cash_flow: dict[str, float] = Field(default_factory=dict)
    capex: dict[str, float] = Field(default_factory=dict)
    free_cash_flow: dict[str, float] = Field(default_factory=dict)
    gross_margin: dict[str, float] = Field(default_factory=dict)
    ebitda_margin: dict[str, float] = Field(default_factory=dict)
    fcf_margin: dict[str, float] = Field(default_factory=dict)


class ScenarioAssumptions(BaseModel):
    revenue_growth: list[float]
    ebitda_margin: list[float]
    da_percent_revenue: float = 0.03
    capex_percent_revenue: float = 0.04
    nwc_percent_revenue: float = 0.01
    tax_rate: float = 0.25
    wacc: float = 0.095
    terminal_growth: float = 0.025


class ForecastRow(BaseModel):
    year: str
    revenue: float
    ebitda: float
    ebit: float
    tax: float
    nopat: float
    da: float
    capex: float
    change_nwc: float
    fcf: float
    ebitda_margin: float
    fcf_margin: float


class DCFOutput(BaseModel):
    scenario: ScenarioName
    enterprise_value: float
    equity_value: float
    target_price: float | None
    pv_fcf: float
    terminal_value: float
    pv_terminal_value: float
    net_debt: float
    shares_outstanding: float | None
    assumptions: ScenarioAssumptions


class SensitivityTable(BaseModel):
    title: str
    row_label: str
    column_label: str
    rows: list[float]
    columns: list[float]
    values: list[list[float | None]]


class TechnicalSnapshot(BaseModel):
    last_price: float | None = None
    ma_20: float | None = None
    ma_50: float | None = None
    ma_200: float | None = None
    rsi_14: float | None = None
    momentum_comment: str = ""


class SectionOutput(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    narrative: str = ""
    tables: list[dict[str, Any]] = Field(default_factory=list)


class CompanyClassification(BaseModel):
    primary_type: str
    sector: str
    industry: str
    valuation_methods: list[ValuationMethod]
    terminal_value_method: TerminalValueMethod
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DynamicAssumptions(BaseModel):
    wacc: float | None = None
    cost_of_equity: float | None = None
    after_tax_cost_of_debt: float | None = None
    tax_rate: float | None = None
    terminal_growth: float | None = None
    terminal_value_method: TerminalValueMethod = "not_applicable"
    exit_multiple: float | None = None
    revenue_growth_logic: str = ""
    margin_logic: str = ""
    capital_intensity_logic: str = ""
    risk_adjustment_logic: str = ""
    sources_and_evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ModelTabPlan(BaseModel):
    tab_name: str
    purpose: str
    key_outputs: list[str] = Field(default_factory=list)
    key_inputs: list[str] = Field(default_factory=list)
    linked_to: list[str] = Field(default_factory=list)


class ForecastDriver(BaseModel):
    driver_name: str
    formula_or_logic: str
    evidence_required: list[str] = Field(default_factory=list)
    current_status: str = "needs_review"


class FinancialModelPlan(BaseModel):
    model_type: str
    model_principle: str
    workbook_tabs: list[ModelTabPlan] = Field(default_factory=list)
    forecast_drivers: list[ForecastDriver] = Field(default_factory=list)
    assumption_audit_trail: list[str] = Field(default_factory=list)
    valuation_stack: list[str] = Field(default_factory=list)
    sensitivity_cases: list[str] = Field(default_factory=list)
    build_warnings: list[str] = Field(default_factory=list)


class DynamicValuationResult(BaseModel):
    selected_methods: list[ValuationMethod]
    primary_method: ValuationMethod
    recommendation: str = "REVIEW"
    target_price: float | None = None
    upside_downside: float | None = None
    confidence: int = 50
    method_weighting: dict[str, float] = Field(default_factory=dict)
    valuation_outputs: dict[str, Any] = Field(default_factory=dict)
    investment_thesis: str = ""
    valuation_rationale: str = ""
    key_assumptions: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    sanity_checks: list[str] = Field(default_factory=list)


class LLMOpinion(BaseModel):
    agent_name: str
    model: str
    role: str
    recommendation: str = "REVIEW"
    confidence: int = 50
    target_price: float | None = None
    implied_upside: float | None = None
    thesis: str = ""
    valuation_view: str = ""
    key_assumptions: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    challenge_to_consensus: str = ""
    evidence_gaps: list[str] = Field(default_factory=list)
    raw_response: str = ""
    error: str | None = None


class LLMCommitteeOutput(BaseModel):
    enabled: bool = False
    opinions: list[LLMOpinion] = Field(default_factory=list)
    final_recommendation: str | None = None
    final_target_price: float | None = None
    final_confidence: int | None = None
    final_thesis: str = ""
    final_risks: list[str] = Field(default_factory=list)
    final_evidence_gaps: list[str] = Field(default_factory=list)
    synthesis_error: str | None = None


class FullReport(BaseModel):
    plan: ReportPlan
    snapshot: MarketSnapshot
    historicals: HistoricalFinancials
    technicals: TechnicalSnapshot
    assumptions: dict[ScenarioName, ScenarioAssumptions]
    forecasts: dict[ScenarioName, list[ForecastRow]]
    dcf_outputs: dict[ScenarioName, DCFOutput]
    sensitivities: list[SensitivityTable]
    sections: list[SectionOutput]
    recommendation: str
    target_price: float | None
    upside_downside: float | None
    company_classification: CompanyClassification | None = None
    dynamic_assumptions: DynamicAssumptions | None = None
    financial_model_plan: FinancialModelPlan | None = None
    dynamic_valuation: DynamicValuationResult | None = None
    llm_committee: LLMCommitteeOutput | None = None
    html_path: str | None = None
