"""yearly_intensity_stats.py.

Utilities to fetch daily carbon intensity statistics for an entire year.

This script contains a small helper to call the Carbon Intensity API's
/intensity/stats/{from}/{to} endpoint once per day for a given year and return
the day's reported intensity statistics. A short sleep is applied between API
requests to avoid overloading the service.

The module can be invoked as a simple script (see the `main` block) and by
default writes CSV rows with columns: index,mean,max,min.

This file intentionally keeps the interface minimal so it can be used in
batch jobs or by other scripts in this repository.
"""

import argparse
import sys
from csv import DictWriter
from datetime import date, timedelta
from pathlib import Path
from time import sleep

import requests

DEFAULT_BASE = "https://api.carbonintensity.org.uk"
DEFAULT_SLEEP = 0.5
DEFAULT_TIMEOUT = 10


def _iso_day_range(dt: date) -> tuple[str, str]:
    """Return (from_iso, to_iso) for the given date in YYYY-MM-DDT00:00Z form."""
    from_iso = dt.strftime("%Y-%m-%dT00:00Z")
    to_iso = (dt + timedelta(days=1)).strftime("%Y-%m-%dT00:00Z")
    return from_iso, to_iso


def fetch_yearly_intensity_stats(
    year: int,
    base_url: str = DEFAULT_BASE,
    sleep_between: float = DEFAULT_SLEEP,
    timeout: int = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> list[dict[str, object]]:
    """Fetch per-day intensity stats for every day in `year`.

    Returns a list of the raw JSON dicts for each day (the 'data' element's
    first entry is used where applicable). On HTTP errors the exception is
    propagated.
    """
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    total_days = (end - start).days

    sess = session or requests.Session()
    rows: list[dict[str, object]] = []
    for i in range(total_days):
        cur = start + timedelta(days=i)
        from_iso, to_iso = _iso_day_range(cur)
        url = f"{base_url.rstrip('/')}/intensity/stats/{from_iso}/{to_iso}"

        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()

        j = resp.json()
        # Attempt to extract the stats payload in a tolerant way
        data = j.get("data", [])
        if data and isinstance(data, list):
            # Use first object if present
            rows.append(data[0])
        else:
            # If the shape is unexpected, append an empty dict to preserve ordering
            rows.append({})

        # sleep between calls to be polite
        if i < total_days - 1:
            sleep(max(0.0, sleep_between))

    return rows


def _extract_row_from_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize a stats payload into index/mean/max/min fields.

    The function looks for common keys such as 'average' or 'mean' for the mean
    and 'min'/'max' for bounds. If a key is missing the value will be None.
    """
    if not payload:
        return {"mean": None, "max": None, "min": None}

    # Common shapes: payload may itself be aggregated or may contain nested dicts
    mean = payload.get("average") or payload.get("mean") or payload.get("avg")
    maxv = payload.get("max")
    minv = payload.get("min")

    # Some variants nest values under an 'intensity' key
    if (
        mean is None
        and "intensity" in payload
        and isinstance(payload["intensity"], dict)
    ):
        mean = payload["intensity"].get("actual") or payload["intensity"].get(
            "forecast"
        )

    return {"mean": mean, "max": maxv, "min": minv}


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: fetch a year's stats and write a CSV to stdout or file."""
    p = argparse.ArgumentParser(
        description="Fetch yearly intensity stats and write CSV"
    )
    p.add_argument("year", type=int, help="Year to fetch (e.g. 2025)")
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help="Output CSV path (default: stdout)",
    )
    p.add_argument(
        "--base",
        "-b",
        default=DEFAULT_BASE,
        help=f"API base URL (default: {DEFAULT_BASE})",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP,
        help="Seconds to sleep between requests",
    )
    p.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-request timeout"
    )
    args = p.parse_args(argv)

    try:
        stats = fetch_yearly_intensity_stats(
            args.year,
            base_url=args.base,
            sleep_between=args.sleep,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"Failed to fetch yearly stats: {exc}", file=sys.stderr)
        return 1

    # Prepare output
    out_path = args.out
    out_fh = sys.stdout
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_fh = out_path.open("w", encoding="utf-8")

    csv_writer = DictWriter(out_fh, fieldnames=["index", "mean", "max", "min"])
    csv_writer.writeheader()
    for idx, payload in enumerate(stats):
        row = _extract_row_from_payload(payload)
        csv_writer.writerow(
            {
                "index": idx,
                "mean": row.get("mean"),
                "max": row.get("max"),
                "min": row.get("min"),
            }
        )

    if out_path:
        out_fh.close()
        print(f"Wrote CSV to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
