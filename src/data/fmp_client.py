"""Financial Modeling Prep data client.

FMP is used as the preferred structured financial-statement provider when
FMP_API_KEY is configured. yfinance remains available as a fallback for market
snapshot and price history.

No real API keys should be committed. Set FMP_API_KEY in your local .env file.
"""
from __future__ import annotations

from typing import Any

import requests

from src.config import settings
from src.schemas import HistoricalFinancials


class FMPError(RuntimeError):
    """Raised when FMP cannot return usable data."""


def _endpoint_url(endpoint: str) -> str:
    base = settings.fmp_base_url.rstrip("/")
    endpoint = endpoint.strip("/")
    return f"{base}/{endpoint}"


def _get(endpoint: str, params: dict[str, Any] | None = None) -> Any:
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is missing. Add it to your .env file or set DATA_PROVIDER=yfinance.")

    url = _endpoint_url(endpoint)
    query = {**(params or {}), "apikey": settings.fmp_api_key}
    response = requests.get(url, params=query, timeout=settings.fmp_timeout_seconds)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise FMPError(f"FMP request failed for {endpoint}: {response.status_code} {response.text[:300]}") from exc

    data = response.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise FMPError(str(data.get("Error Message")))
    return data


def _as_list(data: Any, endpoint: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise FMPError(f"Unexpected FMP response for {endpoint}: expected list, got {type(data).__name__}")
    return [row for row in data if isinstance(row, dict)]


def _annual(endpoint: str, ticker: str, limit: int) -> list[dict[str, Any]]:
    data = _get(endpoint, {"symbol": ticker.upper(), "period": "annual", "limit": limit})
    rows = _as_list(data, endpoint)
    if not rows:
        raise FMPError(f"FMP returned no rows for {endpoint}/{ticker.upper()}")
    return sorted(rows, key=lambda x: str(x.get("calendarYear") or x.get("date") or ""))


def _year(row: dict[str, Any]) -> str:
    return str(row.get("calendarYear") or str(row.get("date") or "")[:4])


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(rows: list[dict[str, Any]], *keys: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        year = _year(row)
        if not year:
            continue
        for key in keys:
            value = _to_float(row.get(key))
            if value is not None:
                out[year] = value
                break
    return dict(sorted(out.items()))


def _margin(numerator: dict[str, float], denominator: dict[str, float]) -> dict[str, float]:
    return {
        year: numerator[year] / denominator[year]
        for year in numerator
        if year in denominator and denominator[year]
    }


def fetch_fmp_historical_financials(ticker: str, limit: int | None = None) -> HistoricalFinancials:
    """Fetch structured annual income statement, balance sheet and cash flow data.

    The returned object contains the full history required by the linked Excel
    model. Forecasting still happens in the modelling layer.
    """
    limit = limit or settings.fmp_statement_limit
    ticker = ticker.upper()
    income = _annual("income-statement", ticker, limit)
    balance = _annual("balance-sheet-statement", ticker, limit)
    cashflow = _annual("cash-flow-statement", ticker, limit)

    revenue = _series(income, "revenue")
    gross_profit = _series(income, "grossProfit")
    ebitda = _series(income, "ebitda")
    ebit = _series(income, "operatingIncome")
    net_income = _series(income, "netIncome")
    income_tax_expense = _series(income, "incomeTaxExpense")
    interest_expense = _series(income, "interestExpense")
    depreciation_amortization_income = _series(income, "depreciationAndAmortization")

    operating_cf = _series(cashflow, "operatingCashFlow", "netCashProvidedByOperatingActivities")
    capex_raw = _series(cashflow, "capitalExpenditure", "investmentsInPropertyPlantAndEquipment")
    capex = {year: abs(value) for year, value in capex_raw.items()}
    fcf = {year: operating_cf.get(year, 0.0) - capex.get(year, 0.0) for year in operating_cf}
    depreciation_amortization_cf = _series(cashflow, "depreciationAndAmortization", "depreciationDepletionAndAmortization")
    stock_based_comp = _series(cashflow, "stockBasedCompensation")
    dividends_paid = {year: abs(value) for year, value in _series(cashflow, "dividendsPaid", "commonDividendsPaid").items()}
    share_repurchases = {year: abs(value) for year, value in _series(cashflow, "commonStockRepurchased", "repurchasesOfStock").items()}

    cash_and_equivalents = _series(balance, "cashAndCashEquivalents", "cashAndShortTermInvestments")
    short_term_investments = _series(balance, "shortTermInvestments")
    receivables = _series(balance, "netReceivables", "accountsReceivables")
    inventory = _series(balance, "inventory")
    total_current_assets = _series(balance, "totalCurrentAssets")
    ppne = _series(balance, "propertyPlantEquipmentNet", "netPPE")
    goodwill = _series(balance, "goodwill")
    intangible_assets = _series(balance, "intangibleAssets")
    total_assets = _series(balance, "totalAssets")

    accounts_payable = _series(balance, "accountPayables", "accountsPayable")
    short_term_debt = _series(balance, "shortTermDebt")
    long_term_debt = _series(balance, "longTermDebt")
    total_debt = _series(balance, "totalDebt")
    total_current_liabilities = _series(balance, "totalCurrentLiabilities")
    total_liabilities = _series(balance, "totalLiabilities")
    shareholders_equity = _series(balance, "totalStockholdersEquity", "totalEquity")
    shares_outstanding = _series(income, "weightedAverageShsOut", "weightedAverageShsOutDil")

    return HistoricalFinancials(
        revenue=revenue,
        ebitda=ebitda,
        ebit=ebit,
        net_income=net_income,
        operating_cash_flow=operating_cf,
        capex=capex,
        free_cash_flow=fcf,
        gross_margin=_margin(gross_profit, revenue),
        ebitda_margin=_margin(ebitda, revenue),
        fcf_margin=_margin(fcf, revenue),
        gross_profit=gross_profit,
        income_tax_expense=income_tax_expense,
        interest_expense=interest_expense,
        depreciation_amortization=depreciation_amortization_cf or depreciation_amortization_income,
        stock_based_compensation=stock_based_comp,
        dividends_paid=dividends_paid,
        share_repurchases=share_repurchases,
        cash_and_equivalents=cash_and_equivalents,
        short_term_investments=short_term_investments,
        receivables=receivables,
        inventory=inventory,
        total_current_assets=total_current_assets,
        ppne=ppne,
        goodwill=goodwill,
        intangible_assets=intangible_assets,
        total_assets=total_assets,
        accounts_payable=accounts_payable,
        short_term_debt=short_term_debt,
        long_term_debt=long_term_debt,
        total_debt=total_debt,
        total_current_liabilities=total_current_liabilities,
        total_liabilities=total_liabilities,
        shareholders_equity=shareholders_equity,
        shares_outstanding=shares_outstanding,
        source="fmp",
    )


def fetch_fmp_analyst_estimates(ticker: str, limit: int | None = None) -> list[dict[str, Any]]:
    limit = limit or settings.fmp_statement_limit
    rows = _get("analyst-estimates", {"symbol": ticker.upper(), "period": "annual", "limit": limit, "page": 0})
    return _as_list(rows, "analyst-estimates")
