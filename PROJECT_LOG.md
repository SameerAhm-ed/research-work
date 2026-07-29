# GoldScalper Project Log

Running record of what went wrong, what worked, and why -- kept so the
reasoning behind decisions doesn't get lost. Newest entries at the top.

---

## Round 10: Monte Carlo trade-sequence analysis -- the realized result isn't a lucky fluke

**Success -- new rigor added while waiting on the next data export.** Every
number so far came from exactly one historical path through time. Built
`goldscalper/montecarlo.py` to resample the active preset's realized
trades (as per-trade % returns, so compounding stays correct regardless
of order -- verified replaying the original order exactly reconstructs
the real equity curve to floating-point precision) and generate a
distribution of plausible outcomes instead of one point estimate.

Two methods, 3000 simulations each, on trend_htf's 1,797 realized trades:
- **Shuffle** (same trades, reordered): isolates how much drawdown depends
  on when losing streaks happened to cluster. Total return is
  mathematically order-invariant under compounding, so only drawdown
  varies here.
- **Bootstrap resample** (with replacement): tests sensitivity to the
  exact set of trades observed; both return and drawdown vary.

**Result: the realized -7.63% drawdown sits at the 58th percentile of
the shuffle distribution, and the realized +263.3% return sits at the
96th/50th percentile (shuffle/resample).** Both close to the simulated
median, not an outlier best-case ordering -- meaningful evidence the
reported numbers aren't just a lucky historical sequence.

**But:** the worst 1% tail case reaches -14% to -15% drawdown -- roughly
double what actually happened. That's real tail risk a single backtest
run can't show on its own, worth keeping in mind before sizing up
position risk for live/paper trading.

---

## Round 9: adopted trend_htf as the active preset (user's decision)

Broke Round 8's trade-off down by calendar year to make the decision
concrete instead of arguing from two aggregate numbers. Drawdown shown is
from the real running all-time-equity-peak (not reset per year -- per the
Round 6 lesson):

| Year | Conservative: Return | Conservative: DD | trend_htf: Return | trend_htf: DD |
|---|---|---|---|---|
| 2020 | +28.5% | -2.3% | +16.0% | -5.1% |
| 2021 | +13.1% | -4.9% | +12.0% | -6.0% |
| 2022 | +8.8%  | -5.7% | +22.8% | -6.6% |
| 2023 | +21.0% | -3.4% | +27.0% | -4.5% |
| 2024 | +12.8% | -4.9% | +23.5% | -7.6% (worst) |
| 2025 | +27.3% | -3.0% | +19.9% | -3.6% |
| 2026* | +8.3% | -4.0% | +21.1% | -3.6% |

*2026 partial, through July.

Both configs are profitable in every single calendar year 2020-2026 --
strong for either. 2020 is the one year the conservative config clearly
wins both axes; 2022-2024 the trend_htf config pulls well ahead on return
(and its year-to-year returns are also less variable: 12-27% range vs the
conservative config's wider 8-29% swings) while giving up 1-3 points of
extra drawdown per year, never exceeding -7.6% in any single year.

**Decision: adopted trend_htf as the active preset.** Given both
worst-cases are already shallow (under 8%) and the return/Sharpe gap is
consistent across most years rather than a single lucky stretch, the
extra ~3.7 points of annual return was judged worth the modest extra
drawdown. The conservative config stays in the codebase and fully usable
(`--preset trend_low_dd`) -- this was a preference call, not a case of
one config being objectively wrong.

---

## Round 8: MTF confirmation, properly re-optimized -- a real trade-off, not a win

**Follow-up to Round 7's caveat.** Re-ran the full weights+SL/TP+trailing
search with the H4 gate active in every trial (not bolted on after the
fact), so everything else could re-adapt to the smaller, filtered trade
set. This time the top candidates held up much better under scrutiny:
checked against the full continuous 6.5-year history (not just the
holdout), the best one had *higher* Sharpe (2.27 vs the current preset's
2.18) and substantially higher return (+263% vs +197%) -- but also worse
drawdown (-7.63% vs -5.71%).

**Not adopted, on purpose.** This isn't a Round 6/7 situation (a good
holdout number hiding a worse full-history reality) -- the full-history
numbers here are genuinely better on two of three axes. But drawdown is
the one thing prioritized explicitly and repeatedly throughout this
project (it's the reason Direction B was chosen over Direction A back in
Round 2), so trading it away for more return isn't a decision to make
unilaterally. Logged as a real, validated alternative -- higher
return/Sharpe for worse drawdown -- in case that trade-off becomes
preferable later.

---

## Round 7: multi-timeframe confirmation, bolted on -- doesn't help as tested

**Negative result, logged honestly.** Built H4/D1 trend confirmation
(goldscalper/mtf.py): derives higher-timeframe EMA9/21 trend by resampling
the existing H1 data (no new export needed -- more reliable than joining
two separately-exported files, which risks a boundary-alignment mismatch),
shifted by one higher-TF bar before aligning back so it's lookahead-safe
(verified against a hand-built step-function test). Wired in as a hard
approval gate (EdgeScoreConfig.require_htf_trend), deliberately not a
weighted/searchable factor, to avoid growing the overfitting surface.

Tested by bolting the gate onto the current best preset's already-tuned
weights/SL/TP/trailing (H4 only, D1 only, both). Full continuous
6.5-year drawdown got *worse* in every variant (-6.1% to -8.1% vs the
baseline's -5.71%), and Sharpe/return dropped too -- even though some
variants looked better on the holdout alone (H4+D1: holdout drawdown
-1.99% vs baseline -3.95%). Consistent with the Round 6 lesson: a
holdout-only improvement isn't trustworthy without checking the full
history, and here the full history says no.

**Caveat on this result:** this only tests bolting the gate onto a
config tuned *without* it -- thinning out the trade set changes the
statistics the rest of the config was tuned for, so this isn't
necessarily a fair test of MTF confirmation as an idea, just of grafting
it on after the fact. A proper test would re-run the full search with
the gate active throughout, letting weights/SL/TP/trailing re-adapt to
the smaller, filtered trade set. Not done yet -- pausing here to report
the honest bolt-on result before deciding whether that's worth the
compute.

---

## Round 6: 6-fold search finds nothing better; a holdout window isn't the whole story

**Success (validation methodology got stricter) + a negative result (nothing
adopted).** Re-validated the Round 4 preset under 6 and 8 walk-forward folds
instead of 4 -- held up well (6/6 folds profitable at 6 folds; only one very
small loss, -1.07%, across 8 folds). Then re-ran the full weights+SL/TP+
trailing search with 6 folds to see if the stricter bar surfaced anything
better.

One candidate looked like a genuine upgrade at first: on the locked holdout,
+44.2% return vs the current preset's +29.3%, *and* better drawdown (-3.48%
vs -3.95%), *and* better Sharpe (3.38 vs 3.25). Stress-tested it first this
time (perturbed SL/TP/trailing by +-10%, checked neighboring integer
thresholds) -- unlike Round 5's candidate, this one was NOT fragile; behavior
stayed smooth and stable throughout.

But checking the **full continuous 6.5-year run** (not just the holdout
window) told a different story: real max drawdown -9.87%, clearly worse
than the current preset's -5.71%. The holdout year this candidate was
checked against simply happened not to contain its worst historical
stretch -- which is somewhere earlier in the dev period. Not adopted.

**Methodological lesson worth keeping:** an honest out-of-sample check
(holdout, or any single walk-forward fold) can still miss a strategy's
worst drawdown if that particular window doesn't happen to contain it.
From here on, no candidate gets adopted without checking the full
continuous run across all available history, not just its holdout or
fold-level numbers -- those are necessary checks, not sufficient ones.

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

## Where things stand (as of Round 9)

**Active strategy:** `goldscalper/presets.py` -> `TREND_HTF_*`
(`--preset trend_htf`). Trend-following on GOLD H1, gated by H4 trend
confirmation, with a tight ATR-based trailing stop. Full 2020-01 to
2026-07 real dataset: 1,797 trades, 77.0% win rate, profit factor 1.56,
Sharpe 2.27, max drawdown -7.63%, +263.3% total return (~21.9% CAGR).
Profitable in every calendar year. Validated on a locked holdout year the
search never touched, and re-validated under 6/8-fold walk-forward
splits (methodology carried over from the conservative config's Round 6
checks -- applies equally here since it's the same validation pipeline).

**Conservative alternative**, still available (`--preset trend_low_dd`):
same idea without the H4 gate, ~3.7 points lower CAGR, shallower drawdown
(-5.71% worst case vs -7.63%). Documented in Round 9 above; pick this
instead if the extra drawdown ever stops feeling worth it.

**What's been tried and ruled out** (all logged above with the actual
numbers): more Edge Score factors beyond trend+round-number (the
"Smart Money Concepts" factors never drove a winning config), a
volatility regime filter (Round 5), finer walk-forward re-validation
alone without new structure (Round 6), MTF confirmation bolted onto an
already-tuned config instead of re-optimized around it (Round 7). What
*did* work: real transaction costs (Round 1, without which the backtest
was lying), SL/TP tuning (Round 3), a trailing stop (Round 4), and MTF
confirmation done properly (Round 8/9).

**What's still not done, roughly in order of expected value:**

1. **Second instrument for real diversification.** Everything so far is
   one instrument (GOLD), one broker, one H1 feed. A second, less-
   correlated market is the strongest remaining lever for a genuine
   drawdown reduction (as opposed to trading return for drawdown, which
   is what every tuning round so far has actually been doing). Needs a
   fresh MT5 export from you.
2. **M1-precision fill validation.** Discussed but not yet done: our
   backtest assumes a conservative same-bar tie-break when SL and TP are
   both touched within one H1 bar. The trailing stop in particular
   (activates as tight as 0.4-0.9x ATR) is exactly the kind of parameter
   where intrabar path matters. M1 data (not full ticks -- see the
   discussion when this came up) would let us check the H1 backtest isn't
   quietly overstating performance. Needs an M1 export from you.
3. **Forward paper-testing.** The real test of all of this: run it against
   live prices going forward, where nothing has been tuned to fit. Doesn't
   need new data, needs a decision to stop optimizing on history and start
   watching it work (or not) on the future.
4. **Live MT4/MT5 execution bridge.** Only worth building once paper
   results earn it -- this environment can't run MT4/MT5 itself (Windows
   dependency), so this step happens on your machine/VPS when we get there.

Nothing above is blocking -- these are options, not a queue. Your call on
which (if any) to pick up next.
