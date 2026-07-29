"""Historical OHLCV data loading for XAUUSD backtesting."""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_csv(path: str) -> pd.DataFrame:
    """Load a historical OHLCV CSV export into a clean OHLCV DataFrame.

    Accepts MT4/MT5-style exports: comma- or tab-delimited, column names
    with or without angle brackets (MT5's native "Export Bars" writes
    <DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>
    tab-separated), either a combined "datetime" column or separate
    "date"+"time" columns, and either "volume" or "tickvol"/"vol" for
    volume (tick volume is used when real volume is all zero, which is
    normal for OTC gold/forex CFDs). Returns a DataFrame indexed by
    timestamp with lowercase columns: open, high, low, close, volume.
    """
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower().strip("<>") for c in df.columns]

    if "datetime" in df.columns:
        idx = pd.to_datetime(df["datetime"])
    elif "date" in df.columns and "time" in df.columns:
        idx = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    elif "date" in df.columns:
        idx = pd.to_datetime(df["date"])
    else:
        raise ValueError(
            "CSV must have a 'datetime' column, or 'date'(+'time') columns"
        )

    df = df.set_index(idx)
    df.index.name = "timestamp"

    if "volume" not in df.columns:
        if "tickvol" in df.columns and df["tickvol"].astype(float).sum() > 0:
            df["volume"] = df["tickvol"]
        elif "vol" in df.columns:
            df["volume"] = df["vol"]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    df = df[REQUIRED_COLUMNS].astype(float)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def generate_synthetic(
    n_bars: int = 3000,
    start: str = "2024-01-01",
    freq: str = "1h",
    start_price: float = 2000.0,
    seed: int = 7,
) -> pd.DataFrame:
    """Generate a synthetic OHLCV series for pipeline smoke-testing only.

    This is NOT a substitute for real market data -- it exists so the
    indicator/SMC/edge-score/backtest pipeline can be exercised end-to-end
    before real XAUUSD history is available.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, periods=n_bars, freq=freq)

    # Random walk with mild trend regimes + volatility clustering, so
    # swing structure / FVGs / order blocks have something realistic to find.
    regime_len = 150
    n_regimes = n_bars // regime_len + 1
    trend = np.repeat(rng.choice([-1, 0, 1], size=n_regimes, p=[0.35, 0.3, 0.35]), regime_len)[:n_bars]
    drift = trend * rng.uniform(0.02, 0.08, size=n_bars)

    vol = rng.uniform(0.8, 2.5, size=n_bars)
    shocks = rng.standard_normal(n_bars) * vol
    returns = drift + shocks
    close = start_price + np.cumsum(returns)
    close = np.maximum(close, 1.0)

    open_ = np.empty(n_bars)
    open_[0] = start_price
    open_[1:] = close[:-1]

    high = np.maximum(open_, close) + rng.uniform(0.1, 1.5, size=n_bars)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.5, size=n_bars)
    volume = rng.uniform(100, 1000, size=n_bars)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df.index.name = "timestamp"
    return df
