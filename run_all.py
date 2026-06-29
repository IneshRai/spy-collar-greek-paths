"""Run the full local pipeline: load the QC export, print diagnostics, aggregate
the Greek paths, and write the charts + an aggregate table.

Examples
--------
    python run_all.py --input data/collar_greek_paths.csv
    python run_all.py --input data/backtest_log.txt --x dte --min-count 10
"""

import argparse
import os

from src.load_data import load_greek_paths
from src.aggregate import aggregate_by, GREEKS
from src.plots import plot_grid


def diagnostics(df):
    print("=" * 60)
    print("LOAD DIAGNOSTICS")
    print("=" * 60)
    print(f"rows loaded        : {len(df):,}")
    print(f"unique collars     : {df['collar_id'].nunique():,}")
    print(f"date range         : {df['date'].min()}  ->  {df['date'].max()}")
    print(f"held_days range    : {df['held_days'].min()} -> {df['held_days'].max()}")
    print(f"NaN greeks (anyrow): {df[GREEKS].isna().any(axis=1).sum():,}")
    obs = df.groupby("held_days").size()
    thin = obs[obs < 10]
    if len(thin):
        print(f"thin buckets (<10) : held_days {list(thin.index)}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Aggregate SPY collar Greek paths.")
    ap.add_argument("--input", required=True, help="QC log .txt or exported .csv")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--x", default="held_days", choices=["held_days", "dte"],
                    help="x-axis: trading days held (default) or calendar days to expiry")
    ap.add_argument("--min-count", type=int, default=5,
                    help="drop x-buckets with fewer than this many samples")
    args = ap.parse_args()

    df = load_greek_paths(args.input)
    diagnostics(df)

    agg = aggregate_by(df, x_col=args.x, min_count=args.min_count)

    os.makedirs(args.outdir, exist_ok=True)
    agg_csv = os.path.join(args.outdir, f"aggregate_{args.x}.csv")
    agg.to_csv(agg_csv, index=False)
    print(f"wrote aggregate table -> {agg_csv}")

    for p in plot_grid(agg, args.outdir, x_col=args.x):
        print(f"wrote chart           -> {p}")


if __name__ == "__main__":
    main()
