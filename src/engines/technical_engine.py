"""Technical analysis calculations."""
from __future__ import annotations

import pandas as pd

from src.schemas import TechnicalSnapshot


def _rsi(close: pd.Series, window: int = 14) -> float | None:
    if close.empty or len(close) < window + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = -delta.clip(upper=0).rolling(window=window).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    try:
        return float(rsi.iloc[-1])
    except Exception:
        return None


def run_technical_analysis(price_history: pd.DataFrame) -> TechnicalSnapshot:
    if price_history.empty or "Close" not in price_history:
        return TechnicalSnapshot(momentum_comment="Insufficient price history for technical analysis.")

    close = price_history["Close"].dropna()
    last_price = float(close.iloc[-1]) if not close.empty else None
    ma_20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
    ma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    ma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    rsi_14 = _rsi(close)

    if last_price and ma_50 and ma_200:
        if last_price > ma_50 > ma_200:
            comment = "Positive momentum: price is above both the 50-day and 200-day moving averages."
        elif last_price < ma_50 < ma_200:
            comment = "Negative momentum: price is below both the 50-day and 200-day moving averages."
        else:
            comment = "Mixed momentum: moving averages do not show a clean trend signal."
    else:
        comment = "Limited technical signal due to incomplete moving-average history."

    return TechnicalSnapshot(
        last_price=last_price,
        ma_20=ma_20,
        ma_50=ma_50,
        ma_200=ma_200,
        rsi_14=rsi_14,
        momentum_comment=comment,
    )
