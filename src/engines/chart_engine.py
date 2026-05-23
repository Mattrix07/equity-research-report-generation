"""Chart generation engine.

Matplotlib is forced to use the non-interactive Agg backend so charts can be
created safely inside FastAPI worker threads on macOS, Linux and hosted servers.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from src.schemas import ForecastRow, HistoricalFinancials


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def chart_forecast_revenue(forecasts: dict[str, list[ForecastRow]], output_dir: Path, ticker: str) -> str | None:
    _ensure_dir(output_dir)
    rows = []
    for scenario, forecast in forecasts.items():
        for row in forecast:
            rows.append({"scenario": scenario, "year": row.year, "revenue": row.revenue / 1_000_000})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for scenario, group in df.groupby("scenario"):
        ax.plot(group["year"], group["revenue"], marker="o", label=scenario.title())
    ax.set_title(f"{ticker.upper()} revenue forecast by scenario")
    ax.set_ylabel("Revenue (m)")
    ax.legend()
    ax.grid(True, alpha=0.25)
    path = output_dir / f"{ticker.lower()}_revenue_forecast.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)


def chart_margin_forecast(forecasts: dict[str, list[ForecastRow]], output_dir: Path, ticker: str) -> str | None:
    _ensure_dir(output_dir)
    rows = []
    for scenario, forecast in forecasts.items():
        for row in forecast:
            rows.append({"scenario": scenario, "year": row.year, "margin": row.ebitda_margin * 100})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for scenario, group in df.groupby("scenario"):
        ax.plot(group["year"], group["margin"], marker="o", label=scenario.title())
    ax.set_title(f"{ticker.upper()} EBITDA margin forecast by scenario")
    ax.set_ylabel("EBITDA margin (%)")
    ax.legend()
    ax.grid(True, alpha=0.25)
    path = output_dir / f"{ticker.lower()}_ebitda_margin_forecast.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)


def chart_price_technicals(price_history: pd.DataFrame, output_dir: Path, ticker: str) -> str | None:
    _ensure_dir(output_dir)
    if price_history.empty or "Close" not in price_history:
        return None
    df = price_history.copy()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    x = df["Date"] if "Date" in df else df.index
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(x, df["Close"], label="Close")
    ax.plot(x, df["MA50"], label="50D MA")
    ax.plot(x, df["MA200"], label="200D MA")
    ax.set_title(f"{ticker.upper()} share price and moving averages")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True, alpha=0.25)
    path = output_dir / f"{ticker.lower()}_technicals.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)
