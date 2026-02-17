"""Download one day's UK generation mix from the Carbon Intensity API.

Provides:
- fetch_generation_for_day(date_str) -> list of period entries for the day
- save_json(data, filename) to persist payloads

This module requests the day's generation mix via the API endpoint:
https://api.carbonintensity.org.uk/generation/{from}/{to}
and returns the list of period entries (skipping the first partial interval).
"""

import argparse
import json
from datetime import datetime, timedelta

import requests


def fetch_generation_for_day(date_str: str) -> list[dict[str, object]]:
    """Fetch generation mix entries for the given date.

    The function requests the day's generation mix from the Carbon Intensity API
    and returns a list of period entries. The first returned entry is commonly
    the current (possibly incomplete) half-hour and is skipped.
    """
    # date_str must be YYYY-MM-DD
    day_start = datetime.strptime(date_str, "%Y-%m-%d")
    day_end = day_start + timedelta(days=1)

    # Build ISO timestamps and query the API once for the full day
    from_ts = day_start.isoformat()
    to_ts = day_end.isoformat()
    url = f"https://api.carbonintensity.org.uk/generation/{from_ts}/{to_ts}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    # Return the day's period entries, skipping the first (partial) interval
    return resp.json().get("data", [])[1:]


def save_json(data: object, filename: str) -> None:
    """Save JSON-serializable `data` to `filename` (pretty-printed)."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download one day's UK generation mix from the Carbon Intensity API"
    )
    parser.add_argument(
        "date",
        help="Date to download in YYYY-MM-DD (defaults to today's UTC date)",
        default=datetime.now().date().isoformat(),
    )
    args = parser.parse_args()

    payload = fetch_generation_for_day(args.date)

    out_filename = f"data/generation_mix_{args.date}.json"
    save_json(payload, out_filename)
    print(f"Saved generation data for {args.date} to {out_filename}")
