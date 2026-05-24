"""LLM-assisted model agents.

These agents add judgement to the deterministic model without letting the LLM do
unchecked arithmetic. The intended pattern is:

LLM proposes peers / assumptions / revisions -> Python calculates -> validation
agent audits -> optional iteration -> report generation.

All outputs are JSON and bounded before use in the model.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from src.agents.llm_committee import llm_enabled, openai_chat_kwargs
from src.config import settings
from src.schemas import HistoricalFinancials, MarketSnapshot


@dataclass
class LLMModelAssumptionPack:
    enabled: bool = False
    forecast: dict[str, Any] = field(default_factory=dict)
    wacc: dict[str, Any] = field(default_factory=dict)
    terminal_value: dict[str, Any] = field(default_factory=dict)
    validation_revision: dict[str, Any] = field(default_factory=dict)
    reasoning_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_outputs: dict[str, Any] = field(default_factory=dict)

    def model_inputs(self) -> dict[str, Any]:
        """Return the structured fields consumed by the model engine."""
        return {
            "forecast": self.forecast,
            "wacc": self.wacc,
            "terminal_value": self.terminal_value,
            "validation_revision": self.validation_revision,
        }


async def _close_client(client: AsyncOpenAI) -> None:
    try:
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


def _json(data: Any, max_chars: int = 55000) -> str:
    return json.dumps(data, default=str, indent=2)[:max_chars]


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_float_list(values: Any, length: int = 5) -> list[float] | None:
    if not isinstance(values, list):
        return None
    out: list[float] = []
    for value in values[:length]:
        parsed = _safe_float(value)
        if parsed is None:
            return None
        out.append(parsed)
    return out if len(out) == length else None


def _clean_assumption_output(data: dict[str, Any]) -> dict[str, Any]:
    """Constrain LLM outputs to safe, model-usable ranges."""
    cleaned: dict[str, Any] = {}
    revenue_growth = _safe_float_list(data.get("revenue_growth"))
    if revenue_growth:
        cleaned["revenue_growth"] = [max(min(x, 0.20), -0.10) for x in revenue_growth]
    ebitda_margin = _safe_float_list(data.get("ebitda_margin"))
    if ebitda_margin:
        cleaned["ebitda_margin"] = [max(min(x, 0.65), 0.00) for x in ebitda_margin]
    for key, low, high in [
        ("da_percent_revenue", 0.0, 0.15),
        ("capex_percent_revenue", 0.0, 0.20),
        ("nwc_percent_revenue", -0.02, 0.05),
        ("tax_rate", 0.0, 0.35),
        ("wacc", 0.05, 0.14),
        ("terminal_growth", 0.0, 0.045),
        ("cost_of_equity", 0.04, 0.18),
        ("after_tax_cost_of_debt", 0.0, 0.10),
    ]:
        value = _safe_float(data.get(key))
        if value is not None:
            cleaned[key] = max(min(value, high), low)
    for key in ["rationale", "reasoning_steps", "evidence_gaps", "revision_instructions"]:
        if key in data:
            cleaned[key] = data[key]
    return cleaned


def _historical_summary(historicals: HistoricalFinancials) -> dict[str, Any]:
    return {
        "revenue": historicals.revenue,
        "ebitda": historicals.ebitda,
        "ebit": historicals.ebit,
        "net_income": historicals.net_income,
        "operating_cash_flow": historicals.operating_cash_flow,
        "capex": historicals.capex,
        "free_cash_flow": historicals.free_cash_flow,
        "ebitda_margin": historicals.ebitda_margin,
        "fcf_margin": historicals.fcf_margin,
    }


async def _call_json_agent(client: AsyncOpenAI, *, name: str, model: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                **openai_chat_kwargs(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": _json(payload)},
                    ],
                    temperature=0.15,
                    response_format={"type": "json_object"},
                )
            ),
            timeout=settings.llm_timeout_seconds,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        data["_agent"] = name
        data["_raw"] = raw
        return data
    except Exception as exc:
        return {"_agent": name, "error": str(exc)}


async def run_llm_model_assumption_agents(
    snapshot: MarketSnapshot,
    historicals: HistoricalFinancials,
    peers: list[str] | None = None,
    prior_model: dict[str, Any] | None = None,
    validation_feedback: dict[str, Any] | None = None,
) -> LLMModelAssumptionPack:
    if not llm_enabled():
        return LLMModelAssumptionPack(enabled=False, warnings=["LLM model agents disabled or API key missing."])

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    try:
        common_payload = {
            "company": snapshot.model_dump(),
            "historicals": _historical_summary(historicals),
            "selected_or_candidate_peers": peers or [],
            "prior_model": prior_model or {},
            "validation_feedback": validation_feedback or {},
            "guardrails": {
                "do_not_invent_missing_facts": True,
                "return_decimal_percentages": True,
                "forecast_years": 5,
                "purpose": "derive evidence-based assumptions for a 5-year DCF and 12-month target price",
            },
        }

        forecast_system = (
            "You are a fundamental forecasting analyst. Derive company-specific base-case operating assumptions from the evidence only. "
            "Return JSON with: revenue_growth as 5 decimals, ebitda_margin as 5 decimals, da_percent_revenue, capex_percent_revenue, "
            "nwc_percent_revenue, tax_rate, rationale, reasoning_steps, evidence_gaps. Do not calculate target price."
        )
        wacc_system = (
            "You are a WACC analyst. Derive a company-specific WACC using beta, risk-free-rate context, equity risk premium, debt/capital structure, "
            "tax rate and business risk. Return JSON with: cost_of_equity, after_tax_cost_of_debt, wacc, tax_rate, rationale, reasoning_steps, evidence_gaps. "
            "Use decimal percentages. Do not invent facts if data is missing."
        )
        terminal_system = (
            "You are a terminal value analyst. Decide an appropriate terminal growth assumption for a mature operating-company DCF. "
            "Return JSON with: terminal_growth, rationale, reasoning_steps, evidence_gaps. Use a conservative decimal value."
        )
        revision_system = (
            "You are a model validation revision agent. If validation feedback indicates the model is detached from market or assumptions are weak, "
            "propose bounded revisions to assumptions without forcing the valuation to match the market. Return JSON with optional revenue_growth, "
            "ebitda_margin, capex_percent_revenue, nwc_percent_revenue, wacc, terminal_growth, revision_instructions, reasoning_steps, evidence_gaps."
        )

        tasks = [
            _call_json_agent(client, name="Forecast Assumption Agent", model=settings.llm_manager_model, system=forecast_system, payload=common_payload),
            _call_json_agent(client, name="WACC Agent", model=settings.llm_valuation_model, system=wacc_system, payload=common_payload),
            _call_json_agent(client, name="Terminal Value Agent", model=settings.llm_valuation_model, system=terminal_system, payload=common_payload),
        ]
        if validation_feedback:
            tasks.append(_call_json_agent(client, name="Validation Revision Agent", model=settings.llm_qa_model, system=revision_system, payload=common_payload))

        outputs = await asyncio.gather(*tasks)
    finally:
        await _close_client(client)

    by_agent = {str(item.get("_agent", "unknown")): item for item in outputs}
    pack = LLMModelAssumptionPack(enabled=True, raw_outputs=by_agent)
    pack.forecast = _clean_assumption_output(by_agent.get("Forecast Assumption Agent", {}))
    pack.wacc = _clean_assumption_output(by_agent.get("WACC Agent", {}))
    pack.terminal_value = _clean_assumption_output(by_agent.get("Terminal Value Agent", {}))
    pack.validation_revision = _clean_assumption_output(by_agent.get("Validation Revision Agent", {}))

    for item in outputs:
        if item.get("error"):
            pack.warnings.append(f"{item.get('_agent')}: {item.get('error')}")
        steps = item.get("reasoning_steps")
        if isinstance(steps, list):
            pack.reasoning_steps.extend([str(step) for step in steps[:4]])
    return pack


def run_llm_model_assumption_agents_sync(*args, **kwargs) -> LLMModelAssumptionPack:
    return asyncio.run(run_llm_model_assumption_agents(*args, **kwargs))
