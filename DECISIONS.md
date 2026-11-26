# Decisions and results log

Moved out of CLAUDE.md (2026-11-25) to keep every session cheap. Read only when revisiting a decision.

## Before running a new experiment (pre-registration checklist)

Adopted 2026-11-25 after the QQQ-trend timing bug and ~80 variants tried (ledger at the bottom).
1. Hypothesis in one sentence, with the economic reason it should work.
2. Parameters and the adoption rule (metric, threshold, and the baselines to beat: QQQ buy-and-hold and the 200d
   trend) written down BEFORE running. Extra values are "sensitivity only", never candidates.
3. Costs on; anything that trades more than the baseline also gets a cost stress (`analysis/cost_stress.py` pattern).
4. Timing: signal at t trades at t+1's close. Any new signal/position path needs a shock test in
   `tests/test_lookahead.py` (perturb prices from t-1 on, nothing earlier may move) with a negative control.
5. Same dates as the baselines; no trimming of the sample after the fact.
6. Report everything tried, failures included, and add a row to the ledger. Adopt only if it beats the baselines
   after costs out of sample or in paper trading. With this many looks, in-sample t-stats near 2 are expected by
   chance; a common factor-research rule of thumb is t > 3.

Key results (costs on, PIT universe, 2014+): momentum CAGR 0.244, excess Sharpe 0.72, MaxDD -0.57;
QQQ excess Sharpe 0.79; equal-weight universe about as good as momentum. Walk-forward OOS 0.75.
With all risk defaults + hard-stop kill switch: CAGR 0.14, MaxDD -0.27 (one kill, 2021-05, then cash).
That -0.27 is not a realistic expectation: it sits in cash after 2021 because nobody resets it. With all
risk defaults and the kill switch re-armed after review (proxy: auto re-arm, 21-126d cooldown, QQQ above
200d): CAGR ~0.20, excess Sharpe ~0.71-0.73, MaxDD -0.45 to -0.48, 4-5 kills since 2014.

Decisions and why:
- Free hybrid PIT data (n100tickers + yfinance), tech-like NDX members: no paid data; accept ~10% missing.
- Kill switch is a hard stop with manual reset: forces a human review instead of silently re-arming.
- Keep untuned defaults (252/21/8): walk-forward did not beat them convincingly; avoid overfitting.
- Rebalance frequency (2026-11-25, `target_weights(freq="M"|"W"|"D")`): weekly ~= monthly, daily clearly
  worse at every lookback (CAGR -4..-7 pts/yr; trading only on pick changes did not help -> whipsaw, not
  just costs). Stay monthly. Constant intraday trading would need a different, short-horizon strategy.
- Shorter lookback (63/0/8): full-sample excess Sharpe PIT 0.92 vs 0.70, static 1.05 vs 0.94; PIT
  walk-forward with 48-combo grid OOS 0.86 vs default 0.63, but static walk-forward 0.83 vs default 0.84
  and grid widened after seeing results (snooping). With all risk rules 63/0/8 is worse (kill 2020-03,
  then cash). Decision: keep 252/21/8 for first paper trades; revisit after paper results.
- Hardware cap 35% (2026-11-25): a 50% cap never bound; 35% gave excess Sharpe 0.72 vs 0.68 (semis cap
  only), MaxDD -0.50 vs -0.57; 25% was best in-sample (0.75) but not chosen to avoid tuning. Cut goes to
  cash. The hardware group is mixed (AAPL, CSCO, storage, optics, solar), not storage-only.
- Earnings (2026-11-25): hold through. yfinance earnings dates 2002+ (cached `data_cache/earnings.csv`,
  `analysis/earnings.py`). Held names' earnings-reaction days: 1.6% of held days, mean +0.62% vs +0.11%
  normal, ~8% of portfolio variance. Exit over earnings: CAGR 0.201 vs 0.234, excess Sharpe 0.64 vs 0.70,
  MaxDD -0.55 vs -0.57; half size in between. Momentum names tend to gap up on earnings.
- Kill switch (2026-11-25): keep the live hard stop with manual reset. Re-arm backtests: vs no kill switch
  (CAGR 0.207, Sharpe 0.70, MaxDD -0.49) it adds little (Sharpe +0.01-0.03, MaxDD a few pts); cooldown
  length barely matters; 35% threshold ~= no kill switch. Its value is forcing a human review, not returns.
- Is there an edge? (2026-11-25, PIT 2014+, daily excess returns, `analysis/edge_test.py`): regression on QQQ
  (Newey-West t): default alpha +1.9%/yr t=0.34, beta 1.43, R2 0.70 -> mostly leveraged QQQ, no evidence of
  skill; 63/0/8 alpha +9.1%/yr t=1.85 (borderline, and a hindsight pick). Block bootstrap (21d blocks, 5000):
  default Sharpe 0.70 [0.21, 1.22], QQQ 0.78 [0.30, 1.30]; P(default > QQQ) 0.31, P(63/0/8 > default) 0.94
  (CI includes 0), P(hw35 cap > semis-only) 0.99 but only +0.04. ~13 years cannot separate Sharpe gaps < ~0.3.
- Volatility scaling (2026-11-25, `analysis/vol_scaling.py`, not implemented in live): at each monthly rebalance scale the
  top-8 basket by min(1, target / trailing 63d vol). Target 25%: CAGR 0.202, vol 0.26, excess Sharpe 0.76 vs
  0.70, MaxDD -0.35 vs -0.57, 2022 -0.24 vs -0.39, but 2020 +0.36 vs +0.90 (sits out the rebound). Paired
  Sharpe diff +0.06, CI [-0.12, 0.26], P>0 0.71: not distinguishable from QQQ (0.78). Not adopted.
- Market-on-close whole-share orders, monthly rebalance from previous month-end signal (matches backtest).
- yfinance known-dead tickers skipped (`KNOWN_NO_DATA`) to keep daily runs quiet.

Reproduction note (2026-11-25): the analysis scripts were rewritten from the descriptions above and re-run on fresh
data. Edge test and vol scaling match the logged numbers within rounding (alpha +2.1%/yr t=0.38, vol-scaled
CAGR 0.202 / MaxDD -0.35). Earnings reaction stats match (1.6% of held days, +0.62% vs +0.11%); the "skip
reaction days" counterfactual ignores exit/re-entry costs (CAGR 0.214 vs 0.236), so it is less negative than the
original -3 pt figure, which included them.

- Full Nasdaq-100 vs tech-like universe (2026-11-25, `analysis/universe_compare.py`, `load_universe("all")`, same
  12-1 / top 8 / monthly rules, costs on, 2014-02..2026-11): full NDX is worse on every measure. No risk layer: CAGR
  0.206 vs 0.236, excess Sharpe 0.65 vs 0.71, MaxDD -0.56 both, $100k -> $1.10M vs $1.51M (QQQ $0.82M). With risk
  re-armed: 0.163 vs 0.205 CAGR, Sharpe 0.61 vs 0.73. Equal-weight full NDX also lags tech-like (0.147 vs 0.202).
  Alpha vs QQQ stays indistinguishable from zero in both (t 0.17 vs 0.38). Momentum did hold non-tech names
  (about 39% of equity on average), so the tech filter is not what drives picks, but those names did not pay.
  Caveat: 15.6% of full-NDX member-days have no price (9.9% tech-like), so the comparison is more survivorship-
  biased against the wider universe; non-tech names are one uncapped "non_tech" risk group. Decision: stay tech-like.

- QQQ trend baseline (2026-11-25, `analysis/qqq_trend.py`, 2014-02..2026-11, costs on, cash earns T-bill): hold QQQ
  above its 200d average, else T-bills; the signal from day t's close trades at t+1's close (position earns from
  t+2). CORRECTED: the first version held the signal shifted by 1 bar (traded at the same close that produced
  it, a look-ahead) and flattered every row below; the timing test missed it because its crash day was followed by
  a flat price. 200d (the a-priori window, same as the risk layer): CAGR 0.133, excess Sharpe 0.72, MaxDD -0.26,
  2022 -0.19, $100k -> $493k, 61 switches; alpha vs QQQ +2.0%/yr t=0.74, beta 0.59. (Wrong version: Sharpe 0.76,
  MaxDD -0.23, $520k, alpha t=1.03.) vs momentum no-risk: CAGR 0.236, Sharpe 0.71, MaxDD -0.56, $1.51M. Other windows
  (three tried, so selection bias): 150d Sharpe 0.75, MaxDD -0.25, alpha t=1.04; 100d Sharpe 0.54. The earlier "150d
  looks like a hint" (Sharpe 0.89, t=1.90) was mostly the timing bug. Read: trend-following QQQ roughly matches
  momentum's risk-adjusted return with about half the drawdown and ~40% lower beta, but earns much less in $ terms,
  and neither shows significant alpha over QQQ buy-and-hold (QQQ Sharpe 0.78 is still the best of all).
- Paper trade both strategies (2026-11-25): momentum (`live.py`) and the QQQ 200d trend baseline (`trend_live.py`),
  each in its own Alpaca paper account because an account holds one set of positions and one equity (a shared
  account would make each runner trade the other's positions and mix the kill-switch equity). Trend orders only on an
  on/off change, so whole-share drift never causes daily trades. Live paper cash earns no T-bill interest, unlike the
  backtest. `compare.py` covers both: the trend shadow mirrors the live runner (98% target, trades only on on/off changes, no cash interest), not the research backtest.
- Trend runner sizing (2026-11-25): target 98% of equity, not 100%, because the order is sized on yesterday's close and
  fills at today's; a full-size order can exceed cash after a gap up and be rejected. Costs about 2% of cash drag.
  `live.py` (momentum) has the same sizing pattern at up to 100% gross; not changed here.

- Distribution-day filter (2026-11-25, `analysis/distribution.py`, QQQ overlay, 2014-02..2026-11, costs on, signal at
  t trades at t+1): IBD-style distribution day = QQQ down >= 0.2% on higher volume than the prior day; rule fixed
  BEFORE looking: out when >= 5 in the last 25 sessions. Result: it fails. With QQQ's volatility such days are 23% of
  all days, so the count is >= 5 on 71% of days and the rule sits in T-bills most of the time: CAGR 0.052, excess
  Sharpe 0.43, 203 switches (QQQ 0.78; 200d trend 0.72). Combined with the 200d trend it is worse (Sharpe 0.30). The
  4 and 6 thresholds (sensitivity only) give 0.05 and 0.59: no setting beats the plain 200d trend, and tuning the
  threshold upward would just be an in-sample pick. The classic 4-5 count was set for a calmer index/era, so the
  threshold does not transfer. Not adopted, not worth integrating into `risk.py`.
  Information content (QQQ forward 21d return by state; descriptive only, overlapping windows, no significance
  test): no clear return difference between states. Below the 200d average the mean forward return is +2.1% vs
  +1.5% above it, but forward volatility is 36% vs 18%; dist >= 5 gives 1.5% vs 1.8% with vol 24% vs 15%. So the 200d trend works as a volatility-regime indicator, not a return
  forecast, which is consistent with the vol-scaling result (lower drawdown, Sharpe roughly unchanged).

- Cost stress (2026-11-25, `analysis/cost_stress.py`, fees 5 bps + slippage 5/10/20/40 bps, 2014-02..2026-11): costs
  do not change the picture. Momentum no-risk CAGR 0.236 -> 0.232 -> 0.225 -> 0.210, excess Sharpe 0.71 -> 0.65,
  $1.51M -> $1.14M (QQQ $818k); traded notional (buys + sells) of ~6.4x average equity per year (~3.2x one-way), so each +10 bps of slippage costs ~0.6 pts/yr.
  QQQ trend 200d: CAGR 0.133 -> 0.114, Sharpe 0.72 -> 0.61, ~4.8 switches/yr. No strategy reaches QQQ's Sharpe (0.78)
  at any cost level. The re-armed risk-layer row is not monotone (CAGR 0.205 at 5 bps, 0.207 at 10 bps): kill-switch
  timing shifts with equity, so read its cost sensitivity loosely. Real slippage is unknown until paper fills
  (`compare.py`); mid-size picks (SNDK, LITE, ...) likely sit at 10-20 bps, not 5.

- Parameter plateau (2026-11-26, `analysis/param_plateau.py`, pre-registered before running: 4x4 walk-forward grid with
  skip 21, PIT, 2014-02..2026-11, costs on, full-sample excess Sharpe; plateau = every grid neighbour of 252/8 within
  0.10 Sharpe). Default 252/21/8 = 0.68, neighbours 189/8 0.66, 252/6 0.72, 252/10 0.65 -> PLATEAU by the rule. Grid
  0.58-0.94, median 0.74. The plateau is in top_n; lookback moves Sharpe much more: 63 is 0.86-0.94 across all top_n,
  189 is 0.58-0.66. So 252 is locally stable but sits in the weaker half of the lookback axis, and a 63-day lookback
  is the best row, which the earlier 63/0/8 result already flagged (hindsight, not adopted). Diagnostic only: no
  parameter change. QQQ 0.76 on the same sample.
  Reproduction note: the default here is 0.68 and QQQ 0.76, but the 2026-11-26 status lines above say momentum 0.71 and
  QQQ 0.78. `analysis/common.py` gives the same 0.677 / 0.761 on the same sample, so the earlier numbers came from an
  earlier data state or run. Not reconciled yet; treat the 0.71 / 0.78 figures as unverified until re-run.

## Variants ledger (lower bound; early exploratory runs were not logged)

| Family | Variants tried |
|---|---|
| Momentum parameters (lookback x skip x top_n), walk-forward grid (widened once after seeing results) | 48 |
| Rebalance frequency (M / W / D) | 3 |
| Universes (static 24, PIT tech-like, full Nasdaq-100) | 3 |
| Risk-layer variants in `backtest.py` (each rule alone, kill-switch hard stop / re-arm, all) | 7 |
| Hardware group cap (50 / 35 / 25, semis-only) | 3 |
| Kill-switch re-arm studies (threshold 25 / 35, cooldown 21-126d) | ~6 |
| Earnings handling (hold / exit / half size) | 3 |
| Volatility scaling (target 25%) | 1 |
| QQQ trend windows (100 / 150 / 200d) | 3 |
| Distribution-day thresholds (4 / 5 / 6) | 3 |
| Parameter plateau check (existing 4x4 grid, no new values, diagnostic only) | 0 new |
| **Total** | **~80** |

Best in-sample alpha t-stat among them: 1.85 (63/0/8 lookback, a hindsight pick). None reached 3. With ~80 looks,
that is what noise looks like, which is consistent with "no evidence of edge beyond QQQ".
