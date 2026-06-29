"""Aggregate per-collar daily Greeks into an average path across many collars."""

import pandas as pd

GREEKS = ["agg_delta", "agg_gamma", "agg_theta", "agg_vega"]


def aggregate_by(df, x_col="held_days", greeks=GREEKS, min_count=1):
    """Group by `x_col` and return mean / median / q25 / q75 / std / count per Greek.

    x_col is typically 'held_days' (trading days since entry) or 'dte'
    (calendar days to expiry). Buckets with fewer than `min_count` samples are
    dropped so the thin tail does not produce noisy averages.
    """
    g = df.groupby(x_col)
    out = pd.DataFrame({"count": g.size()})
    for gk in greeks:
        out[f"{gk}_mean"] = g[gk].mean()
        out[f"{gk}_median"] = g[gk].median()
        out[f"{gk}_q25"] = g[gk].quantile(0.25)
        out[f"{gk}_q75"] = g[gk].quantile(0.75)
        out[f"{gk}_std"] = g[gk].std()
    out = out.reset_index()
    out = out[out["count"] >= min_count].reset_index(drop=True)
    return out
