"""LLM-assisted peer selection.

The LLM proposes a peer set and explains inclusions/exclusions. Python then
normalises the LLM output, verifies that selected peers are valid candidate
symbols, and fetches market data. This keeps peer selection judgement-led without
trusting unsupported or malformed LLM facts.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from src.agents.llm_committee import llm_enabled, openai_chat_kwargs
from src.config import settings
from src.schemas import MarketSnapshot


@dataclass
class LLMPeerSelection:
    enabled: bool = False
    primary_peers: list[str] = field(default_factory=list)
    secondary_peers: list[str] = field(default_factory=list)
    excluded_companies: list[dict[str, Any]] = field(default_factory=list)
    peer_rationale: str = ""
    reasoning_steps: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    error: str | None = None
    raw_response: str = ""

    @property
    def selected_tickers(self) -> list[str]:
        tickers: list[str] = []
        for ticker in self.primary_peers + self.secondary_peers:
            clean = _clean_ticker(ticker)
            if clean and clean not in tickers:
                tickers.append(clean)
        return tickers


async def _close_client(client: AsyncOpenAI) -> None:
    try:
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Closing is best-effort. We do not want cleanup issues to break report generation.
        pass


def _clean_ticker(value: Any) -> str | None:
    """Extract a usable ticker from LLM output.

    The LLM sometimes returns objects such as
    {"ticker": "AMZN", "company_name": "Amazon", "rationale": "..."}
    even when instructed to return strings. The old implementation stringified
    the full object, creating invalid tickers like TICKERAMZNCOMPANYNAME...
    """
    if isinstance(value, dict):
        for key in ("ticker", "symbol", "company_ticker"):
            if key in value:
                return _clean_ticker(value.get(key))
        return None
    if not isinstance(value, str):
        return None
    text = value.upper().strip().replace(".", "-")
    # Accept direct ticker-like strings. Also tolerate "Ticker: AMZN".
    match = re.search(r"\b[A-Z]{1,5}(?:-[A-Z])?\b", text)
    if not match:
        return None
    return match.group(0)


def _clean_ticker_list(values: Any, target_ticker: str, limit: int, allowed_tickers: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        ticker = _clean_ticker(value)
        if not ticker or ticker == target_ticker.upper() or ticker in out:
            continue
        if allowed_tickers and ticker not in allowed_tickers:
            continue
        out.append(ticker)
        if len(out) >= limit:
            break
    return out


def _normalise_exclusions(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[:10]:
        if isinstance(item, dict):
            ticker = _clean_ticker(item)
            out.append({
                "ticker": ticker,
                "company_name": item.get("company_name") or item.get("name"),
                "rationale": item.get("rationale") or item.get("reason"),
            })
        elif isinstance(item, str):
            out.append({"ticker": _clean_ticker(item), "rationale": item})
    return out


async def select_peers_with_llm(snapshot: MarketSnapshot, candidate_tickers: list[str], max_peers: int = 5) -> LLMPeerSelection:
    if not llm_enabled():
        return LLMPeerSelection(enabled=False, error="LLM peer selector disabled or API key missing.")

    allowed_tickers = {ticker for ticker in (_clean_ticker(t) for t in candidate_tickers) if ticker}
    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    system_prompt = (
        "You are an equity research associate selecting comparable companies. "
        "Choose peers based on business model, revenue drivers, customer/end-market exposure, scale, margins, capital intensity and valuation relevance. "
        "Do not choose a company simply because it is in the same broad sector. "
        "Use only the supplied company profile and candidate tickers. Return JSON only. "
        "IMPORTANT: primary_peers and secondary_peers must be arrays of ticker strings only, e.g. [\"NFLX\", \"DIS\"]. "
        "Put rationale in peer_rationale or excluded_companies, never inside primary_peers or secondary_peers."
    )
    payload = {
        "target_company": snapshot.model_dump(),
        "candidate_tickers": sorted(allowed_tickers),
        "instructions": {
            "max_primary_peers": max_peers,
            "max_secondary_peers": 3,
            "required_json_fields": [
                "primary_peers",
                "secondary_peers",
                "excluded_companies",
                "peer_rationale",
                "reasoning_steps",
                "evidence_gaps",
            ],
            "format_rules": {
                "primary_peers": "array of ticker strings only",
                "secondary_peers": "array of ticker strings only",
                "excluded_companies": "array of objects with ticker and rationale",
            },
        },
    }
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                **openai_chat_kwargs(
                    model=settings.llm_manager_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, default=str, indent=2)},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            ),
            timeout=settings.llm_timeout_seconds,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        primary = _clean_ticker_list(data.get("primary_peers"), snapshot.ticker, max_peers, allowed_tickers)
        secondary = _clean_ticker_list(data.get("secondary_peers"), snapshot.ticker, 3, allowed_tickers)
        return LLMPeerSelection(
            enabled=True,
            primary_peers=primary,
            secondary_peers=[ticker for ticker in secondary if ticker not in primary],
            excluded_companies=_normalise_exclusions(data.get("excluded_companies")),
            peer_rationale=str(data.get("peer_rationale", "")),
            reasoning_steps=[str(x) for x in data.get("reasoning_steps", [])[:6]] if isinstance(data.get("reasoning_steps"), list) else [],
            evidence_gaps=[str(x) for x in data.get("evidence_gaps", [])[:6]] if isinstance(data.get("evidence_gaps"), list) else [],
            raw_response=raw,
        )
    except Exception as exc:
        return LLMPeerSelection(enabled=True, error=str(exc))
    finally:
        await _close_client(client)


def select_peers_with_llm_sync(snapshot: MarketSnapshot, candidate_tickers: list[str], max_peers: int = 5) -> LLMPeerSelection:
    return asyncio.run(select_peers_with_llm(snapshot, candidate_tickers, max_peers=max_peers))
