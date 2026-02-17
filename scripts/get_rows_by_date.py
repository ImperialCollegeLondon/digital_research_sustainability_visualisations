"""Read a CSV of settlement (demand) data and return rows for a given date.

Designed to work with the project data file `data/demanddata_2026.csv`.

Typical usage:
  python3 energy-demand-mix/scripts/get_rows_by_date.py 2026-01-01
  python3 energy-demand-mix/scripts/get_rows_by_date.py 2026-01-01 \
    --input data/demanddata_2026.csv --output out.csv

Features:
- Parse `SETTLEMENT_DATE` into datetimes (best-effort).
- Accept ISO date strings (e.g. "2026-01-01") or any format pandas accepts.
- Print the filtered DataFrame to stdout by default, or save to CSV with --output.
- Exit non-zero with a message when no rows are found.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = Path("data/demanddata_2026.csv")


def load_csv_with_date(
    csv_path: Path, date_col: str = "SETTLEMENT_DATE"
) -> pd.DataFrame:
    """Load CSV into a DataFrame and ensure the date column is parsed to datetime64.

    Parameters
    - csv_path: path to CSV file
    - date_col: name of the date column to parse

    Returns:
    - pandas.DataFrame with `date_col` as datetime64[ns] (or with NaT if parsing failed)
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")

    # Try reading with parse_dates first; fall back to a plain read if that fails
    try:
        df = pd.read_csv(csv_path, parse_dates=[date_col])
    except ValueError, KeyError:
        # If parse_dates failed because the column wasn't found, read normally
        df = pd.read_csv(csv_path)

    # Ensure the date column exists
    if date_col not in df.columns:
        raise KeyError(
            f"Expected date column '{date_col}' not found. Columns: {list(df.columns)}"
        )

    # Coerce the column to datetimes (safe)
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    return df


def filter_rows_for_date(
    df: pd.DataFrame, date_input: str, date_col: str = "SETTLEMENT_DATE"
) -> pd.DataFrame:
    """Return rows from `df` where the date_col matches `date_input`'s date part.

    Parameters:
    - df: DataFrame with a datetime-like `date_col`.
    - date_input: date string (e.g. '2026-01-01') - will be parsed by pandas.
    - date_col: name of date column in df.

    Returns:
    - Filtered DataFrame with rows for that date (empty DataFrame if none).
    """
    # Parse the requested date to a date object
    try:
        requested_ts = pd.to_datetime(date_input)
    except Exception as exc:
        raise ValueError(
            f"Could not parse the requested date '{date_input}': {exc}"
        ) from exc

    if requested_ts is pd.NaT:
        raise ValueError(f"Requested date '{date_input}' parsed to NaT")

    # Ensure date column is datetime-like
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    # Filter: use date equality (ignore time-of-day)
    requested_date = requested_ts.date()
    mask = df[date_col].dt.date == requested_date

    return df.loc[mask].copy()


def get_rows_for_date(
    csv_path: Path | str, date: str, date_col: str = "SETTLEMENT_DATE"
) -> pd.DataFrame:
    """Loads the CSV at `csv_path` and returns DataFrame containing all rows for `date`.

    Parameters:
    - csv_path: path to the CSV file (Path or string). If relative, resolved
      relative to the current working directory.
    - date: date string parseable by pandas (e.g. '2026-01-01').
    - date_col: name of the date column to use (default 'SETTLEMENT_DATE').

    Returns:
    - pandas.DataFrame with matching rows (may be empty).
    """
    path_obj = Path(csv_path) if not isinstance(csv_path, Path) else csv_path
    df = load_csv_with_date(path_obj, date_col=date_col)
    return filter_rows_for_date(df, date, date_col=date_col)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments and return an argparse.Namespace.

    This function exposes the CLI options used by the script.
    """
    parser = argparse.ArgumentParser(
        description="Filter demand CSV rows by SETTLEMENT_DATE."
    )
    parser.add_argument(
        "date",
        help="Date to filter by (e.g. 2026-01-01).",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input CSV path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Save filtered rows to this CSV path (otherwise print to stdout).",
    )
    parser.add_argument(
        "--columns",
        "-c",
        action="store_true",
        help="If set, print the available columns in the CSV and exit.",
    )
    parser.add_argument(
        "--date-col",
        type=str,
        default="SETTLEMENT_DATE",
        help="Name of the date column to use (default: SETTLEMENT_DATE).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Parse CLI arguments, load the CSV, filter rows for the requested date and
    either print the results or save them to a CSV. Returns an exit code.
    """
    args = parse_args(argv)

    try:
        df = load_csv_with_date(args.input, date_col=args.date_col)
    except Exception as exc:
        print(f"Error loading CSV: {exc}", file=sys.stderr)
        return 2

    if args.columns:
        # Print columns and exit
        print("Columns found in CSV:")
        for col in df.columns:
            print(f" - {col}")
        return 0

    try:
        result = filter_rows_for_date(df, args.date, date_col=args.date_col)
    except Exception as exc:
        print(f"Error filtering rows: {exc}", file=sys.stderr)
        return 3

    if result.empty:
        print(f"No rows found for date {args.date}", file=sys.stderr)
        return 4

    if args.output:
        # Ensure parent directory exists
        outp = args.output
        if outp.parent and not outp.parent.exists():
            outp.parent.mkdir(parents=True, exist_ok=True)
        try:
            result.to_csv(outp, index=False)
            print(f"Wrote {len(result)} rows for date {args.date} to: {outp}")
        except Exception as exc:
            print(f"Failed to write output CSV: {exc}", file=sys.stderr)
            return 5
    else:
        # Print to stdout — use to_string for nicer full table display
        pd.set_option("display.width", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.max_columns", None)
        print(result.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
