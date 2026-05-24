"""Data provider router.

Use Financial Modeling Prep for structured statement history when configured,
with yfinance as a resilient fallback for local development.
"""
from __future__ import annotations

from src.config import settings
from src.data.yfinance_client import (
    fetch_historical_financials as fetch_yfinance_historical_financials,
    fetch_market_snapshot,
    fetch_peer_snapshot,
    fetch_price_history,
)
from src.schemas import HistoricalFinancials


def fetch_historical_financials(ticker: str) -> HistoricalFinancials:
    """Fetch historical financials from the configured provider.

    DATA_PROVIDER=fmp uses FMP first and falls back to yfinance if FMP is not
    configured or cannot return usable data. The fallback warning is stored in
    HistoricalFinancials.source so it is visible in the model output.
    """
    if settings.data_provider == "fmp":
        try:
            from src.data.fmp_client import fetch_fmp_historical_financials

            financials = fetch_fmp_historical_financials(ticker)
            if len(financials.revenue) >= settings.min_statement_years:
                return financials
            fallback = fetch_yfinance_historical_financials(ticker)
            fallback.source = f"yfinance fallback: FMP returned only {len(financials.revenue)} revenue years"
            return fallback
        except Exception as exc:
            fallback = fetch_yfinance_historical_financials(ticker)
            fallback.source = f"yfinance fallback: FMP failed - {exc}"
            return fallback

    return fetch_yfinance_historical_financials(ticker)


def fetch_analyst_estimates(ticker: str) -> list[dict]:
    if settings.data_provider == "fmp" and settings.fmp_api_key:
        try:
            from src.data.fmp_client import fetch_fmp_analyst_estimates

            return fetch_fmp_analyst_estimates(ticker)
        except Exception:
            return []
    return []
