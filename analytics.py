"""Normalize Gadgetbridge records into plain dictionaries for charts and CSV.

This module describes recorded measurements, not medical conclusions. Unknown
raw units and unverified sleep-stage source 13 are deliberately excluded.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from statistics import mean
from zoneinfo import ZoneInfo

from flask import current_app, g

import database


WORKOUT_TYPES = {1: "Running", 2: "Walking", 5: "Indoor running"}


def display_timezone():
    return ZoneInfo(current_app.config.get("DISPLAY_TIMEZONE", "Europe/Berlin"))


def local_datetime(timestamp, milliseconds=False):
    """Invalid/missing epochs stay absent rather than becoming false 1970 dates."""
    if timestamp is None or isinstance(timestamp, bool) or timestamp == -1:
        return None
    try:
        value = float(timestamp)
        if not math.isfinite(value) or value == -1:
            return None
        return datetime.fromtimestamp(
            value / 1000 if milliseconds else value, timezone.utc
        ).astimezone(display_timezone())
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def measured_number(value, zero=True, allow_negative=False):
    """Treat -1/NULL as absent while retaining valid zeros."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number == -1 or (not allow_negative and number < 0) or (not zero and number == 0):
        return None
    return int(number) if number.is_integer() else number


def heart_rate(value):
    """Huawei Java byte values >=128 can be stored as negative SQLite ints."""
    if value is None or value in (-1, 0):
        return None
    if -128 <= value <= -2:
        value += 256
    return int(value) if 0 < value <= 255 else None


def duration_label(seconds):
    if seconds is None:
        return "Unavailable"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    pieces = []
    if hours:
        pieces.append(f"{hours}h")
    if minutes:
        pieces.append(f"{minutes}m")
    if seconds or not pieces:
        pieces.append(f"{seconds}s")
    return " ".join(pieces)


def _json_summaries(warnings):
    summaries = {}
    invalid = 0
    for row in database.get_base_summaries():
        try:
            value = json.loads(row["SUMMARY_DATA"] or "{}")
            if not isinstance(value, dict):
                raise ValueError("Summary JSON is not an object")
            summaries[(row["START_TIME"], row["DEVICE_ID"], row["USER_ID"])] = value
        except (ValueError, TypeError):
            invalid += 1
    if invalid:
        warnings.append(f"{invalid} workout summary JSON record(s) could not be read.")
    return summaries


def _json_value(summary, key, unit, zero=True, allow_negative=False):
    field = summary.get(key)
    if not isinstance(field, dict) or field.get("unit") != unit:
        return None
    return measured_number(field.get("value"), zero=zero, allow_negative=allow_negative)


def _summary_key(row):
    if local_datetime(row["START_TIMESTAMP"]) is None:
        return None
    return (float(row["START_TIMESTAMP"]) * 1000, row["DEVICE_ID"], row["USER_ID"])


def _workout(row, summary):
    started = local_datetime(row["START_TIMESTAMP"])
    distance = measured_number(row["DISTANCE"])
    seconds = measured_number(row["DURATION"])
    workout_type = measured_number(row["TYPE"])
    result = {
        "id": row["WORKOUT_ID"], "start_iso": started.isoformat() if started else None,
        "date": started.date().isoformat() if started else None,
        "start_label": started.strftime("%d %B %Y, %H:%M:%S").lstrip("0") if started else "Unavailable",
        "type_code": workout_type,
        "type_label": WORKOUT_TYPES.get(workout_type, f"Type {workout_type}" if workout_type is not None else "Unknown type"),
        "distance_km": distance / 1000 if distance is not None else None,
        "duration_s": seconds, "duration_label": duration_label(seconds),
        "steps": measured_number(row["STEP_COUNT"]),
        "calories": measured_number(row["CALORIES"]),
        "avg_hr": _json_value(summary, "averageHR", "bpm", zero=False),
        "max_hr": _json_value(summary, "maxHR", "bpm", zero=False),
        "avg_pace_s": _json_value(summary, "averageKMPaceSeconds", "seconds_km", zero=False),
        "elevation_gain_m": _json_value(summary, "elevationGain", "meters"),
        "metrics": [], "zones": [],
    }
    # Every metric names its original unit-bearing JSON field. Raw workload is
    # omitted because export values are implausible and its units are unverified.
    metric_fields = [
        ("averageHR", "Average heart rate", "bpm", "bpm"),
        ("minHR", "Minimum heart rate", "bpm", "bpm"),
        ("maxHR", "Maximum heart rate", "bpm", "bpm"),
        ("averageKMPaceSeconds", "Average pace", "seconds_km", "s/km"),
        ("maxPace", "Fastest instantaneous pace", "seconds_km", "s/km"),
        ("stepRateAvg", "Average cadence", "spm", "steps/min"),
        ("averageAltitude", "Average elevation", "meters", "m"),
        ("minAltitude", "Minimum elevation", "meters", "m"),
        ("maxAltitude", "Maximum elevation", "meters", "m"),
        ("elevationGain", "Elevation gain", "meters", "m"),
        ("elevationLoss", "Elevation loss", "meters", "m"),
        ("maximumOxygenUptake", "Watch VO₂ max estimate", "unit_ml_kg_min", "ml/kg/min"),
        ("recoveryTime", "Watch recovery estimate", "unit_hours", "h"),
        ("aerobicTrainingEffect", "Watch aerobic training effect", "", ""),
        ("anaerobicTrainingEffect", "Watch anaerobic training effect", "", ""),
    ]
    for key, label, source_unit, display_unit in metric_fields:
        value = _json_value(summary, key, source_unit, allow_negative=key in {"averageAltitude", "minAltitude", "maxAltitude"})
        if value is not None:
            result["metrics"].append({
                "label": label, "value": value, "unit": display_unit,
                "source": f"BASE_ACTIVITY_SUMMARY.SUMMARY_DATA.{key}",
            })
    for key, label in [
        ("hrZoneWarmUp", "Warm-up"), ("hrZoneFatBurn", "Fat burn"),
        ("hrZoneAerobic", "Aerobic"), ("hrZoneAnaerobic", "Anaerobic"),
        ("hrZoneExtreme", "Extreme"),
    ]:
        value = _json_value(summary, key, "seconds")
        if value is not None:
            result["zones"].append({"label": label, "seconds": value})
    return result


def _stress(rows, warnings=None):
    records = []
    invalid_timestamps = 0
    for row in rows:
        value = measured_number(row["STRESS"])
        # Device stress index is 0–100; out-of-range values are absent.
        if value is None or value > 100:
            continue
        timestamp = local_datetime(row["TIMESTAMP"], milliseconds=True)
        if timestamp is None:
            invalid_timestamps += 1
            continue
        records.append({"date": timestamp.date().isoformat(), "timestamp_iso": timestamp.isoformat(), "value": value})
    if invalid_timestamps and warnings is not None:
        warnings.append(f"Skipped {invalid_timestamps} stress record(s) with invalid timestamps.")
    return records


def _union_seconds(intervals):
    total = 0
    previous_end = None
    for start, end in sorted(intervals):
        if previous_end is None or start > previous_end:
            total += end - start
        elif end > previous_end:
            total += end - previous_end
        previous_end = end if previous_end is None else max(previous_end, end)
    return total


def _valid_intervals(rows, label, warnings=None):
    valid = []
    skipped = 0
    for row in rows:
        started = local_datetime(row["TIMESTAMP"])
        ended = local_datetime(row["OTHER_TIMESTAMP"])
        # These wearable samples are minute/activity or overnight/sleep intervals.
        # A seven-day ceiling admits ordinary records while preventing corrupted
        # decades-long intervals from expanding the daily aggregation.
        if started is None or ended is None or not 0 < ended.timestamp() - started.timestamp() <= 7 * 86400:
            skipped += 1
            continue
        valid.append({**dict(row), "TIMESTAMP": started.timestamp(), "OTHER_TIMESTAMP": ended.timestamp()})
    if skipped and warnings is not None:
        warnings.append(f"Skipped {skipped} {label} interval(s) with invalid timestamps or duration longer than seven days.")
    return valid


def _sleep(rows, warnings=None):
    """Group recorded intervals, without adding the small gaps to duration."""
    by_source = defaultdict(list)
    for row in _valid_intervals(rows, "sleep", warnings):
        by_source[(row["DEVICE_ID"], row["USER_ID"])].append((row["TIMESTAMP"], row["OTHER_TIMESTAMP"]))
    sessions = []
    for intervals in by_source.values():
        group = []
        group_end = None
        for start, end in sorted(set(intervals)):
            if group and start > group_end + 300:
                sessions.append(group)
                group = []
            group.append((start, end))
            group_end = max(group_end or end, end) if len(group) > 1 else end
        if group:
            sessions.append(group)
    result = []
    for intervals in sessions:
        started = local_datetime(min(start for start, _ in intervals))
        ended = local_datetime(max(end for _, end in intervals))
        result.append({
            "date": ended.date().isoformat(), "start_iso": started.isoformat(),
            "end_iso": ended.isoformat(), "duration_hours": _union_seconds(intervals) / 3600,
        })
    return sorted(result, key=lambda row: datetime.fromisoformat(row["start_iso"]).timestamp())


def _day_intervals(start, end):
    """Split coverage at local midnights; UTC seconds handle daylight saving."""
    current = start
    while current < end:
        local = local_datetime(current)
        next_midnight = datetime.combine(local.date() + timedelta(days=1), time.min, display_timezone()).timestamp()
        boundary = min(end, next_midnight)
        yield local.date().isoformat(), (current, boundary)
        current = boundary


def _daily(activity, sleep, stress, workouts):
    by_date = defaultdict(lambda: {"steps": [], "hr": [], "coverage": [], "sleep": [], "stress": [], "workouts": []})
    for row in activity:
        key = local_datetime(row["TIMESTAMP"]).date().isoformat()
        steps = measured_number(row["STEPS"])
        hr = heart_rate(row["HEART_RATE"])
        if steps is not None:
            by_date[key]["steps"].append(steps)
        if hr is not None:
            by_date[key]["hr"].append(hr)
        for interval_date, interval in _day_intervals(row["TIMESTAMP"], row["OTHER_TIMESTAMP"]):
            by_date[interval_date]["coverage"].append(interval)
    for row in sleep:
        by_date[row["date"]]["sleep"].append(row["duration_hours"])
    for row in stress:
        by_date[row["date"]]["stress"].append(row["value"])
    for row in workouts:
        if row["date"] is not None:
            by_date[row["date"]]["workouts"].append(row)
    if not by_date:
        return []
    first, last = date.fromisoformat(min(by_date)), date.fromisoformat(max(by_date))
    result = []
    day = first
    while day <= last:
        values = by_date[day.isoformat()]
        hr_values, stress_values = values["hr"], values["stress"]
        distances = [row["distance_km"] for row in values["workouts"] if row["distance_km"] is not None]
        durations = [row["duration_s"] for row in values["workouts"] if row["duration_s"] is not None]
        result.append({
            "date": day.isoformat(),
            "steps": sum(values["steps"]) if values["steps"] else None,
            "recorded_minutes": _union_seconds(values["coverage"]) / 60 if values["coverage"] else None,
            "hr_avg": mean(hr_values) if hr_values else None,
            "hr_min": min(hr_values) if hr_values else None,
            "hr_max": max(hr_values) if hr_values else None,
            "hr_count": len(hr_values),
            "sleep_hours": sum(values["sleep"]) if values["sleep"] else None,
            "stress_avg": mean(stress_values) if stress_values else None,
            "stress_min": min(stress_values) if stress_values else None,
            "stress_max": max(stress_values) if stress_values else None,
            "stress_count": len(stress_values),
            "workout_count": len(values["workouts"]),
            "workout_distance_km": sum(distances) if distances else None,
            "workout_duration_s": sum(durations) if durations else None,
        })
        day += timedelta(days=1)
    return result


def _coverage(key, label, records, notes):
    dates = sorted({row["date"] for row in records if row["date"] is not None})
    return {"key": key, "label": label, "count": len(records),
            "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "observed_days": len(dates), "notes": notes}


def load_data():
    """Return normalized data once per request; never cache a replaced export."""
    if "_fitness_data" in g:
        return g._fitness_data
    warnings = []
    summaries = _json_summaries(warnings)
    workout_rows = database.get_workouts()
    workouts = [_workout(row, summaries.get(_summary_key(row), {})) for row in workout_rows]
    missing_starts = sum(row["date"] is None for row in workouts)
    if missing_starts:
        warnings.append(f"{missing_starts} workout(s) have unavailable start timestamps and are excluded from daily totals.")
    activity = _valid_intervals(database.get_activity(), "activity", warnings)
    sleep = _sleep(database.get_sleep_intervals(), warnings)
    stress = _stress(database.get_stress(), warnings)
    activity_dates = [{"date": local_datetime(row["TIMESTAMP"]).date().isoformat()} for row in activity]
    coverage = [
        _coverage("activity", "Daily activity", activity_dates, "Source 11 start markers only. Coverage is recorded interval minutes; heart rate is an unweighted sample mean. Raw daily distance and calorie units remain unverified."),
        _coverage("sleep", "Recorded sleep", sleep, "Source 10 intervals grouped with gaps of at most five minutes. Duration sums interval union; gaps add no sleep. Assigned to local wake date. Source 13 stages are unverified and excluded."),
        _coverage("stress", "Stress samples", stress, "Device-reported 0–100 index. Samples are sparse, and daily means describe available samples only."),
        _coverage("workouts", "Workout summaries", workouts, "Huawei workout summaries with unit-bearing BASE_ACTIVITY_SUMMARY JSON. No GPS track is present in this export; calorie and fitness estimates are device-reported."),
    ]
    warnings.extend(database.get_warnings())
    warnings.append("Missing dates and measurements remain unavailable; a recorded zero is preserved. Older workouts and recent daily records cover different periods.")
    warnings.append("Sleep charts show recorded source 10 duration. Sleep stages, daily calorie/distance fields and unverified workload values are excluded.")
    result = {"workouts": workouts, "daily": _daily(activity, sleep, stress, workouts),
              "sleep": sleep, "stress": stress, "coverage": coverage, "warnings": warnings}
    g._fitness_data = result
    g._fitness_summaries = summaries
    return result


def get_workout_details(workout_id):
    data = load_data()
    workout = next((row for row in data["workouts"] if row["id"] == workout_id), None)
    if workout is None:
        return {"samples": [], "splits": []}
    samples = []
    invalid_timestamps = 0
    for row in database.get_workout_samples(workout_id):
        timestamp = local_datetime(row["TIMESTAMP"])
        if timestamp is None:
            invalid_timestamps += 1
            continue
        speed = measured_number(row["SPEED"])
        speed_kmh = speed * 0.36 if speed is not None else None
        altitude = measured_number(row["ALTITUDE"], allow_negative=True)
        # The parser stores speed in tenths of m/s. Sample altitude/10 matches
        # all 25 JSON maximum elevations and 24/25 minimum elevations (0.5m
        # difference for workout 19), confirming decimetres for this export.
        altitude_m = altitude / 10 if altitude is not None else None
        samples.append({
            "timestamp_iso": timestamp.isoformat(),
            "heart_rate": heart_rate(row["HEART_RATE"]),
            "pace_min_km": 60 / speed_kmh if speed_kmh and speed_kmh > 0 else None,
            "speed_kmh": speed_kmh, "altitude_m": altitude_m,
        })
    if invalid_timestamps:
        data["warnings"].append(f"Skipped {invalid_timestamps} workout sample(s) with invalid timestamps.")
    for warning in database.get_warnings():
        if warning not in data["warnings"]:
            data["warnings"].append(warning)
    source_row = next((row for row in database.get_workouts() if row["WORKOUT_ID"] == workout_id), None)
    summary = g._fitness_summaries.get(_summary_key(source_row), {}) if source_row is not None else {}
    splits = []
    # JSON already selects kilometre splits. Raw pace table includes mile rows,
    # so reading it without a verified TYPE mapping would duplicate distances.
    for key, value in summary.items():
        if not key.startswith("paces_table_") or not isinstance(value, dict) or value.get("isHeader"):
            continue
        columns = value.get("columns", [])
        if not isinstance(columns, list) or len(columns) < 3 or not all(isinstance(column, dict) for column in columns[:3]):
            continue
        if columns[1].get("unit") != "km" or columns[2].get("unit") != "seconds_km":
            continue
        index = measured_number(columns[0].get("value"))
        distance = measured_number(columns[1].get("value"))
        pace = measured_number(columns[2].get("value"), zero=False)
        if index is not None and distance is not None and pace is not None:
            splits.append({"index": index, "distance_km": distance, "pace_s": pace, "label": f"Split {index}"})
    return {"samples": samples, "splits": sorted(splits, key=lambda row: row["index"])}


def get_day_details(date_str):
    selected = date.fromisoformat(date_str)
    start = datetime.combine(selected, time.min, display_timezone()).timestamp()
    end = datetime.combine(selected + timedelta(days=1), time.min, display_timezone()).timestamp()
    activity = [{
        "timestamp_iso": local_datetime(row["TIMESTAMP"]).isoformat(),
        "end_iso": local_datetime(row["OTHER_TIMESTAMP"]).isoformat(),
        "steps": measured_number(row["STEPS"]), "heart_rate": heart_rate(row["HEART_RATE"]),
        "resting_hr": heart_rate(row["RESTING_HEART_RATE"]),
    } for row in _valid_intervals(database.get_activity(start, end), "activity")]
    return {"activity": activity, "stress": _stress(database.get_stress(start, end)),
            "sleep": [row for row in load_data()["sleep"] if row["date"] == date_str]}
