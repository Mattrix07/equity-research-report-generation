"""Company-specific evidence agent.

Builds an evidence pack that can be used to populate sector-specific workbook
tabs. The first layer is deterministic and grounded in yfinance/company metadata.
When the LLM committee is enabled, the LLM can convert this evidence into sector
model rows without inventing facts.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from openai import AsyncOpenAI

from src.config import settings
from src.agents.llm_committee import llm_enabled, openai_chat_kwargs
from src.schemas import (
    CompanyClassification,
    CompanyEvidencePack,
    DynamicAssumptions,
    EvidenceItem,
    FinancialModelPlan,
    HistoricalFinancials,
    MarketSnapshot,
    SectorTabEvidence,
)


def _last_values(values: dict[str, float], n: int = 4) -> list[tuple[str, float]]:
    return [(k, values[k]) for k in sorted(values.keys())[-n:] if k in values]


def _evidence(source_type: str, source_name: str, title: str, topic: str, value: Any = None, period: str | None = None, url: str | None = None, excerpt: str = "", confidence: str = "medium") -> EvidenceItem:
    return EvidenceItem(
        source_type=source_type,
        source_name=source_name,
        title=title,
        metric_or_topic=topic,
        value=None if value is None else str(value),
        period_or_date=period,
        url=url,
        excerpt=excerpt,
        confidence=confidence,
    )


def build_base_evidence_pack(
    snapshot: MarketSnapshot,
    historicals: HistoricalFinancials,
    classification: CompanyClassification,
    dynamic_assumptions: DynamicAssumptions,
    model_plan: FinancialModelPlan,
    source_urls: list[str] | None = None,
) -> CompanyEvidencePack:
    source_urls = source_urls or []
    items: list[EvidenceItem] = []

    items.append(_evidence("market_data", "yfinance", "Company classification", "sector_industry", f"{snapshot.sector} / {snapshot.industry}", excerpt=classification.rationale, confidence="high"))
    items.append(_evidence("market_data", "yfinance", "Business summary", "business_description", excerpt=snapshot.business_summary[:1200], confidence="medium"))
    items.append(_evidence("market_data", "yfinance", "Current market price", "current_price", snapshot.current_price, confidence="high"))
    items.append(_evidence("market_data", "yfinance", "Market capitalisation", "market_cap", snapshot.market_cap, confidence="high"))
    items.append(_evidence("market_data", "yfinance", "Enterprise value", "enterprise_value", snapshot.enterprise_value, confidence="medium"))
    items.append(_evidence("market_data", "yfinance", "Net debt", "net_debt", snapshot.net_debt, confidence="medium"))
    items.append(_evidence("market_data", "yfinance", "Beta", "beta", snapshot.beta, confidence="medium"))

    for year, value in _last_values(historicals.revenue):
        items.append(_evidence("financial_statement", "yfinance", "Historical revenue", "revenue", value, year, confidence="medium"))
    for year, value in _last_values(historicals.ebitda):
        items.append(_evidence("financial_statement", "yfinance", "Historical EBITDA", "ebitda", value, year, confidence="medium"))
    for year, value in _last_values(historicals.free_cash_flow):
        items.append(_evidence("financial_statement", "yfinance", "Historical FCF", "free_cash_flow", value, year, confidence="medium"))
    for year, value in _last_values(historicals.ebitda_margin):
        items.append(_evidence("financial_statement", "yfinance", "Historical EBITDA margin", "ebitda_margin", value, year, confidence="medium"))

    for idx, url in enumerate(source_urls, start=1):
        items.append(_evidence("user_source_url", "user_provided", f"User source URL {idx}", "source_to_review", url=url, excerpt="Source URL provided by user. Fetching/parsing external documents should be added with a filings/presentation ingestion layer.", confidence="low"))

    gaps = []
    for driver in model_plan.forecast_drivers:
        gaps.extend([f"{driver.driver_name}: needs evidence for {', '.join(driver.evidence_required[:4])}"])

    pack = CompanyEvidencePack(
        ticker=snapshot.ticker,
        evidence_items=items,
        source_urls=source_urls,
        gaps=gaps[:20],
        warnings=classification.warnings + dynamic_assumptions.warnings,
    )
    pack.sector_tab_evidence = _fallback_sector_tab_evidence(pack, classification, snapshot)
    return pack


def _fallback_sector_tab_evidence(pack: CompanyEvidencePack, classification: CompanyClassification, snapshot: MarketSnapshot) -> dict[str, SectorTabEvidence]:
    rows_by_tab: dict[str, SectorTabEvidence] = {}

    healthcare_rows = [
        {"asset": "Marketed portfolio", "indication": "Multiple", "phase": "Approved", "pos": 1.0, "evidence": "Existing marketed products from company business summary / yfinance metadata", "source": "yfinance business summary", "status": "requires product-level revenue split"},
        {"asset": "Pipeline assets", "indication": "To be sourced", "phase": "To be sourced", "pos": "To be sourced", "evidence": "Pipeline-specific data not yet ingested from filings/investor presentations", "source": "evidence gap", "status": "needs filing/presentation extraction"},
    ]
    mining_rows = [
        {"asset": "Project 1", "production": "To be sourced", "commodity_price": "To be sourced", "aisc": "To be sourced", "capex": "To be sourced", "evidence": "Requires reserves, mine plan and commodity deck", "source": "evidence gap"},
    ]
    saas_rows = [
        {"metric": "ARR / subscription revenue", "value": "To be sourced", "evidence": "Requires ARR/NRR/churn disclosures", "source": "evidence gap"},
    ]
    financials_rows = [
        {"metric": "Book value per share", "value": snapshot.book_value, "evidence": "yfinance book value field", "source": "yfinance"},
        {"metric": "ROE", "value": snapshot.return_on_equity, "evidence": "yfinance returnOnEquity field", "source": "yfinance"},
    ]

    rows_by_tab["Healthcare rNPV"] = SectorTabEvidence(tab_name="Healthcare rNPV", rows=healthcare_rows, notes=["LLM/source extraction can replace placeholders with product/pipeline evidence."])
    rows_by_tab["Mining NAV"] = SectorTabEvidence(tab_name="Mining NAV", rows=mining_rows, notes=["NAV requires project-level evidence."])
    rows_by_tab["SaaS Unit Economics"] = SectorTabEvidence(tab_name="SaaS Unit Economics", rows=saas_rows, notes=["SaaS metrics require company disclosures."])
    rows_by_tab["Financials ROE-PBV"] = SectorTabEvidence(tab_name="Financials ROE-PBV", rows=financials_rows, notes=["Financials engine uses balance-sheet and ROE evidence."])
    return rows_by_tab


async def enrich_sector_tab_evidence_with_llm(pack: CompanyEvidencePack, classification: CompanyClassification, snapshot: MarketSnapshot) -> CompanyEvidencePack:
    if not llm_enabled():
        return pack

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    prompt = {
        "instruction": (
            "Convert the evidence pack into company-specific rows for sector model tabs. Use only provided evidence. "
            "Do not invent pipeline assets, commodity projects, ARR metrics, guidance, or management claims. "
            "If evidence is missing, mark value as 'To be sourced' and explain the gap. Return JSON only with key 'sector_tab_evidence'."
        ),
        "ticker": pack.ticker,
        "classification": classification.model_dump(),
        "company": snapshot.model_dump(),
        "evidence_items": [item.model_dump() for item in pack.evidence_items],
        "existing_sector_tab_evidence": {k: v.model_dump() for k, v in pack.sector_tab_evidence.items()},
    }
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                **openai_chat_kwargs(
                    model=settings.llm_valuation_model,
                    messages=[
                        {"role": "system", "content": "You are an equity research modelling associate. Populate model tab evidence strictly from supplied evidence."},
                        {"role": "user", "content": json.dumps(prompt, default=str)[:50000]},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
            ),
            timeout=settings.llm_timeout_seconds,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        tab_data = data.get("sector_tab_evidence", {})
        for tab_name, tab_payload in tab_data.items():
            if isinstance(tab_payload, dict):
                pack.sector_tab_evidence[tab_name] = SectorTabEvidence(
                    tab_name=tab_name,
                    rows=tab_payload.get("rows", []),
                    notes=tab_payload.get("notes", []),
                )
    except Exception as exc:
        pack.warnings.append(f"LLM evidence enrichment failed: {exc}")
    return pack


def build_company_evidence_pack(
    snapshot: MarketSnapshot,
    historicals: HistoricalFinancials,
    classification: CompanyClassification,
    dynamic_assumptions: DynamicAssumptions,
    model_plan: FinancialModelPlan,
    source_urls: list[str] | None = None,
) -> CompanyEvidencePack:
    pack = build_base_evidence_pack(snapshot, historicals, classification, dynamic_assumptions, model_plan, source_urls)
    if llm_enabled():
        pack = asyncio.run(enrich_sector_tab_evidence_with_llm(pack, classification, snapshot))
    return pack
