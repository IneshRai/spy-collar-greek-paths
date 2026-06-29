"""Charts: average aggregate Greek vs held days (or dte), with an IQR band and a
faint sample-count strip so thinning tails are obvious."""

import os

import matplotlib
matplotlib.use("Agg")          # headless backend; safe in PyCharm run configs / CI
import matplotlib.pyplot as plt

GREEK_LABELS = {
    "agg_delta": "Aggregate Delta",
    "agg_gamma": "Aggregate Gamma",
    "agg_theta": "Aggregate Theta",
    "agg_vega":  "Aggregate Vega",
}


def _plot_one(ax, agg, greek, x_col, with_count=False):
    x = agg[x_col].values
    mean = agg[f"{greek}_mean"].values
    q25 = agg[f"{greek}_q25"].values
    q75 = agg[f"{greek}_q75"].values

    ax.fill_between(x, q25, q75, alpha=0.20, label="IQR (25-75%)")
    ax.plot(x, mean, linewidth=2.0, label="mean")
    ax.axhline(0, color="k", linewidth=0.6, alpha=0.5)
    ax.set_title(GREEK_LABELS.get(greek, greek))
    ax.set_xlabel(x_col)
    ax.set_ylabel("per 1 collar (100x mult)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="best")

    if with_count:
        ax2 = ax.twinx()
        ax2.bar(x, agg["count"].values, alpha=0.12, color="grey", width=0.8)
        ax2.set_ylabel("sample count", color="grey")
        ax2.tick_params(axis="y", labelcolor="grey")


def plot_grid(agg, outdir, x_col="held_days", greeks=None):
    """Write a 2x2 grid plus one detailed chart per Greek. Returns the file paths."""
    greeks = greeks or list(GREEK_LABELS.keys())
    os.makedirs(outdir, exist_ok=True)
    paths = []

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, gk in zip(axes.ravel(), greeks):
        _plot_one(ax, agg, gk, x_col, with_count=False)
    fig.suptitle(f"Average collar Greek paths vs {x_col}", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    grid_path = os.path.join(outdir, f"greek_paths_grid_{x_col}.png")
    fig.savefig(grid_path, dpi=150)
    plt.close(fig)
    paths.append(grid_path)

    for gk in greeks:
        fig, ax = plt.subplots(figsize=(8, 5))
        _plot_one(ax, agg, gk, x_col, with_count=True)
        fig.tight_layout()
        p = os.path.join(outdir, f"{gk}_{x_col}.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        paths.append(p)

    return paths
