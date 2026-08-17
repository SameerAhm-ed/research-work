"""Multi-timeframe trend context: derive H4/D1 trend direction from the
existing H1 series (no separate export needed -- OHLC resampling from the
same source is more reliable than joining two independently-exported
files, which risks a subtle boundary/alignment mismatch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import ema


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate an OHLC(V) series to a coarser timeframe."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])


def higher_tf_trend(
    df: pd.DataFrame, rule: str, ema_fast: int = 9, ema_slow: int = 21
) -> pd.Series:
    """EMA9/21 trend direction (1/-1/0) on a higher timeframe, aligned back
    onto df's original index -- lookahead-safe.

    A higher-timeframe bar labeled at time T covers [T, T+rule) and is only
    "closed" (its trend known) once that window ends. The trend series is
    shifted by one higher-TF bar before being forward-filled onto the
    original index, so an original-timeframe bar only ever sees the most
    recently *closed* higher-timeframe bar's trend -- never the one still
    forming around it.
    """
    htf = resample_ohlc(df, rule)
    fast = ema(htf["close"], ema_fast)
    slow = ema(htf["close"], ema_slow)
    trend = pd.Series(np.where(fast > slow, 1, np.where(fast < slow, -1, 0)), index=htf.index)

    trend_closed = trend.shift(1)  # only known once that HTF bar has closed
    aligned = trend_closed.reindex(df.index, method="ffill")
    return aligned


def add_multi_timeframe_trend(df: pd.DataFrame, rules: dict[str, str]) -> pd.DataFrame:
    """Return a copy of df with one added column per {column_name: rule},
    e.g. {"trend_h4": "4h", "trend_d1": "1D"}.
    """
    out = df.copy()
    for col_name, rule in rules.items():
        out[col_name] = higher_tf_trend(df, rule)
    return out
