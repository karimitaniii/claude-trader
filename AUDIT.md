# Repository audit, 2026-11-26

Scope: the whole repository at `9e82388` (`main`), 45 tracked files. Nothing tracked was changed, committed or pushed.
(An untracked `I_DONT_LIKE.md` appeared in the root during the audit; it is not part of it and was not opened.)
All reproductions ran on temporary copies with fake brokers and no Alpaca calls. Checksums of `data_cache/`, `state/`
and `logs/` taken before the reproductions still matched afterwards.

## What this repo does

A paper-trading bot for US tech stocks: monthly momentum picks (`live.py`) and a QQQ 200-day trend rule
(`trend_live.py`), a risk layer, Alpaca paper orders, and backtests. Assumed load: one person running each script by
hand once a day on one Mac.

## Verdict

No look-ahead found in the live order path or the main backtest, no way to reach a live (real-money) endpoint found,
no secrets found in git history, and the headline backtest numbers reproduce. The weak part is **what happens when
something goes wrong**, and **the tests do not protect the live order path** (32 of 38 deliberate bugs went
unnoticed in our own checks). Before 2026-12-01, work through the "Must do" table below.

Severity: **High** = can cause wrong or missing orders, or defeats a safety rule. **Medium** = wrong numbers, lost
protection in a less likely case, or misleading instructions. **Low** = small or unlikely.
Status: **Verified** = reproduced by running it. **Code** = confirmed by reading the code only. **Plausible** = depends
on outside behaviour that could not be checked.

## Must do before 2026-12-01

| # | Action | Size |
|---|---|---|
| 1 | Make the dry run show the planned orders | few lines |
| 2 | Write down how to recover when an order is not filled or fails (finding 2 and 3) | docs, or small code |
| 3 | Fix the RUNBOOK on when orders are planned: any `--submit` before this month is recorded trades, including before 12-01 (finding 4) | few sentences |
| 4 | Add one test of the real broker adapter and the cutoff refusal (finding 5) | small test file |

Recommended in the same pass (cheap, and each can lead to a wrong or unnoticed order): abort on short or stale QQQ
history (findings 8, 19), keep `state/` safe and know that deleting it re-arms the kill switch (12), and alert on every
run while killed (29).

Also expect on 12-01: QQQ closed 11-25 at 633.93, below its 200-day average (682.54). If it is still below on 11-30,
the sell-off rule cuts momentum to **50% invested**, not the 85% in the earlier dry runs (`report.py` on cached data
shows 4 semis at 7.4% and 4 hardware names at 5.1%). The trend runner should plan no order.

## High

### 1. The dry run does not show the orders it asks you to check
- Where: `live.py:111`, `RUNBOOK.md:40-41`. **Verified.**
- Scenario: `log_event` drops the `orders` and `targets` fields from the printed line. The terminal shows only
  `[signal] signal_day=...`, `[risk] fired=..., gross=0.45`, `[dry_run] n_orders=3`. No ticker, side or quantity.
  RUNBOOK step 4 says to confirm exactly those from the output. The user may submit without having seen them.
- Fix: print one line per planned order (`side qty symbol`) in `submit_all` for dry runs, or add the `tail` command
  to step 4 and say the orders are only in the log file. Print is better.

### 2. A month counts as rebalanced when orders are accepted, not when they fill
- Where: `live.py:237-238`, `live.py:133-137`. **Verified.** RUNBOOK line 116 states the behaviour.
- Scenario: all 8 orders are accepted on 12-01, then rejected or expired at the close. The next run logs an alert,
  sends nothing, and the account stays in cash until January. There is no flag or documented step to retry.
- Fix (smallest): document the recovery (check the Alpaca dashboard, then set `last_rebalance_month` to `null` in
  `state/live_state.json` and dry-run again). Better: do not treat the month as done while an order ended unfilled.

### 3. One order that keeps failing turns the monthly strategy into a daily one
- Where: `live.py:162-169`, `live.py:237`. **Verified.**
- Scenario: one symbol is always refused (not tradable, halted). The month is never recorded, so every daily
  `--submit` re-sizes all names. Reproduced: orders on Dec 2, 3 and 4 trading 1-3 shares of names already held.
- Same cause: a same-day re-run after a partial failure re-sends accepted orders. Only Alpaca refusing a repeated
  `client_order_id` prevents double buying; that refusal was **not verified** (`broker.py:22` asserts it, RUNBOOK
  line 128 says it is unverified).
- Fix: after the first submission, store the planned quantities in state and on later runs send only what failed.
  Until then, RUNBOOK: after any `order failed`, do not `--submit` again before checking the dashboard.

### 4. Submitting now would rebalance November at once
- Where: `live.py:209-211`, `state/live_state.json` (`last_rebalance_month: null`), `RUNBOOK.md:44`. **Verified.**
- Scenario: `python live.py --submit` on 11-27 buys immediately on the October month-end signal, then rebalances
  again on 12-01. RUNBOOK says momentum plans orders "on the first trading day of a month", which suggests an early
  submit is harmless. In fact any run in a month with nothing recorded plans orders.
- Same cause: `RUNBOOK.md:121-122` says that after `not submitting` you may "wait for the next rebalance". Any later
  `--submit` in that month still trades the old month-end signal.
- Fix: correct both sentences and add the warning.

### 5. The tests do not protect the live order path
- Where: `tests/`. **Verified** by mutation: break one thing in a copy, run the suite. **28 of 34 breaks passed**, then 4 of 4 more.
- Survived, live path: cutoff check ignored; 15-minute limit removed; market-closed check removed; order type
  changed from market-on-close to day; every order sent as a buy; intraday equity used; paper endpoint check removed;
  previous-session off by one; today's partial bar not dropped (both runners); sell-off rule off; **all risk limits
  off**; kill check run on every run; month recorded after a failed submit; submit failure reported as success;
  `--offline` writing real state; kill-switch reset doing nothing; fills never logged; trend runner ignoring stale
  data or a missing session.
- Survived, research: backtest fees and slippage set to zero; `call_seq` changed; walk-forward look-ahead; walk-forward
  starting early; shadow backtest trading before the live start; wrong shadow start equity; dead names kept; risk
  variants ignoring the risk layer.
- Also survived (found by the test agent, re-run here): a kill-switch liquidation falling through into a rebalance;
  momentum picking the worst names instead of the best; semiconductor-equipment names leaving the semis cap;
  walk-forward selecting the worst parameters.
- Reported by the test agent, not re-run here: no test pins the live signal wiring (eligibility, signal day, trend,
  parameters), `load_universe`, the `main()` flag handling of either runner, trend stale-data and missing-session
  aborts, or most of `data.py`. `test_select_params_...` checks only that later data has no effect, and
  `test_live_targets_equal_backtest_row` compares a shared helper with itself.
- Also weak: `test_broker_is_hardcoded_to_paper` only searches source text. `test_dry_run...` and the other
  end-to-end tests use `symbol_groups` all "software" and a rising benchmark, so no cap or sell-off rule ever fires.
- Checked now: with `alpaca-py 0.45.0` and a fake transport, the adapter builds a correct CLS market order, accepts
  the paper URL, returns the right previous session and sends a valid `orders_since` request. So these are missing
  tests, not known bugs.
- Fix: first a fake-client test of `AlpacaPaperBroker` (CLS, side, `last_equity`, cutoff, previous session), then
  `run()` tests for risk caps, partial submit failure and partial bar, then costs-on for `simulate`.

### 6. A data failure stops the kill switch
- Where: `live.py:182-200` (data load before the check), `trend_live.py:97-117`. **Verified.**
- Scenario: Yahoo is down or QQQ data is more than 5 days old while equity is 40% below peak. The run raises or
  returns before `ks.update`; nothing is sold. The kill switch only needs the broker's equity. This works against
  rule 4. In `trend_live.py:106-109` a stray position also returns before the check.
- Fix: read equity and positions and run the kill switch (and liquidation) first, then load prices. The trend flag
  is unused by the hard stop.

### 7. `compare.py` fill slippage will be wrong or empty
- Where: `compare.py:148`, `compare.py:57-61`, `RUNBOOK.md:160-161`. **Verified.**
- Scenario A: prices are cached under a key made from the set of filled symbols and are never refreshed. Daily runs
  refresh other keys. A later fill on the same set shows `close = NaN` for good and drops out of the mean. RUNBOOK says
  a later daily run fixes it; that is false for momentum (true for QQQ, which shares the runner's cache).
- Scenario B: the reference is the dividend- and split-adjusted close. A 0.15% dividend after the fill reads as 15 bps
  of slippage (the assumption is 5); a 10:1 split reads as 90,000 bps.
- Fix: fetch unadjusted closes (or Alpaca daily bars) with `refresh=True` for this table. Not needed for the 12-01
  submit; needed before the first weekly compare.

### 8. Short or truncated QQQ history means "invest"
- Where: `risk.py:63`, `trend_live.py:97-102`, `live.py:184-189`. **Verified.**
- Scenario: with fewer than 200 bars the trend rule answers "above trend". 60 bars of a falling QQQ produced a
  980-share buy. A truncated Yahoo reply would do this silently, and momentum's sell-off rule would be off the same way.
  Two agents rated this their top item; that Yahoo would truncate a reply this way is plausible, not observed.
- Fix: in both runners, abort with an alert when `len(bench) < trend_window`. Leave the backtest as it is.

## Medium

Numbers are stable references, so they are not consecutive within a severity.

9. **A failed download overwrites a good cache, and retries can be thrown away.** `data.py:55-67`, `data.py:82-84`.
   **Verified:** a total failure left 0 rows in the cache; when the first call returned nothing and the retry returned
   data, the result still had 0 rows (reindexed to the empty first index). Live aborts loudly, but `backtest.py`,
   `report.py`, `compare.py` and `analysis/` read the damaged file. Fix: raise, and do not write, when the result is
   empty or shorter than the file it replaces; build the index from the retry too.
10. **`live.py` does not check it is on the right account.** `live.py:236`. **Verified:** pointed at an account holding
    QQQ it sells all of it. Only `trend_live.py` has guards (stray positions, equal keys). Fix: abort if QQQ (or any
    symbol outside the universe's history) is held.
11. **Kill-switch reset works when nothing was killed.** `live.py:261-267`, `trend_live.py:158-166`. **Verified:** reset
    at -20% moves the peak down; a further -20% (-36% from the true peak) does not fire. Fix: refuse unless
    `ks.killed`, and log the old peak.
12. **Losing the state file silently re-arms and re-buys.** `live.py:94-102`, `trend_live.py:64-72`. **Verified:** killed,
    file deleted, next run bought again. A half-written file (`write_text` is not atomic) crashes before anything is
    logged (**Verified**). Fix: write to a temp file and `os.replace`; alert when state is missing but the account
    has positions or past orders.
13. **Unfilled and partly filled orders vanish from the comparison.** `live.py:134`, `compare.py:53-55,123,134`.
    **Verified:** a partial fill that ends `canceled` is not counted in fills, slippage or the start date. Fix: count
    any event with `filled_qty > 0`.
14. **Equity is filed under the price bar's date, not the equity's date.** `compare.py:41`, `live.py:192`. **Verified:**
    if Yahoo lags a day on a no-rebalance run (no session check there), today's equity overwrites the earlier day's.
    Fix: log the broker's previous session date and key on it.
15. **The shadow backtests can differ from live for reasons that are not tracking error.** `compare.py:65-103`.
    The trend shadow has no kill switch although the docstring says it mirrors the live runner (**Verified**: it sits at
    -36% where live would be in cash after -25%). Neither shadow replays a manual reset. If the cache ends before the
    first fill, both frames come back empty with no message (**Verified**). `previous_month_end` can return `None`
    and crash at line 72 (**Code**).
16. **Index membership goes stale without any warning.** `universe.py:140-150`; `refresh=True` refreshes prices only.
    The newest change in the CSV is 2026-10-09. The annual Nasdaq-100 change usually takes effect in late December, so
    the January rebalance could use an old list. **Code.** Fix: RUNBOOK step to bump `SOURCE_COMMIT` and refresh before
    the January rebalance; alert if the newest change is older than N months.
25. The high-water mark only includes days the runner ran (`live.py:196-197`). A peak on a skipped day
    is never seen, so the kill fires late. **Code.** Fix: say "run daily" is required, alert when `last_kill_check` is
    older than the previous session.
29. The `KILL SWITCH` alert is raised only on the run that trips it (`live.py:196-207`,
    `trend_live.py:112-123`). If that is the dry run, the `--submit` run sells with only `order_submitted` lines, and
    while positions remain not even `killed` is logged. **Code**; reproduced by the silent-failure agent. Fix: alert on
    every run while `ks.killed`.
32. `broker.py:45,69`: no request timeout was set, so a hung call could run past the cutoff. alpaca-py retries a 504
    on the order POST, so an accepted order may be reported as failed. The retry codes `[429, 504]` are confirmed in
    the installed library; the outcome is **Plausible**.
34. **A partly filled trend entry is never topped up.** `trend_live.py:57-59`. Any QQQ holding counts as "invested":
    with 10 of 98 shares held and the signal on, no order is planned until the trend flips. **Verified** for the
    planning; that a closing-auction order can end partly filled is **Plausible**.
35. **The head-to-head comparison starts too early.** `compare.py:153,173-174`. `report_strategy` returns all logged
    equity, including dry-run days before the first fill, so the table starts at the first common run, not "since the
    later start". **Verified** (first fill 12-01, series starts 11-24). Fix: return `equity.loc[start:]` (keep the
    earlier value for the shadow's starting equity).

## Low

17. `live.py:215-218`: an aborted run exits with status 0; only the printed alert shows it. **Verified.**
18. `live.py:85-89`: liquidation skips short positions; `ceil` on a fractional holding sells more than held
    (`live.py:79`). The bot creates neither. **Code.**
19. `live.py:184`: the benchmark's last date is not checked. A QQQ series missing the signal day raises a bare
    `KeyError` (**Verified**); one that has the signal day but misses later bars is used silently by the kill-switch
    trend input (**Code**; harmless under the hard stop). Fix: abort if `bench.index[-1] != last_bar`.
20. `risk.py:121`: equity 0 on the first run fires the kill switch (**Verified**). Only matters for an unfunded account.
21. `report.py:139-156`: "today's picks" ranks the latest bar, not the month-end signal live trading uses, with its own
    copy of the trend rule (also ignores the kill switch, already known). **Code.**
22. `walkforward.py:76-81`: if every train score is NaN, `select_params` returns `None` and fails later. **Code.**
23. `backtest.py:156,170`, `report.py:97`: years `2022` / `2026` are hard-coded; stale in 2027. **Code.**
24. Lean: `analysis/common.completed_bars` (local time zone) duplicates `data.finished_bars` (New York) and is now
    redundant; `live.py` and `trend_live.py` carry identical copies of the kill-switch state helpers and `save_state`;
    `data.py:11-19` comment says the static list should be replaced by point-in-time membership, which is done.
26. `live.py:129-136`: fills are logged only by a later run that looks back 7 days. After a longer gap they are never
    logged. `compare.py:131` tells you to run `--submit` when the real need is one more run after the fill. **Code.**
27. No input checks on `OrderRequest` (any `side` other than `"buy"` becomes a sell, `broker.py:65`) or on
    `RiskLimits.group_caps` (a mistyped group name caps nothing). All current callers are correct. **Code.**
28. State and account are not linked: swapped keys apply one account's peak and kill flag to the other (see 10).
    The trend `account` event is logged before the stray-position abort, so a wrong account's equity enters
    `compare.py` (see 14). **Code.**
30. `live.py:129`: `done_for_day` is treated as final, so a fill reported after it is never logged (reproduced by the
    silent-failure agent with a fake; whether Alpaca sends this status for these orders is **Plausible**).
31. `live.py:143-145`: if the broker calendar returns no earlier session, the freshness check passes. A month-end row
    missing for all tickers would make an earlier day the signal day without notice. **Plausible.**
33. `analysis/earnings.py:29-49`: a partial earnings download is cached for good; `backtest.align_rf` forward-fills a
    never-refreshed T-bill cache. **Code.**
36. The runbook gives only normal-day times. 2026-11-27 closes at 13:00 ET (the code handles early closes through the
    broker clock; the document does not mention them). The date is from CodeRabbit and was not checked against a
    calendar here. State the target as "25 minutes before the close".
37. `analysis/universe_compare.py:65-70`: coverage is measured on forward-filled prices, so a gap after a name's first
    price would count as priced. No such gap exists in the current cache. Line 49 also aligns only the start date of
    the two universes, not the end. **Code.**
38. `analysis/common.py:61`: the QQQ buy-and-hold reference carries no entry cost (about 0.1% once), strictly against
    rule 2. **Code.**
39. `compare.py:72-74`: for a mid-month first trade the shadow takes the trend state of the day before the trade, while
    `live.py:228` takes it from the month-end signal day. **Code.**

## Documentation vs code

| Document | Says | Reality |
|---|---|---|
| `CLAUDE.md` Status | 76 tests pass | 81 pass |
| `CLAUDE.md` Commands | Python 3.10-3.11 | pinned pandas 3.1.1, numpy 2.4.6, vectorbt 1.2.1 need >= 3.11 |
| `CLAUDE.md` Commands | walk-forward writes `walkforward_oos.png` | writes `walkforward_oos_<universe>.png` |
| `README.md:46` | excess Sharpe ~0.72 vs QQQ ~0.79 | 0.70 vs 0.78 on current data |
| `README.md:8-21` | file tree | omits `trend_live.py`, `report.py`, `analysis/`, `RUNBOOK.md`, `DECISIONS.md` |
| `README.md:13` | position/semis caps | also a 35% hardware cap |
| `README.md:33-41` | how to use | no mention of the trend runner or `RUNBOOK.md` |
| `RUNBOOK.md:40` | read planned orders in the output | not printed (finding 1) |
| `RUNBOOK.md:44` | momentum plans orders on the first trading day of a month | any run until the month is recorded (finding 4) |
| `RUNBOOK.md:66` | quiet days log `no_rebalance`/`no_orders` "and nothing else" | also `run_start`, `account`, `signal` (trend), fills, `run_end` |
| `RUNBOOK.md:90` | `signal` only on rebalance days | `trend_live.py:131` logs it on normal days |
| `RUNBOOK.md:104-130` | alert list | missing `no price data before this month` and `unexpected positions in the trend account` |
| `RUNBOOK.md:160` | later daily run refreshes fill closes | false for momentum (finding 7) |
| `live.py:15` | rebalances on the first run of a new month | on every run until a submission succeeds |
| `RUNBOOK.md:43-45` | trend plans orders only when QQQ crosses the average | whenever wanted state differs from holdings (first entry, retry, kill sale) |
| `RUNBOOK.md:121-122` | may wait for the next rebalance | a later `--submit` that month still trades (finding 4) |
| `RUNBOOK.md:134-136`, `live.py:14` | the kill run sells, then logs `killed` daily | only `--submit` before the cutoff sells; `killed` is logged only once flat; "Liquidating" prints on dry runs too |
| `RUNBOOK.md:129` | read the traceback in the `error` line | the line holds only `repr(e)`; the traceback is only in the terminal |
| `RUNBOOK.md:93` | `no_orders` = already at target | trend also uses it for "already submitted today" |
| `RUNBOOK.md:74-75` | 15:35 appears in the `trend_live.py` header | it does not |
| `RUNBOOK.md:148`, `live.py:8` | reset at current equity | previous-close equity |
| `compare.py:7` | "5 bps + 5 bps fees" | 5 bps slippage + 5 bps fees |
| `risk.py:103` | kill switch has cooldown and trend re-arm | default is a manual-reset hard stop |
| `trend_live.py:3` | holds 100% QQQ | 98% target |
| `data.py:75` | T-bill rate only for reporting and scoring | also the cash return in `analysis/qqq_trend.py` |
| `broker.py:22` | re-run cannot double-submit | unverified; RUNBOOK says so |
| `broker.py:72` | cutoff ~15:50 ET | code refuses after 15:45 (RUNBOOK already notes this) |
| `broker.py:5` | keys `ALPACA_API_KEY/SECRET` | also the `ALPACA_TREND_*` pair |
| `compare.py:14` | trend shadow mirrors the live runner | no kill switch (finding 15) |
| `data.py:11-14` | static list to be replaced | already replaced; static is comparison only |

Reproduced and matching: all `$100k` figures, CAGR, drawdown, excess Sharpe, alpha t=0.33 and beta 1.43, bootstrap
intervals, cost stress, full-vs-tech universe, vol scaling, earnings (including "about 20% of held earnings days move
>10%": 20.1% of 412), distribution days, parameter plateau, both walk-forward runs, 9.9% / 15.6% missing member days,
5 kills when re-armed, the $3.25M peak on 2026-06-22 and -55% after it, NVDA +31.5% on 11-23, the 80-row ledger sum,
and 45 tracked files.

Not checkable here: the Alpaca daily-bar match, GitHub repo privacy, the two account numbers, and DECISIONS items it
marks "not re-run".

## Security

- Git history on all refs: no file such as `.env` was ever committed; a pattern search for key, token and private-key
  shapes found nothing. This is a pattern search, not a dedicated secret scanner.
- Keys are read from environment variables only. No code path logs them. `paper=True` is hard-coded and the base URL
  is checked.
- `universe.py` downloads from a pinned commit and parses with `yaml.BaseLoader` (safe).
- `.claude/settings.json` enables a third-party plugin marketplace (`DietrichGebert/ponytail`) for anyone who opens the
  repo and accepts it. It is not pinned to a version. Your call whether that belongs in the repo.
- No dependency vulnerability scan (needs `pip-audit`, not installed).

## Checked and found sound

Signal timing (month-end close, traded next close) matches between backtest and live; today's unfinished bar is
dropped; trend state is taken on the signal day in both; the kill switch acts at the next close; point-in-time
membership intervals are `[start, end)`; costs are applied in every research path; walk-forward selects on train windows
only and starts each test window on a rebalance row; Newey-West and block bootstrap code; the risk loop's equity is
within 0.13% of vectorbt's.

## Tools: what ran and what it could not cover

| Tool | Result | Limits |
|---|---|---|
| `pytest` | 81 passed | see finding 5 |
| Own mutation check (38 mutations) | 32 survived | hand-picked, not exhaustive |
| Research scripts on a temp copy | all ran, numbers match | cached data only, not refreshed |
| Pyright 1.1.414 | 195 errors | mostly missing pandas / alpaca type information; the real ones are in findings 15 and 22 |
| `/ponytail-audit` | applied to the whole repo; results merged above | same reader as this report, not independent |
| `/code-review` on the seven live-path files | done inline | no separate verifier pass |
| `code-reviewer` agent | completed, 8 findings, all matching items above (3, 7, 9, 13, 18, 6, 21, known sizing) | only skimmed tests and some analysis scripts |
| `pr-test-analyzer` agent | completed after the limit reset; merged into 5 and 19 | skipped `report.py`, most analysis scripts |
| `comment-analyzer` agent | completed; merged into 4, 26 and the table | static; skimmed `DECISIONS.md` and the CSVs |
| `type-design-analyzer` agent | completed; merged into 25-28 and earlier items | traced in code, nothing run |
| `silent-failure-hunter` agent | completed after the limit reset; merged into 8, 12 and 29-33 | did not read `walkforward.py`, `report.py`, tests in full |
| CodeRabbit CLI | three attempts ended `WebSocket closed`; the retry after the limit reset **completed** with 14 findings, over the diff from the first commit to `main` | not in its reviewed list: `.gitignore`, `pytest.ini`, `requirements.txt`, `test_backtest.py`, `test_trend_live.py`, `test_walkforward.py`, the CSVs |
| `/security-review` | not run (only covers pending changes); done by reading | |
| ruff, pytest-cov, vulture, pip-audit | not installed, not run | no coverage percentage, dead-code or CVE scan |

Nothing was tested against Alpaca itself: duplicate order IDs, how paper accounts fill closing-auction orders,
buying-power checks, and the real cutoff.

### CodeRabbit findings, checked one by one

| CodeRabbit item | Verdict |
|---|---|
| Does a killed run retry a rejected liquidation? | No bug: both runners re-send `-kill` orders on each `--submit` while positions remain. The runbook wording is wrong (table above) |
| Kill switch needs market data (`trend_live.py`) | Real, finding 6 |
| Partial trend fill never topped up | Real, finding 34 |
| Local date in `analysis/common.completed_bars` | Real, finding 24 |
| Early-close schedule | Documentation gap, finding 36 |
| QQQ reference without costs | Real, immaterial, finding 38 |
| Partial earnings download cached | Real, finding 33 |
| Coverage on forward-filled prices; end dates not aligned | Real in code, no effect on current data, finding 37 |
| Head-to-head includes pre-trade days | Real, finding 35 |
| Shadow trend date on first order | Real, finding 39 |
| Slippage against adjusted closes | Real, finding 7 |
| Trend shadow has no kill switch | Real, finding 15 |
| Trend equity keyed to the quote date | Real, findings 14 and 28 |

None described code that does not exist. New to this audit: 34-39; the rest repeat earlier items.

## File coverage

All read in full by the main reviewer.

- [x] Live path: `live.py`, `trend_live.py`, `broker.py`, `risk.py`, `data.py`, `compare.py`
- [x] Research: `signals.py`, `backtest.py`, `walkforward.py`, `universe.py`, `report.py`
- [x] `analysis/`: `__init__.py` (empty), `common.py`, `cost_stress.py`, `distribution.py`, `earnings.py`,
  `edge_test.py`, `param_plateau.py`, `qqq_trend.py`, `universe_compare.py`, `vol_scaling.py`
- [x] `tests/`: `test_analysis.py`, `test_backtest.py`, `test_compare.py`, `test_data.py`, `test_live.py`,
  `test_lookahead.py`, `test_param_plateau.py`, `test_risk.py`, `test_signals.py`, `test_trend_live.py`,
  `test_universe.py`, `test_walkforward.py`
- [x] Docs: `CLAUDE.md`, `AGENTS.md`, `README.md`, `RUNBOOK.md`, `DECISIONS.md`
- [x] Config: `requirements.txt`, `pytest.ini`, `pyrightconfig.json`, `.gitignore`, `.claude/settings.json`
- [x] `AGENTS.md` matches `CLAUDE.md` and `RUNBOOK.md`; no mismatch found
- [~] `universe_data/ndx_membership.csv`, `ndx_sector_map.csv`: checked by script (duplicates, alias conflicts,
  categories, current members), last rows read; not read row by row, and not checked against Nasdaq announcements
