# Energy-Demand-Mix

Description for project.

This is a Python application that uses [uv] for packaging and dependency management.
It  provides [`pre-commit`][pre-commit] hooks for various linters
and formatters and automated tests using [`pytest`][pytest] and [GitHub Actions].
Pre-commit hooks are automatically kept updated with a dedicated GitHub Action, this can
be removed and replaced with [pre-commit.ci] if using a public repo. The package version
is dynamically generated from the most recent git tag using
[`setuptools-scm`][setuptools-scm].

It was developed by the [Imperial College Research Software Engineering Team].

## Usage

This repository includes a small set of utility scripts to fetch UK carbon intensity data, compute daily/yearly statistics, and produce plots.

Quick environment setup

1. Follow the [Download and install uv] instructions for your OS.

2. Install dependencies and create the virtual environment:

```bash
uv sync --all-groups
```

1. Activate the virtual environment, or just preface your commands with `uv run` to use
the virtual environment (see [uv activate] for more info):

    ```bash
    source .venv/bin/activate
    <command>
    ```

Scripts overview and examples

1) Fetch half-hourly intensity for a single date

- Script: `scripts/fetch_intensity.py`
- Example (fetch and save CSV):

```bash
python scripts/fetch_intensity.py 2026-01-12 --out data/intensity_2026-01-12.csv
```

The script caches JSON responses under `data/` by default.

1) Compute daily min/max for an entire year

- Script: `scripts/yearly_intensity_stats.py`
- Example:

```bash
python scripts/yearly_intensity_stats.py 2025 --out data/yearly_intensity_stats_2025.csv
```

Notes:

- The script calls the Carbon Intensity API once per day and sleeps briefly between requests (default 0.5s). Adjust with `--sleep` as needed.
- Output CSV fields may include `date,min_actual,max_actual,min_forecast,max_forecast` (newer script) or the older `index,mean,max,min` shape depending on how it was produced.

1) Plot yearly statistics (mean with shaded min/max)

- Script: `energy-demand-mix/scripts/plot_yearly_stats.py`
- Example (map integer day indices to calendar dates with `--year` and save PNG):

```bash
python scripts/plot_yearly_stats.py data/yearly_intensity_stats_2025.csv --year 2025 --out figures/2025_yearly_stats.png
```

Behavior:

- If the CSV contains a `date` column it will use those dates for the x-axis.
- If the CSV supplies integer `index` values, pass `--year` to map day indices to calendar dates (day 0 -> YYYY-01-01).
- The script draws the daily mean as a solid line and shades the area between min and max.

1) Plot a single day's demand, generation mix and intensity

- Script: `scripts/plot_day.py`
- Example:

```bash
python scripts/plot_day.py 2026-01-12 --demand data/demand_2026-01-12.csv --mix data/generation_mix_2026-01-12.json --intensity data/intensity_2026-01-12.csv --out figures/2026-01-12.png --show
```

Tips and troubleshooting

- API rate limiting: the scripts include sleeps and retry behaviour, but if you plan large numbers of requests increase `--sleep` to be conservative.
- CSV column names: `plot_yearly_stats.py` accepts both `index,mean,max,min` and CSVs with a `date` column. If your CSV uses other names, either rename columns or modify the script mapping.
- Headless environments (no display): save figures to `--out` and avoid `--show`.

## Updating Dependencies

Use the commands `uv add <package>` and `uv remove <package>` to add or remove dependencies.

- Use the optional flag `--dev` to add/remove development dependencies.
- Include the optional flag `--group <group-name>` to add/remove dependencies from specific groups.
- These will automatically update the `pyproject.toml` file.

For further information, see the [uv] docs for managing dependencies.

[uv]: https://docs.astral.sh/uv
[pre-commit]: https://pre-commit.com/
[pytest]: https://pytest.org/
[GitHub Actions]: https://github.com/features/actions
[pre-commit.ci]: https://pre-commit.ci
[setuptools-scm]: https://setuptools-scm.readthedocs.io/en/latest/
[Imperial College Research Software Engineering Team]: https://www.imperial.ac.uk/admin-services/ict/self-service/research-support/rcs/service-offering/research-software-engineering/
[Download and install uv]: https://docs.astral.sh/uv/getting-started/installation/
[uv activate]: https://docs.astral.sh/uv/pip/environments/
