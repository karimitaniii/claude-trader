# Independent check of AUDIT.md, 2026-11-27

Checks [AUDIT.md](AUDIT.md) against the code at `9e82388` (`main`), by Claude Code.

## Verdict

AUDIT.md holds up well. No numbered finding is false in substance. Two are rated too high (finding 5 is also partly
wrong), two cite wrong lines, one supporting claim about the tests is wrong, and it missed two things that matter for
12-01.

All 81 tests pass. **R** means reproduced with fake brokers or rerun on a scratchpad copy; **C** means checked in the
code only.

## Findings

| # | Verdict | Evidence |
|---|---|---|
| 1 | Correct, R | [live.py:111](live.py#L111) drops `orders` and `targets` from the printed line. They are still in the log file. |
| 2 | Correct, C | [live.py:237-238](live.py#L237-L238) records the month on acceptance. Its suggested recovery needs a caveat (below). |
| 3 | Correct, R | One refused symbol caused further 1-3 share orders on Dec 2-4. Alpaca's duplicate-ID refusal is unverifiable. |
| 4 | Correct, R | [live.py:209-211](live.py#L209-L211): an 11-27 submit planned orders, and 12-01 planned again. Orders fill at the close, not "immediately". |
| 5 | **Partly wrong** | The coverage gap is real: all 25 listed breaks that were rerun survived. The walk-forward, shadow, dead-name, risk-variant and `call_seq` ones were not rerun, so "32 of 38" is unconfirmed. See notes below. |
| 6 | Correct, R | Stale data returns at [live.py:186-188](live.py#L186-L188) before the kill check at line 195. Same in [trend_live.py:99-113](trend_live.py#L99-L113). |
| 7 | Correct, C; **overrated** | [compare.py:148](compare.py#L148). It only affects reporting, so by the audit's own definition it is Medium, not High. |
| 8 | Correct, R | 60 falling bars produced a 980-share buy ([risk.py:63](risk.py#L63)). Truncation by Yahoo is unobserved. |
| 9 | Correct, R | [data.py:65-67](data.py#L65-L67): both cases left 0 rows. |
| 10 | Correct, R | Momentum sold a held QQQ position. |
| 11 | Correct, R | Reset at 80, then 64, did not fire ([risk.py:126-128](risk.py#L126-L128)). |
| 12 | Correct, R/C | Half-written state crashed with nothing logged (R). Missing state loads defaults, [live.py:94-97](live.py#L94-L97) (C). |
| 13 | Correct, C | [compare.py:54](compare.py#L54) and line 123 use `fill` events only. |
| 14 | Correct, C | [compare.py:41](compare.py#L41) keys equity on `last_bar`. |
| 15 | Correct, R/C | Trend shadow lost about 39% with no kill; an early-ending cache gave an empty result (R). The `None` crash at line 72 is C. |
| 16 | Correct, C | Newest change is 2026-10-09. The December reconstitution timing was not checked. |
| 17 | Correct, C | True of [live.py:215-218](live.py#L215-L218) and the other early returns. |
| 18 | Correct, C | [live.py:79](live.py#L79), [live.py:88](live.py#L88). |
| 19 | Correct, R | `KeyError` raised at [live.py:228](live.py#L228). |
| 20 | Correct, R | [risk.py:120-121](risk.py#L120-L121). |
| 21 | Correct, C | [report.py:139-144](report.py#L139-L144). |
| 22 | Correct, C | [walkforward.py:76-81](walkforward.py#L76-L81). |
| 23 | Correct, **wrong lines** | The years are at [backtest.py:25](backtest.py#L25) and [155-156](backtest.py#L155-L156), not 170. Also [universe_compare.py:53](analysis/universe_compare.py#L53). |
| 24 | Correct, C | [analysis/common.py:26-28](analysis/common.py#L26-L28); duplicated helpers in both runners. |
| 25 | Correct, C | [live.py:195-198](live.py#L195-L198). |
| 26 | Correct, C | 7-day lookback, [live.py:130](live.py#L130). |
| 27 | Correct, C | [broker.py:65](broker.py#L65). |
| 28 | Correct, C | [trend_live.py:104-109](trend_live.py#L104-L109). |
| 29 | Correct, C | [live.py:199-206](live.py#L199-L206). |
| 30 | Code correct; outcome unverifiable | [live.py:129](live.py#L129). |
| 31 | Correct, C | [live.py:144](live.py#L144). |
| 32 | Code correct; outcome unverifiable | The installed library sets no timeout and retries 429 and 504, POSTs included. |
| 33 | Correct, C | [earnings.py:35-49](analysis/earnings.py#L35-L49), [backtest.py:47-52](backtest.py#L47-L52). |
| 34 | Correct, R | 10 shares held plans nothing. Whether a closing-auction order can partly fill is unverifiable. |
| 35 | Correct, C | [compare.py:153](compare.py#L153) returns the whole series. |
| 36 | Correct | [RUNBOOK.md:73](RUNBOOK.md#L73) gives normal-day times. 11-27 is the day after Thanksgiving, normally a 13:00 close (not checked against the exchange calendar). |
| 37 | Correct, **one wrong line** | Start alignment is [universe_compare.py:38](analysis/universe_compare.py#L38), not 49. Confirmed zero such gaps in the cache. |
| 38 | Correct, C | [analysis/common.py:61](analysis/common.py#L61). |
| 39 | Correct, C | [compare.py:72-74](compare.py#L72-L74) with [risk.py:172](risk.py#L172), against [live.py:228](live.py#L228). |

## Errors elsewhere in the report

- **Finding 5, "no cap or sell-off rule ever fires" is wrong for caps.** The tests use `top_n=3`
  ([test_live.py:98](tests/test_live.py#L98)), so each 33% target hits the 15% position cap; seen firing in a
  reproduction. No test asserts on it, so the gap remains.
- **Finding 5, other points:** [test_live_targets_equal_backtest_row](tests/test_live.py#L34) does check the one-bar
  shift, so "compares a shared helper with itself" is overstated. The trend stale-data and missing-session aborts
  appear both as re-run survivors and as "not re-run". A test gap also does not meet the report's own definition of
  High.
- **"Costs are applied in every research path" is wrong.** The earnings "skip" and "half size" results charge nothing
  for exiting and re-entering ([earnings.py:93-96](analysis/earnings.py#L93-L96); the docstring admits it). That
  conflicts with rule 2.
- **"Within 0.13% of vectorbt":** measured 0.10% (hard stop) and 0.16% (re-armed).
- **CodeRabbit:** the text says 14 findings, but the table has 13 rows.

**Documentation table:** all 30 rows match the code and docs.

**Numbers:** the scripts reran on cached data through 11-25, and the headline figures compared match, including CAGR,
Sharpe, alpha, bootstrap, cost stress, walk-forward, plateau, 5 re-armed kills, 20.1% of 412 earnings days, and QQQ
633.93 against 682.54. The 45 tracked files and 80-row ledger also match. A filename and pattern search of git history
found no secrets.

**Unverifiable:** the audit's checksums, agent and CodeRabbit runs, Pyright count, and anything depending on Alpaca.

## What the audit missed

1. **A stock with truncated history silently changes the picks (R).** The checks cover only the signal day and last bar
   ([live.py:219](live.py#L219)), and retries cover only wholly empty columns ([data.py:60](data.py#L60)). With one
   pick's older history blanked, a different stock replaced it, with no alert. Whether Yahoo does this is unobserved.
2. **`--submit` does not send the plan you reviewed (C).** It downloads again and re-plans
   ([live.py:182](live.py#L182), [236-237](live.py#L236-L237)). Printing the dry run alone leaves this open; each order
   appears only after it is sent.
3. **The recovery for finding 2 needs a caveat (C).** On the same day, order IDs repeat ([live.py:81](live.py#L81))
   and may be refused. Recover the next day. A partial fill also causes every name to be re-sized. The trend runner
   retries by itself the next day if it still holds nothing.
4. **Minor (C):** a kill-switch reset leaves `last_rebalance_month` set, so momentum can stay in cash until the next
   month. [RUNBOOK.md:148](RUNBOOK.md#L148) does not say so.

## Out of date

The code is unchanged from `9e82388`, so the findings still apply. Since the audit:

- CLAUDE.md has an uncommitted backlog section.
- `AUDIT-VSCODE.md` and `AUDIT-CODEX.md` are now in the root. Neither was opened for this check.
- Finding 36 matters on 11-27, not for 12-01.
- The 12-01 expectation of 50% invested still depends on the 11-30 QQQ close. The listed picks are from 11-25 data and
  may change.

## The "Must do before 2026-12-01" list

Mostly right. Suggested changes:

| Priority | Action | Change from audit |
|---|---|---|
| 1 | Print planned orders, on the submit run too, before sending | Item 1, widened |
| 2 | Abort on short or stale QQQ history (8, 19) | **Promoted**: small, and it can reverse the trend decision |
| 3 | Write recovery steps (2, 3): stop after any failure, check Alpaca, retry no sooner than next day; run again 12-02 to log fills | Item 2, with caveat |
| 4 | Correct the RUNBOOK on early submits (4) | Item 3 |
| Manual | Compare 12-01 picks with an 11-30 evening dry run and explain any change; compare submitted orders with the dry run; confirm each key pair points to the intended account | New |
| Later | Broker adapter and cutoff tests (5) | **Demoted**: tests alone change nothing on 12-01. Add them with any live-code change. |

## Limits of this check

Checksums of `data_cache/`, `state/` and `logs/` matched after the reproductions. No `--submit` or reset was run, no
Alpaca calls were made and no keys were read. Closing-auction fills, duplicate order IDs and the real cutoff remain
untested against Alpaca.
