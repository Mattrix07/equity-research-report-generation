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


@dataclass(frozen=True)
class Settings:
    port: int = int(os.getenv("PORT", "8080"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    default_wacc: float = _float_env("DEFAULT_WACC", 0.095)
    default_terminal_growth: float = _float_env("DEFAULT_TERMINAL_GROWTH", 0.025)
    default_tax_rate: float = _float_env("DEFAULT_TAX_RATE", 0.25)


settings = Settings()
