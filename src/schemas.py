"""Typed data models for the report workflow."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

ReportType = Literal["quick", "update", "initiation", "valuation_only", "healthcare_initiation"]
ScenarioName = Literal["bear", "base", "bull"]


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
    html_path: str | None = None
