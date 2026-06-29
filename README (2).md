# spy-collar-greek-paths

Collect the **average Greek path** of a large sample of SPY bear put-spread collars,
held to expiration, to find candidate signals for closing a collar early vs. holding
to expiry. Output is four charts (delta, gamma, theta, vega) of the aggregate collar
position vs. days held.

```
spy-collar-greek-paths/
  quantconnect/main.py   # data collector — paste into the QuantConnect cloud IDE
  src/load_data.py       # parse the QC export (log .txt or .csv) into a DataFrame
  src/aggregate.py       # group by held_days (or dte): mean / median / IQR / count
  src/plots.py           # the four Greek-path charts
  run_all.py             # local pipeline: load -> diagnostics -> aggregate -> plot
  data/                  # put the QC export here (gitignored)
  output/                # charts land here (gitignored)
```

## The collar

A 3-leg structure, opened every `ENTRY_CADENCE` trading days and held to expiry:

| leg        | qty | strike (default) | role                                   |
|------------|-----|------------------|----------------------------------------|
| long put   | +1  | ATM (0%)         | the floor                              |
| short put  | -1  | -7%              | below the floor; sets buffer width     |
| short call | -1  | +4%              | the cap that finances the structure    |

All strikes are parameters at the top of `main.py` — set them to match your live
study config before the first real run.

`main.py` places **no trades**. It tracks "virtual" collars and reads each leg's
Greeks from the chain once per trading day, so the paths are free of fill/assignment
noise. Greeks are aggregated as `signed_qty * 100 * per_share_greek`, i.e. per one
collar with the 100x contract multiplier already baked in. `INCLUDE_UNDERLYING`
(default off) adds +100 delta/collar if you want the net exposure including a long
SPY overlay rather than the option-only overlay.

## Step 1 — run the collector on QuantConnect

1. New Python algorithm in the QC cloud IDE; paste in `quantconnect/main.py`.
2. Tune the params block (window, cadence, strike offsets, DTE band).
3. Backtest. Watch the monthly `HEARTBEAT` lines and the `FUNNEL` summary at the end.
   - `obs_logged` should be in the thousands; large `obs_skipped_*` means the chain
     filter (`STRIKE_RANGE`) is too tight for the moves in your window — widen it.
   - If `obs_logged` is ~0, your data subscription may not serve daily options:
     set `OPTION_RESOLUTION = Resolution.Minute` and rerun.

## Step 2 — get the data out

Either works; `load_data.py` accepts both:
- **CSV (cleaner):** open the **Object Store** tab, download `collar_greek_paths.csv`,
  drop it in `data/`.
- **Log:** download the backtest log `.txt`; the loader extracts the `DATA,` rows.

## Step 3 — run the charts locally (PyCharm)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_all.py --input data/collar_greek_paths.csv
# or by calendar days to expiry, dropping thin buckets:
python run_all.py --input data/collar_greek_paths.csv --x dte --min-count 10
```

Charts and an `aggregate_*.csv` summary table land in `output/`.

## Next: testing the signals

`held_days` paths suggest the timing signals; `dte` paths suggest the decay-driven
ones. Once a signal looks promising (e.g. theta crossing a threshold, gamma turning
up near expiry), the natural follow-up is a second QC run that actually trades the
collar and exits on that rule, compared against hold-to-expiry on net P&L after the
bid-ask haircut and commissions.
