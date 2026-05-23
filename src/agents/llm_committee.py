"""Optional multi-LLM investment committee.

This layer lets LLM agents form independent views from the same evidence pack
that feeds the deterministic Python valuation engines. The deterministic model
remains the numerical anchor; the LLM committee adds judgement, challenge,
interpretation and a reconciled recommendation.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from src.config import settings
from src.schemas import DCFOutput, ForecastRow, LLMCommitteeOutput, LLMOpinion, MarketSnapshot, TechnicalSnapshot


def llm_enabled() -> bool:
    placeholder_values = {"", "your_openai_or_openai_compatible_key_here", "your_key_here"}
    return settings.enable_llm_committee and settings.openai_api_key not in placeholder_values


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _evidence_pack(
    snapshot: MarketSnapshot,
    forecasts: dict[str, list[ForecastRow]],
    dcfs: dict[str, DCFOutput],
    technicals: TechnicalSnapshot,
    comps: dict[str, Any],
) -> dict[str, Any]:
    return {
        "company": snapshot.model_dump(),
        "forecast_summary": {
            scenario: [row.model_dump() for row in rows] for scenario, rows in forecasts.items()
        },
        "dcf_outputs": {scenario: dcf.model_dump() for scenario, dcf in dcfs.items()},
        "technical_analysis": technicals.model_dump(),
        "peer_comps": comps,
        "instruction": (
            "Use only this evidence pack. Do not invent missing facts. If evidence is missing, say so. "
            "You may form an independent valuation view, but distinguish it from the Python DCF output."
        ),
    }


def _json_prompt(data: dict[str, Any], max_chars: int = 45000) -> str:
    text = json.dumps(data, default=str, indent=2)
    return text[:max_chars]


def _parse_opinion(raw: str, agent_name: str, model: str, role: str, current_price: float | None) -> LLMOpinion:
    try:
        data = json.loads(raw)
        target = _safe_float(data.get("target_price"))
        implied = None
        if current_price and target:
            implied = target / current_price - 1
        return LLMOpinion(
            agent_name=agent_name,
            model=model,
            role=role,
            recommendation=str(data.get("recommendation", "REVIEW")).upper(),
            confidence=int(data.get("confidence", 50)),
            target_price=target,
            implied_upside=implied,
            thesis=str(data.get("thesis", "")),
            valuation_view=str(data.get("valuation_view", "")),
            key_assumptions=list(data.get("key_assumptions", [])),
            key_risks=list(data.get("key_risks", [])),
            challenge_to_consensus=str(data.get("challenge_to_consensus", "")),
            evidence_gaps=list(data.get("evidence_gaps", [])),
            raw_response=raw,
        )
    except Exception as exc:
        return LLMOpinion(agent_name=agent_name, model=model, role=role, raw_response=raw, error=str(exc))


async def _call_agent(
    client: AsyncOpenAI,
    agent_name: str,
    model: str,
    role: str,
    system_prompt: str,
    evidence: dict[str, Any],
    current_price: float | None,
) -> LLMOpinion:
    user_prompt = (
        "Review the evidence pack and return JSON only with these fields: "
        "recommendation, confidence, target_price, thesis, valuation_view, "
        "key_assumptions, key_risks, challenge_to_consensus, evidence_gaps.\n\n"
        f"Evidence pack:\n{_json_prompt(evidence)}"
    )
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            ),
            timeout=settings.llm_timeout_seconds,
        )
        raw = response.choices[0].message.content or "{}"
        return _parse_opinion(raw, agent_name, model, role, current_price)
    except Exception as exc:
        return LLMOpinion(agent_name=agent_name, model=model, role=role, error=str(exc))


async def run_llm_committee(
    snapshot: MarketSnapshot,
    forecasts: dict[str, list[ForecastRow]],
    dcfs: dict[str, DCFOutput],
    technicals: TechnicalSnapshot,
    comps: dict[str, Any],
) -> LLMCommitteeOutput:
    if not llm_enabled():
        return LLMCommitteeOutput(enabled=False)

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    evidence = _evidence_pack(snapshot, forecasts, dcfs, technicals, comps)

    agent_specs = [
        (
            "Bull Analyst",
            settings.llm_bull_model,
            "Constructive fundamental analyst",
            "You are a constructive equity research analyst. Identify the strongest investment thesis, upside drivers, valuation support and catalysts. Stay grounded in the evidence pack.",
        ),
        (
            "Bear Analyst",
            settings.llm_bear_model,
            "Contrarian risk analyst",
            "You are a sceptical equity research analyst. Challenge the thesis, stress test assumptions, identify valuation downside and highlight missing evidence. Stay grounded in the evidence pack.",
        ),
        (
            "Valuation Analyst",
            settings.llm_valuation_model,
            "Independent valuation analyst",
            "You are a valuation specialist. Review the Python DCF, scenario outputs, sensitivities, peer comps and technicals. Form an independent valuation view and explain whether the model assumptions are reasonable.",
        ),
    ]

    opinions = await asyncio.gather(*[
        _call_agent(client, name, model, role, prompt, evidence, snapshot.current_price)
        for name, model, role, prompt in agent_specs
    ])

    synthesis_pack = {
        "deterministic_base_dcf": dcfs.get("base").model_dump() if dcfs.get("base") else None,
        "current_price": snapshot.current_price,
        "committee_opinions": [op.model_dump() for op in opinions],
        "instruction": "Reconcile the deterministic DCF and the LLM committee opinions into a final investment committee view.",
    }

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.llm_report_writer_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the chair of an equity research investment committee. Synthesize the bull, bear and valuation analyst views. "
                            "Return JSON only with: final_recommendation, final_target_price, final_confidence, final_thesis, final_risks, final_evidence_gaps. "
                            "Do not invent facts. Explicitly balance deterministic valuation against judgement-based LLM views."
                        ),
                    },
                    {"role": "user", "content": _json_prompt(synthesis_pack)},
                ],
                temperature=0.15,
                response_format={"type": "json_object"},
            ),
            timeout=settings.llm_timeout_seconds,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        return LLMCommitteeOutput(
            enabled=True,
            opinions=list(opinions),
            final_recommendation=str(data.get("final_recommendation", "REVIEW")).upper(),
            final_target_price=_safe_float(data.get("final_target_price")),
            final_confidence=int(data.get("final_confidence", 50)),
            final_thesis=str(data.get("final_thesis", "")),
            final_risks=list(data.get("final_risks", [])),
            final_evidence_gaps=list(data.get("final_evidence_gaps", [])),
        )
    except Exception as exc:
        return LLMCommitteeOutput(enabled=True, opinions=list(opinions), synthesis_error=str(exc))


def run_llm_committee_sync(
    snapshot: MarketSnapshot,
    forecasts: dict[str, list[ForecastRow]],
    dcfs: dict[str, DCFOutput],
    technicals: TechnicalSnapshot,
    comps: dict[str, Any],
) -> LLMCommitteeOutput:
    return asyncio.run(run_llm_committee(snapshot, forecasts, dcfs, technicals, comps))
