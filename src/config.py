"""Application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _model_env(name: str, fallback: str) -> str:
    return os.getenv(name, fallback).strip() or fallback


OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


@dataclass(frozen=True)
class Settings:
    port: int = int(os.getenv("PORT", "8080"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = OPENAI_MODEL_DEFAULT
    enable_llm_committee: bool = _bool_env("ENABLE_LLM_COMMITTEE", False)
    llm_timeout_seconds: float = _float_env("LLM_TIMEOUT_SECONDS", 90.0)
    llm_manager_model: str = _model_env("LLM_MANAGER_MODEL", OPENAI_MODEL_DEFAULT)
    llm_bull_model: str = _model_env("LLM_BULL_MODEL", OPENAI_MODEL_DEFAULT)
    llm_bear_model: str = _model_env("LLM_BEAR_MODEL", OPENAI_MODEL_DEFAULT)
    llm_valuation_model: str = _model_env("LLM_VALUATION_MODEL", OPENAI_MODEL_DEFAULT)
    llm_report_writer_model: str = _model_env("LLM_REPORT_WRITER_MODEL", OPENAI_MODEL_DEFAULT)
    llm_qa_model: str = _model_env("LLM_QA_MODEL", OPENAI_MODEL_DEFAULT)
    default_wacc: float = _float_env("DEFAULT_WACC", 0.095)
    default_terminal_growth: float = _float_env("DEFAULT_TERMINAL_GROWTH", 0.025)
    default_tax_rate: float = _float_env("DEFAULT_TAX_RATE", 0.25)


settings = Settings()
