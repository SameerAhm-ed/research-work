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
  tune.py        # randomized Edge Score weight/threshold search w/ train-test split
scripts/
  run_backtest.py    # CLI entry point for a single backtest run
  tune_edge_score.py # CLI entry point for the weight search
data/    # put historical OHLCV CSVs here (gitignored)
reports/ # generated trade logs, equity curve charts, tuning results (gitignored)
```

### Usage

```bash
pip install -r requirements.txt

# Smoke-test the pipeline with generated data (NOT real market data):
python scripts/run_backtest.py --synthetic --bars 4000

# Run on real historical data exported from MT4/MT5:
python scripts/run_backtest.py --csv data/xauusd_h1.csv

# Search for better Edge Score weights + threshold (once you have real data):
python scripts/tune_edge_score.py --csv data/xauusd_h1.csv --trials 300
```

The CSV loader expects an MT4/MT5-style export with either a `datetime`
column or separate `date`/`time` columns, plus `open`, `high`, `low`,
`close`, `volume` (column names are matched case-insensitively).

### Weight tuning

`tune_edge_score.py` runs a randomized search over the Edge Score weights
and approval threshold, using a chronological (no-shuffle) train/test split
so a config that only worked on in-sample noise gets flagged rather than
handed back as a "winner" — it ranks candidates on the train segment, then
re-evaluates the top few out-of-sample and warns when a candidate's
performance collapses on the test segment (that's overfitting, not edge).
Per-bar SMC feature lookups are computed once per segment and reused across
all trials, so hundreds of trials stay fast even on a few years of data.

Run it against `--synthetic` data and it will only validate that the search
machinery works — since that data is a random walk, "tuned" weights on it
are fitting noise. Point it at a real `--csv` before trusting any output.

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
