from datetime import datetime, timezone
import sqlite3
from zoneinfo import ZoneInfo

from flask import Flask, render_template

import database


app = Flask(__name__)
database.init_app(app)
DISPLAY_TIMEZONE = ZoneInfo("Europe/Berlin")


def format_duration(seconds):
    """Format active seconds without treating a valid zero as missing."""
    if seconds is None or seconds == -1:
        return "Unavailable"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


def format_workout(row):
    """Prepare readable values for the HTML table."""
    def available(value):
        return value is not None and value != -1

    timestamp = row["START_TIMESTAMP"]
    start_time = "Unavailable"
    if available(timestamp):
        start_time = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
            .astimezone(DISPLAY_TIMEZONE)
            .strftime("%d %B %Y, %H:%M:%S")
        )

    return {
        "id": row["WORKOUT_ID"],
        "start_time": start_time,
        "distance_km": (
            f'{row["DISTANCE"] / 1000:.2f}'
            if available(row["DISTANCE"]) else "Unavailable"
        ),
        "active_duration": format_duration(row["DURATION"]),
        "steps": (
            f'{row["STEP_COUNT"]:,}'
            if available(row["STEP_COUNT"]) else "Unavailable"
        ),
        "calories": (
            f'{row["CALORIES"]:,}'
            if available(row["CALORIES"]) else "Unavailable"
        ),
        "type_code": row["TYPE"] if available(row["TYPE"]) else "Unavailable",
    }


@app.get("/")
def home():
    return render_template("home.html", page_title="Home")


@app.route("/data_overview")
def data_overview():
    try:
        rows = database.get_workouts()
    except sqlite3.Error:
        app.logger.exception("Unable to read Gadgetbridge workout summaries")
        return render_template(
            "data_overview.html",
            page_title="Data Overview",
            workouts=[],
            database_error=True,
        ), 503

    workouts = [format_workout(row) for row in rows]
    return render_template(
        "data_overview.html",
        page_title="Data Overview",
        workouts=workouts,
        database_error=False,
    )


@app.route("/daily")
def daily():
    return render_template("daily.html", page_title="Daily")
