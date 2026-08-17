"""These tests exist because mtf.py's whole job is a correctness property
that's easy to silently break in a refactor: a bar must never see a
higher-timeframe trend value derived from bars that haven't happened yet
relative to it. Backtest results from a lookahead-leaking MTF gate would
look *better* than reality, not crash -- exactly the kind of bug that
would otherwise only surface live, the hard way (as Round 12's trailing-
distance bug did).
"""
import numpy as np
import pandas as pd

from goldscalper.mtf import add_multi_timeframe_trend, higher_tf_trend, resample_ohlc


def _make_ohlc(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = 2000 + np.cumsum(rng.standard_normal(n) * 2)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.1, 1.0, n),
            "low": close - rng.uniform(0.1, 1.0, n),
            "close": close,
        },
        index=idx,
    )


def test_resample_ohlc_aggregates_correctly():
    idx = pd.date_range("2024-01-01", periods=8, freq="1h")
    df = pd.DataFrame(
        {
            "open": [1, 2, 3, 4, 5, 6, 7, 8],
            "high": [10, 20, 30, 40, 50, 60, 70, 80],
            "low": [0, -1, -2, -3, -4, -5, -6, -7],
            "close": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5],
        },
        index=idx,
        dtype=float,
    )
    out = resample_ohlc(df, "4h")
    assert len(out) == 2
    assert out["open"].iloc[0] == 1  # first of the first 4 bars
    assert out["high"].iloc[0] == 40  # max of the first 4 bars
    assert out["low"].iloc[0] == -3  # min of the first 4 bars
    assert out["close"].iloc[0] == 4.5  # last of the first 4 bars


def test_higher_tf_trend_never_uses_a_bar_from_the_future():
    """The direct no-lookahead check: computing trend_h4 on the full series
    vs. on a truncated prefix of it must agree everywhere both are defined.
    If the HTF trend at some early bar depended on later bars, truncating
    the future away would change that early value -- it must not."""
    df = _make_ohlc(n=400)
    full = higher_tf_trend(df, "4h")

    cutoff = 300
    truncated = higher_tf_trend(df.iloc[:cutoff], "4h")

    common_idx = truncated.dropna().index
    common_idx = common_idx.intersection(full.dropna().index)
    assert len(common_idx) > 50  # sanity: the overlap isn't trivially empty

    pd.testing.assert_series_equal(
        full.loc[common_idx], truncated.loc[common_idx], check_names=False
    )


def test_higher_tf_trend_is_shifted_not_same_bar_close():
    """A H4 bar's trend must only become visible AFTER that H4 bar closes,
    not during it -- guards against accidentally removing the .shift(1)."""
    df = _make_ohlc(n=200)
    htf = resample_ohlc(df, "4h")
    from goldscalper.indicators import ema

    fast, slow = ema(htf["close"], 9), ema(htf["close"], 21)
    raw_trend = pd.Series(np.where(fast > slow, 1, np.where(fast < slow, -1, 0)), index=htf.index)

    aligned = higher_tf_trend(df, "4h")

    # For each H4 bar boundary, the value visible on H1 bars *during* that
    # H4 bar must equal the PREVIOUS H4 bar's raw trend, not this one's.
    for pos in range(1, len(htf.index) - 1):
        h4_start = htf.index[pos]
        h4_end = htf.index[pos + 1]
        during = aligned.loc[(aligned.index >= h4_start) & (aligned.index < h4_end)]
        if during.empty or during.isna().all():
            continue
        assert (during.dropna() == raw_trend.iloc[pos - 1]).all()


def test_add_multi_timeframe_trend_adds_requested_columns_only():
    df = _make_ohlc(n=200)
    out = add_multi_timeframe_trend(df, {"trend_h4": "4h", "trend_d1": "1D"})
    assert "trend_h4" in out.columns and "trend_d1" in out.columns
    assert set(out["trend_h4"].dropna().unique()) <= {-1, 0, 1}
    # original columns untouched
    for col in ["open", "high", "low", "close"]:
        pd.testing.assert_series_equal(out[col], df[col])
