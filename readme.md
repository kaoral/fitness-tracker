# Fitness Tracker

A local, personal Flask website for exploring a read-only Gadgetbridge fitness export. The dark dashboard includes workouts and their detail charts, daily activity, recorded sleep, stress readings, source coverage, and CSV downloads.

## Run locally

Use Python 3.12 or newer. From the project folder in your terminal:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app run --debug
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. Then open <http://127.0.0.1:5000>. Keep Flask's default loopback address for local use.

Place the exported database at `instance/Gadgetbridge.db`. This directory and all local health data are excluded from Git. The application opens SQLite with `mode=ro`, reuses one connection per request, and closes it afterwards. It cannot import, modify, or add records to the export. To refresh data, stop the app, replace the export, and start it again. No database server is needed for SQLite.

## Pages and exports

- **Overview:** totals, recent steps/sleep, historical workout volume, stress points, and source coverage. Different sources have different date ranges.
- **Workouts:** date/type filters, sorting, all recorded workouts, training charts, and individual workout detail with heart rate, pace, altitude, splits, and available device estimates.
- **Daily:** choose a date or navigate between dates with records; view observed steps, heart-rate and stress samples, sleep, and recording coverage.
- **Sleep and stress:** source-specific views with date filters and CSV downloads.
- **Data sources:** provenance, observed ranges, counts, interpretation rules, and limitations.
- **Appearance:** accent presets, compact layout, reset, and chart visibility preferences. Settings are stored in this browser only.

CSV endpoints are `/exports/daily.csv`, `/exports/workouts.csv`, `/exports/sleep.csv`, and `/exports/stress.csv`. Optional `start=YYYY-MM-DD` and `end=YYYY-MM-DD` filters are inclusive. Workout exports also accept the same `type` and `sort` choices as the workout page.

The daily CSV includes one row per calendar day across the selected range within the recorded date span. Empty cells mean unavailable measurements, while valid measured zeros remain zero. `recorded_minutes` and sample counts describe coverage. A zero `workout_count` means no recorded workout in the export; it does not establish that no exercise occurred. Times use Europe/Berlin and include an offset when a timestamp is present. Distances are kilometres, durations seconds/hours as named, pace seconds per kilometre, and heart rate beats per minute.

## Customize the design

Edit `static/css/theme.css` for the central colors, surfaces, borders, typography, radius, spacing, and chart colors. `static/css/app.css` controls component layouts. Theme tokens are mapped to Tabler's CSS variables and used by the charts, so the two stay consistent. Appearance presets can override the accent; reset saved preferences when checking a theme-file change.

The UI uses [Tabler](https://docs.tabler.io/ui/getting-started/customize), a Bootstrap-based external component framework. Charts use [Plotly.js](https://plotly.com/javascript/), with hover, zoom, legend controls, and image download. Both are pinned and served from `static/vendor/`; no Node build, remote CDN, cloud account, or external font is required to run the site. Edit Jinja templates to reuse other Tabler components rather than modifying vendor files.

`static/vendor/manifest.json` records the asset versions, original URLs and hashes. License files are included. When upgrading, download the chosen official version, update its manifest and license, and check the pages on desktop and mobile.

## Code structure

- `app.py`: Flask application factory, routes, filters, formatters, and CSV responses.
- `database.py`: read-only queries and Flask connection lifecycle.
- `analytics.py`: timestamp/unit decoding, interval aggregation, daily rows, coverage, and workout details.
- `charts.py`: Python dictionaries describing charts; Plotly renders them in the browser.
- `templates/`: shared page layout and page-specific HTML.
- `static/`: editable styling/behavior and local third-party assets.
- `tests/`: synthetic-database regression checks, with no real health records.

This keeps Python calculations separate from HTML and styling while remaining a small Flask project. pandas and SQLAlchemy are unnecessary for the current read-only export; CSVs can be analyzed in pandas separately.

## Data interpretation

Workout and activity timestamps are Unix seconds; stress and base-summary timestamps are milliseconds. Group daily rows in Europe/Berlin, including daylight-saving changes. Source 11 activity has paired interval markers: only begin markers are counted. Heart-rate byte decoding applies only to documented byte fields after missing values are excluded.

Sleep shows **recorded TruSleep source 10 intervals**, grouped into sessions across recording gaps of at most five minutes. Duration counts only the union of recorded intervals, excludes gaps, and is assigned to the wake date. Source 13 sleep kinds lack verified stage meanings and are not mixed into totals. This does not supply a verified light/deep/REM breakdown or a sleep score.

Workout labels, unit-bearing summary metrics, and recorded kilometre splits use Gadgetbridge's export/parser semantics. Training effects, recovery, estimated oxygen uptake and calculated heart-rate zones remain source-reported estimates. Daily calorie/distance encoding and implausible workout-load values are omitted until verified. Missing tables degrade to available sections and explicit warnings; a missing database gives a clear unavailable page without creating a file.

Primary decoding references: [Huawei sample provider](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/HuaweiSampleProvider.java) and [Huawei workout parser](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiWorkoutGbParser.java).

## Verify

```sh
python -m unittest discover -s tests -v
```

Tests use synthetic records, never your health export. Keep `instance/`, CSV exports, configuration secrets, and exploration files out of commits. Review `git status` and the diff before committing.

## Future additions

A separate writable application database can later hold daily journals and imported Renpho measurements. Automated ingestion, phone access, authentication, richer analysis, and AI questions can be added after the source formats and hosting requirements are agreed. This version explores the current local export.
