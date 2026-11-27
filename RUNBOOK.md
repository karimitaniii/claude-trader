# Paper-trading runbook

Two Alpaca **paper** accounts, one per strategy:

- **Momentum** (`live.py`): keys `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`.
- **QQQ 200d trend** (`trend_live.py`): keys `ALPACA_TREND_API_KEY` / `ALPACA_TREND_SECRET_KEY`.

Each account holds its own positions and equity, so the two strategies cannot share one. Both runners are
dry runs unless you pass `--submit`. Nothing here touches live money.

Keys live in `~/.alpaca_paper_env` (outside the repo, `chmod 600`). Never paste key values into chat or commit them.

## Daily steps (each trading day, before the cutoff)

Run these from the repo. Use one terminal window for the whole sequence.

1. Go to the repo and activate the virtualenv:

```bash
cd ~/Desktop/Claude\ Trader
source .venv/bin/activate
```

2. Load the paper keys into this shell (the file only contains `export` lines):

```bash
source ~/.alpaca_paper_env
```

3. Dry run both strategies. This plans orders and logs them, and submits nothing:

```bash
python live.py
```

```bash
python trend_live.py
```

4. Read the output. Confirm the `planned_order` lines (ticker, side, quantity) are what you expect before
   anything is sent. Check the `signal`, `risk` and `alert` lines (see "Log lines" below).

5. Submit only after checking step 4. `--submit` downloads and plans again, so compare its `planned_order` lines
   (printed before anything is sent, with no confirmation prompt) with the dry run.

   **Momentum trades on any `--submit` in a month that has no recorded rebalance**, not only on the first trading
   day, and always on the previous month-end signal. An early or "just testing" `--submit` places real paper
   orders. For example, any run dated 2026-11-30 (New York) or earlier in November uses the 10-30 signal; the
   11-30 signal is used from 2026-12-01. Momentum also trades on a kill-switch liquidation. The trend strategy
   plans an order whenever what it wants (in or out of QQQ) differs from what it holds. Submit each strategy once
   per day:

```bash
python live.py --submit
```

```bash
python trend_live.py --submit
```

6. Check the logs. `live.py` writes to `logs/YYYY-MM-DD.jsonl` (Eastern date), and `trend_live.py` writes to
   `logs/trend/`. Look at the last events of the day:

```bash
tail -n 20 logs/$(TZ=America/New_York date +%F).jsonl
```

```bash
tail -n 20 logs/trend/$(TZ=America/New_York date +%F).jsonl
```

On days with nothing to trade, momentum normally logs `no_rebalance` and the trend runner `no_orders`, besides the
usual `run_start`, `account`, `signal` (trend) and `run_end` lines. That is expected.

## Cutoff (market-on-close orders)

- Orders are market-on-close. They must reach Alpaca while the market is open.
- The code refuses to submit when fewer than **15 minutes** remain before the close (`broker.py`,
  `can_submit_moc`). On a normal day that is **15:45 ET**. You will see an alert such as
  `not submitting: only 12 min to close`.
- The project's own target is to submit **before 15:35 ET** (the time used in the `live.py` and `trend_live.py`
  headers), which leaves a 10-minute margin.
- Note: the `can_submit_moc` docstring says "~15:50 ET", but the code checks 15 minutes before close. The code
  is the stricter of the two, so follow the 15:35 target.

Recommended order: dry runs at about 15:00-15:20 ET, then `--submit` for both before 15:35 ET.

**Early-close days** (for example the day after Thanksgiving, usually a 13:00 ET close): every time above moves with
the close. Submit at least 25 minutes before it. The code checks the broker's real close time before each order.

## Log lines

Each log line is one JSON object with `ts`, `kind`, and fields specific to that kind. The `alert` and `error`
kinds are also printed to the terminal (stderr).

| kind | meaning | what to do |
|---|---|---|
| `run_start` | run began; mode is `dry_run` or `submit` | none |
| `account` | last-close equity, current positions, last price bar, and whether QQQ is above its 200d average | check equity looks right |
| `signal` | targets from the previous month-end close (only on rebalance days) | compare with the backtest picks if unsure |
| `risk` | targets after the risk layer; `fired` lists any caps or sell-off rules that changed them | note any cap that fired |
| `planned_order` | one order in the plan (symbol, quantity, side), printed on dry and submit runs | review |
| `dry_run` | dry run only: the number of planned orders (nothing was sent) | none |
| `no_orders` | the plan is already at target | none |
| `no_rebalance` | this month is already rebalanced | none |
| `order_submitted` | an order was accepted by Alpaca (paper) | confirm it later as a `fill` |
| `fill` | an order filled; includes fill price and quantity | check fills against the close in `compare.py` |
| `order_final` | an order ended without filling (rejected, canceled, expired) | see "Errors" |
| `killed` | the kill switch is active and the account is flat | see "Kill switch" |
| `manual_reset` | the kill switch was re-armed by a person | record why in the notes |
| `error` | an exception, with `where` naming the step | see "Errors" |
| `alert` | a human needs to look: kill switch, stale data, failed or unfilled order, cutoff missed | see below |
| `run_end` | run finished (always logged, even after an error) | none |

## Alerts and errors

- **`unusable QQQ history: ...; aborting`**: QQQ came back with fewer than 200 days or (momentum) does not end on
  the same day as the stock prices. No new rebalance or trend order is sent (a kill-switch liquidation is sent before
  this check). Re-run later; do not work around it.
- **`QQQ held in the momentum account; is it the wrong account?`**: momentum never holds QQQ. Nothing is done, not
  even the kill-switch check. Check which keys are loaded and the Alpaca dashboard. The guard cannot recognise the
  trend account while it holds no QQQ, so check the keys yourself.
- **`unexpected positions in the trend account: [...]`**: the same guard for the trend runner.
- **`no price data before this month; aborting`**: there is no month-end row to take the signal from. Investigate.
- **`stale data: last bar <date>; aborting`**: the price data is more than 5 days old. No new rebalance or trend
  order is sent (a kill-switch liquidation is sent before this check). Re-run later, and check that the market data
  source is up.
- **`no price for [...] on <date> or <date>; aborting`**: a current member's price is missing (usually a failed
  download). Nothing is sent. Re-run the dry run. If the same name keeps failing, stop and investigate; do not
  work around the check.
- **`last bar <date> but the previous session was <date>; aborting`**: the data source has not delivered the
  previous trading day yet. Wait a few minutes and re-run.
- **`no price for target [...] on <date>`**: a stock the strategy wants to hold has no price on the latest bar,
  possibly because it left the index and stopped trading. Nothing is sent. Re-run the dry run. If it persists, stop
  and investigate; do not work around the check.
- **`no valid signal on <date>`**: the month-end signal could not be computed. No orders are placed. Investigate
  before the next rebalance.
- **`not submitting: ...; N of M orders were attempted`**: the cutoff passed, the market is closed, or the cutoff
  check itself failed. It runs before each order, so the first N may already be in the account. See "Failed or
  unfilled orders".
- **`order failed: <client_order_id>`**: an order was rejected at submit time. The run keeps going for the other
  orders. Read the `error` line next to it, then see "Failed or unfilled orders".
- **`order <id> ended <status>`**: an order was not filled (for example `rejected`). See "Failed or unfilled orders".
- **`run failed`** (with an `error` before it): the run stopped with an exception. The terminal shows the traceback
  (the `error` line holds only the message). If today's log has any `order_submitted` line, even one sent before
  the step that failed, see "Failed or unfilled orders". Otherwise fix the cause and re-run the dry run before any
  `--submit`.

## Failed or unfilled orders

Applies after any failed, cut-off, interrupted or unfilled order, and whenever a run that sent orders ended in an
alert or error.

1. **Do not run `--submit` again that day.** Order IDs repeat within a day (`tm-YYYYMMDD-TICKER-side`, `-kill` for
   liquidations), and how Alpaca treats a repeated ID has not been tested here.
2. In the Alpaca paper dashboard, check every order and the positions.
3. On the next trading day, once no earlier order is still open, do a dry run. This also logs the earlier fills
   (the runners only look back 7 days).
4. Then, depending on the case:
   - **Momentum, a submission failed or was cut off:** the month is not recorded, so the dry run plans again from the
     current positions. It may also contain small resizing orders. Review, then `--submit`.
   - **Momentum, all orders accepted but some ended unfilled:** the month is recorded and nothing is retried. To retry,
     set `"last_rebalance_month"` to `null` in `state/live_state.json`, dry run, review (the whole portfolio is
     recalculated from the same month-end signal), then `--submit`. Or leave it until next month.
   - **Trend:** if it holds no QQQ and wants to, it plans the buy again by itself, and if it holds QQQ and wants
     out, the sell. A partly filled entry is **not** topped up.
   - **Liquidation:** while killed and still holding positions, `--submit` sends the sells again.

## Kill switch

- The kill switch fires when previous-close equity is **25%** below the highest value any run has seen
  (`risk.py`, `kill_drawdown`), so run daily. It is checked before any price or order-history request.
- While killed, every run, dry or not, alerts `KILL SWITCH active: ...` (unless a wrong-account guard stops it
  first). Only `--submit` before the cutoff sells (`-kill` orders). Once the account is flat, a run whose data
  downloads succeed also logs `killed`.
- It stays killed until a person reviews and re-arms it. **Do not re-arm without reviewing why it fired.** Review
  the logs, decide, then run the reset for that strategy:

```bash
python live.py --reset-kill-switch
```

```bash
python trend_live.py --reset-kill-switch
```

  The reset sets the new peak at previous-close equity and logs `manual_reset`. Run it only when the switch has
  fired, the account is flat with no open orders, and not on the day of a liquidation: otherwise the next `--submit`
  can send a second sell for shares already being sold. It does not clear the momentum month record: if this month was already rebalanced, momentum stays in cash
  until next month.

## Weekly compare

Once a week, after both strategies have some fills, compare live paper results with the backtest over the same
dates. The check covers equity, fill slippage against the close, failed orders, and alerts. Run it with both
strategies:

```bash
python compare.py --strategy both
```

Today's price is never cached, so a fill from today shows no close (NaN slippage) until a later daily run
refreshes the prices.

Read the output together. Early on, there are few fills, so expect little signal from one week. Use the
`--strategy momentum` or `--strategy trend` flags to look at one strategy at a time.

## Tests

Run after any code change, before submitting anything:

```bash
python -m pytest
```

## Known small items (not fixed, from CLAUDE.md)

- `live.py` sizes on the previous close with up to 100% gross exposure.
- `report.py` "today's picks" ignores the live kill-switch state.
- `trend_live.py` redirects `live.LOG_DIR` while it runs.
- `analysis/earnings.py` skips names silently on download errors.
- `compare.py`'s shadow backtest uses cached prices.
