# Decisions and results log

Moved out of CLAUDE.md (2026-11-25) to keep every session cheap. Read only when revisiting a decision.

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
  analysis not in repo). Held names' earnings-reaction days: 1.6% of held days, mean +0.62% vs +0.11%
  normal, ~8% of portfolio variance. Exit over earnings: CAGR 0.201 vs 0.234, excess Sharpe 0.64 vs 0.70,
  MaxDD -0.55 vs -0.57; half size in between. Momentum names tend to gap up on earnings.
- Kill switch (2026-11-25): keep the live hard stop with manual reset. Re-arm backtests: vs no kill switch
  (CAGR 0.207, Sharpe 0.70, MaxDD -0.49) it adds little (Sharpe +0.01-0.03, MaxDD a few pts); cooldown
  length barely matters; 35% threshold ~= no kill switch. Its value is forcing a human review, not returns.
- Is there an edge? (2026-11-25, PIT 2014+, daily excess returns, script not in repo): regression on QQQ
  (Newey-West t): default alpha +1.9%/yr t=0.34, beta 1.43, R2 0.70 -> mostly leveraged QQQ, no evidence of
  skill; 63/0/8 alpha +9.1%/yr t=1.85 (borderline, and a hindsight pick). Block bootstrap (21d blocks, 5000):
  default Sharpe 0.70 [0.21, 1.22], QQQ 0.78 [0.30, 1.30]; P(default > QQQ) 0.31, P(63/0/8 > default) 0.94
  (CI includes 0), P(hw35 cap > semis-only) 0.99 but only +0.04. ~13 years cannot separate Sharpe gaps < ~0.3.
- Volatility scaling (2026-11-25, script not in repo, not implemented): at each monthly rebalance scale the
  top-8 basket by min(1, target / trailing 63d vol). Target 25%: CAGR 0.202, vol 0.26, excess Sharpe 0.76 vs
  0.70, MaxDD -0.35 vs -0.57, 2022 -0.24 vs -0.39, but 2020 +0.36 vs +0.90 (sits out the rebound). Paired
  Sharpe diff +0.06, CI [-0.12, 0.26], P>0 0.71: not distinguishable from QQQ (0.78). Not adopted.
- Market-on-close whole-share orders, monthly rebalance from previous month-end signal (matches backtest).
- yfinance known-dead tickers skipped (`KNOWN_NO_DATA`) to keep daily runs quiet.
