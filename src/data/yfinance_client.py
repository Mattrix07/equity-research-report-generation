"""Public market data client using yfinance.

The workflow treats this as a data layer, not a source of truth. Outputs should be
reviewed before investment use.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from src.schemas import HistoricalFinancials, MarketSnapshot


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _dict_from_series(series: pd.Series, scale: float = 1.0) -> dict[str, float]:
    out: dict[str, float] = {}
    for idx, value in series.items():
        if value is None or pd.isna(value):
            continue
        year = str(pd.to_datetime(idx).year) if not isinstance(idx, str) else idx
        out[year] = float(value) / scale
    return dict(sorted(out.items()))


def fetch_market_snapshot(ticker: str, company_name: str | None = None) -> MarketSnapshot:
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    current_price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    total_debt = _safe_float(info.get("totalDebt")) or 0.0
    total_cash = _safe_float(info.get("totalCash")) or 0.0
    net_debt = total_debt - total_cash
    return MarketSnapshot(
        ticker=ticker.upper(),
        company_name=company_name or info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector") or "Unknown",
        industry=info.get("industry") or "Unknown",
        current_price=current_price,
        market_cap=_safe_float(info.get("marketCap")),
        enterprise_value=_safe_float(info.get("enterpriseValue")),
        shares_outstanding=_safe_float(info.get("sharesOutstanding")),
        currency=info.get("financialCurrency") or info.get("currency") or "USD",
        beta=_safe_float(info.get("beta")),
        trailing_pe=_safe_float(info.get("trailingPE")),
        forward_pe=_safe_float(info.get("forwardPE")),
        revenue_ttm=_safe_float(info.get("totalRevenue")),
        ebitda=_safe_float(info.get("ebitda")),
        total_cash=total_cash,
        total_debt=total_debt,
        net_debt=net_debt,
        book_value=_safe_float(info.get("bookValue")),
        price_to_book=_safe_float(info.get("priceToBook")),
        return_on_equity=_safe_float(info.get("returnOnEquity")),
        profit_margins=_safe_float(info.get("profitMargins")),
        fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
        fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
        business_summary=info.get("longBusinessSummary") or "",
    )


def fetch_historical_financials(ticker: str) -> HistoricalFinancials:
    yf_ticker = yf.Ticker(ticker)
    income = yf_ticker.financials
    cashflow = yf_ticker.cashflow

    if income is None or income.empty:
        income = pd.DataFrame()
    if cashflow is None or cashflow.empty:
        cashflow = pd.DataFrame()

    def row(df: pd.DataFrame, names: list[str]) -> pd.Series:
        for name in names:
            if name in df.index:
                return df.loc[name]
        return pd.Series(dtype=float)

    revenue = _dict_from_series(row(income, ["Total Revenue", "Operating Revenue"]))
    gross_profit = _dict_from_series(row(income, ["Gross Profit"]))
    ebitda = _dict_from_series(row(income, ["EBITDA", "Normalized EBITDA"]))
    ebit = _dict_from_series(row(income, ["EBIT", "Operating Income"]))
    net_income = _dict_from_series(row(income, ["Net Income", "Net Income Common Stockholders"]))
    operating_cf = _dict_from_series(row(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"]))
    capex_raw = _dict_from_series(row(cashflow, ["Capital Expenditure", "Capital Expenditures"]))
    capex = {k: abs(v) for k, v in capex_raw.items()}
    fcf = {year: operating_cf.get(year, 0.0) - capex.get(year, 0.0) for year in operating_cf}

    gross_margin = {
        year: gross_profit[year] / revenue[year]
        for year in gross_profit
        if year in revenue and revenue[year]
    }
    ebitda_margin = {
        year: ebitda[year] / revenue[year]
        for year in ebitda
        if year in revenue and revenue[year]
    }
    fcf_margin = {
        year: fcf[year] / revenue[year]
        for year in fcf
        if year in revenue and revenue[year]
    }

    return HistoricalFinancials(
        revenue=revenue,
        ebitda=ebitda,
        ebit=ebit,
        net_income=net_income,
        operating_cash_flow=operating_cf,
        capex=capex,
        free_cash_flow=fcf,
        gross_margin=gross_margin,
        ebitda_margin=ebitda_margin,
        fcf_margin=fcf_margin,
    )


def fetch_price_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    data = yf.Ticker(ticker).history(period=period)
    if data is None:
        return pd.DataFrame()
    return data.reset_index()


def fetch_peer_snapshot(tickers: list[str]) -> list[dict[str, Any]]:
    peers: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            snap = fetch_market_snapshot(ticker)
            peers.append(snap.model_dump())
        except Exception:
            continue
    return peers
