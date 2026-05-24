"""LLM-assisted peer selection.

The LLM proposes a peer set and explains inclusions/exclusions. Python then
verifies tickers and fetches market data. This keeps peer selection judgement-led
without trusting unsupported LLM facts.
"""
from __future__ import annotations

import asyncio
import json
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
            clean = str(ticker).upper().strip()
            if clean and clean not in tickers:
                tickers.append(clean)
        return tickers


def _clean_ticker(value: Any) -> str | None:
    ticker = str(value or "").upper().strip().replace(".", "-")
    ticker = "".join(ch for ch in ticker if ch.isalnum() or ch in {"-"})
    return ticker or None


def _clean_ticker_list(values: Any, target_ticker: str, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        ticker = _clean_ticker(value)
        if not ticker or ticker == target_ticker.upper() or ticker in out:
            continue
        out.append(ticker)
        if len(out) >= limit:
            break
    return out


async def select_peers_with_llm(snapshot: MarketSnapshot, candidate_tickers: list[str], max_peers: int = 5) -> LLMPeerSelection:
    if not llm_enabled():
        return LLMPeerSelection(enabled=False, error="LLM peer selector disabled or API key missing.")

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    system_prompt = (
        "You are an equity research associate selecting comparable companies. "
        "Choose peers based on business model, revenue drivers, customer/end-market exposure, scale, margins, capital intensity and valuation relevance. "
        "Do not choose a company simply because it is in the same broad sector. "
        "Use only the supplied company profile and candidate tickers. Return JSON only."
    )
    payload = {
        "target_company": snapshot.model_dump(),
        "candidate_tickers": candidate_tickers,
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
        return LLMPeerSelection(
            enabled=True,
            primary_peers=_clean_ticker_list(data.get("primary_peers"), snapshot.ticker, max_peers),
            secondary_peers=_clean_ticker_list(data.get("secondary_peers"), snapshot.ticker, 3),
            excluded_companies=list(data.get("excluded_companies", [])) if isinstance(data.get("excluded_companies"), list) else [],
            peer_rationale=str(data.get("peer_rationale", "")),
            reasoning_steps=[str(x) for x in data.get("reasoning_steps", [])[:6]] if isinstance(data.get("reasoning_steps"), list) else [],
            evidence_gaps=[str(x) for x in data.get("evidence_gaps", [])[:6]] if isinstance(data.get("evidence_gaps"), list) else [],
            raw_response=raw,
        )
    except Exception as exc:
        return LLMPeerSelection(enabled=True, error=str(exc))


def select_peers_with_llm_sync(snapshot: MarketSnapshot, candidate_tickers: list[str], max_peers: int = 5) -> LLMPeerSelection:
    return asyncio.run(select_peers_with_llm(snapshot, candidate_tickers, max_peers=max_peers))
