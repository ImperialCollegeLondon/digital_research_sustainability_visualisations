#!/usr/bin/env python3
"""plot_day.py.

Plot a single day's system demand, generation mix and carbon intensity.

Key points:
- Loads demand CSV (default: data/demand_{date}.csv). Expected columns:
  SETTLEMENT_DATE, SETTLEMENT_PERIOD, ENGLAND_WALES_DEMAND.
- Loads generation mix JSON (default: data/generation_mix_{date}.json). Each
  period entry should contain a 'generationmix' list of {"fuel", "perc"} items.
- Loads intensity CSV (default: data/intensity_{date}.csv). Expected columns:
  from, to, forecast, actual, index. The first intensity row is discarded.
- Aligns/truncates the three inputs to the same length and computes timestamps
  from settlement fields (30-minute periods).
- Produces a multi-panel matplotlib figure with a datetime x-axis and 2-hour
  major ticks; adds simple annotations for intraday dynamics.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Defaults (relative to repo root)
DATA_DIR = Path("data")
DEMAND_TEMPLATE = "demand_{date}.csv"
MIX_TEMPLATE = "generation_mix_{date}.json"
INTENSITY_TEMPLATE = "intensity_{date}.csv"


def load_demand(path: Path) -> pd.DataFrame:
    """Load demand CSV and validate required column."""
    if not path.exists():
        raise FileNotFoundError(f"Demand CSV not found: {path}")
    df = pd.read_csv(path)
    if "ENGLAND_WALES_DEMAND" not in df.columns:
        raise KeyError("demand CSV must contain 'ENGLAND_WALES_DEMAND'")
    # sort by settlement period if present
    if "SETTLEMENT_PERIOD" in df.columns:
        df = df.sort_values("SETTLEMENT_PERIOD").reset_index(drop=True)
    return df


def load_mix(path: Path) -> pd.DataFrame:
    """Load generation-mix JSON and convert to a DataFrame.

    Returns a DataFrame with one row per period and a column for each fuel.
    Missing fuel entries are filled with 0.0.
    """
    if not path.exists():
        raise FileNotFoundError(f"Generation mix JSON not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("generation mix JSON expected to be a list of period objects")
    rows = []
    for entry in data:
        gm = entry.get("generationmix", []) or []
        row = {e.get("fuel"): float(e.get("perc", 0.0)) for e in gm}
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.columns.size > 0:
        df = df.reindex(sorted(df.columns), axis=1)
    return df.fillna(0.0)


def load_intensity(path: Path) -> pd.DataFrame:
    """Load intensity CSV, parse timestamps and coerce actual to numeric."""
    if not path.exists():
        raise FileNotFoundError(f"Intensity CSV not found: {path}")
    df = pd.read_csv(path)
    req = {"from", "actual"}
    if not req.issubset(df.columns):
        raise KeyError(f"Intensity CSV must contain columns: {req}")
    df["from"] = pd.to_datetime(df["from"], utc=True)
    if "to" in df.columns:
        df["to"] = pd.to_datetime(df["to"], utc=True)
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    return df


def timestamps_from_demand(demand_df: pd.DataFrame) -> pd.DatetimeIndex:
    """Compute timestamps from settlement date and period.

    Each settlement period is 30 minutes. If the expected columns are
    missing, fall back to a simple 30-minute sequence starting at midnight UTC.
    """
    if (
        "SETTLEMENT_DATE" in demand_df.columns
        and "SETTLEMENT_PERIOD" in demand_df.columns
    ):
        dates = pd.to_datetime(demand_df["SETTLEMENT_DATE"], errors="coerce")
        periods = pd.to_numeric(demand_df["SETTLEMENT_PERIOD"], errors="coerce").astype(
            int
        )
        offsets = pd.to_timedelta((periods - 1) * 30, unit="m")
        ts = dates + offsets
        # ensure tz-aware in UTC
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        return pd.DatetimeIndex(ts)

    # fallback: create a simple 30-minute sequence starting at midnight UTC
    base = pd.Timestamp.now(tz="UTC").normalize()
    return pd.date_range(start=base, periods=len(demand_df), freq="30T", tz="UTC")


def align_truncate(dfs: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Truncate DataFrames to the same minimum length.

    Returns new DataFrames with reset integer indices.
    """
    lengths = [len(d) for d in dfs]
    if not lengths:
        return list(dfs)
    n = min(lengths)
    if any(length != n for length in lengths):
        logger.warning("Input lengths differ %s; truncating all to %d rows", lengths, n)
    return [d.iloc[:n].reset_index(drop=True) for d in dfs]


def plot_day(
    date: str,
    demand_csv: Path | None = None,
    mix_json: Path | None = None,
    intensity_csv: Path | None = None,
    output_path: Path | None = None,
    show: bool = False,
) -> plt.Figure:
    """Main plotting function. Returns the matplotlib Figure."""
    # Resolve default file locations
    demand_path = (
        Path(demand_csv) if demand_csv else DATA_DIR / DEMAND_TEMPLATE.format(date=date)
    )
    mix_path = Path(mix_json) if mix_json else DATA_DIR / MIX_TEMPLATE.format(date=date)
    intensity_path = (
        Path(intensity_csv)
        if intensity_csv
        else DATA_DIR / INTENSITY_TEMPLATE.format(date=date)
    )

    # Load inputs
    demand = load_demand(demand_path)
    mix = load_mix(mix_path)
    intensity = load_intensity(intensity_path)

    # Discard the first intensity row as requested
    if len(intensity) > 0:
        intensity = intensity.iloc[1:].reset_index(drop=True)

    # Align/truncate to minimum length
    demand_tr, mix_tr, intensity_tr = align_truncate([demand, mix, intensity])

    # Compute timestamps and arrays
    times = timestamps_from_demand(demand_tr)
    demand_vals = demand_tr["ENGLAND_WALES_DEMAND"].astype(float).to_numpy()
    pct_arr = (
        mix_tr.fillna(0.0).astype(float).to_numpy().T
        if mix_tr.shape[1] > 0
        else np.zeros((0, len(times)))
    )
    fuels = list(mix_tr.columns)
    intensity_vals = (
        intensity_tr["actual"].astype(float).to_numpy()
        if "actual" in intensity_tr.columns
        else np.full(len(times), np.nan)
    )
    if len(intensity_vals) != len(times):
        intensity_vals = np.resize(intensity_vals, len(times))

    # Create figure
    fig, (ax_d, ax_m, ax_i) = plt.subplots(
        3,
        1,
        figsize=(14, 10),
        sharex=True,
        gridspec_kw={"height_ratios": (1, 1.2, 0.8)},
    )
    fig.suptitle(
        f"System demand, generation mix and carbon intensity for {date}", fontsize=14
    )

    # Top: demand line (MW)
    ax_d.plot(times, demand_vals, color="tab:blue", lw=2, marker="o", markersize=4)
    ax_d.set_ylabel("Demand (MW)")
    ax_d.grid(axis="y", linestyle="--", alpha=0.35)
    ax_d.legend(["England & Wales demand (MW)"], loc="upper left", fontsize="small")

    # Middle: generation mix (percent stacked)
    if pct_arr.size == 0:
        ax_m.text(
            0.5,
            0.5,
            "No generation mix data",
            ha="center",
            va="center",
            transform=ax_m.transAxes,
        )
    else:
        cmap = plt.get_cmap("tab20")
        colors = [cmap(i % 20) for i in range(pct_arr.shape[0])]
        ax_m.stackplot(
            times,
            *[pct_arr[i] for i in range(pct_arr.shape[0])],
            labels=fuels,
            colors=colors,
            alpha=0.85,
        )
        ax_m.legend(loc="upper left", ncol=2, fontsize="small")
    ax_m.set_ylabel("Generation mix (%)")
    ax_m.set_ylim(0, 100)
    ax_m.grid(axis="y", linestyle="--", alpha=0.35)

    # Bottom: carbon intensity (actual)
    ax_i.plot(times, intensity_vals, color="tab:red", lw=2, marker="s", markersize=4)
    ax_i.set_ylabel("gCO2 / kWh")
    ax_i.grid(axis="y", linestyle="--", alpha=0.35)
    ax_i.legend(["Carbon intensity (actual)"], loc="upper left", fontsize="small")

    # x-axis formatting: major = every 2 hours, minor = hour
    ax_i.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax_i.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_i.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    fig.autofmt_xdate(rotation=45)

    plt.tight_layout(rect=(0, 0.03, 1, 0.95))

    # Save or show
    if output_path:
        outp = Path(output_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(outp, dpi=150)
        logger.info("Saved figure to: %s", outp)
    if show:
        plt.show()

    return fig


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot demand, generation mix and carbon intensity for a given date"
    )
    p.add_argument("date", help="Date to plot (YYYY-MM-DD)")
    p.add_argument(
        "--demand",
        "-d",
        type=Path,
        default=None,
        help="Path to demand CSV (default: data/demand_{date}.csv)",
    )
    p.add_argument(
        "--mix",
        "-m",
        type=Path,
        default=None,
        help="Path to generation mix JSON (default: data/generation_mix_{date}.json)",
    )
    p.add_argument(
        "--intensity",
        "-i",
        type=Path,
        default=None,
        help=(
            "Path to intensity CSV (first row discarded). "
            "Default: data/intensity_{date}.csv"
        ),
    )
    p.add_argument(
        "--out", "-o", type=Path, default=None, help="Path to save figure (png/svg/pdf)"
    )
    p.add_argument("--show", action="store_true", help="Show the plot interactively")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Parse CLI arguments, create the day's plot and handle common errors.
    Returns 0 on success; non-zero on error.
    """
    args = _parse_args(argv)
    try:
        plot_day(
            date=args.date,
            demand_csv=args.demand,
            mix_json=args.mix,
            intensity_csv=args.intensity,
            output_path=args.out,
            show=args.show,
        )
    except FileNotFoundError as exc:
        logger.error("Input file not found: %s", exc)
        return 2
    except KeyError as exc:
        logger.error("Missing expected column or field: %s", exc)
        return 3
    except Exception as exc:
        logger.exception("Failed to create plot: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
