"""Company classifier and valuation router.

This module prevents the app from forcing every company through a generic DCF.
It classifies the company, chooses suitable valuation frameworks and defines the
terminal-value logic that should be used.
"""
from __future__ import annotations

from src.schemas import CompanyClassification, HistoricalFinancials, MarketSnapshot


def classify_company(snapshot: MarketSnapshot, historicals: HistoricalFinancials) -> CompanyClassification:
    sector = (snapshot.sector or "Unknown").lower()
    industry = (snapshot.industry or "Unknown").lower()
    summary = (snapshot.business_summary or "").lower()
    text = " ".join([sector, industry, summary])

    warnings: list[str] = []
    evidence = [f"Sector: {snapshot.sector}", f"Industry: {snapshot.industry}"]

    if any(k in text for k in ["bank", "banks", "credit", "lending", "mortgage"]):
        return CompanyClassification(
            primary_type="bank_or_lender",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["bank_insurer_roe_pbv", "relative_valuation"],
            terminal_value_method="not_applicable",
            rationale="Bank and lending businesses are better framed around ROE, book value, capital strength, credit losses and P/B rather than a generic operating-company DCF.",
            evidence=evidence,
            warnings=warnings,
        )

    if any(k in text for k in ["insurance", "insurer", "reinsurance", "underwriting"]):
        return CompanyClassification(
            primary_type="insurer",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["bank_insurer_roe_pbv", "relative_valuation"],
            terminal_value_method="not_applicable",
            rationale="Insurance companies should be assessed using book value, ROE, underwriting performance, capital adequacy and peer multiples, not a simple FCF perpetuity model.",
            evidence=evidence,
            warnings=warnings,
        )

    if any(k in text for k in ["gold", "copper", "lithium", "iron ore", "coal", "uranium", "mining", "miner", "resources", "metals", "royalty stream"]):
        return CompanyClassification(
            primary_type="resources_or_mining",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["mining_nav", "relative_valuation"],
            terminal_value_method="finite_life",
            rationale="Resource assets often require NAV based on reserves, production schedules, commodity prices, capex and finite mine life rather than perpetual terminal growth.",
            evidence=evidence,
            warnings=["Mining NAV requires project-level reserves, production and commodity price assumptions; yfinance data alone is insufficient."] + warnings,
        )

    if any(k in text for k in ["biotechnology", "biotech", "clinical", "phase 1", "phase 2", "phase 3", "fda", "therapeutic", "drug", "pipeline"]):
        method = "royalty_healthcare_sotp" if any(k in text for k in ["royalty", "milestone", "partner", "licensed"] ) else "biotech_rnpv"
        return CompanyClassification(
            primary_type="healthcare_pipeline_or_royalty",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=[method, "relative_valuation"],
            terminal_value_method="asset_level_rnpv",
            rationale="Pipeline and royalty-backed healthcare companies should use asset-level risk-adjusted valuation, clinical probability weighting, launch timing, peak sales, royalties and milestones.",
            evidence=evidence,
            warnings=["Pipeline valuation needs asset-level clinical-stage, probability, pricing, penetration and launch timing assumptions."] + warnings,
        )

    if any(k in text for k in ["software", "saas", "cloud", "subscription", "platform", "application software"]):
        return CompanyClassification(
            primary_type="software_or_saas",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["saas_unit_economics", "mature_operating_dcf", "relative_valuation"],
            terminal_value_method="perpetuity_growth",
            rationale="Software companies should be assessed using revenue durability, retention, operating leverage, FCF conversion, reinvestment intensity and peer multiples alongside DCF.",
            evidence=evidence,
            warnings=warnings,
        )

    if any(k in text for k in ["semiconductor", "hardware", "consumer electronics", "technology", "devices", "services"]):
        return CompanyClassification(
            primary_type="mature_technology_or_platform",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["mature_operating_dcf", "sotp", "relative_valuation"],
            terminal_value_method="perpetuity_growth",
            rationale="Mature technology platforms should use a triangulated approach: FCF/DCF, segment or services mix analysis, buybacks, ROIC durability and peer multiple cross-checks.",
            evidence=evidence,
            warnings=warnings,
        )

    if any(k in text for k in ["utilities", "infrastructure", "industrial", "manufacturing", "transportation", "airline", "railroad", "energy"]):
        return CompanyClassification(
            primary_type="asset_heavy_operating_company",
            sector=snapshot.sector,
            industry=snapshot.industry,
            valuation_methods=["asset_heavy_industrial", "mature_operating_dcf", "relative_valuation"],
            terminal_value_method="exit_multiple",
            rationale="Asset-heavy companies require capital intensity, maintenance capex, leverage and cycle-aware exit multiple analysis alongside DCF.",
            evidence=evidence,
            warnings=warnings,
        )

    warnings.append("Company type could not be classified with high confidence from available metadata; valuation should be treated as preliminary.")
    return CompanyClassification(
        primary_type="general_operating_company",
        sector=snapshot.sector,
        industry=snapshot.industry,
        valuation_methods=["mature_operating_dcf", "relative_valuation"],
        terminal_value_method="perpetuity_growth",
        rationale="Defaulted to a general operating company valuation framework because no specialist sector pattern was confidently identified.",
        evidence=evidence,
        warnings=warnings,
    )
