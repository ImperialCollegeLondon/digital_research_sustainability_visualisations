#!/usr/bin/env python3
"""Plot a CSV of daily yearly intensity statistics.

Expected CSV shapes (supported):
- A file with columns: index,mean,max,min
  where `index` is an integer day-of-year starting at 0 (0..364 or 0..365).
- A file with a `date` column (ISO date strings) and numeric `mean`, `min`, `max`
  columns.

The script draws:
- The daily mean as a solid line.
- A shaded area between min and max values (filled band).
- Optional dashed lines at min and max (disabled by default).
- X-axis formatted as months when actual dates are available.

Usage:
    python3 energy-demand-mix/scripts/plot_yearly_stats.py \
        data/yearly_intensity_stats_2025.csv \
        --year 2025 --out figures/2025_yearly_stats.png

If your CSV does not include a `date` column, provide `--year` so the script can
map integer indices to calendar dates (day 0 -> YYYY-01-01).

Options:
    infile          Positional path to the CSV file to plot.
    --year YEAR     Year to map integer day indices onto (optional).
    --out PATH      Output image path (PNG). If omitted a sensible default under
                    data/ will be used if the input file is in data/, otherwise
                    a file named `yearly_stats.png` is used in the current dir.
    --dpi DPI       DPI for saved image (default: 150).
    --show          If set, display the plot interactively.
    --title TEXT    Custom title for the plot.
    --no-bounds     Do not draw dashed lines for min/max (only the shaded area).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot yearly intensity statistics (mean/min/max)."
    )
    p.add_argument(
        "infile",
        type=Path,
        help="Input CSV file with columns like index,mean,max,min or date,mean,min,max",
    )
    p.add_argument(
        "--year",
        "-y",
        type=int,
        default=None,
        help="Year for mapping integer day indices to dates (optional)",
    )
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help="Output image file path (PNG). If omitted a default path is chosen.",
    )
    p.add_argument(
        "--dpi", type=int, default=150, help="Saved image DPI (default: 150)"
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="Show the plot interactively after creating it",
    )
    p.add_argument("--title", "-t", type=str, default=None, help="Optional plot title")
    p.add_argument(
        "--no-bounds",
        action="store_true",
        help="Do not draw dashed boundary lines for min/max (only shaded area)",
    )
    return p.parse_args(argv)


def _infer_output_path(inpath: Path, year: int | None) -> Path:
    if inpath.parent.name == "data":
        # place plots alongside data by default
        name = f"{inpath.stem}.png"
        return (
            inpath.parent.parent / "figures" / name
            if (inpath.parent.parent / "figures").exists()
            else inpath.parent / name
        )
    if year:
        return Path(f"data/yearly_stats_{year}.png")
    return Path("yearly_stats.png")


def _read_csv(infile: Path) -> pd.DataFrame:
    df = pd.read_csv(infile)
    # Normalize column names to lower case for flexibility
    df.columns = [c.strip() for c in df.columns]
    return df


def _prepare_x_and_series(
    df: pd.DataFrame, year: int | None
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, bool]:
    """Return (x, mean, min, max, x_is_dates).

    x is either a pandas.DatetimeIndex or numeric index (pandas.Series).
    """
    cols = {c.lower(): c for c in df.columns}
    # Try date column first (case-insensitive search)
    date_col = None
    for candidate in ("date", "day", "datetime", "timestamp"):
        if candidate in cols:
            date_col = cols[candidate]
            break

    # Identify mean/min/max columns (flexible names)
    mean_col = None
    min_col = None
    max_col = None
    for candidate in ("mean", "average", "avg"):
        if candidate in cols:
            mean_col = cols[candidate]
            break
    for candidate in ("min", "minimum", "min_actual"):
        if candidate in cols:
            min_col = cols[candidate]
            break
    for candidate in ("max", "maximum", "max_actual"):
        if candidate in cols:
            max_col = cols[candidate]
            break

    # Fallback: try fixed names as seen in some files
    if mean_col is None and "mean" in df.columns:
        mean_col = "mean"
    if min_col is None and "min" in df.columns:
        min_col = "min"
    if max_col is None and "max" in df.columns:
        max_col = "max"

    if mean_col is None:
        raise RuntimeError("Could not find a 'mean' column in the CSV.")
    if min_col is None:
        raise RuntimeError("Could not find a 'min' column in the CSV.")
    if max_col is None:
        raise RuntimeError("Could not find a 'max' column in the CSV.")

    # Convert series to numeric, preserving NaN
    mean_s = pd.to_numeric(df[mean_col], errors="coerce")
    min_s = pd.to_numeric(df[min_col], errors="coerce")
    max_s = pd.to_numeric(df[max_col], errors="coerce")

    # Build x axis
    if date_col:
        x = pd.to_datetime(df[date_col], utc=True, errors="coerce")
        # If many values failed to parse, raise an informative error
        if x.isna().sum() > 0:
            raise RuntimeError(f"Failed to parse some dates in column '{date_col}'.")
        return x, mean_s, min_s, max_s, True

    # No date column: look for integer index column
    if "index" in df.columns:
        idx = pd.to_numeric(df["index"], errors="coerce")
        if idx.isna().any():
            # fallback to using the DataFrame's implicit integer index
            idx = pd.Series(range(len(df)))
    else:
        # Use implicit index
        idx = pd.Series(range(len(df)))

    # Map to dates if year provided
    if year is not None:
        start = pd.to_datetime(f"{year}-01-01").tz_localize("UTC")
        x = start + pd.to_timedelta(idx.astype(int), unit="D")
        return x, mean_s, min_s, max_s, True

    # Otherwise return numeric x
    return idx, mean_s, min_s, max_s, False


def plot_yearly_stats(
    infile: Path,
    outpath: Path,
    year: int | None = None,
    dpi: int = 150,
    title: str | None = None,
    show: bool = False,
    draw_bounds: bool = True,
) -> None:
    """Plot the yearly statistics CSV.

    Draw the daily mean as a solid line and shade the area between min and max.
    """
    df = _read_csv(infile)
    x, mean_s, min_s, max_s, x_is_dates = _prepare_x_and_series(df, year)

    # Align series lengths
    n = min(len(x), len(mean_s), len(min_s), len(max_s))
    if n == 0:
        raise RuntimeError("No data available to plot.")
    x = x.iloc[:n] if hasattr(x, "iloc") else x[:n]
    mean_s = mean_s.iloc[:n]
    min_s = min_s.iloc[:n]
    max_s = max_s.iloc[:n]

    # Begin plotting
    fig, ax = plt.subplots(figsize=(12, 5))
    # Plot mean line
    ax.plot(x, mean_s, color="C0", lw=1.8, label="Mean (daily)")

    # Fill between min and max
    ax.fill_between(x, min_s, max_s, color="C0", alpha=0.18, label="Min-Max (daily)")

    # Optionally draw dashed bound lines
    if draw_bounds:
        ax.plot(x, min_s, color="C0", lw=0.8, linestyle="--", alpha=0.6, label="Min")
        ax.plot(x, max_s, color="C0", lw=0.8, linestyle="--", alpha=0.6, label="Max")

    # Labels and title
    ax.set_ylabel("Carbon intensity (gCO2/kWh)")
    ax.set_xlabel("Date" if x_is_dates else "Day index")
    if title:
        ax.set_title(title)
    else:
        # sensible default title
        if year:
            ax.set_title(f"Daily carbon intensity (mean ± min/max) — {year}")
        else:
            ax.set_title("Daily carbon intensity (mean ± min/max)")

    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize="small")

    # Format x-axis when dates are present
    if x_is_dates:
        # Use month ticks for yearly data
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        fig.autofmt_xdate(rotation=0)

    fig.tight_layout()

    # Save figure
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=dpi)
    print(f"Saved plot to {outpath}")

    # Optionally show
    if show:
        plt.show()
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for plotting yearly stats.

    Parse command-line arguments, validate the input file, construct a sensible
    output path (if not provided), and call the plotting routine. Returns 0 on
    success and a non-zero exit code on error.
    """
    args = _parse_args(argv)
    infile: Path = args.infile
    if not infile.exists():
        print(f"Input file not found: {infile}", file=sys.stderr)
        return 2

    outpath: Path = args.out or _infer_output_path(infile, args.year)
    # Normalize to .png extension if not provided
    if outpath.suffix == "":
        outpath = outpath.with_suffix(".png")

    try:
        plot_yearly_stats(
            infile=infile,
            outpath=outpath,
            year=args.year,
            dpi=args.dpi,
            title=args.title,
            show=args.show,
            draw_bounds=not args.no_bounds,
        )
    except Exception as exc:
        print(f"Failed to create plot: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
