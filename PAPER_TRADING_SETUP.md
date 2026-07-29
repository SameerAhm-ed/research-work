# Paper Trading Setup: GOLD, `trend_htf` preset

Runs on your Windows machine (where MT5 is already installed and logged
into your XM Global demo account) -- this sandbox has no live market
data access, so this can't run here.

**Not live-tested.** Both pieces reuse code already validated in
backtesting, and were reasoned through carefully, but neither has run
against a real live MT5 connection (impossible to do from this dev
environment). Follow the dry-run steps below before trusting it with
even demo trades.

## How it works

1. `scripts/live_signal_generator.py` runs continuously on your PC. Once
   per hour (just after each H1 candle closes) it pulls fresh bars
   straight from your running MT5 terminal, runs them through the exact
   same `goldscalper` pipeline used in every backtest in this project,
   and -- if a trade is approved -- writes it to a signal file
   (`goldscalper_signal.csv`).
2. `mt_scripts/GoldScalperLiveEA.mq5`, attached to a GOLD chart in MT5,
   watches that file. It has no strategy logic of its own -- it just
   opens the trade the Python side decided on, then manages the ATR-based
   trailing stop tick-by-tick (this is actually *more* precise than our
   M1 validation, since it's your broker's real live feed, not replayed
   history).

## Setup

### 1. Python side

On the Windows machine running MT5:

```
pip install MetaTrader5 pandas numpy
```

Copy this `research-work` project (or at least the `goldscalper/`
package and `scripts/live_signal_generator.py`) onto that machine.

**Dry run first** -- confirms the connection and signal logic work
without writing anything the EA could act on:

```
python scripts/live_signal_generator.py --symbol GOLD --preset trend_htf --once --dry-run
```

Check the printed output: it should show the current bar, both
direction scores, and whether a signal would be approved. If this
works, watch it for real (still dry-run, no file writes) for a while:

```
python scripts/live_signal_generator.py --symbol GOLD --preset trend_htf --dry-run
```

Once you're satisfied it's behaving sensibly, drop `--dry-run` to let it
actually write `goldscalper_signal.csv`:

```
python scripts/live_signal_generator.py --symbol GOLD --preset trend_htf
```

Leave this running (a plain console window, or a scheduled task that
restarts it if it dies). It logs every check to
`goldscalper_live_log.txt` next to it.

### 2. MT5 / EA side

1. File -> Open Data Folder -> `MQL5/Experts/` -> copy
   `GoldScalperLiveEA.mq5` in.
2. Open it in MetaEditor, Compile (F7) -- 0 errors expected.
3. Open a GOLD chart, timeframe doesn't matter (the EA runs on
   `OnTick`/`OnTimer`, not candle events).
4. Drag the compiled EA onto the chart. In the inputs dialog:
   - `InpSignalFile`: must match `--signal-file` from the Python side
     (default `goldscalper_signal.csv`) -- **use the same working
     directory** for both, or give the EA the full path.
   - `InpRiskPct`: 0.01 matches the backtested config; change only if
     you deliberately want different sizing than what was validated.
   - Leave the rest at defaults unless you know why you're changing them.
5. Make sure **Algo Trading** is enabled (toolbar button, should be
   green) and the EA's smiley-face icon in the top-right of the chart is
   also green/enabled.
6. Check the **Experts**/**Journal** tab for
   `GoldScalperLiveEA initialized...` -- confirms it's watching.

## Watching it

- Every signal the Python side generates is logged in
  `goldscalper_live_log.txt` (this machine) -- compare that against what
  the EA actually does in MT5's **Journal**/**Trade** tabs.
- If you export the demo account's trade history periodically (Account
  History -> right-click -> Save as Report, or a fresh CSV export like
  the ones you've already done), send it over and it can be compared
  against the Python side's log to check the two are staying in sync --
  that's the whole point of paper testing before this ever touches a
  live account.

## Stopping / resetting

- Stop the Python script (Ctrl+C) any time; the EA will just stop seeing
  new signals but keeps managing any already-open position.
- Remove the EA from the chart to stop it trading entirely (it won't
  touch any position it doesn't recognize by magic number, so removing
  it is safe even mid-trade -- you'd just manage that position manually
  from then on).
