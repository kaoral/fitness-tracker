"""Read-only queries for a local Gadgetbridge export.

Connections live for one Flask request. Optional data tables may be absent in an
older export; opening an absent database still raises rather than creating one.
"""

from pathlib import Path
import sqlite3

from flask import current_app, g


def get_db():
    """Reuse one read-only SQLite connection in the current app context."""
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


def table_exists(name):
    """Table names come from fixed application queries, never request input."""
    if "_gadgetbridge_tables" not in g:
        g._gadgetbridge_tables = {
            row[0] for row in get_db().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    return name in g._gadgetbridge_tables


def _optional_query(table, sql, parameters=()):
    if not table_exists(table):
        warnings = g.setdefault("_gadgetbridge_warnings", [])
        message = f"This export has no {table} table; that data is unavailable."
        if message not in warnings:
            warnings.append(message)
        return []
    return get_db().execute(sql, parameters).fetchall()


def get_warnings():
    return list(g.get("_gadgetbridge_warnings", []))


def get_workouts():
    """Return summary fields in original source units, newest first."""
    return _optional_query(
        "HUAWEI_WORKOUT_SUMMARY_SAMPLE",
        """SELECT WORKOUT_ID, DEVICE_ID, USER_ID, START_TIMESTAMP, END_TIMESTAMP,
                  DISTANCE, DURATION, STEP_COUNT, CALORIES, TYPE
           FROM HUAWEI_WORKOUT_SUMMARY_SAMPLE
           ORDER BY START_TIMESTAMP DESC, WORKOUT_ID DESC""",
    )


def get_base_summaries():
    """Unit-bearing JSON is safer than guessing scaled workout raw fields."""
    return _optional_query(
        "BASE_ACTIVITY_SUMMARY",
        """SELECT START_TIME, DEVICE_ID, USER_ID, SUMMARY_DATA
           FROM BASE_ACTIVITY_SUMMARY ORDER BY START_TIME""",
    )


def get_activity(start=None, end=None):
    """Source 11 start markers avoid counting the matching end marker twice."""
    sql = """SELECT TIMESTAMP, OTHER_TIMESTAMP, DEVICE_ID, USER_ID,
                    STEPS, HEART_RATE, RESTING_HEART_RATE
             FROM HUAWEI_ACTIVITY_SAMPLE
             WHERE SOURCE = 11 AND TIMESTAMP < OTHER_TIMESTAMP"""
    parameters = ()
    if start is not None and end is not None:
        sql += " AND TIMESTAMP >= ? AND TIMESTAMP < ?"
        parameters = (start, end)
    return _optional_query("HUAWEI_ACTIVITY_SAMPLE", sql + " ORDER BY TIMESTAMP", parameters)


def get_sleep_intervals():
    """Source 10 is recorded TruSleep coverage, without inferred sleep stages."""
    return _optional_query(
        "HUAWEI_ACTIVITY_SAMPLE",
        """SELECT TIMESTAMP, OTHER_TIMESTAMP, DEVICE_ID, USER_ID
           FROM HUAWEI_ACTIVITY_SAMPLE
           WHERE SOURCE = 10 AND TIMESTAMP < OTHER_TIMESTAMP
           ORDER BY DEVICE_ID, USER_ID, TIMESTAMP""",
    )


def get_stress(start=None, end=None):
    sql = "SELECT TIMESTAMP, STRESS FROM HUAWEI_STRESS_SAMPLE"
    parameters = ()
    if start is not None and end is not None:
        # Stress timestamps are Unix milliseconds; activity timestamps are seconds.
        sql += " WHERE TIMESTAMP >= ? AND TIMESTAMP < ?"
        parameters = (int(start * 1000), int(end * 1000))
    return _optional_query("HUAWEI_STRESS_SAMPLE", sql + " ORDER BY TIMESTAMP", parameters)


def get_workout_samples(workout_id):
    return _optional_query(
        "HUAWEI_WORKOUT_DATA_SAMPLE",
        """SELECT TIMESTAMP, HEART_RATE, SPEED, ALTITUDE
           FROM HUAWEI_WORKOUT_DATA_SAMPLE WHERE WORKOUT_ID = ?
           ORDER BY TIMESTAMP""",
        (workout_id,),
    )
