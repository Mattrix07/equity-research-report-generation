"""Dynamic peer selection agent.

The goal is to avoid one static sector peer list. The selector starts from a broad
candidate universe, filters and scores companies by sector, industry, market-cap
similarity, revenue similarity and business-summary overlap, then returns the
best 4-5 peers for the requested company.

User-supplied peers still take precedence.
"""
from __future__ import annotations

import math
import re
from typing import Any

from src.data.yfinance_client import fetch_market_snapshot
from src.schemas import MarketSnapshot

# Broad discovery universe. These are not default peers for a sector; they are
# candidates that are dynamically scored against the requested company.
CANDIDATE_UNIVERSE = sorted(set([
    # Mega / large-cap tech and software
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "ORCL", "CRM", "ADBE", "NOW", "INTU", "IBM", "SAP", "SNOW", "DDOG",
    # Semis / hardware
    "NVDA", "AMD", "AVGO", "QCOM", "INTC", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL",
    # Biotech / pharma
    "AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "INCY", "ALNY", "BMRN", "UTHR", "ARGX", "IONS",
    "LLY", "NVO", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVS", "GSK", "SNY", "TAK", "RHHBY",
    # Medtech / tools / diagnostics
    "TMO", "DHR", "A", "ILMN", "IQV", "LH", "DGX", "ABT", "MDT", "SYK", "BSX", "ISRG", "EW", "DXCM", "ZBH",
    # Healthcare plans / services
    "UNH", "ELV", "CI", "HUM", "CNC", "CVS", "MOH", "HCA", "UHS", "THC",
    # Banks / financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "SCHW", "BLK", "BX", "KKR", "APO",
    # Insurance
    "BRK-B", "AIG", "TRV", "PGR", "CB", "MET", "PRU", "ALL", "AFL", "AON", "MMC",
    # Consumer
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "LULU", "TJX", "ROST", "AMZN",
    # Industrials
    "CAT", "DE", "HON", "GE", "MMM", "ETN", "EMR", "PH", "ROK", "ITW", "UPS", "FDX", "UNP", "CSX",
    # Energy / resources
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "VLO", "BHP", "RIO", "FCX", "NEM", "SCCO", "TECK", "VALE",
    # Utilities / infra / REITs
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "PLD", "AMT", "CCI", "EQIX", "SPG", "O",
]))

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "its", "their", "company", "companies", "products",
    "services", "including", "provides", "develops", "operates", "markets", "business", "customers", "through", "segment",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def _similarity(a: float | None, b: float | None) -> float:
    if not a or not b or a <= 0 or b <= 0:
        return 0.0
    distance = abs(math.log(a) - math.log(b))
    return max(0.0, 1.0 - min(distance / 2.5, 1.0))


def _score_peer(target: MarketSnapshot, peer: MarketSnapshot) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if peer.ticker.upper() == target.ticker.upper():
        return -999.0, ["excluded: same ticker"]

    if target.industry != "Unknown" and peer.industry == target.industry:
        score += 55
        reasons.append("same industry")
    elif target.sector != "Unknown" and peer.sector == target.sector:
        score += 25
        reasons.append("same sector")

    market_cap_score = _similarity(target.market_cap, peer.market_cap) * 20
    if market_cap_score:
        score += market_cap_score
        reasons.append("similar market cap")

    revenue_score = _similarity(target.revenue_ttm, peer.revenue_ttm) * 10
    if revenue_score:
        score += revenue_score
        reasons.append("similar revenue scale")

    target_tokens = _tokens(target.business_summary + " " + target.industry)
    peer_tokens = _tokens(peer.business_summary + " " + peer.industry)
    if target_tokens and peer_tokens:
        overlap = len(target_tokens & peer_tokens) / max(len(target_tokens), 1)
        if overlap:
            score += min(overlap * 20, 10)
            reasons.append("business description overlap")

    # Penalise companies with missing enterprise value or EBITDA because they are
    # less useful for EV/EBITDA comps.
    if not peer.enterprise_value or not peer.ebitda:
        score -= 8
        reasons.append("incomplete multiple data")

    return score, reasons


def select_dynamic_peer_tickers(target: MarketSnapshot, user_peers: list[str] | None = None, min_peers: int = 4, max_peers: int = 5) -> list[str]:
    if user_peers:
        return [p.upper().strip() for p in user_peers if p and p.upper().strip() != target.ticker.upper()][:max_peers]

    scored: list[tuple[float, str, list[str]]] = []
    for ticker in CANDIDATE_UNIVERSE:
        if ticker.upper() == target.ticker.upper():
            continue
        try:
            peer = fetch_market_snapshot(ticker)
        except Exception:
            continue
        score, reasons = _score_peer(target, peer)
        if score > 0:
            scored.append((score, ticker, reasons))

    scored.sort(reverse=True, key=lambda x: x[0])
    selected = [ticker for _, ticker, _ in scored[:max_peers]]

    # If the dynamic score is too restrictive, return the best available scored
    # peers rather than a static sector default.
    return selected[:max_peers]


def build_peer_selection_table(target: MarketSnapshot, peer_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for peer_dict in peer_snapshots:
        peer = MarketSnapshot(**peer_dict)
        score, reasons = _score_peer(target, peer)
        rows.append({
            "ticker": peer.ticker,
            "company_name": peer.company_name,
            "sector": peer.sector,
            "industry": peer.industry,
            "market_cap": peer.market_cap,
            "revenue_ttm": peer.revenue_ttm,
            "peer_score": round(score, 1),
            "selection_reasons": "; ".join(reasons),
        })
    return sorted(rows, key=lambda x: x.get("peer_score", 0), reverse=True)
