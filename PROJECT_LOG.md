# GoldScalper Project Log

Running record of what went wrong, what worked, and why -- kept so the
reasoning behind decisions doesn't get lost. Newest entries at the top.

---

## Round 5: found a real bug via manual reproduction; volatility filter doesn't beat Round 4

**Mistake, caught before shipping.** Added a volatility regime filter (halve
position size when ATR is running hot vs its own rolling average), wired it
into the search, and found a candidate whose fold-level walk-forward numbers
looked spectacular (worst-fold objective +2.479, the best margin yet).
Manually reproducing it to sanity-check before adopting it gave wildly
different numbers (drawdown -4.52% in the search's own report vs -16.4%+
when I copied the *rounded, printed* parameters into a fresh script).

Root cause, found by isolating each parameter change one at a time: Edge
Score weights are always whole integers, so achievable per-bar scores are
sums of a subset of them -- a small discrete set, not a continuum. This
candidate's weights had a subset summing to exactly 70, and the search
had picked threshold=70.02 -- 0.02 above that boundary. Rounding it to
70.0 for the reproduction script flipped every bar with that exact score
from rejected to approved, nearly doubling the trade count (580 -> 1073)
and blowing up drawdown. Confirmed with a direct A/B (identical weights
and SL/TP, threshold=70.02 vs 70.00) that this one value alone caused the
entire discrepancy. A stress test that only perturbed the ATR-based
parameters (SL/TP/trailing/vol, +-10%) showed smooth, stable behavior --
so the fragility was specific to the threshold sitting near a discrete
score boundary, not the strategy being fragile in general.

**Fix:** sample the search threshold as an integer too, matching the
weights' granularity, so "approved" can no longer flip on sub-integer
precision that a live system couldn't reliably reproduce anyway.

**After the fix, re-ran the full weights+SL/TP+trailing+volatility-filter
search properly and checked the top candidates against the locked
holdout.** None beat the Round 4 preset (no volatility filter) on the
metric that matters most here: the best candidate had higher return
(+32.6% vs +29.3%) but *worse* drawdown (-5.04% vs -3.95%), lower win
rate, and lower profit factor -- a different, worse point on the
risk/reward frontier, not an improvement. Kept the Round 4 config as the
active preset; the volatility filter code stays in the backtester (off by
default) since it's still a reasonable tool, it just didn't help here.

## Round 4: Trailing stop + locked holdout validation

**Success.** Added an ATR-based trailing stop (activates after a small
profit, then trails close behind price instead of capping at a fixed
target) and searched it jointly with weights/threshold/SL/TP. Result:
profit factor 1.54 -> 1.66, Sharpe 0.98 -> 2.18, win rate 48.6% -> 80.3%,
on the full 6.5-year real dataset.

**Process improvement, not a mistake caught after the fact:** before running
this search, split the data 85/15 and locked the most recent 15%
(2025-07 to 2026-07) away entirely -- no search in this round touched it.
Reasoning: by this point we'd run many rounds of "search, pick the best
result" on the same 6.5 years of data. Walk-forward validation catches a
single search overfitting, but repeatedly re-searching and picking winners
across *many* rounds adds its own quiet selection bias that walk-forward
alone doesn't catch. Checked the winning candidate against the untouched
holdout exactly once: 83.8% win rate, Sharpe 3.25, max DD -3.95% on data
the search never saw. Held up cleanly -- meaningful evidence this isn't
just fitting noise.

## Round 3: SL/TP were never tuned -- big gap, big fix

**Mistake (caught before shipping, not after):** every search up to this
point only tuned Edge Score weights and the approval threshold. The
stop-loss (2.0x ATR) and take-profit (2.5x ATR) were left at arbitrary
defaults nobody had ever validated -- for a trend-following strategy
specifically, this is a real gap, since a too-tight stop shakes out real
trends and a too-close target caps winners early.

**Fix:** extended the search to sample SL/TP multipliers jointly with
weights. Found 3.79x ATR stop / 6.30x ATR target performed far better:
max drawdown -20/-25% -> -5.3%, Sharpe 0.17 -> 0.98.

## Round 2: multi-seed + focused search revealed real signal vs. noise

**Success.** Ran the weight search across 5 different random seeds
instead of trusting one. Most "winning" configs only worked on their own
seed's search (classic overfitting). But two patterns kept reappearing
independently across seeds: heavy round-number weighting (paired with
near-zero structure-break weighting), and heavy trend-alignment weighting.
Finding the *same* signal from independent random starting points is much
stronger evidence than one good-looking result.

Ran focused searches (biased sampling around each pattern) to sharpen
both: "Direction A" (round-number heavy) reached +23.7% avg per
out-of-sample fold but with -20% to -25% worst-case drawdown; "Direction
B" (trend heavy) reached +4.6-6.4% per fold with a much shallower -8% to
-9% worst case. User picked B: -25% drawdown was judged too painful to
trade regardless of the return, and "you can lever up a reliable low-risk
strategy, you can't un-blow-up an aggressive one."

**Finding worth remembering:** of the 8 factors scored (trend, RSI, fair
value gaps, order blocks, liquidity sweeps, structure breaks, round
numbers, session timing), only round-number proximity and trend alignment
consistently drove the winners. The "Smart Money Concepts" factors that
give this style of strategy its name -- order blocks, FVGs, liquidity
sweeps, structure breaks -- never reliably differentiated a winning
config from a losing one. The fashionable part of the framework wasn't
where the edge was; two old, simple concepts were.

## Round 1: zero-cost backtest was overstating the edge

**Mistake, caught before any real conclusion was drawn.** The first
backtests ran with no transaction costs modeled at all. Once real
historical spread (already present in the MT5 export, just not being
read) was wired in as a real per-trade cost: return dropped from +26.5%
to +8.9%, Sharpe from 0.38 to 0.17, on the same untuned config. A
zero-cost backtest is not a conservative approximation for a
higher-frequency strategy -- it's a materially wrong number.

**Fix:** `data.load_csv()` keeps the `<SPREAD>` column; `backtest.py`
charges it once per trade (bid-basis OHLC, so a buy fills at ask on
entry, a sell fills at ask on exit -- whichever leg is the "buy").

Also replaced the single train/test split used for the first tuning run
with proper walk-forward validation (multiple non-overlapping
expanding-window folds) after noticing a single lucky split could produce
a false "winner" -- the single-split search's top candidate collapsed
hard on a second look.

## Round 0: two performance bugs made real data unusable

**Mistake.** The pipeline was built and validated on ~4,000 bars of
synthetic data. Real data was 38,367 bars (~10x), and two things that
looked fine at small scale didn't finish in 5+ minutes at real scale:

1. `edge_score.compute_direction_features()` looped bar-by-bar doing
   ~15-20 pandas filter operations per bar. Fixed by looping over SMC
   *events* (hundreds, not tens of thousands) and using numpy slicing to
   mark active bar-ranges instead -- 38k bars: didn't finish -> ~3.5s.
   Verified zero mismatches against the old per-bar logic before trusting it.
2. `backtest.run_backtest()` read `df.iloc[i]`/`scores.iloc[i]` every bar --
   fine once, but a 300-trial tuning search called it hundreds of times.
   Fixed by reading from plain numpy arrays instead. 38k bars: 3.5s -> 0.15s.
   Verified identical trade-for-trade output before trusting it.

**Also discovered:** this sandbox has no general internet access (Yahoo
Finance, Stooq etc. all blocked by the network policy) -- had to get real
historical data via MT5's own CSV export instead of fetching it
automatically. MT5's native export format (tab-separated, `<ANGLE
BRACKET>` column headers, separate real-volume/tick-volume columns) also
needed the CSV loader to be more flexible than a first pass assumed.

---

## Current best (as of Round 5)

Unchanged from Round 4 -- see `goldscalper/presets.py` ->
`TREND_LOW_DRAWDOWN_*`. Full 6.5-year dataset: 826 trades, 80.3% win
rate, profit factor 1.66, Sharpe 2.18, max drawdown -5.71%, +197.45%
total return. Validated on a locked, never-searched holdout year: 83.8%
win rate, Sharpe 3.25, max DD -3.95%. Round 5's volatility filter was
tried and properly validated but didn't beat this, so it wasn't adopted.

**Still not done:** no second instrument for diversification, no forward
paper-trading, no live execution bridge.
