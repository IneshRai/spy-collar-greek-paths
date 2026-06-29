"""Load collar Greek-path data exported from QuantConnect.

Accepts either:
  * the exported CSV (ObjectStore key `collar_greek_paths.csv`), or
  * the raw QuantConnect backtest log (.txt), from which we pull the `DATA,` rows.
"""

import pandas as pd

EXPECTED_COLS = [
    "collar_id", "entry_date", "date", "held_days", "held_days_cal", "dte",
    "underlying", "agg_delta", "agg_gamma", "agg_theta", "agg_vega",
    "k_long_put", "k_short_put", "k_short_call",
]

DATE_COLS = ["entry_date", "date"]


def load_greek_paths(path):
    text_path = str(path)

    if text_path.lower().endswith(".csv"):
        df = pd.read_csv(text_path)
    else:
        # treat as a raw QC log; QC prefixes each line with a timestamp, e.g.
        # "2021-01-04 00:00:00 DATA,1,2021-01-04,..."  -> we slice from "DATA,"
        rows, header = [], None
        with open(text_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.rstrip("\n")
                i = line.find("DATA,")
                if i != -1:
                    rows.append(line[i + len("DATA,"):])
                    continue
                h = line.find("HEADER,")
                if h != -1 and header is None:
                    header = line[h + len("HEADER,"):]
        if not rows:
            raise ValueError(
                f"No 'DATA,' rows found in {text_path}. "
                "Pass the QuantConnect log .txt or the exported .csv."
            )
        cols = header.split(",") if header else EXPECTED_COLS
        df = pd.DataFrame([r.split(",") for r in rows], columns=cols)

    # coerce dtypes
    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in df.columns:
        if c not in DATE_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["held_days"]).reset_index(drop=True)
    df["held_days"] = df["held_days"].astype(int)
    if "dte" in df.columns:
        df["dte"] = df["dte"].astype(int)
    return df
