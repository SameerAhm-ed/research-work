"""Smart Money Concepts primitives: swings, order blocks, fair value gaps,
liquidity sweeps, and break of structure / change of character.

All detectors are backtest-safe: each event is only recognized once the bars
that confirm it have closed, so nothing here looks into the future relative
to the bar it's attached to.
"""
from __future__ import annotations

import pandas as pd


def find_swings(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    """Add boolean swing_high / swing_low columns (fractal pivots).

    A bar is a swing high if its high is strictly greater than the highs of
    `lookback` bars on each side (and symmetric for swing low). Because the
    right side must be known, a swing at bar i is only confirmed at bar
    i + lookback -- callers that need "as of now" state should only trust
    swings whose index is <= current_bar - lookback.
    """
    out = df.copy()
    high, low = out["high"], out["low"]

    swing_high = pd.Series(True, index=out.index)
    swing_low = pd.Series(True, index=out.index)
    for shift in list(range(1, lookback + 1)) + [-s for s in range(1, lookback + 1)]:
        swing_high &= high > high.shift(shift)
        swing_low &= low < low.shift(shift)

    out["swing_high"] = swing_high.fillna(False)
    out["swing_low"] = swing_low.fillna(False)
    return out


def find_fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Detect 3-candle fair value gaps (imbalances).

    Bullish FVG at bar i: low[i] > high[i-2]  -> gap zone (high[i-2], low[i])
    Bearish FVG at bar i: high[i] < low[i-2]  -> gap zone (high[i], low[i-2])

    `confirmed_at` is bar i (the third candle), so this is known as of the
    close of bar i -- safe to use going forward from bar i+1. `mitigated_at`
    marks the first later bar whose range trades back into the gap zone.
    """
    events = []
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    idx = df.index

    for i in range(2, len(df)):
        if low[i] > high[i - 2]:
            top, bottom = float(low[i]), float(high[i - 2])
            direction = "bullish"
        elif high[i] < low[i - 2]:
            top, bottom = float(low[i - 2]), float(high[i])
            direction = "bearish"
        else:
            continue

        mitigated_at = None
        for j in range(i + 1, len(df)):
            if low[j] <= top and high[j] >= bottom:
                mitigated_at = idx[j]
                break

        events.append(
            {
                "confirmed_at": idx[i],
                "direction": direction,
                "top": top,
                "bottom": bottom,
                "mitigated_at": mitigated_at,
            }
        )

    return pd.DataFrame(events)


def find_order_blocks(
    df: pd.DataFrame, atr: pd.Series, displacement_mult: float = 1.5
) -> pd.DataFrame:
    """Detect order blocks: the last opposite-colored candle immediately
    before a displacement move (a candle whose body is a large multiple of
    ATR), in the direction of that displacement.

    Bullish order block: last bearish candle before a strong-up candle.
    Bearish order block: last bullish candle before a strong-down candle.
    """
    events = []
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    atr_vals = atr.to_numpy()
    idx = df.index

    for i in range(1, len(df)):
        body = c[i] - o[i]
        if atr_vals[i] != atr_vals[i] or atr_vals[i] == 0:  # NaN guard
            continue
        if abs(body) < displacement_mult * atr_vals[i]:
            continue

        prev_bearish = c[i - 1] < o[i - 1]
        prev_bullish = c[i - 1] > o[i - 1]

        if body > 0 and prev_bearish:
            direction = "bullish"
            top, bottom = float(h[i - 1]), float(l[i - 1])
        elif body < 0 and prev_bullish:
            direction = "bearish"
            top, bottom = float(h[i - 1]), float(l[i - 1])
        else:
            continue

        mitigated_at = None
        for j in range(i + 1, len(df)):
            if l[j] <= top and h[j] >= bottom:
                mitigated_at = idx[j]
                break

        events.append(
            {
                "confirmed_at": idx[i],
                "origin_at": idx[i - 1],
                "direction": direction,
                "top": top,
                "bottom": bottom,
                "mitigated_at": mitigated_at,
            }
        )

    return pd.DataFrame(events)


def find_liquidity_sweeps(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    """Detect liquidity sweeps: price wicks beyond a confirmed swing
    high/low then closes back on the other side (a stop-hunt / rejection).

    Bearish sweep: high trades above a prior swing high, closes back below it.
    Bullish sweep: low trades below a prior swing low, closes back above it.
    Only the most recent unswept prior swing is checked per bar to avoid
    re-flagging the same level repeatedly.
    """
    swings = find_swings(df, lookback=lookback)
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    idx = df.index

    events = []
    last_swing_high = None
    last_swing_high_swept = False
    last_swing_low = None
    last_swing_low_swept = False

    confirm_lag = lookback  # a swing at bar k is confirmed at bar k + lookback
    for i in range(len(df)):
        confirmable = i - confirm_lag
        if confirmable >= 0:
            if swings["swing_high"].iloc[confirmable]:
                last_swing_high = float(high[confirmable])
                last_swing_high_swept = False
            if swings["swing_low"].iloc[confirmable]:
                last_swing_low = float(low[confirmable])
                last_swing_low_swept = False

        if (
            last_swing_high is not None
            and not last_swing_high_swept
            and high[i] > last_swing_high
        ):
            last_swing_high_swept = True
            if close[i] < last_swing_high:
                events.append(
                    {
                        "at": idx[i],
                        "direction": "bearish",
                        "level": last_swing_high,
                    }
                )

        if (
            last_swing_low is not None
            and not last_swing_low_swept
            and low[i] < last_swing_low
        ):
            last_swing_low_swept = True
            if close[i] > last_swing_low:
                events.append(
                    {
                        "at": idx[i],
                        "direction": "bullish",
                        "level": last_swing_low,
                    }
                )

    return pd.DataFrame(events)


def find_structure_breaks(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    """Detect break of structure (BOS) and change of character (CHoCH).

    Tracks the most recently confirmed swing high/low. A close beyond that
    level is a structure break in that direction; it's labeled CHoCH if it
    reverses the prevailing trend (as tracked by the last break direction),
    otherwise BOS (continuation).
    """
    swings = find_swings(df, lookback=lookback)
    close = df["close"].to_numpy()
    idx = df.index

    events = []
    last_swing_high = None
    last_swing_low = None
    broken_high = False
    broken_low = False
    trend = 0  # 1 bullish, -1 bearish, 0 unknown

    confirm_lag = lookback
    for i in range(len(df)):
        confirmable = i - confirm_lag
        if confirmable >= 0:
            if swings["swing_high"].iloc[confirmable]:
                last_swing_high = float(df["high"].iloc[confirmable])
                broken_high = False
            if swings["swing_low"].iloc[confirmable]:
                last_swing_low = float(df["low"].iloc[confirmable])
                broken_low = False

        if last_swing_high is not None and not broken_high and close[i] > last_swing_high:
            broken_high = True
            label = "CHoCH" if trend == -1 else "BOS"
            events.append(
                {"at": idx[i], "direction": "bullish", "type": label, "level": last_swing_high}
            )
            trend = 1

        if last_swing_low is not None and not broken_low and close[i] < last_swing_low:
            broken_low = True
            label = "CHoCH" if trend == 1 else "BOS"
            events.append(
                {"at": idx[i], "direction": "bearish", "type": label, "level": last_swing_low}
            )
            trend = -1

    return pd.DataFrame(events)


def active_zones(events: pd.DataFrame, as_of, direction: str | None = None) -> pd.DataFrame:
    """Filter FVG/order-block style events (with confirmed_at/mitigated_at)
    down to zones that were confirmed at-or-before `as_of` and not yet
    mitigated at that point -- i.e. still "live" from the backtest's view.
    """
    if events.empty:
        return events
    mask = events["confirmed_at"] <= as_of
    mask &= events["mitigated_at"].isna() | (events["mitigated_at"] > as_of)
    if direction is not None:
        mask &= events["direction"] == direction
    return events[mask]
