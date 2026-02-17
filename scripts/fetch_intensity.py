#!/usr/bin/env python3
"""fetch_intensity.py.

Fetch carbon intensity data for a given date from the Carbon Intensity API
(endpoint: /intensity/{from}/{to}) and return it as a pandas.DataFrame.

The script provides:
- fetch_intensity_for_date(date, base_url, session, cache_path)
  -> returns a DataFrame with columns: ['from', 'to', 'forecast', 'actual', 'index']
  where 'from' is parsed as UTC datetime and set as the DataFrame index.

- A small CLI for convenience, for example:
    python3 energy-demand-mix/scripts/fetch_intensity.py 2026-01-12
    python3 energy-demand-mix/scripts/fetch_intensity.py 2026-01-12 \
        --out data/intensity_2026-01-12.csv

Notes:
- Default API base URL: https://api.carbonintensity.org.uk
- The API is called for the full day from YYYY-MM-DDT00:00Z to the next day
  YYYY-MM-DDT00:00Z (returns 30-minute intervals).
- The function supports optional local caching (save JSON to disk and reuse).
- Uses a requests.Session with retries to be resilient to transient errors.
"""

import argparse
import json
import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.carbonintensity.org.uk"
DEFAULT_CACHE_DIR = Path("data")


def _build_session(
    total_retries: int = 3,
    backoff_factor: float = 0.3,
    status_forcelist: tuple[int, ...] = (500, 502, 503, 504),
) -> requests.Session:
    """Create a requests.Session with retry behaviour."""
    session = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"]),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _default_cache_path_for(date_str: str, cache_dir: Path | None = None) -> Path:
    cd = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
    cd.mkdir(parents=True, exist_ok=True)
    return cd / f"intensity_{date_str}.json"


def _parse_api_response(json_data: dict[str, list[object]]) -> pd.DataFrame:
    """Parse the API response JSON into a DataFrame.

    Expected top-level structure:
    {
      "data": [
        {
          "from": "YYYY-MM-DDTHH:MMZ",
          "to": "YYYY-MM-DDTHH:MMZ",
          "intensity": { "forecast": 266, "actual": 263, "index": "moderate" }
        }, ...
      ]
    }
    """
    data = json_data.get("data", [])
    rows = []
    for item in data:
        intensity = (item.get("intensity", {}) or {}) if isinstance(item, dict) else {}
        rows.append(
            {
                "from": item.get("from") if isinstance(item, dict) else None,
                "to": item.get("to") if isinstance(item, dict) else None,
                "forecast": intensity.get("forecast")
                if isinstance(intensity, dict)
                else None,
                "actual": intensity.get("actual")
                if isinstance(intensity, dict)
                else None,
                "index": intensity.get("index")
                if isinstance(intensity, dict)
                else None,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["from", "to", "forecast", "actual", "index"]
        ).set_index(pd.Index([], name="from"))

    df = pd.DataFrame(rows)
    # Parse timestamps and set index to the 'from' time in UTC
    df["from"] = pd.to_datetime(df["from"], utc=True)
    df["to"] = pd.to_datetime(df["to"], utc=True)
    df = df.set_index("from")
    # Ensure forecast/actual numeric where possible
    df["forecast"] = pd.to_numeric(df["forecast"], errors="coerce")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    return df


def fetch_intensity_for_date(
    date: str,
    base_url: str = DEFAULT_API_BASE,
    session: requests.Session | None = None,
    cache_path: Path | None = None,
    use_cache: bool = True,
    timeout: int = 10,
) -> pd.DataFrame:
    """Fetch carbon intensity data for a given date.

    Parameters:
      - date: date string in YYYY-MM-DD format (or any format parseable by pandas)
      - base_url: base URL of the API (default is UK Carbon Intensity API)
      - session: optional requests.Session to use (if None one is created)
      - cache_path: optional Path to a JSON file used to cache the API response
      - use_cache: if True and cache_path exists, load from cache instead of calling API
      - timeout: request timeout in seconds

    Returns:
      pandas.DataFrame indexed by the 'from' timestamp (UTC) with columns:
        ['to', 'forecast', 'actual', 'index']
    """
    # Parse date and compute from/to ISO strings: from date@00:00 -> next date@00:00
    try:
        dt = pd.to_datetime(date).normalize()
    except Exception as exc:
        raise ValueError(f"Could not parse date '{date}': {exc}") from exc

    from_iso = dt.strftime("%Y-%m-%dT00:00Z")
    to_dt = dt + timedelta(days=1)
    to_iso = to_dt.strftime("%Y-%m-%dT00:00Z")

    if cache_path is None:
        cache_path = _default_cache_path_for(dt.strftime("%Y-%m-%d"))

    # Load from cache if available and requested
    if use_cache and cache_path.exists():
        try:
            logger.info("Loading intensity data from cache: %s", cache_path)
            with cache_path.open("r", encoding="utf-8") as fh:
                json_data = json.load(fh)
            return _parse_api_response(json_data)
        except Exception as exc:
            logger.warning("Failed to load cache (will refetch): %s", exc)

    # Build URL and session
    url = f"{base_url.rstrip('/')}/intensity/{from_iso}/{to_iso}"
    sess = session if session is not None else _build_session()

    logger.info("Fetching intensity data from API: %s", url)
    resp = sess.get(url, timeout=timeout)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # Surface useful information
        raise RuntimeError(f"API request failed: {exc} - {resp.text[:200]}") from exc

    try:
        json_data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Failed to decode JSON response: {exc}") from exc

    # Cache response (best-effort)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump(json_data, fh, indent=2)
        logger.info("Cached API response to %s", cache_path)
    except Exception as exc:
        logger.debug("Unable to write cache file: %s", exc)

    return _parse_api_response(json_data)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch carbon intensity for a date and return as CSV/DataFrame."
    )
    p.add_argument("date", help="Date to fetch (YYYY-MM-DD)")
    p.add_argument(
        "--base",
        "-b",
        default=DEFAULT_API_BASE,
        help=f"API base URL (default: {DEFAULT_API_BASE})",
    )
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help="If provided, save the resulting DataFrame to this CSV path",
    )
    p.add_argument(
        "--nocache",
        dest="use_cache",
        action="store_false",
        help="Do not use or write a local cache (always fetch fresh data)",
    )
    p.add_argument(
        "--cache-dir",
        dest="cache_dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory where JSON responses are cached (default: data/)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse arguments, fetch intensity data, and optionally save it.

    Returns:
        Exit code (0 on success, non-zero on error).
    """
    args = _parse_args(argv)
    cache_path = _default_cache_path_for(args.date, cache_dir=args.cache_dir)
    try:
        sess = _build_session()
        df = fetch_intensity_for_date(
            args.date,
            base_url=args.base,
            session=sess,
            cache_path=cache_path,
            use_cache=args.use_cache,
            timeout=args.timeout,
        )
    except Exception as exc:
        logger.error("Failed to fetch intensity data: %s", exc)
        return 1

    if df.empty:
        logger.warning("No intensity data returned for %s", args.date)

    # CLI behavior: print a short summary and optionally save
    print(df.to_string())

    if args.out:
        outp = args.out
        outp.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(outp)
        logger.info("Saved intensity CSV to %s", outp)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
