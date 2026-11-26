# tech_momentum

Hybrid trading agent for US tech stocks: a deterministic algorithmic core makes all
trading decisions; an LLM (added last) only produces structured features or veto flags.
This is a learning/engineering project, not an income plan.

## Architecture

Data ingestion -> signal engine -> strategy -> risk checks -> order execution -> logging/monitoring

Current files:
- `data.py`      download and cache adjusted daily closes (yfinance -> `data_cache/close_<hash>.csv`, keyed by
                 ticker set; empty columns retried; today's unfinished bar never cached) and the 13w T-bill rate (`data_cache/irx.csv`)
- `universe.py`  point-in-time Nasdaq-100 membership (jmccarrell/n100tickers, pinned commit) filtered to
                 tech-like names via `universe_data/ndx_sector_map.csv`; `load_universe("pit"|"all"|"static")` ("all" = every sector, comparison only)
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
- `trend_live.py` second paper strategy for live comparison: hold QQQ while above its 200d average, else cash.
                 Needs its OWN Alpaca paper account (`ALPACA_TREND_API_KEY/SECRET_KEY`); same kill switch;
                 logs in `logs/trend/`, state in `state/trend_state.json`. Dry run by default, `--submit` sends
- `compare.py`   step 6: live paper equity vs a shadow backtest of the same config from the first
                 live trade, fill slippage vs close, failed orders and alerts; covers momentum and the QQQ trend
                 runner (`--strategy momentum|trend|both`), plus both live accounts head to head
- `walkforward.py` rolling 3y-train / 1y-test walk-forward with a 48-combo parameter sweep, OOS report
                 (`python walkforward.py pit|static`)
- `report.py`    visual report: $100k growth vs QQQ, drawdowns, annual returns, start-date sensitivity,
                 holdings by group, today's picks -> `report/*.png` (`python report.py`)
- `analysis/`    reproducible research scripts (`python -m analysis.edge_test|vol_scaling|earnings|universe_compare|qqq_trend|distribution|cost_stress`);
                 research only, nothing in live trading imports them
- `tests/`       pytest: no look-ahead, weights, excess Sharpe, fold/selection/stitching logic

## Commands

- Setup: fresh venv (Python 3.10-3.11; vectorbt is picky about numpy/numba), `pip install -r requirements.txt`
- Run backtest: `python backtest.py`
- QQQ-trend paper strategy (second paper account): `export ALPACA_TREND_API_KEY=... ALPACA_TREND_SECRET_KEY=...`,
  then `python trend_live.py` / `--submit`, daily, same time window as `live.py`
- Paper trading: `export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...` (paper keys), then
  `python live.py` (dry run) / `python live.py --submit`, once per trading day, before ~15:35 ET.
  After a kill-switch alert: review, then `python live.py --reset-kill-switch`.
- Walk-forward: `python walkforward.py` (writes `walkforward_oos.png`)
- Tests: `python -m pytest`
- Daily paper steps, cutoff, log lines, kill-switch reset, weekly compare: `RUNBOOK.md`
- Parameter plateau heat map: `python -m analysis.param_plateau` (writes `report/param_plateau_pit.png`)
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

## Status (2026-11-26)

Steps 1-5 done; step 6 started: both paper runners are set up and dry-run tested on the user's Mac
(2026-11-25); no orders submitted yet. Repo: github.com/karimitaniii/claude-trader (private, `main`). 76 tests pass.

Key results (costs on, PIT universe, 2014-02-03..2026-11-25, final closes, recomputed 2026-11-26; numbers and
reasoning in `DECISIONS.md`):
- $100k becomes: momentum no risk layer $1.45M (CAGR 23.2%, MaxDD -57%); momentum + risk re-armed $1.09M
  (CAGR 20.5%, MaxDD -45%); QQQ buy-and-hold $813k (CAGR 17.8%, MaxDD -35%); QQQ 200d trend $493k (CAGR 13.3%,
  MaxDD -26%); momentum with the live hard-stop kill switch CAGR 14.1% (in cash after the 2021 kill until a human
  resets it).
- Excess Sharpe: QQQ 0.78 > momentum + risk re-armed 0.73 > QQQ trend 0.72 > momentum 0.70; equal-weight universe
  0.75. No evidence of edge beyond leveraged QQQ (alpha t=0.33, beta 1.43). Cost stress (5-40 bps slippage), full
  Nasdaq-100 universe, vol scaling and a distribution-day filter do not change that.
- Walk-forward (48 combos, OOS 2017+) shows excess Sharpe 0.87 vs QQQ 0.77 and default 0.63, with MaxDD -50% vs
  -35%; on the static universe it adds nothing (0.82 vs default 0.82). Grid widened after seeing results and no
  significance test: not adopted.
- About 80 variants tried and none reached t > 3 (ledger in `DECISIONS.md`): be skeptical of any new in-sample win.
- Recent: momentum's equity peaked at $3.25M on 2026-06-22 and was 55% below that on 2026-11-25. QQQ is below
  its 200d average (the trend strategy is in cash). The large 11-20..11-24 moves (e.g. NVDA +31.5% on 11-23) match
  Alpaca's daily bars within 0.6 pts.

Paper trading setup (done 2026-11-25):
- Two Alpaca paper accounts, because an account holds one set of positions and one equity (strategies cannot share
  one): momentum via `live.py` (`ALPACA_API_KEY/SECRET_KEY`), QQQ trend via `trend_live.py`
  (`ALPACA_TREND_API_KEY/SECRET_KEY`). The account numbers differ (verified). Both dry runs worked: momentum plans
  8 orders (85% gross after the hardware cap), trend plans none (QQQ below its 200d average).
- The user's Mac: repo at `~/Desktop/Claude Trader`, `.venv` (Python 3.11.9), keys in `~/.alpaca_paper_env` (outside
  the repo, chmod 600). Before each run: `source .venv/bin/activate && source ~/.alpaca_paper_env`. Cloud sessions
  cannot see the Mac (no keys, no files, the folder is not offered to cloud sessions): the user runs the runners
  and pastes output with key values removed. Give macOS zsh commands, each in its own code block.

Working conventions (how this project has been run):
- Cloud session develops on the branch it is given, opens a draft PR, and the user says "review and merge". Review
  means re-reading the diff critically, running the tests, and fixing real findings (several found so far, including a
  1-bar look-ahead in the first QQQ trend baseline). Never merge unasked; unsubscribe from the PR after merging.
- The cloud environment `claude-trader` allows only Yahoo Finance hosts (yfinance works; docs.alpaca.markets and
  most other sites are blocked). GitHub only through `gh api` REST calls. Retry on temporary GitHub 503s.
- Before a new experiment follow the checklist at the top of `DECISIONS.md` and add it to the variants ledger.

Next:
- 2026-12-01 (Tuesday, the next rebalance): run both dry runs from about 15:00 ET, check the planned orders with the
  user, then `--submit` on both by 15:35 ET (target). `can_submit_moc` refuses after 15:45 ET (15 min before close).
  The user decided NOT to submit before then. Procedure: `RUNBOOK.md`. After that run both daily and
  `python compare.py` weekly; read its output together once there are fills.
- Done (PR #9): `RUNBOOK.md`; parameter plateau check (`analysis/param_plateau.py`). Result: 252/21/8 = 0.70,
  neighbours 0.67-0.74, rule says PLATEAU; lookback matters more than top_n (63 row 0.88-0.96).
- Fixed 2026-11-26: a midday `live.py` run had cached the unfinished 11-25 bar as a close, which distorted the
  figures published that day (momentum 0.68). `load_prices` now never caches today's bar.
- Known small items, not fixed: `live.py` sizes on the previous close with up to 100% gross (a margin account makes
  an entry rejection unlikely); `report.py` "today's picks" ignores the live kill-switch state; `trend_live.py`
  redirects `live.LOG_DIR` while it runs; `analysis/earnings.py` skips names silently on download errors and never
  refreshes its cache; `compare.py` shadow uses cached prices (live.py refreshes the same cache daily).
- Open question: Step 7 (LLM layer) only after weeks to months of paper results. Idea for then: free SEC EDGAR
  8-K / 10-Q feeds as data inputs, with LLM outputs logged live to avoid training-data look-ahead.

## Style

- Python, type hints, small pure functions; pandas/numpy conventions already used in the repo.
- Add tests (pytest) for anything touching signals, weights, or risk limits; new signal/position paths also get a
  shock test in `tests/test_lookahead.py`. Before a new experiment follow the checklist at the top of `DECISIONS.md`
  and add it to the variants ledger there.
- Explain trade-offs briefly; flag assumptions rather than silently choosing.
