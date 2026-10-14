"""Read-only access to the local Gadgetbridge export."""

from pathlib import Path
import sqlite3

from flask import current_app, g


def get_db():
    """Reuse one database connection for the current Flask request."""
    if "_database" not in g:
        database_path = Path(current_app.config["GADGETBRIDGE_DB"]).resolve()
        connection = sqlite3.connect(
            database_path.as_uri() + "?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        g._database = connection
    return g._database


def close_connection(exception=None):
    connection = g.pop("_database", None)
    if connection is not None:
        connection.close()


def init_app(app):
    app.config.setdefault(
        "GADGETBRIDGE_DB", Path(app.instance_path) / "Gadgetbridge.db"
    )
    app.teardown_appcontext(close_connection)


def get_workouts():
    """Return workout summaries with the newest workout first."""
    return get_db().execute(
        """
        SELECT WORKOUT_ID, START_TIMESTAMP, DISTANCE, DURATION,
               STEP_COUNT, CALORIES, TYPE
        FROM HUAWEI_WORKOUT_SUMMARY_SAMPLE
        ORDER BY START_TIMESTAMP DESC, WORKOUT_ID DESC
        """
    ).fetchall()
