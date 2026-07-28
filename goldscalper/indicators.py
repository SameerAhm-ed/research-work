"""Base technical indicators: EMA, RSI, ATR, H1 trend direction."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.where(avg_loss != 0.0, 100.0)
    return result


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_base_indicators(
    df: pd.DataFrame,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Return a copy of df with ema_fast/ema_slow/rsi/atr columns and a
    trend_direction column (1 bullish, -1 bearish, 0 flat) derived from the
    EMA crossover, mirroring the H1 trend filter used as the base signal.
    """
    out = df.copy()
    out[f"ema_{ema_fast}"] = ema(out["close"], ema_fast)
    out[f"ema_{ema_slow}"] = ema(out["close"], ema_slow)
    out["rsi"] = rsi(out["close"], rsi_period)
    out["atr"] = atr(out, atr_period)

    fast, slow = out[f"ema_{ema_fast}"], out[f"ema_{ema_slow}"]
    out["trend_direction"] = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    return out
