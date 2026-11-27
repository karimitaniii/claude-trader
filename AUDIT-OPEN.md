# Open audit findings, 2026-11-27

Every finding in `AUDIT.md`, `AUDIT-CC.md`, `AUDIT-CODEX.md` and `AUDIT-VSCODE.md` (all written against `9e82388`),
checked against `origin/main` = `617ad82`. Numbers `A1`-`A39` are `AUDIT.md`'s; `CC`, `CX` and `VS` mark points the
reviews added.

## How it was checked

- **R**: reproduced on 2026-11-27 on a scratch copy of `617ad82`, with fake brokers or fake downloads.
- **C**: confirmed by reading the current code or documents only.
- 191 tests pass on that copy. 37 deliberate bugs were put in one at a time: 20 caught, 17 survived (A5).
- No Alpaca call, `--submit`, reset or key access. Research scripts and backtests were **not** rerun, so no published
  number is re-verified here. Checksums of `data_cache/`, `state/` and `logs/` were unchanged.

Severity: **High** = wrong or missing orders, or a safety rule defeated, in a likely case. **Medium** = the same in a
less likely case, or wrong numbers. **Low** = small or unlikely. No open item rates High.

**12-01** column: **Yes** = can affect the first submit; **After** = affects the days or weekly review after it;
**No** = neither.

## Fix first: can affect the 12-01 submit

| # | Finding (source) | Where now | Check | Sev | 12-01 |
|---|---|---|---|---|---|
| 1 | A stock with truncated price history silently changes the picks, with no alert. Only the signal day and last bar are checked (CC missed 1). Whether Yahoo does this is unobserved | `live.py:288-292`, `universe.py:153-166`, `data.py:59-65` | R: blanking one pick's older history swapped it for another name | Medium | Yes |
| 2 | `--submit` downloads and plans again, then sends with no confirmation, so it can differ from the reviewed dry run (CC missed 2, CX). Printing and the runbook warning exist; nothing binds the two plans | `live.py:252-254, 305-309`, `trend_live.py:125, 148-153`, `RUNBOOK.md:62-63` | C | Medium | Yes |
| 3 | A month counts as rebalanced when orders are accepted; later rejected or expired orders are not retried (A2). Manual recovery is now documented | `live.py:309-310`, `RUNBOOK.md:202-204` | R: 3 rejected, nothing re-sent, month stays recorded | Medium | Yes |
| 4 | One refused order leaves the month open, so every later `--submit` re-sizes the portfolio (A3). "Do not re-submit the same day" is only a runbook rule; Alpaca's refusal of a repeated order ID is untested here (CX says Alpaca's documentation states it) | `live.py:209-215, 305-310`, `broker.py:22`, `RUNBOOK.md:191-201` | R: small extra buys on the next two days | Medium | Yes |
| 5 | A run killed mid-batch records nothing about orders already accepted; the next run plans again from current positions (CX) | `live.py:306-316` | R: stopped after 1 order, the next run sent all 3 again | Medium | Yes |
| 6 | If a sell fails, the buys are still sent (VS). Effect on buying power at Alpaca is unknown | `live.py:87, 209-214` | R | Low | Yes |
| 7 | No request timeout, and the SDK retries 429 and 504 on order POSTs: a hung call can pass the cutoff, an accepted order can be reported failed (A32). The per-order cutoff check does not stop a hung call | `broker.py:46, 73, 78`; installed `alpaca/common/rest.py:113-131, 198` | C (outcome unverifiable) | Medium | Yes |
| 8 | An empty broker calendar passes the freshness check, and a month-end row missing from all data silently moves the signal day earlier (A31, CX). The new QQQ check stops this only if QQQ also keeps that day | `live.py:181-187, 279, 284`, `broker.py:90` | R: with 10-30 missing from both, signal day became 10-29, no alert | Low | Yes |
| 9 | A missing state file silently starts un-killed with no month recorded; a corrupt one stops the run with nothing logged (A12). Saving is now atomic (fixed part) | `live.py:99-102, 223`, `trend_live.py:65-68, 95` | R: both | Medium | Yes, if `state/` is touched |
| 10 | Momentum sizes on the previous close at up to 100% gross, no cash buffer (VS). Already listed as a known item | `live.py:79, 305` | C | Low | Yes, if exposure is near 100% |

Manual checks for 12-01 that need no code (CC, CX): dry run on the evening of 11-30 and explain any change in the
12-01 picks (item 1); compare the submit run's `planned_order` lines with the dry run (item 2); after any failure stop
and follow `RUNBOOK.md` "Failed or unfilled orders" (items 3-7); keep `state/` (item 9); run again on 12-02 to log fills.

## Next: right after the first fills

| # | Finding (source) | Where now | Check | Sev | 12-01 |
|---|---|---|---|---|---|
| 11 | Fills are logged only by a later run looking back 7 days (A26). `compare.py` then says to run `--submit` when one more run after the fill is what is needed (CX) | `live.py:146`, `compare.py:131` | C | Low | After |
| 12 | `done_for_day` is treated as final, so a later `filled` is never logged (A30) | `live.py:145` | R with a fake; whether Alpaca does this is unverified | Low | After |
| 13 | A partly filled trend entry is never topped up: any QQQ holding counts as invested (A34). Documented in `RUNBOOK.md:206` | `trend_live.py:57-60` | R (a partial closing-auction fill is unverified) | Medium | After |
| 14 | Fill slippage is blank or wrong: prices are cached per set of filled symbols and never refreshed, and the reference is the dividend- and split-adjusted close (A7) | `compare.py:57-61, 148`, `data.py:50-51` | R (no refresh, NaN close); adjusted-close part C | Medium | After |
| 15 | Partly filled orders that end `canceled` or `expired` are left out of fills, slippage and the start date (A13). They still show as `order_final` and alerts | `compare.py:54, 123, 134` | R | Medium | After |
| 16 | Equity is filed under the price bar's date. A one-day-late download on a no-rebalance run overwrites the earlier day, since the session check comes after (A14) | `compare.py:41`, `live.py:265, 277`, `trend_live.py:135, 146` | R: no alert, equity keyed to the older day | Medium | After |
| 17 | Shadow backtests differ from live: trend shadow has no kill switch, neither replays a reset, a cache ending before the first fill gives an empty table without a message, and no prior month raises a bare `KeyError` (A15) | `compare.py:65-103, 138-146` | R: shadow fell 39% with no kill; `KeyError` | Medium | After |
| 18 | Head-to-head includes dry-run days before the first fill (A35) | `compare.py:153, 173-174` | R | Medium | After |
| 19 | A mid-month first trade makes the shadow use a different trend day from live (A39) | `compare.py:72-74`, `risk.py:172`, `live.py:297` | C | Low | After (not if the first trade is 12-01) |

## Then: live-path protection

| # | Finding (source) | Where now | Check | Sev | 12-01 |
|---|---|---|---|---|---|
| 20 | Tests still miss live wiring (A5). Surviving bugs: sell-off rule off, all risk limits off, trend taken from the last bar, eligibility ignored, strategy parameters changed, kill update on every run (harmless under the hard stop), trend `--offline` writing real state. Research survivors: backtest costs zero, `call_seq`, walk-forward look-ahead and picks-worst, momentum picks worst, semi equipment leaving the semis cap, shadow start and start equity, dead names kept, risk variants ignoring the risk layer. Do before the next live-code change | `tests/test_live.py:87-97` (fixture: all "software", rising benchmark) and the modules named | R: 17 of 37 survived | Medium | No |
| 21 | Kill-switch reset works when nothing was killed and lowers the peak (A11). The runbook says only reset after a kill; the code does not enforce it | `live.py:333-340`, `trend_live.py:179-188`, `risk.py:126-128` | R | Medium | No |
| 22 | The high-water mark only sees days the runner ran; no alert after a gap (A25). `RUNBOOK.md:212` now says to run daily | `live.py:233-237`, `trend_live.py:107-110` | C | Medium | No |
| 23 | State is not tied to an account (A28, A12). The account guard stops swapped keys; swapping keys and numbers together, or replacing an account without deleting state, still applies the old peak and kill flag. Documented in `RUNBOOK.md:28-30` | `live.py:99-102`, `trend_live.py:65-68` | C | Low | No |
| 24 | A stray position makes the trend runner return before the kill check (A6, remaining part). `CX`: blindly liquidating a possibly wrong account is not the fix; it does alert | `trend_live.py:101-104` | R | Low | No |
| 25 | Aborted runs exit with status 0 (A17). Only the wrong-account refusal exits 1 | `live.py:230, 258, 263, 278, 282, 287, 292, 296, 304`, `trend_live.py:104, 129, 133, 147` | R | Low | No |
| 26 | Liquidation skips shorts and rounds a fractional holding up (A18) | `live.py:84, 90-94` | R | Low | No |
| 27 | Equity 0 on the first run fires the kill switch (A20). Unfunded account only | `risk.py:120-121` | R | Low | No |
| 28 | Any `side` other than `buy` becomes a sell; a mistyped risk group caps nothing (A27). Current callers are correct | `broker.py:69`, `risk.py:83-88` | R (group), C (side) | Low | No |

Liquidation retries reuse the same `-kill` order ID within a day (CX), so a same-day retry may be refused. The runbook
now says not to re-submit that day (`RUNBOOK.md:191-193`); it is part of item 4.

## Before the January rebalance

| # | Finding (source) | Where now | Check | Sev | 12-01 |
|---|---|---|---|---|---|
| 29 | Index membership goes stale with no warning; `refresh=True` refreshes prices only. Newest change in the CSV is 2026-10-09 (A16; CX: an old last change does not prove it is wrong; the December reconstitution date is unchecked) | `universe.py:24, 80-83, 140-149` | C | Medium | No |

## Research, data and cleanup

| # | Finding (source) | Where now | Check | Sev | 12-01 |
|---|---|---|---|---|---|
| 30 | A failed download overwrites a good price cache, and a successful retry is dropped when the first reply was empty; the T-bill cache has no check either (A9). Live aborts; research reads the damaged file. CX: do not simply reject every shorter file | `data.py:55-67, 82-84` | R: 5 rows to 0 | Medium | No |
| 31 | Costs missing in places, against rule 2: QQQ references (A38, CX) and the earnings "skip" and "half size" results (CC, CX; docstring admits it) | `analysis/common.py:61`, `backtest.py:105`, `walkforward.py:140`, `analysis/earnings.py:8-9, 93-94` | C | Low | No |
| 32 | A partial earnings download is cached for good, empty replies are skipped silently, the T-bill cache is never refreshed and is forward-filled (A33) | `analysis/earnings.py:35-49`, `data.py:79-80`, `backtest.py:47-50` | C | Low | No |
| 33 | "Today's picks" ranks the latest bar with its own trend rule and ignores the kill switch (A21) | `report.py:139-144` | C | Low | No. Do not compare 12-01 orders with it |
| 34 | All-NaN training scores return `None` and fail later (A22) | `walkforward.py:76-81` | R | Low | No |
| 35 | "2026 YTD" labels go stale in 2027 (A23; CC corrected the lines; CX: a named 2022 drawdown year is fine) | `backtest.py:155-156`, `report.py:97`; years also at `backtest.py:25`, `analysis/universe_compare.py:53` | C | Low | No |
| 36 | `completed_bars` uses local time, unlike `data.finished_bars`; both runners duplicate the state helpers; stale universe comment (A24; "redundant" is too strong, cached reads skip `finished_bars`) | `analysis/common.py:26-28`, `live.py:99-139` and `trend_live.py:65-86`, `data.py:11-14` | C | Low | No |
| 37 | Universe coverage counts forward-filled prices, and only start dates are aligned (A37) | `analysis/universe_compare.py:38, 65-70` | C; effect on current cache not rechecked | Low | No |
| 38 | `.claude/settings.json` enables an unpinned third-party plugin marketplace in a public repo (A security; your call). No dependency vulnerability scan has been run | `.claude/settings.json`, `requirements.txt` | C | Low | No |

## Documentation still wrong

All Low, none changes behaviour. Only `RUNBOOK.md` rows are worth reading before 12-01.

| Where now | Says | Reality |
|---|---|---|
| `RUNBOOK.md:119` | `signal` only on rebalance days | the trend runner logs it on normal days |
| `RUNBOOK.md:123` | `no_orders` = already at target | trend also uses it for "already submitted today" |
| `RUNBOOK.md:100-101` | 15:35 is in both runner headers | not in `trend_live.py` |
| `RUNBOOK.md:242-243` | a later daily run fills in today's close | false for momentum (item 14) |
| `RUNBOOK.md:261`, `CLAUDE.md` known items | earnings errors skip names silently | exceptions are printed; only empty replies are silent (CX) |
| `live.py:8` | reset re-arms at current equity | previous-close equity |
| `trend_live.py:3` | holds 100% QQQ | 98% target (lines 15-16 say so) |
| `compare.py:7` | "5 bps + 5 bps fees" | 5 bps slippage + 5 bps fees |
| `compare.py:14` | trend shadow mirrors the live runner | no kill switch (item 17) |
| `risk.py:103` | kill switch has cooldown and trend re-arm | default is a manual-reset hard stop |
| `broker.py:5` | keys `ALPACA_API_KEY/SECRET_KEY` | also the `ALPACA_TREND_*` pair |
| `broker.py:22` | a same-day re-run cannot double-submit | untested here |
| `broker.py:76` | cutoff about 15:50 ET | refuses with under 15 minutes left |
| `data.py:75` | T-bill rate for reporting and scoring only | also the cash return in `analysis/qqq_trend.py` |
| `data.py:11-14` | static list to be replaced | already replaced (item 36) |
| `README.md:46` | excess Sharpe about 0.72 vs QQQ 0.79 | `CLAUDE.md` records 0.70 vs 0.78 (not rerun) |
| `README.md:8-21` | file tree | omits `trend_live.py`, `report.py`, `analysis/`, `RUNBOOK.md`, `DECISIONS.md` |
| `README.md:13` | position and semis caps | also a 35% hardware cap |
| `README.md:33-41` | how to use | no trend runner |
| `CLAUDE.md` on `origin/main` | 76 tests pass | 191; corrected only in the uncommitted local copy |
| `CLAUDE.md` Commands | Python 3.10-3.11 | pinned pandas, numpy, vectorbt need 3.11 or later |
| `CLAUDE.md` Commands | writes `walkforward_oos.png` | writes `walkforward_oos_<universe>.png` |

## Fixed since the audits

PR #19 is `d1cb924`, PR #20 is `617ad82`.

| Finding | Fix | Fixed by | Check |
|---|---|---|---|
| A1 dry run hid the orders | `planned_order` line per order, before anything is sent | #19 | tests |
| A4 early submit trades the old signal (docs) | runbook warns; behaviour is unchanged on purpose | #19 | C |
| A5 adapter, cutoff and many failure paths untested (part) | new `tests/test_broker.py`, runner failure tests; rest is item 20 | #19, #20 | R |
| A6, VS: data failure blocked the kill switch | kill check and liquidation run before downloads (rest: item 24) | #19 | tests, C |
| CX: order-history failure blocked the kill switch | order polling moved after the kill check | #19 | tests, C |
| A8 short QQQ history meant "invest" | both runners abort under 200 rows | #19 | tests, C |
| CX: missing QQQ values could still mean "invest" | not reachable: a one-ticker download drops empty rows, so the length check counts real values (gaps inside the history are not counted separately) | existing `data.py:66` + #19 | R |
| A19 QQQ date not checked | momentum requires the same last bar and the signal day | #19 | tests |
| A10, VS: momentum could run on the wrong account | QQQ guard (#19); account-number check (#20) | #19, #20 | tests |
| A12 half-written state file (part) | atomic save; rest is item 9 | #19 | tests |
| A28 trend equity logged before the stray abort; swapped keys (part) | abort comes first; account check; rest is item 23 | #19, #20 | C |
| A29 kill alert only once | alerts on every run while killed | #19 | tests |
| A36 no early-close times | runbook "Early-close days" | #19 | C |
| CX: cutoff checked once per batch | checked before each order | #19 | tests |
| CC missed 3: recovery needed caveats | runbook "Failed or unfilled orders" | #19 | C |
| CC missed 4: reset keeps the month record | documented at `RUNBOOK.md:227-230` | #19 | C |
| Docs: planned orders shown; early-submit and "wait for next rebalance" wording; quiet-day lines; missing alerts; kill and liquidation wording; traceback location; reset equity in runbook; `live.py` header on rebalance timing | rewritten | #19 (alerts also #20) | C |

## Review points with nothing left to fix

- **CC and CX corrections to `AUDIT.md`'s text**: A5's "no cap ever fires" and "helper compared with itself" are
  overstated, and a trend `main()` guard test existed; "costs applied in every research path" is wrong (item 31);
  risk-loop vs vectorbt gap measured 0.10-0.16%, not 0.13%; 14 CodeRabbit findings claimed but 13 listed (the missing
  one, if any, is unknown); A7 rated Medium here; wrong line numbers in A23 and A37; "81 tests" is now 191.
- **CX on A3, A13, A16, A19, A23, A24, VS on A3**: wording qualifications, folded into the items above.
- **Priority advice** (CX, VS, CC "Must do" changes): promoting A6, A8, A19 and account checks is done (#19, #20);
  the rest is items 1-10 and the manual checks.
- **12-01 exposure forecast** (A, CX): not a defect. Today's logs show QQQ below its 200-day average on the 11-25
  close. If it still is at the 11-30 close, momentum targets at most 50% gross; picks and weights may change. Trend
  plans nothing only if its account is flat and the signal is still off.

## Never tested against Alpaca (all four audits)

Order submission, repeated client order IDs, closing-auction and partial fills, buying-power checks and the real
cutoff.
