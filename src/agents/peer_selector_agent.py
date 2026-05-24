"""Dynamic peer selection agent.

The selector avoids static sector defaults, but it should also avoid the previous
slow path of calling yfinance for the entire broad universe on every request.
It now shortlists candidates by sector/industry/business keywords first, then
fetches only the most relevant candidates concurrently and scores those.

User-supplied peers still take precedence.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import re
from functools import lru_cache
from typing import Any

from src.data.yfinance_client import fetch_market_snapshot
from src.schemas import MarketSnapshot

CANDIDATE_UNIVERSE = sorted(set([
    # Networking, communications infrastructure, security and adjacent infrastructure software
    "CSCO", "ANET", "JNPR", "HPE", "DELL", "NTAP", "PSTG", "FFIV", "CIEN", "COMM", "UI", "MSI", "PANW", "FTNT", "CHKP", "ZS", "CRWD", "NET",
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

SECTOR_SHORTLISTS = {
    "technology": ["MSFT", "ORCL", "IBM", "CRM", "ADBE", "NOW", "ANET", "JNPR", "HPE", "DELL", "NTAP", "PANW", "FTNT", "CHKP", "FFIV", "CIEN"],
    "healthcare": ["JNJ", "PFE", "MRK", "ABBV", "BMY", "AMGN", "GILD", "REGN", "VRTX", "TMO", "DHR", "ABT", "MDT", "SYK"],
    "financial": ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "SCHW", "BLK"],
    "consumer": ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "LULU", "TJX"],
    "industrial": ["CAT", "DE", "HON", "GE", "MMM", "ETN", "EMR", "PH", "ROK", "ITW"],
    "energy": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "VLO"],
}

KEYWORD_SHORTLISTS = {
    "network": ["ANET", "JNPR", "HPE", "DELL", "FFIV", "CIEN", "COMM", "UI", "MSI"],
    "switch": ["ANET", "JNPR", "HPE", "DELL", "FFIV"],
    "router": ["ANET", "JNPR", "HPE", "FFIV"],
    "security": ["PANW", "FTNT", "CHKP", "ZS", "CRWD", "NET"],
    "cloud": ["MSFT", "AMZN", "GOOGL", "ORCL", "IBM", "SNOW", "DDOG", "NET"],
    "semiconductor": ["NVDA", "AMD", "AVGO", "QCOM", "INTC", "TXN", "MRVL"],
    "biotech": ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "ALNY", "BMRN"],
    "pharma": ["LLY", "NVO", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVS"],
    "medical": ["TMO", "DHR", "ABT", "MDT", "SYK", "BSX", "ISRG", "EW"],
}

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


@lru_cache(maxsize=512)
def _cached_snapshot(ticker: str) -> MarketSnapshot:
    return fetch_market_snapshot(ticker)


def _candidate_shortlist(target: MarketSnapshot, max_candidates: int = 28) -> list[str]:
    target_text = f"{target.sector} {target.industry} {target.business_summary}".lower()
    candidates: list[str] = []

    for sector_key, tickers in SECTOR_SHORTLISTS.items():
        if sector_key in target_text:
            candidates.extend(tickers)

    for keyword, tickers in KEYWORD_SHORTLISTS.items():
        if keyword in target_text:
            candidates.extend(tickers)

    # If the text match is sparse, use the broad universe as a fallback, but cap
    # the fetch count. This keeps the UI from sitting on peer selection for ages.
    if not candidates:
        candidates.extend(CANDIDATE_UNIVERSE[:max_candidates])

    candidates = [ticker for ticker in dict.fromkeys(candidates) if ticker.upper() != target.ticker.upper()]
    return candidates[:max_candidates]


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

    if not peer.enterprise_value or not peer.ebitda:
        score -= 8
        reasons.append("incomplete multiple data")

    return score, reasons


def select_dynamic_peer_tickers(target: MarketSnapshot, user_peers: list[str] | None = None, min_peers: int = 4, max_peers: int = 5) -> list[str]:
    if user_peers:
        return [p.upper().strip() for p in user_peers if p and p.upper().strip() != target.ticker.upper()][:max_peers]

    candidates = _candidate_shortlist(target)
    scored: list[tuple[float, str, list[str]]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(_cached_snapshot, ticker): ticker for ticker in candidates}
        for future in as_completed(future_map):
            ticker = future_map[future]
            try:
                peer = future.result()
            except Exception:
                continue
            score, reasons = _score_peer(target, peer)
            if score > 0:
                scored.append((score, ticker, reasons))

    scored.sort(reverse=True, key=lambda x: x[0])
    selected = [ticker for _, ticker, _ in scored[:max_peers]]
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
