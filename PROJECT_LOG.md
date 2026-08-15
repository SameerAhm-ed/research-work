# GoldScalper Project Log

Running record of what went wrong, what worked, and why -- kept so the
reasoning behind decisions doesn't get lost. Newest entries at the top.

---

## Round 15: portfolio re-check + quantifying the lot-granularity gap

Two pieces of offline work done in parallel while the live paper test
sits idle waiting on data (weekend market closure, terminal/script left
running to prove out the uptime fix from Round 14).

**1. Re-ran the GOLD+EURUSD combined portfolio** (`scripts/run_portfolio.py`)
against the corrected, post-Round-12-fix presets -- `presets.py` had
flagged this as stale since Round 11's check used the invalidated
configs. Result: $5,000/leg, 758 GOLD + 142 EURUSD trades, combined
return +130.4%, max drawdown -5.42% (vs GOLD alone's -9.94%), Sharpe
1.22, ending equity $23,037 on $10,000 combined starting capital.
Confirms genuine diversification survives the fix -- this matches the
number already (correctly, as it turns out) quoted in the
`EURUSD_WEIGHTS` comment block; only the separate, older "needs
re-checking" note further down in the file was actually stale. Cleaned
up both.

**2. Built and ran a lot-size-granularity sweep.** The backtester
(`goldscalper/backtest.py`) has always sized positions as a continuous
real number (`units = risk_amount / stop_distance`) -- it never modeled
a broker's minimum tradeable lot or lot-step rounding. That gap is
exactly what caused the Round 14 live sizing bug and went unnoticed
until a real trade hit it. Added optional `lot_step`/`lot_min` fields to
`BacktestConfig` (default `None` -- fully opt-in, doesn't change any
existing validated numbers) that quantize `units` the same way the live
EA does: floor to the nearest step, clamp up to the minimum. For GOLD's
standard 100oz contract, `units` in this codebase's PnL math already
equals ounces directly (PnL = price_delta * units), so the broker's
0.01-lot step/minimum maps to exactly 1 unit -- a clean, exact
correspondence, not an approximation.

Swept `TREND_HTF` full-dataset backtest across starting equity from
$500 to $100,000, continuous vs. discrete sizing:

| Equity | Continuous Return | Discrete Return | Continuous MaxDD | Discrete MaxDD |
|---|---|---|---|---|
| $500 | 233.4% | 484.7% | -9.94% | -27.51% |
| $1,000 | 233.4% | 250.7% | -9.94% | -19.54% |
| $1,170 (current live balance) | 233.4% | 214.7% | -9.94% | -18.67% |
| $2,500 | 233.4% | 144.4% | -9.94% | -11.59% |
| $5,000 | 233.4% | 180.6% | -9.94% | -8.69% |
| $10,000 | 233.4% | 213.7% | -9.94% | -9.79% |
| $25,000 | 233.4% | 226.3% | -9.94% | -9.73% |
| $50,000 | 233.4% | 232.5% | -9.94% | -9.84% |
| $100,000 | 233.4% | 232.2% | -9.94% | -9.91% |

Two takeaways: (a) below roughly $10k-25k, lot-size rounding is not a
small effect -- it adds real, unpredictable variance (both return and
drawdown swing meaningfully away from the continuous baseline, in
either direction depending on exactly where in the trade sequence
equity crosses a rounding boundary), and (b) by $25k+ it's basically
gone (<1pp drawdown difference). At the account's actual current
balance (~$1,170), discrete-lot max drawdown is -18.67% vs. the
backtested -9.94% -- essentially double. This is a quantified version of
exactly the risk flagged qualitatively in the earlier live-trade
discussion: a small account isn't running "the same strategy, smaller,"
it's running a meaningfully higher-variance version of it because the
broker's minimum lot doesn't shrink with the account.

**Not acted on yet:** this doesn't change the decision already made (stay
at the current balance) -- it just makes the tradeoff being accepted
concrete and numeric instead of hand-wavy. Worth revisiting if/when the
balance decision gets reconsidered.

---

## Round 14: first live demo trade caught a real position-sizing bug

First actual trade went live on the XM Global GOLD demo account (Ticket
2165264453, buy 0.01 lots, entry 4076.14, SL 4004.92, TP 4248.84). SL/TP
price levels checked out exactly against the signal's offsets -- the
entry/exit math was correct from day one. But the *sizing* wasn't:
account balance $1,000, `InpRiskPct=0.01` should mean $10 risked, and
the EA's log line said exactly that ("risk $10.0") -- except the actual
trade risked roughly $71 (the full 4076.14-4004.92 stop distance times
the 0.01-lot minimum), about 7x the intended amount.

**Root cause:** `OpenTradeFromSignal()` computes `lots =
riskAmount / riskPerLot` correctly, but GOLD's minimum tradeable lot
(broker's `SYMBOL_VOLUME_MIN`, 0.01) is bigger than what $10 of risk at
this stop distance calls for. The clamp `lots =
MathMax(volMin, MathMin(volMax, lots))` silently rounds *up* to the
broker minimum whenever the risk-based size would otherwise round down
to zero -- and the actual dollar risk taken scales with that clamped
lot size, not the intended one. The subsequent `Print()` reported the
pre-clamp `riskAmount` ($10, what was *intended*), not what was actually
risked, so the log itself was misleading: everything looked fine
watching the Journal, but the account was carrying ~7% risk per trade
instead of ~1%. This is exactly the failure mode paper-testing exists to
catch -- a bug invisible in backtesting (position sizing isn't
simulated the same way) and invisible in dry-run mode (no real lot
clamping happens until an order is actually sized against a real
account's broker limits).

**Fix** (`mt_scripts/GoldScalperLiveEA.mq5`):
1. `OpenTradeFromSignal()` now computes `actualRisk = lots * riskPerLot`
   *after* clamping and logs that, not the pre-clamp intended amount --
   the Journal log is now honest about what was actually risked.
2. Added `InpMaxRiskMultiple` (default 1.5): if the broker's minimum lot
   would force actual risk above `InpRiskPct * InpMaxRiskMultiple`, the
   EA now aborts the entry with a clear explanation instead of silently
   taking oversized risk. This is a real constraint on a $1,000 account
   trading GOLD at these validated ATR multiples (~$70-90 typical stop
   distances) -- it will legitimately skip some signals until the
   account is larger or `InpRiskPct` is raised to match what 0.01 lots
   actually costs at this stop distance. That's the correct behavior:
   skipping a trade beats taking it at 7x the intended risk.

**Also found while investigating:** `goldscalper/backtest.py`'s
`BacktestConfig` defaults to `starting_equity=$10,000`, and every preset
in this project was validated against that. The demo account was
started at $1,000 -- 10x smaller than what was ever backtested. At $10k,
1% risk is $100/trade, comfortably above GOLD's ~$70-90 typical stop
distance; at $1k it's $10, which is *why* the min-lot floor kept biting.
Decision: recreate the XM Global demo account at $10,000 to match the
backtest exactly, rather than distorting `InpRiskPct` to compensate for
an account size mismatch.

**Added a startup sanity check** (`CheckAccountSizeVsRisk()`, runs once
in `OnInit()`): computes the largest stop distance the current account
can take without the min-lot floor pushing risk past
`InpMaxRiskMultiple`, and compares it against a rough H1-ATR-based
estimate of a typical stop distance (informational only -- real SL
always comes from the signal file, this never duplicates the actual
strategy logic). Logs a clear WARNING at EA attach time if the account
looks too small for the instrument, instead of only finding out after a
live trade. This is exactly the check that would have caught today's
mismatch before the $1,000 account ever took a trade.

---

## Round 13: paper-trading infrastructure built (GOLD only, trend_htf)

Moved from pure backtesting to live-adjacent infrastructure. Chose GOLD
alone first (not the GOLD+EURUSD combined portfolio) to keep the first
real-world setup simple to debug -- EURUSD can be added the same way
once this is confirmed working.

Built a file-bridge architecture (same pattern as the original
inspiration for this whole project): `scripts/live_signal_generator.py`
runs on the user's Windows machine (this sandbox has no live market
data access), pulls fresh H1 bars via the MetaTrader5 Python package,
and runs them through the *exact same* goldscalper pipeline already
validated in backtesting -- no strategy logic duplicated or
reimplemented. Approved signals are written as plain price-unit offsets
(SL/TP/trailing, derived from ATR at signal time) to a CSV file.
`mt_scripts/GoldScalperLiveEA.mq5` watches that file and handles
execution only: opens the trade, sizes it by fixed-fractional risk
against real account equity, and manages the trailing stop tick-by-tick
(more precise than even the M1 validation, since it's the live broker
feed). The EA has no strategy logic of its own by design.

**Not live-tested** -- this environment can't reach a live MT5
connection to test that part. Verified everything that could be
verified from here: Python syntax, presets resolving correctly, and the
core signal-computation path running correctly end-to-end using real
historical data as a stand-in for the live feed. PAPER_TRADING_SETUP.md
has a dry-run mode to build confidence before it's trusted with even
demo trades.

---

## Round 12: the biggest mistake caught in this project -- and the fix

**Mistake, caught properly before real money was ever at stake.** Got a
~2.5-month GOLD M1 (1-minute) export. Built goldscalper/fill_validation.py
to replay the H1-backtest's realized trades against real intrabar M1
price paths (same SL/TP/trailing logic, just driven by 60x finer bars),
to check whether the H1 approximation (which can't see the true path
within an hour) was materially wrong.

It was. H1-simulated PnL for the 68 trend_htf trades in the M1 window:
$2,526. M1-precise replay: $881 -- a ~65% overstatement. Root cause:
GOLD's average H1 bar range is ~1x its own ATR (they're nearly the same
statistic), so the tuned trailing distance (0.46-0.53x ATR) sat *inside*
a single bar's ordinary noise. The H1 backtest used the bar's high/low as
"best price reached" and assumed the trade could ride toward it before
the trailing stop caught it -- but within that same hour, price often
touched the stop first. Exit *reason* always matched (68/68); the bias
was purely in exit *price*, concentrated entirely in trailing-stop exits
(plain SL exits matched to the cent).

This also meant `trend_low_dd` and `EURUSD` were almost certainly broken
the same way -- both used equally tight trailing distances (0.51x,
0.48x), just unverified since M1 data doesn't cover their trades.

**Fix:** raised the trailing distance floor to 1.5x ATR (default changed
in TuneConfig itself, not just the presets, so this can't silently recur
in a future search). Re-tuned all three presets with the same
methodology as before -- walk-forward validation, locked holdout, full
continuous history check -- then re-verified trend_htf against the M1
data: largest single-trade discrepancy dropped from ~$50 to $4.54, no
systematic bias remaining.

**Honest recalibration -- performance is real but less flattering than
before:**

| | trend_htf (before/after) | trend_low_dd (before/after) | EURUSD (before/after) |
|---|---|---|---|
| Win rate | 77% -> **42%** | 80% -> **44%** | 83% -> **58%** |
| Max drawdown | -7.63% -> **-9.94%** | -5.71% -> **-8.97%** | -5.09% -> **-4.67%** |
| Profit factor | 1.56 -> 1.45 | 1.66 -> 1.61 | 1.35 -> 1.44 |
| Sharpe | 2.27 -> 1.33 | 2.18 -> 1.21 | 1.17 -> 0.73 |

The high win rates and shallow drawdowns reported through Rounds 4-11
were partly an artifact of a simulation that let the tightest trailing
stops "cheat" -- not a real property of the strategies. The corrected
numbers are a normal trend-following profile: fewer, bigger wins, real
(higher) drawdown.

**One more honest layer, found by re-running Monte Carlo (Round 10) on
the corrected configs:** the realized drawdowns above are themselves on
the *favorable* side of what could have happened. trend_htf's -9.94%
sits at the 98th percentile of the shuffle distribution (only 2% of
reorderings of the same trades would have had a shallower drawdown);
the median simulated drawdown is -14.7%, and the worst 1% tail reaches
-25.8%. Same pattern for trend_low_dd (actual -8.97% at the 86th
percentile, median -11.4%, 1% tail -21.2%). Fewer trades (a side effect
of the wider, now-trustworthy trailing stops) means more variance in
what a given historical sequence could have looked like -- the single
realized path is less representative of "typical" performance than it
was with the old, higher-frequency (but broken) configs.

**Portfolio combination re-checked with corrected configs:** GOLD+EURUSD
combined drawdown -5.42% vs GOLD alone's -9.94% (still a real,
substantial reduction) while retaining ~56% of the return (130.4% vs
233.4%, same total capital). The diversification finding from Round 11
survives the fix.

Old (buggy) presets kept under `_INVALIDATED_` names in
goldscalper/presets.py, not deleted -- so the record of what changed and
why stays intact.

---

## Round 11: EURUSD generalization confirmed + real diversification benefit found

**Success -- this is the strongest validation result in the project.**
Got EURUSD H1 data (2020-01 to 2026-07, same period as GOLD). Two tests:

1. **Direct transfer** (GOLD's exact tuned weights/SL/TP, just fixing
   EURUSD's instrument scale -- round_number_step 10.0->0.01, point_size
   0.01->0.00001): weak. Profit factor 1.06, Sharpe 0.26, DD -13.27%.
   Not a surprise -- exact parameter transfer between different-character
   instruments rarely works well.
2. **Independent search** (own random seed, own 85/15 dev/holdout split,
   anchored on the same trend-following hypothesis but free to find its
   own weights): converged on the same signature GOLD did -- moderate-high
   trend_alignment + round_number + session_timing, structure_break near
   zero -- *without being told to*. Full dataset: 716 trades, 82.8% win
   rate, profit factor 1.35, Sharpe 1.17, max DD -5.09%, +55.45% return.
   Holdout year: PF 1.20, Sharpe 0.69, DD -3.82%, +3.32% -- smaller
   numbers (EURUSD is much lower-volatility than gold) but positive and
   consistent with the full-history result.

That the *same underlying pattern* (not the same numbers, the same
concept: trend + round-number + session timing + H4 confirmation) emerges
independently on a second, unrelated instrument is real evidence this
isn't a gold-specific curve-fit -- it's the strongest generalization
signal in the whole project so far.

**Then the actual point of getting a second instrument: portfolio
diversification.** Built goldscalper/portfolio.py to combine both legs'
equity curves (dollar PnL, resampled onto a common index, summed).
Combining GOLD + EURUSD at full risk_pct each, same total capital as
GOLD alone: **combined drawdown -3.99%, roughly half of GOLD alone's
-7.63%, while keeping ~60% of the return (159.4% vs 263.3%).** This is
genuine diversification, not just an average -- each leg's own individual
drawdown (GOLD -7.63%, EURUSD -5.09%) is *deeper* than the combined
portfolio's -3.99%, because their bad stretches don't fully overlap in
time. Verified the portfolio module reproduces the manual calculation
exactly before trusting it.

**Also fixed along the way:** tune.py's search() hardcoded GOLD-scale
structural settings (round_number_step=10.0, point_size=0.01) with no
way to override them -- silently wrong for any other instrument. Made
these TuneConfig fields before running the EURUSD search.

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

## Where things stand (as of Round 12)

**Active strategy:** `goldscalper/presets.py` -> `TREND_HTF_*`
(`--preset trend_htf`). Trend-following on GOLD H1, gated by H4 trend
confirmation, with an ATR-based trailing stop wide enough to be
trustworthy on H1 data (>=3x ATR, fixed in Round 12 after M1 validation
caught a ~65% overstatement bug in the previous, too-tight version).
Full 2020-01 to 2026-07 real dataset: 758 trades, 42.0% win rate, profit
factor 1.45, Sharpe 1.33, max drawdown -9.94%, +233.4% total return.
Holdout year (locked, never searched): 117 trades, profit factor 1.74,
Sharpe 2.40, max DD -7.50%, +40.3% return. Verified against real M1
intrabar data (largest single-trade discrepancy: $4.54).

Per the Monte Carlo check (Round 10, re-run in Round 12 on the corrected
config): treat -9.94% as an optimistic case, not the expected one --
median simulated drawdown for this same set of trades is -14.7%, and the
worst 1% tail reaches -25.8%.

**Conservative alternative**, still available (`--preset trend_low_dd`):
same idea without the H4 gate. 283 trades, profit factor 1.61, Sharpe
1.21, max DD -8.97%, +157.4% return -- closer to trend_htf than it used
to be, now that both use the same trustworthy trailing-distance floor.

**EURUSD** (`presets.EURUSD_*`, no CLI preset yet): the generalization
check (Round 11) that confirmed this isn't a gold-specific pattern. 142
trades, profit factor 1.44, Sharpe 0.73, max DD -4.67%, +27.3% return.
Combined with GOLD in a portfolio (`scripts/run_portfolio.py`): -5.42%
drawdown vs GOLD alone's -9.94%, retaining ~56% of the return -- genuine
diversification, survives the Round 12 fix.

**What's been tried and ruled out** (all logged above with the actual
numbers): more Edge Score factors beyond trend+round-number (the
"Smart Money Concepts" factors never drove a winning config), a
volatility regime filter (Round 5), finer walk-forward re-validation
alone without new structure (Round 6), MTF confirmation bolted onto an
already-tuned config instead of re-optimized around it (Round 7). What
*did* work: real transaction costs (Round 1, without which the backtest
was lying), SL/TP tuning (Round 3), a trailing stop -- eventually, after
Round 12 fixed how tight it could safely be (Round 4/12), MTF
confirmation done properly (Round 8/9), a second instrument for real
diversification (Round 11), and Monte Carlo trade-sequence analysis
becoming a standard check, not an afterthought (Round 10/12).

**What's still not done, roughly in order of expected value:**

1. **Forward paper-testing.** The real test of all of this: run it
   against live prices going forward, where nothing has been tuned to
   fit. Doesn't need new data, needs a decision to stop optimizing on
   history and start watching it work (or not) on the future. More
   pressing now than before Round 12 -- the honest tail-risk numbers
   from Monte Carlo make this the natural next checkpoint rather than
   further tuning.
2. **M1 data for EURUSD**, and/or a longer GOLD M1 window, to extend the
   fill-precision check's coverage (currently only ~2.5 months of GOLD).
   Not blocking -- the fix (wider trailing floor) is a structural,
   instrument-agnostic correction, not something that needs new data to
   justify -- but broader M1 coverage would sharpen confidence further.
3. **Live MT4/MT5 execution bridge.** Only worth building once paper
   results earn it -- this environment can't run MT4/MT5 itself (Windows
   dependency), so this step happens on your machine/VPS when we get there.

Nothing above is blocking -- these are options, not a queue. Your call on
which (if any) to pick up next.
