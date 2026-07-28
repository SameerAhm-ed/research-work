# research-work

## GoldScalper — SMC-based XAUUSD backtesting engine

A Python backtesting pipeline for a Smart Money Concepts (SMC) style gold
(XAUUSD) trading strategy: EMA/RSI trend base signal, gated by an "Edge
Score" that adds confluence from order blocks, fair value gaps, liquidity
sweeps, break of structure / change of character, round-number levels, and
session timing.

This is currently **backtesting/paper-research only** — there is no live
broker connection. A live MT4/MT5 execution bridge (file-based signal
hand-off, same pattern as most retail Python+MT4 bots) is a later phase,
and would run on a Windows machine/VPS since MetaTrader doesn't run in this
Linux dev environment.

### Layout

```
goldscalper/
  data.py        # CSV loader (MT4/MT5 export format) + synthetic data generator
  indicators.py  # EMA, RSI, ATR, trend direction
  smc.py         # swings, fair value gaps, order blocks, liquidity sweeps, BOS/CHoCH
  edge_score.py  # weighted 0-100 confluence score + approval threshold
  backtest.py    # event-driven backtester (ATR SL/TP, fixed-fractional risk sizing)
  report.py      # stats (win rate, profit factor, drawdown, Sharpe) + charts
scripts/
  run_backtest.py  # CLI entry point
data/    # put historical OHLCV CSVs here (gitignored)
reports/ # generated trade logs + equity curve charts (gitignored)
```

### Usage

```bash
pip install -r requirements.txt

# Smoke-test the pipeline with generated data (NOT real market data):
python scripts/run_backtest.py --synthetic --bars 4000

# Run on real historical data exported from MT4/MT5:
python scripts/run_backtest.py --csv data/xauusd_h1.csv
```

The CSV loader expects an MT4/MT5-style export with either a `datetime`
column or separate `date`/`time` columns, plus `open`, `high`, `low`,
`close`, `volume` (column names are matched case-insensitively).

### Notes

- This dev environment has no general internet access, so historical price
  data can't be auto-fetched here (e.g. Yahoo Finance is blocked by the
  sandbox's network policy) — export candles from your MT4/MT5 terminal and
  drop the CSV into `data/`.
- The Edge Score weights/thresholds in `edge_score.py` are a reasonable
  starting point, not a tuned/validated strategy — treat backtest results
  as a pipeline check until run against real history and iterated on.
- `--synthetic` data is a random walk with regime shifts for exercising the
  pipeline only; performance on it says nothing about real trading edge.
