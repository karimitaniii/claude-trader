# tech_momentum

Hybrid trading agent for US tech stocks: a deterministic algorithmic core makes all
trading decisions; an LLM (added last) only produces structured features or veto flags.
This is a learning/engineering project, not an income plan.

## Architecture

Data ingestion -> signal engine -> strategy -> risk checks -> order execution -> logging/monitoring

Current files:
- `data.py`      download and cache adjusted daily closes (yfinance -> `data_cache/close_<hash>.csv`, keyed by
                 ticker set; empty columns retried) and the 13w T-bill rate (`data_cache/irx.csv`)
- `universe.py`  point-in-time Nasdaq-100 membership (jmccarrell/n100tickers, pinned commit) filtered to
                 tech-like names via `universe_data/ndx_sector_map.csv`; `load_universe("pit"|"static")`
- `signals.py`   12-1 momentum -> monthly equal-weight top-N target weights (shifted 1 bar), only names
                 eligible on the signal date; `equal_weights` = same-universe no-selection benchmark
- `backtest.py`  vectorbt backtest vs equal-weight universe and QQQ, with fees and slippage,
                 sub-period stats incl. excess Sharpe (vs 13w T-bill), equity plot
- `risk.py`      risk layer, separate from the strategy and able to override it: position cap, group caps
                 (semis 50%, hardware 35%), sell-off rule (QQQ < 200d SMA -> 50% gross), drawdown kill switch with cooldown;
                 `run_with_risk` is a causal daily loop whose orders are re-run through vectorbt
- `broker.py`    Alpaca PAPER-only wrapper (paper=True hard-coded, endpoint checked), market-on-close
                 orders with deterministic client_order_id; `PaperSimBroker` for offline runs/tests
- `live.py`      daily runner: fills -> fresh prices (today's partial bar dropped) -> kill switch ->
                 monthly targets from previous month-end close -> risk layer -> whole-share orders.
                 Dry run by default; `--submit` sends to paper. Logs: `logs/YYYY-MM-DD.jsonl`,
                 state: `state/live_state.json` (`--offline` uses separate files)
- `compare.py`   step 6: live paper equity vs a shadow backtest of the same config from the first
                 live trade, fill slippage vs close, failed orders and alerts
- `walkforward.py` rolling 3y-train / 1y-test walk-forward with a 48-combo parameter sweep, OOS report
                 (`python walkforward.py pit|static`)
- `report.py`    visual report: $100k growth vs QQQ, drawdowns, annual returns, start-date sensitivity,
                 holdings by group, today's picks -> `report/*.png` (`python report.py`)
- `analysis/`    reproducible research scripts (`python -m analysis.edge_test|vol_scaling|earnings`);
                 research only, nothing in live trading imports them
- `tests/`       pytest: no look-ahead, weights, excess Sharpe, fold/selection/stitching logic

## Commands

- Setup: fresh venv (Python 3.10-3.11; vectorbt is picky about numpy/numba), `pip install -r requirements.txt`
- Run backtest: `python backtest.py`
- Paper trading: `export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...` (paper keys), then
  `python live.py` (dry run) / `python live.py --submit`, once per trading day, before ~15:35 ET.
  After a kill-switch alert: review, then `python live.py --reset-kill-switch`.
- Walk-forward: `python walkforward.py` (writes `walkforward_oos.png`)
- Tests: `python -m pytest`
- Refresh data: call `load_prices(..., refresh=True)`; refresh membership: `universe.refresh_membership()`
  (bump `SOURCE_COMMIT` first; any new ticker must be classified in `ndx_sector_map.csv` or loading fails)

## Non-negotiable rules

1. **No look-ahead.** Signals use data up to the close of day t and trade no earlier than t+1.
2. **Costs always on.** Never report a backtest without fees and slippage.
3. **LLM never decides size or places orders.** It may only emit structured features
   (sentiment, guidance up/down, event flags) or veto flags consumed by deterministic code.
4. **Risk layer is separate from the strategy** (position caps, total exposure, max-drawdown
   kill switch) and must be able to override the strategy.
5. **Paper trading only** (Alpaca paper account) until I explicitly say otherwise.
   Never place live orders, and never add code paths that default to live.
6. **Secrets** (API keys) come from environment variables. Never commit or print them.
7. Keep changes small and runnable; run the backtest after each change and report results honestly,
   including when a change makes things worse.

## Known limitations (fix before trusting results)

- Universe is now point-in-time Nasdaq-100 tech-like members, but with free data: yfinance has no prices
  for acquired/delisted names (XLNX, CTXS, ANSS, SPLK, MXIM, ...), so ~10% of tech member-days are
  untradable and excluded. The tech/non-tech sector map is hand-made (not point-in-time GICS).
  The old static 24-name list is kept only as a comparison (`load_universe("static")`).
- Parameters (lookback 252, skip 21, top_n 8, monthly rebalance, 5 bps fees + 5 bps slippage)
  are untuned defaults.
- Tech's long bull run flatters long-only backtests; always inspect 2022, and 2000-2002 / 2008
  if data allows.
- Stocks in this universe are highly correlated; top-N is less diversified than it looks.
- Risk defaults (15% position, 50% semis, 35% hardware, 25% kill switch, 21-day cooldown, 200d trend) are a priori,
  not tuned. The kill switch is a hard stop on drawdown from the all-time high: once fired, the
  strategy stays in cash until a human reviews and calls `KillSwitch.reset()`. It acts at the next
  close, so gaps can push a loss past 25%.
- Earnings gaps: decided to hold through (see Decisions). About 20% of held-name earnings days move >10%.

## Roadmap (in order)

1. Run `backtest.py` end to end, fix any environment or API issues, confirm the outputs are sane.
2. Add walk-forward validation (rolling train/test windows) and a small parameter sweep
   with out-of-sample reporting; avoid picking parameters on the full sample.
3. Point-in-time universe.
4. Risk layer module with unit tests (caps, drawdown kill switch, cash rule on sector sell-offs).
5. Alpaca paper-trading execution (daily/weekly rebalance), with full logging of signals,
   orders, fills, errors, and alerts.
6. Paper trade for weeks to months; compare live paper results to backtest expectations.
7. Only then: LLM feature layer (earnings transcripts, 10-K/10-Q, 8-K). Keep it only if it
   improves out-of-sample results over the baseline. Log LLM outputs live to avoid
   training-data look-ahead bias in evaluation.

## Status (2026-11-25)

Steps 1-5 done; step 6 tooling done (`compare.py`), no paper orders submitted yet. Repo:
github.com/karimitaniii/claude-trader (private, `main`). 55 tests pass.

Key results (costs on, PIT universe, 2014+): momentum excess Sharpe 0.72 vs QQQ 0.79, MaxDD -0.57; no
evidence of edge beyond leveraged QQQ (alpha t=0.34). Full numbers and reasoning: `DECISIONS.md`.

Decisions in force (details and why in `DECISIONS.md`):
- Free hybrid PIT data, tech-like NDX members; ~10% of member history missing.
- Untuned defaults 252/21/8, monthly rebalance (weekly ~= monthly, daily worse); revisit after paper results.
- Risk: 15% position, 50% semis, 35% hardware caps; hard-stop kill switch (25%) with manual reset.
- Hold through earnings. Volatility scaling and shorter lookback (63/0/8) tested, not adopted.
- Market-on-close whole-share orders; `KNOWN_NO_DATA` tickers skipped to keep runs quiet.

Next:
- Recommended: wait for the 2026-12-01 rebalance before the first `live.py --submit` (current signal is
  stale and all-semis/storage; a shadow run from 2026-11-03 lost ~17%). User has not decided.
- Then run `live.py` every trading day (no schedule yet; launchd only if asked), `compare.py` weekly.
- Open questions: Step 7 only after
  weeks-months of paper results.

## Style

- Python, type hints, small pure functions; pandas/numpy conventions already used in the repo.
- Add tests (pytest) for anything touching signals, weights, or risk limits.
- Explain trade-offs briefly; flag assumptions rather than silently choosing.
