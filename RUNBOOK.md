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

4. Read the output. Confirm the planned orders (ticker, side, quantity) are what you expect before anything is
   sent. Check the `signal`, `risk` and `alert` lines (see "Log lines" below).

5. Submit only the orders you checked in step 4. Momentum plans orders on the first trading day of a month
   (monthly rebalance), and on a kill-switch liquidation. The trend strategy plans orders only when QQQ crosses
   its 200d average. Submit each strategy once per day:

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

On days with no rebalance, both runs normally log `no_rebalance` or `no_orders` and nothing else. That is expected.

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

## Log lines

Each log line is one JSON object with `ts`, `kind`, and fields specific to that kind. The `alert` and `error`
kinds are also printed to the terminal (stderr).

| kind | meaning | what to do |
|---|---|---|
| `run_start` | run began; mode is `dry_run` or `submit` | none |
| `account` | last-close equity, current positions, last price bar, and whether QQQ is above its 200d average | check equity looks right |
| `signal` | targets from the previous month-end close (only on rebalance days) | compare with the backtest picks if unsure |
| `risk` | targets after the risk layer; `fired` lists any caps or sell-off rules that changed them | note any cap that fired |
| `dry_run` | the orders that `--submit` would send (nothing was sent) | review before submitting |
| `no_orders` | the plan is already at target | none |
| `no_rebalance` | this month is already rebalanced | none |
| `order_submitted` | an order was accepted by Alpaca (paper) | confirm it later as a `fill` |
| `fill` | an order filled; includes fill price and quantity | check fills against the close in `compare.py` |
| `order_final` | an order ended without filling (rejected, canceled, expired) | see "Errors" |
| `killed` | the kill switch is active; the strategy holds cash | see "Kill switch" |
| `manual_reset` | the kill switch was re-armed by a person | record why in the notes |
| `error` | an exception, with `where` naming the step | see "Errors" |
| `alert` | a human needs to look: kill switch, stale data, failed or unfilled order, cutoff missed | see below |
| `run_end` | run finished (always logged, even after an error) | none |

## Alerts and errors

- **`stale data: last bar <date>; aborting`**: the price data is more than 5 days old. The run stops without
  trading. Re-run later, and check that the market data source is up.
- **`no price for [...] on <date> or <date>; aborting`**: a current member's price is missing (usually a failed
  download). Nothing is sent. Re-run the dry run. If the same name keeps failing, stop and investigate; do not
  work around the check.
- **`last bar <date> but the previous session was <date>; aborting`**: the data source has not delivered the
  previous trading day yet. Wait a few minutes and re-run.
- A momentum order that is accepted but later ends unfilled is **not retried**: the month already counts as
  rebalanced. Check the alert and the Alpaca dashboard.
- **`no valid signal on <date>`**: the month-end signal could not be computed. No orders are placed. Investigate
  before the next rebalance.
- **`not submitting: ...`**: the cutoff passed or the market is closed. Nothing was sent. Run `--submit` the
  next trading day, or wait for the next rebalance if the rebalance day has passed.
- **`order failed: <client_order_id>`**: an order was rejected at submit time. The run keeps going for the other
  orders. Read the `error` line next to it.
- **`order <id> ended <status>`**: an order was not filled (for example `rejected`). Check it in the Alpaca paper
  dashboard before doing anything else. Client order IDs are deterministic per day (`tm-YYYYMMDD-TICKER-side`), so
  before re-running `--submit` on the same day, check whether the order is already in the account. Re-running
  may create duplicates or be rejected, and I have not verified how Alpaca handles a repeated client ID.
- **`run failed`** (with an `error` before it): the run stopped with an exception. Read the traceback in the
  `error` line, fix the cause, and re-run the dry run before any `--submit`.

## Kill switch

- The kill switch fires when equity falls **25%** below its all-time high (`risk.py`, `kill_drawdown`). The alert
  says `KILL SWITCH: ...`. The run then sells everything (`-kill` orders) and holds cash.
- While killed, every daily run logs `killed` and does nothing else.
- It stays killed until a person reviews and re-arms it. **Do not re-arm without reviewing why it fired.** Review
  the logs, decide, then run the reset for that strategy:

```bash
python live.py --reset-kill-switch
```

```bash
python trend_live.py --reset-kill-switch
```

  The reset sets the new peak at current equity and logs `manual_reset`.

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
