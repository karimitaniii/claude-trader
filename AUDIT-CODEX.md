# Independent review of AUDIT.md

Review context: 2026-11-26. Saved as `AUDIT-CODEX.md` on 2026-11-27.

Scope: Claude Code's `AUDIT.md`, checked against commit
`9e8238853717a33b06207c2459658ac2e94868b5` in `karimitaniii/claude-trader`.
This document preserves the findings and qualifications presented in the chat; saving it did not constitute a new audit.

## Overall assessment

The audit is **mostly correct about the code, but its assurances are too broad and its pre-launch checklist is incomplete**.
Kill-switch independence, data validation, and order recovery should take priority before the first paper orders.

The tracked Python files matched the audited commit. `AUDIT.md` was untracked, and `CLAUDE.md` had subsequent local additions,
so its committed version was also read. All source line references below refer to the audited commit unless identified as
installed SDK code. They are plain file-and-line references so the document remains portable.

The review changed no files, read no API keys, and ran no broker or submission commands. Validation consisted of source
review and selected in-memory checks. Pytest, mutation testing, and research scripts were **not** rerun; their reported
results remain independently unverified. This Markdown file was subsequently created at the user's request.

“Correct” below means the behavior follows from the code—not that Claude's exact reproduction was independently repeated.

## Finding-by-finding review

### 1. Dry-run orders are hidden from terminal output — Correct

`submit_all` includes the orders in the log record, but the printer explicitly excludes `orders` and `targets`.

Evidence: `live.py:111`, `live.py:155`.

### 2. Successful submission completes the month before fills — Correct

Later rejected or expired orders generate alerts but never clear the month marker. The suggested manual recovery needs
stronger precautions: reconcile outstanding orders and actual positions first. Clearing the marker recalculates the
entire portfolio.

Evidence: `live.py:133`, `live.py:237`.

### 3. A persistent submission failure permits daily resizing — Correct

One exception makes the batch unsuccessful; the next run recomputes every target quantity. Same-day attempts reuse IDs.
Alpaca now explicitly documents rejection of duplicate client IDs, so duplicate acceptance is not the expected behavior.
The bot still lacks reconciliation.

Evidence: `live.py:162`, `live.py:236`;
[Alpaca Trading CLI documentation](https://docs.alpaca.markets/us/docs/alpacas-cli).

### 4. An earlier submission can rebalance November — Correct, conditional on state and cutoff

There is no first-trading-day restriction. The audit's specific claim about the existing state file cannot be established
from the commit, because state is not versioned.

Evidence: `live.py:209`, `live.py:215`.

### 5. Tests do not protect the live order path — Overstated

There are serious test gaps, but several supporting statements are wrong:

- The momentum fixture selects three names, so their one-third weights **do trigger the 15% position cap**. The tests
  simply fail to assert the resulting quantities.
- The shared-helper comparison tests some timing/integration behavior. It is not literally a helper compared with itself,
  although it cannot independently establish ranking correctness.
- A trend `main()` flag/account guard test does exist.
- The precise “32 of 38 mutations survived” result is **unverifiable without the mutations and execution evidence**.

The missing real-adapter and failure-path coverage remains a valid concern.

Evidence: `tests/test_live.py:87`, `tests/test_live.py:34`, `tests/test_trend_live.py:108`.

### 6. Market-data failure can prevent kill-switch evaluation and liquidation — Correct

Both runners load prices first. The trend stray-position guard also precedes the kill check, although blindly liquidating
a possibly wrong account would not be an appropriate fix.

Evidence: `live.py:182`, `trend_live.py:97`.

### 7. Fill slippage can be missing or distorted — Correct

Fill-symbol caches generally differ from the momentum universe cache, and comparison does not refresh them.
Split/dividend-adjusted historical prices are unsuitable references for historical execution prices.

Evidence: `compare.py:148`, `compare.py:61`, `data.py:55`.

### 8. Insufficient QQQ history permits investment — Correct

An independent in-memory check confirmed that 60 falling observations produce `True`. Checking length alone is
insufficient: missing observations can also produce an unavailable moving average and therefore `True`.

Evidence: `risk.py:62`.

### 9. Failed refreshes can destroy usable caches and discard successful retries — Correct

Retries are aligned to the original index; an empty original index stays empty. Both price and rate caches can be
overwritten without a completeness check. A blanket “reject shorter files” remedy would need to accommodate legitimate
data corrections.

Evidence: `data.py:55`, `data.py:82`.

### 10. Momentum has no account-identity guard — Correct

Holdings absent from its targets are sold, including QQQ. Checking holdings would help, but cannot identify the wrong
account when it is empty or holds plausible universe names.

Evidence: `live.py:67`, `broker.py:51`.

### 11. Reset can lower an active high-water mark — Correct

An independent check confirmed that 100 → reset at 80 → 64 does not trigger. This requires explicit operator misuse of
the reset command; it is not an automatic loss of protection.

Evidence: `live.py:261`, `risk.py:126`.

### 12. Missing state starts afresh; malformed state fails before normal logging — Correct

Atomic writing would address interrupted writes, but not deletion, wrong-account state, or concurrent writers.

Evidence: `live.py:94`, `live.py:176`, `trend_live.py:64`.

### 13. Terminal partial fills are excluded from execution comparisons — Correct

They remain visible as `order_final` events and alerts, so “vanish” means from fill statistics and start-date detection,
not from all logs.

Evidence: `live.py:134`, `compare.py:123`.

### 14. Equity is assigned the market-data date — Correct

The broker returns previous-close equity independently of Yahoo's last bar. Stale data can therefore misdate or overwrite
observations.

Evidence: `broker.py:51`, `live.py:192`, `compare.py:41`.

### 15. Shadows do not fully reproduce live operation — Correct

The trend shadow has no kill switch; neither shadow replays manual resets. Missing overlap produces an empty comparison,
and an absent previous-month signal date is unhandled.

Evidence: `compare.py:65`, `compare.py:88`, `compare.py:138`.

### 16. Membership never automatically refreshes — Correct

The CSV's latest change was independently confirmed as October 9, 2026. That does not itself prove membership is already
wrong: the age of the last membership change is not the same as the age of the last verification.

Evidence: `universe.py:80`, `universe.py:146`.

### 17. Ordinary aborts return success to the shell — Correct

Exceptions are re-raised, but alert-and-return branches produce no unsuccessful exit status.

Evidence: `live.py:215`, `live.py:269`.

### 18. Liquidation ignores shorts and rounds fractional longs upward — Correct

An independent check confirmed that 0.2 shares becomes a one-share sell. Whether Alpaca rejects or otherwise handles that
order is external behavior, not established here.

Evidence: `live.py:79`, `live.py:85`.

### 19. Momentum does not validate benchmark freshness — Correct, but incomplete

Missing the signal-date index raises; missing later observations can be irrelevant to the default hard stop. More
importantly, an index-date check alone would not detect stale values hidden by forward-filling.

Evidence: `live.py:184`, `live.py:228`.

### 20. Zero initial equity triggers the kill switch — Correct

Independently confirmed. This is conservative behavior for an unfunded account, not a material launch defect for a funded
account.

Evidence: `risk.py:120`.

### 21. “Today's picks” are not the live order plan — Correct

They use the latest bar, an independently implemented trend comparison, and no persisted kill state.

Evidence: `report.py:138`.

### 22. All-NaN training scores return None — Correct

The later dictionary lookup cannot use that as a valid parameter selection.

Evidence: `walkforward.py:76`, `walkforward.py:125`.

### 23. Hard-coded years become stale — Overstated

The 2026 YTD labels become stale; the 2022 stress period does not. Keeping a named historical drawdown year is legitimate.
Calling 2026 “YTD” in 2027 would be misleading.

Evidence: `backtest.py:155`, `report.py:97`.

### 24. Duplicated helpers and stale commentary exist — Correct in substance

The local-time helper differs from the New York helper. “Redundant” is too absolute because cached reads bypass
`finished_bars`.

Evidence: `analysis/common.py:26`, `data.py:50`, `data.py:11`.

### 25. Skipped days can hide equity peaks — Correct

Only the equity observed during each run updates the high-water mark.

Evidence: `live.py:190`, `live.py:197`.

### 26. The seven-day polling window loses older order history — Correct

“Run submit first” is also misleading when orders already filled but have not yet been polled.

Evidence: `live.py:130`, `compare.py:131`.

### 27. Input validation is incomplete — Correct

Unknown sides become sells; misspelled group names silently cap nothing. Existing callers do not demonstrate an actual
current misconfiguration.

Evidence: `broker.py:65`, `risk.py:83`.

### 28. Account and state are not bound together — Correct

The trend account event also precedes its stray-position abort, contaminating comparison data if the wrong account is
supplied.

Evidence: `live.py:115`, `trend_live.py:103`.

### 29. The prominent kill alert occurs only on transition — Correct

While positions remain, subsequent runs attempt liquidation without repeating that alert or emitting `killed`.

Evidence: `live.py:196`, `trend_live.py:112`.

### 30. done_for_day suppresses future updates — Correct as a conditional code defect

Once its client ID is recorded, a subsequent filled status is ignored. Whether this occurs for these paper CLS orders
remains unverified.

Evidence: `live.py:129`.

### 31. Calendar failure permits freshness validation to pass — Correct

Separately, selecting the last available pre-month row does not establish that the actual month-end session exists.
A valid latest session would not catch a missing historical month-end row.

Evidence: `live.py:143`, `live.py:57`.

### 32. Missing timeout and retry ambiguity — Correct about implementation; consequences conditional

The installed SDK supplies no request timeout in this path and retries 429/504 responses. A timeout/retry can create
uncertainty about whether an order was accepted.

Evidence: `broker.py:69`; installed SDK
`.venv/lib/python3.11/site-packages/alpaca/common/rest.py:198` and
`.venv/lib/python3.11/site-packages/alpaca/common/constants.py:13`.

### 33. Incomplete earnings data and stale rates persist by default — Correct

Explicit refresh parameters exist; the normal callers do not use them. Earnings exceptions actually print the symbol and
exception type, contrary to the separate documentation claim that failures are always silent.

Evidence: `analysis/earnings.py:29`, `data.py:79`, `backtest.py:49`.

### 34. Any positive QQQ holding suppresses a top-up — Correct

Actual partial CLS execution remains an external contingency; the planning behavior is explicit.

Evidence: `trend_live.py:57`.

### 35. Head-to-head results include pre-trade observations — Correct

`report_strategy` returns the untrimmed series.

Evidence: `compare.py:153`, `compare.py:174`.

### 36. The runbook omits early-close timing — Correct

November 27, 2026 closes at 13:00 ET, independently confirmed against the exchange calendar. The code derives its cutoff
from the broker clock.

Evidence: `RUNBOOK.md:70`, `broker.py:76`;
[NYSE calendar](https://www.nyse.com/trade/hours-calendars).

### 37. Coverage uses forward-filled prices and only start dates are aligned — Correct about code

The additional assurance that no relevant gaps exist in the current caches was not independently reproduced.

Evidence: `analysis/universe_compare.py:38`, `analysis/universe_compare.py:65`.

### 38. The QQQ reference omits execution costs — Correct

This directly contradicts the audit's later statement that costs are applied in every research path.

Evidence: `analysis/common.py:61`.

### 39. A mid-month shadow entry can use a different trend state — Correct

The shadow inserts the previous-month selection on the start date, then the risk loop uses the immediately preceding
session's trend. Live uses the month-end signal's trend.

Evidence: `compare.py:72`, `risk.py:172`, `live.py:228`.

## Important omissions or insufficiently developed findings

### Order-history failure also blocks the kill switch

Both runners poll order updates before evaluating risk. Moving risk ahead of Yahoo downloads alone would leave this
dependency intact.

Evidence: `live.py:180`, `trend_live.py:96`.

### The cutoff is checked once for the whole batch

A slow first submission can allow subsequent orders to be attempted beyond the local cutoff. Timeouts alone would not
fix this; the deadline must also be checked between submissions.

Evidence: `live.py:157`.

### Order submission and local state persistence are not recoverable as one operation

If the process stops after broker acceptance but before saving, the next run has no durable state record of that accepted
batch. Order polling records terminal outcomes but does not reconstruct submission state. This is another route into
findings 2–3, even without a normally reported partial failure.

Evidence: `live.py:164`, `live.py:244`.

### The audit overstates successful liquidation retries

The runners attempt them again, but same-day attempts reuse the same `-kill` ID. Given documented duplicate-ID rejection,
a new attempt is not necessarily a new accepted liquidation. The recovery procedure must distinguish an existing pending
order from a terminal failure.

Evidence: `live.py:85`;
[Alpaca documentation](https://docs.alpaca.markets/us/docs/alpacas-cli).

### The proposed QQQ checks do not cover missing values

An independent check confirmed that even 200 rows can return “invest” when insufficient valid observations make the moving
average unavailable. Forward-filling can additionally conceal stale observations. Validate actual observation coverage,
not just length and final index.

Evidence: `risk.py:62`, `trend_live.py:97`.

### A displayed dry-run plan is not bound to the subsequent submission

Submission refreshes prices, rereads holdings and equity, and replans. Printing orders fixes visibility, but does not
guarantee that the reviewed quantities are the ones submitted.

Evidence: `live.py:182`, `live.py:236`.

### Cost omissions extend beyond finding 38

Main-backtest and walk-forward QQQ references also use plain price returns. The earnings exit counterfactual explicitly
omits additional exit/re-entry costs. These qualify the audit's blanket “costs everywhere” assurance.

Evidence: `backtest.py:105`, `walkforward.py:140`, `analysis/earnings.py:8`.

## Documentation, stale information, and limits of verification

The documentation discrepancy list is otherwise substantially accurate, with these qualifications:

- There are **81 test functions**, independently counted; “81 passed” remains an unverified execution claim. Installed
  package metadata confirms the pinned pandas, NumPy and vectorbt require Python ≥3.11.
- The README's older figures differ from the newer recorded figures, but that does not independently reproduce either
  set. Its omissions, the walk-forward filename correction, and the operational logging/reset discrepancies are supported
  by the code.
- “May wait for the next rebalance” is ambiguous advice, not logically false: waiting until the next month is possible.
  The missing explanation is that submitting later **within the current month** still triggers its rebalance.
- Alpaca's duplicate-ID behavior is now documented, although still not tested against these accounts.
- “Earnings errors are silent” is already outdated for exceptions; they are printed. Empty responses can still be skipped
  silently. Evidence: `analysis/earnings.py:37`.
- The audit's tool-run history, mutation counts, full numerical reproductions, clean-secret-history claim, account
  separation and broker-bar comparisons remain **unverifiable from this review**. History was deliberately not searched
  for secret values. The paper-only constructor and safe YAML loader are supported by source.
  Evidence: `broker.py:45`, `universe.py:73`.

## December 1 forecast

The forecast needs qualification. The local cached November 25 QQQ close and moving average match **633.93 and 682.54**.
If the November 30 signal remains below trend, momentum is capped at **at most 50% target gross**, with whole-share rounding
reducing actual exposure. The November 25 picks and their exact weights are not December 1 commitments. Trend plans no
order only if its account remains flat and the signal remains off.

Evidence: `risk.py:90`, `live.py:215`, `trend_live.py:57`.

## Assessment of “Must do before 2026-12-01”

Retain the audit's four items, but **do not treat completing them as sufficient**:

1. Make the planned orders reviewable.
2. Establish recovery for accepted, rejected, partial, pending and uncertain orders—including interruption after acceptance.
3. Correct the month-trigger and early-close instructions.
4. Test the real adapter with a fake transport and assert cutoff refusal.
5. Promote **kill-switch independence from data and order-history polling** into the must-do list.
6. Promote **valid, fresh QQQ history checks** into the must-do list.
7. Verify the intended paper-account/state pairing, preserve state, and make an active kill unmistakable.
8. Include failure-path assertions for these behaviors; one adapter test alone is insufficient.

The comparison fixes can follow before the first weekly review. Research reporting and cosmetic documentation repairs
should not displace those operational protections.
