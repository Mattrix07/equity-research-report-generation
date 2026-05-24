"""Dynamic peer selection agent.

The selector avoids static sector defaults, but it should also avoid the previous
slow path of calling yfinance for the entire broad universe on every request.
It shortlists candidates by sector/industry/business keywords first, then fetches
only the most relevant candidates concurrently and scores those.

User-supplied peers still take precedence.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import re
from functools import lru_cache
from typing import Any

from src.data.yfinance_client import fetch_market_snapshot
from src.schemas import MarketSnapshot

CANDIDATE_UNIVERSE = sorted(set([
    # Internet platforms, digital advertising, streaming and marketplace peers
    "META", "GOOGL", "SNAP", "PINS", "RDDT", "TTD", "NFLX", "SPOT", "ROKU", "BIDU", "TCEHY", "AMZN", "MSFT", "AAPL",
    # Networking, communications infrastructure, security and adjacent infrastructure software
    "CSCO", "ANET", "JNPR", "HPE", "DELL", "NTAP", "PSTG", "FFIV", "CIEN", "COMM", "UI", "MSI", "PANW", "FTNT", "CHKP", "ZS", "CRWD", "NET",
    # Mega / large-cap tech and software
    "ORCL", "CRM", "ADBE", "NOW", "INTU", "IBM", "SAP", "SNOW", "DDOG",
    # Semis / hardware
    "NVDA", "AMD", "AVGO", "QCOM", "INTC", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "TSM", "ASML", "ARM", "SMCI",
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
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "LULU", "TJX", "ROST",
    # Industrials
    "CAT", "DE", "HON", "GE", "MMM", "ETN", "EMR", "PH", "ROK", "ITW", "UPS", "FDX", "UNP", "CSX",
    # Energy / resources
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "VLO", "BHP", "RIO", "FCX", "NEM", "SCCO", "TECK", "VALE",
    # Utilities / infra / REITs
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "PLD", "AMT", "CCI", "EQIX", "SPG", "O",
]))

SECTOR_SHORTLISTS = {
    "communication": ["GOOGL", "SNAP", "PINS", "RDDT", "TTD", "NFLX", "SPOT", "ROKU", "BIDU", "TCEHY", "AMZN", "MSFT"],
    "technology": ["MSFT", "ORCL", "IBM", "CRM", "ADBE", "NOW", "ANET", "JNPR", "HPE", "DELL", "NTAP", "PANW", "FTNT", "CHKP", "FFIV", "CIEN", "GOOGL", "META", "AMZN", "TTD"],
    "healthcare": ["JNJ", "PFE", "MRK", "ABBV", "BMY", "AMGN", "GILD", "REGN", "VRTX", "TMO", "DHR", "ABT", "MDT", "SYK"],
    "financial": ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "SCHW", "BLK"],
    "consumer": ["WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "LULU", "TJX"],
    "industrial": ["CAT", "DE", "HON", "GE", "MMM", "ETN", "EMR", "PH", "ROK", "ITW"],
    "energy": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "VLO"],
}

KEYWORD_SHORTLISTS = {
    "advertising": ["GOOGL", "SNAP", "PINS", "RDDT", "TTD", "AMZN", "BIDU"],
    "social": ["GOOGL", "SNAP", "PINS", "RDDT", "TCEHY"],
    "media": ["GOOGL", "NFLX", "SPOT", "ROKU", "SNAP", "PINS"],
    "metaverse": ["GOOGL", "MSFT", "AAPL", "NVDA", "SNAP"],
    "platform": ["GOOGL", "AMZN", "MSFT", "AAPL", "SNAP", "PINS", "TTD"],
    "network": ["ANET", "JNPR", "HPE", "DELL", "FFIV", "CIEN", "COMM", "UI", "MSI"],
    "switch": ["ANET", "JNPR", "HPE", "DELL", "FFIV"],
    "router": ["ANET", "JNPR", "HPE", "FFIV"],
    "security": ["PANW", "FTNT", "CHKP", "ZS", "CRWD", "NET"],
    "cloud": ["MSFT", "AMZN", "GOOGL", "ORCL", "IBM", "SNOW", "DDOG", "NET"],
    "semiconductor": ["NVDA", "AMD", "AVGO", "QCOM", "INTC", "TXN", "MRVL", "TSM", "ASML", "ARM", "SMCI"],
    "gpu": ["AMD", "AVGO", "TSM", "ASML", "MRVL", "ARM", "SMCI"],
    "graphics": ["AMD", "AVGO", "TSM", "ASML", "MRVL", "ARM", "SMCI"],
    "data center": ["AMD", "AVGO", "TSM", "ASML", "MRVL", "ANET", "SMCI"],
    "accelerated": ["AMD", "AVGO", "TSM", "ASML", "MRVL", "ARM", "SMCI"],
    "biotech": ["AMGN", "GILD", "REGN", "VRTX", "BIIB", "MRNA", "ALNY", "BMRN"],
    "pharma": ["LLY", "NVO", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVS"],
    "medical": ["TMO", "DHR", "ABT", "MDT", "SYK", "BSX", "ISRG", "EW"],
}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "its", "their", "company", "companies", "products",
    "services", "including", "provides", "develops", "operates", "markets", "business", "customers", "through", "segment",
}


def _as_text(value: Any) -> str:
    """Defensively coerce provider/LLM values before regex or `.lower()` calls.

    Some upstream providers can return tuples/lists for text-like fields. Passing
    those directly into `re.findall` causes: expected string or bytes-like object,
    got 'tuple'.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, (tuple, list, set)):
        return " ".join(_as_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return str(value)


def _tokens(text: Any) -> set[str]:
    safe_text = _as_text(text).lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", safe_text)
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
    target_text = _as_text([target.sector, target.industry, target.business_summary]).lower()
    candidates: list[str] = []

    if target.ticker.upper() in {"META", "GOOGL", "SNAP", "PINS", "RDDT", "TTD"} or any(x in target_text for x in ["advertising", "social", "family of apps", "digital", "internet content", "communication services"]):
        candidates.extend(["GOOGL", "SNAP", "PINS", "RDDT", "TTD", "NFLX", "SPOT", "ROKU", "AMZN", "MSFT", "TCEHY", "BIDU"])

    if target.ticker.upper() in {"NVDA", "AMD", "AVGO", "MRVL", "TSM", "ASML", "ARM"} or any(x in target_text for x in ["semiconductor", "gpu", "graphics", "data center", "accelerated computing"]):
        candidates.extend(["AMD", "AVGO", "TSM", "ASML", "MRVL", "QCOM", "ARM", "MU", "ANET", "SMCI"])

    for sector_key, tickers in SECTOR_SHORTLISTS.items():
        if sector_key in target_text:
            candidates.extend(tickers)

    for keyword, tickers in KEYWORD_SHORTLISTS.items():
        if keyword in target_text:
            candidates.extend(tickers)

    if not candidates:
        candidates.extend(CANDIDATE_UNIVERSE[:max_candidates])

    candidates = [ticker for ticker in dict.fromkeys(candidates) if ticker.upper() != target.ticker.upper()]
    return candidates[:max_candidates]


def _score_peer(target: MarketSnapshot, peer: MarketSnapshot) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if peer.ticker.upper() == target.ticker.upper():
        return -999.0, ["excluded: same ticker"]

    target_text = _as_text([target.industry, target.business_summary]).lower()
    peer_text = _as_text([peer.industry, peer.business_summary]).lower()

    if any(x in target_text for x in ["advertising", "social", "family of apps", "digital"]):
        if any(x in peer_text for x in ["advertising", "social", "search", "video", "streaming", "digital"]):
            score += 45
            reasons.append("digital advertising/platform exposure")
        if peer.ticker.upper() in {"GOOGL", "SNAP", "PINS", "RDDT", "TTD", "AMZN"}:
            score += 30
            reasons.append("explicit internet advertising peer")

    if any(x in target_text for x in ["semiconductor", "gpu", "graphics", "data center", "accelerated"]):
        if any(x in peer_text for x in ["semiconductor", "chip", "silicon", "gpu", "data center", "foundry", "server"]):
            score += 45
            reasons.append("AI semiconductor / infrastructure exposure")
        if peer.ticker.upper() in {"AMD", "AVGO", "TSM", "ASML", "MRVL", "QCOM", "ARM", "MU", "SMCI"}:
            score += 30
            reasons.append("explicit semiconductor / AI infrastructure peer")

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

    target_tokens = _tokens([target.business_summary, target.industry])
    peer_tokens = _tokens([peer.business_summary, peer.industry])
    if target_tokens and peer_tokens:
        overlap = len(target_tokens & peer_tokens) / max(len(target_tokens), 1)
        if overlap:
            score += min(overlap * 20, 10)
            reasons.append("business description overlap")

    if peer.ticker.upper() in {"WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST"} and any(x in target_text for x in ["advertising", "social", "digital", "semiconductor", "gpu"]):
        score -= 80
        reasons.append("excluded/penalised: retail business model mismatch")

    if not peer.enterprise_value or not peer.ebitda:
        score -= 8
        reasons.append("incomplete multiple data")

    return score, reasons


def select_dynamic_peer_tickers(target: MarketSnapshot, user_peers: list[str] | None = None, min_peers: int = 4, max_peers: int = 5) -> list[str]:
    if user_peers:
        return [str(p).upper().strip() for p in user_peers if p and str(p).upper().strip() != target.ticker.upper()][:max_peers]

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
