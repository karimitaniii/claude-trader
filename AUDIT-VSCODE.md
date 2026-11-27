# Independent review of `AUDIT.md`

Reviewed against commit `9e8238853717a33b06207c2459658ac2e94868b5` on `main`, dated 2026-11-26.
The current checkout has the same tracked tree as that commit. The user-requested review did not
change code, run tests or trading scripts, contact Alpaca, or read API keys.

## What this repo does

This repository runs two deterministic paper-trading strategies: monthly tech-stock momentum and a
QQQ 200-day trend rule. It includes a risk layer, Alpaca paper-order wrappers, logs, backtests, and
research scripts. I assumed one person runs each daily script by hand on one Mac.

## Overall assessment

The audit is broadly reliable. I found no numbered finding that is wholly wrong, but some findings
need qualification. The most important operational issue is that both runners load market data
before checking the kill switch, so a data failure can prevent liquidation.

## High

1. **Correct — dry-run output hides planned orders.** The JSONL event includes orders, but terminal
   logging omits them; the runbook asks the user to confirm ticker, side, and quantity from output.
   ([live.py:105](./live.py#L105), [live.py:155](./live.py#L155), [RUNBOOK.md:40](./RUNBOOK.md#L40))

2. **Correct — accepted orders count as a completed monthly rebalance.** The month is recorded
   after submission succeeds, not after orders fill. Later canceled or rejected orders do not
   automatically reopen that rebalance.
   ([live.py:128](./live.py#L128), [live.py:238](./live.py#L238), [RUNBOOK.md:116](./RUNBOOK.md#L116))

3. **Overstated in wording; retry risk is real.** A failed batch leaves the month unrecorded, so a
   later submission recalculates orders using current positions. This can repeat attempts or cause
   small top-ups, but does not necessarily resize every holding. Whether Alpaca rejects a repeated
   client order ID was not verified.
   ([live.py:150](./live.py#L150), [live.py:238](./live.py#L238), [broker.py:22](./broker.py#L22))

4. **Correct, conditional on state.** If the month has no recorded rebalance, a submit on any date
   that month can trade from the previous month-end signal. The audit's cited local
   `last_rebalance_month: null` is runtime state and is not included in the audited commit.
   ([live.py:210](./live.py#L210), [live.py:215](./live.py#L215), [live.py:238](./live.py#L238))

5. **Correct that live-path test coverage is weak; mutation results not independently verified.**
   Tests cover helpers and fake-broker runs, but do not exercise the Alpaca adapter or cutoff
   refusal. I counted 81 test definitions, but did not run pytest or reproduce the claimed
   32-of-38 mutation results.
   ([test_live.py:72](./tests/test_live.py#L72), [test_live.py:106](./tests/test_live.py#L106),
   [test_trend_live.py:99](./tests/test_trend_live.py#L99))

6. **Correct and important — data failure can block the kill switch.** Both runners load market
   data before checking the switch; the trend runner also returns early for unexpected positions.
   A data failure can therefore prevent the kill check and liquidation.
   ([live.py:182](./live.py#L182), [trend_live.py:97](./trend_live.py#L97),
   [trend_live.py:107](./trend_live.py#L107))

7. **Correct — comparison slippage can be stale or misleading.** `compare.py` loads prices without
   forcing a refresh, while downloaded prices are cached and adjusted. A cached close can be
   missing/stale for a fill, and adjusted closes are not a clean reference for execution slippage.
   ([compare.py:148](./compare.py#L148), [data.py:50](./data.py#L50), [data.py:55](./data.py#L55))

8. **Correct code behavior; truncated-history scenario unverified.** With fewer than 200 QQQ bars,
   `trend_ok` treats the trend as okay. A truncated but otherwise fresh response could bypass the
   sell-off cut; I did not verify Yahoo returns such a response.
   ([risk.py:62](./risk.py#L62), [risk.py:63](./risk.py#L63), [live.py:189](./live.py#L189))

## Medium

9. **Correct — failed price downloads can damage the cache.** Retry data is reindexed to the
   original result's index. If that index is empty, the retry can be discarded; the resulting
   frame is then written to cache.
   ([data.py:64](./data.py#L64), [data.py:67](./data.py#L67))

10. **Correct — momentum does not guard against a wrong account's holdings.** Its order planner
    includes every held symbol as well as target symbols, so unrelated positions can be sold.
    ([live.py:67](./live.py#L67), [live.py:191](./live.py#L191))

11. **Correct — reset is allowed when the switch is not killed.** Reset has no guard for the
    current killed state and sets the high-water mark to current equity.
    ([live.py:261](./live.py#L261), [trend_live.py:158](./trend_live.py#L158))

12. **Correct — missing state silently creates an un-killed state.** State loading returns defaults
    when no file exists, and state writes are not atomic. Whether the next run re-buys depends on
    the account's holdings and the current signal.
    ([live.py:94](./live.py#L94), [live.py:102](./live.py#L102))

13. **Correct — partial fills ending canceled are missed by comparison.** The runner logs canceled
    orders as `order_final`, while comparison counts only `fill` events.
    ([live.py:129](./live.py#L129), [compare.py:122](./compare.py#L122))

14. **Correct — equity is keyed to the price bar date.** The account event stores equity with
    `last_bar`; on a no-rebalance path the runner can return before checking whether the latest
    price bar is the previous session.
    ([compare.py:39](./compare.py#L39), [live.py:141](./live.py#L141),
    [live.py:191](./live.py#L191))

15. **Correct — shadow comparisons do not fully mirror live behavior.** The trend shadow has no
    kill switch, neither shadow replays manual resets, and empty or misaligned shadow data can
    leave the report without a useful comparison.
    ([compare.py:78](./compare.py#L78), [compare.py:72](./compare.py#L72),
    [compare.py:136](./compare.py#L136))

16. **Correct structurally; the dates were not independently checked.** Membership is loaded from
    the CSV unless absent; refreshing prices does not refresh membership. I did not verify the
    audit's claim about the newest CSV change or Nasdaq's calendar.
    ([universe.py:80](./universe.py#L80), [universe.py:82](./universe.py#L82),
    [universe.py:132](./universe.py#L132))

25. **Correct — the high-water mark only updates when the runner checks it.** A peak on a skipped
    trading day can be missed, delaying a drawdown trigger.
    ([live.py:196](./live.py#L196), [trend_live.py:112](./trend_live.py#L112))

29. **Correct — killed-state alerts are not repeated.** The kill alert is emitted on the transition
    into killed state. Later runs with positions still held do not log the `killed` event.
    ([live.py:196](./live.py#L196), [live.py:202](./live.py#L202),
    [trend_live.py:118](./trend_live.py#L118))

32. **Plausible, not established — request timeout and retry behavior.** The wrapper sets no
    request timeout and checks the cutoff before sending the batch. I did not verify whether the
    installed Alpaca client sets its own timeout or retries orders.
    ([broker.py:60](./broker.py#L60), [broker.py:71](./broker.py#L71))

34. **Correct — partial trend entries are not topped up.** Any positive QQQ holding counts as
    invested, so the planner sends no additional buy while the desired state remains invested.
    ([trend_live.py:53](./trend_live.py#L53))

35. **Correct — head-to-head can include pre-fill days.** The strategy report returns all logged
    equity, so the first common date can precede the later strategy's first fill.
    ([compare.py:153](./compare.py#L153), [compare.py:170](./compare.py#L170))

## Low

17. **Correct — aborts can exit with status 0.** Early-return alerts do not set a failure exit
    status; exceptions are separately re-raised.
    ([live.py:215](./live.py#L215))

18. **Correct but limited to unusual account states.** Liquidation ignores non-positive positions
    and rounds positive fractional holdings up. The bot plans whole-share orders, but manual or
    external account changes could create these conditions.
    ([live.py:85](./live.py#L85))

19. **Correct — QQQ's last date is not checked against the stock bar.** Momentum validates stock
    freshness but not benchmark freshness; a missing signal-day QQQ value can fail at lookup.
    ([live.py:184](./live.py#L184), [live.py:228](./live.py#L228))

20. **Correct — zero starting equity trips the kill switch.** The first update sets peak to zero,
    then the drawdown comparison is true at zero equity.
    ([risk.py:121](./risk.py#L121))

21. **Correct — report picks are not the live signal.** The report ranks targets from the newest
    bar and calculates trend locally; it does not reflect the live monthly signal or live kill
    state.
    ([report.py:141](./report.py#L141), [report.py:143](./report.py#L143))

22. **Correct, conditional — all-NaN training scores can break selection.** If no score beats
    negative infinity, selection remains `None` and later code cannot use it as a parameter key.
    ([walkforward.py:76](./walkforward.py#L76), [walkforward.py:81](./walkforward.py#L81))

23. **Correct — report periods are hard-coded.** The year labels and `2026 YTD` statistic will
    become stale in later years.
    ([backtest.py:24](./backtest.py#L24), [backtest.py:156](./backtest.py#L156))

24. **Partly correct; “redundant” is overstated.** The analysis helper duplicates bar filtering but
    uses local time rather than New York time, so it can treat today's bar differently. The state
    helpers are duplicated, but serve separate runner state files.
    ([analysis/common.py:26](./analysis/common.py#L26), [data.py:29](./data.py#L29),
    [trend_live.py:75](./trend_live.py#L75))

26. **Correct — order updates are only queried for seven days.** A longer gap can miss an update;
    comparison also needs the fill event in the logs.
    ([live.py:128](./live.py#L128), [compare.py:131](./compare.py#L131))

27. **Correct — broker and risk inputs are not fully validated.** Any side other than `buy`
    becomes a sell, and a misspelled risk group will not match a cap. Current callers may still be
    valid.
    ([broker.py:65](./broker.py#L65), [risk.py:77](./risk.py#L77))

28. **Correct — state is not linked to account identity.** Swapping credentials can apply one
    account's stored peak and kill flag to another account. The trend check only compares its key
    to the momentum key.
    ([trend_live.py:143](./trend_live.py#L143), [live.py:248](./live.py#L248))

30. **Plausible — `done_for_day` is treated as final.** The order ID is remembered after that
    status; a later status change would be suppressed. Whether Alpaca changes these orders from
    that status was not verified.
    ([live.py:129](./live.py#L129))

31. **Plausible — an empty calendar result passes the freshness check.** The broker returns `None`
    if no earlier session is returned, and the helper treats that as not missing. I did not verify
    Alpaca returns an empty result in this situation.
    ([broker.py:81](./broker.py#L81), [live.py:141](./live.py#L141))

33. **Correct — earnings and risk-free caches can be incomplete or stale.** Earnings errors are
    skipped while a partial result can be cached; risk-free data is reused unless explicitly
    refreshed.
    ([analysis/earnings.py:37](./analysis/earnings.py#L37),
    [analysis/earnings.py:49](./analysis/earnings.py#L49), [data.py:79](./data.py#L79))

36. **Correct as a documentation gap; the date-specific example is unverified.** A fixed 15:35 ET
    target does not generalize to early closes, though the broker cutoff uses the actual close.
    ([RUNBOOK.md:74](./RUNBOOK.md#L74), [RUNBOOK.md:79](./RUNBOOK.md#L79),
    [broker.py:71](./broker.py#L71))

37. **Correct code behavior; current-cache impact not rechecked.** Coverage uses forward-filled
    prices, and the comparison aligns starts but not ends.
    ([universe_compare.py:65](./analysis/universe_compare.py#L65),
    [universe_compare.py:49](./analysis/universe_compare.py#L49))

38. **Correct and immaterial — QQQ reference omits an entry cost.** The benchmark uses raw price
    returns; it does not charge a one-time entry cost.
    ([analysis/common.py:54](./analysis/common.py#L54))

39. **Correct — mid-month shadow can use a different trend date.** The shadow risk loop uses the
    day before the trade date, while the live momentum runner uses the month-end signal-day trend.
    ([compare.py:72](./compare.py#L72), [live.py:228](./live.py#L228))

## Important points the audit missed or should emphasize

- **Promote finding 6 before any submission.** It is a safety-rule failure: a market-data problem
  can prevent the kill check and liquidation.
- **Check account identity before submitting.** Findings 10 and 28 show the risk of selling
  unrelated positions or applying the wrong stored equity peak and kill state.
- **Momentum sizing has no cash buffer.** It sizes using prior-close equity and prices, unlike the
  trend runner's 2% buffer. A price gap can cause a buying-power rejection or change realized
  exposure. ([live.py:63](./live.py#L63), [CLAUDE.md:153](./CLAUDE.md#L153))
- **Test the sells-first failure case.** Orders are sorted sells-first, but submission continues
  after a sell fails. Possible buying-power or exposure effects depend on Alpaca behavior and were
  not verified. ([live.py:150](./live.py#L150))

## Out-of-date claims and pre-December checklist

The audit's documentation findings are supported. The README still has older Sharpe figures and
omits the trend runner. The current `CLAUDE.md` says 76 tests, lists Python 3.10–3.11, and gives an
outdated walk-forward output name. The test tree contains 81 test definitions; I did not execute
them.
([README.md:46](./README.md#L46), [CLAUDE.md:45](./CLAUDE.md#L45),
[CLAUDE.md:52](./CLAUDE.md#L52), [CLAUDE.md:107](./CLAUDE.md#L107))

The audit's four-item **“Must do before 2026-12-01” list is mostly right, but incomplete**:

1. Keep the dry-run output/review fix.
2. Keep clear recovery steps for failed or unfilled orders.
3. Keep the warning that submitting before the month is recorded can trade using the previous
   month-end signal.
4. Keep a fake-client test of the adapter and cutoff refusal. Do not make a real Alpaca call or
   place an order for this test.
5. Add finding 6: the kill switch must not be bypassed by a data-loading failure.
6. Before the first submission, also prioritize QQQ history/date guards (findings 8 and 19) and
   account verification (findings 10 and 28).

State-file protection and repeated killed-state alerts are worthwhile, but secondary to those
safeguards.

## Not checked

I did not rerun backtests, mutation checks, pytest, external Alpaca behavior, the Git-history secret
scan, or calendar/source-data checks. I did not read API keys or run any submit/reset command.

**Verdict:** The audit is a useful, mostly accurate review. Before the first paper orders, add the
kill-switch data-ordering issue and stronger account and QQQ safeguards to its priority list.
