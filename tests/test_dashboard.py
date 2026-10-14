"""Regression checks against synthetic exports; no personal health data is used.

Run from the project folder with: python -m unittest discover -s tests -v
"""
import csv
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

import analytics
import database
from app import create_app


BERLIN = ZoneInfo("Europe/Berlin")


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "script" and "src" in attributes:
            self.assets.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.assets.append(attributes.get("href", ""))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.db"
        connection = sqlite3.connect(self.path)
        connection.executescript("""
            CREATE TABLE HUAWEI_WORKOUT_SUMMARY_SAMPLE (
                WORKOUT_ID INTEGER, DEVICE_ID INTEGER, USER_ID INTEGER,
                START_TIMESTAMP INTEGER, END_TIMESTAMP INTEGER,
                DISTANCE REAL, DURATION REAL, STEP_COUNT INTEGER,
                CALORIES REAL, TYPE INTEGER
            );
            CREATE TABLE BASE_ACTIVITY_SUMMARY (
                START_TIME INTEGER, DEVICE_ID INTEGER, USER_ID INTEGER,
                SUMMARY_DATA TEXT
            );
            CREATE TABLE HUAWEI_ACTIVITY_SAMPLE (
                TIMESTAMP INTEGER, OTHER_TIMESTAMP INTEGER,
                DEVICE_ID INTEGER, USER_ID INTEGER, SOURCE INTEGER,
                STEPS INTEGER, HEART_RATE INTEGER, RESTING_HEART_RATE INTEGER
            );
            CREATE TABLE HUAWEI_STRESS_SAMPLE (TIMESTAMP INTEGER, STRESS REAL);
            CREATE TABLE HUAWEI_WORKOUT_DATA_SAMPLE (
                WORKOUT_ID INTEGER, TIMESTAMP INTEGER, HEART_RATE INTEGER,
                SPEED REAL, ALTITUDE REAL
            );
        """)
        workouts = [
            (101, "2026-03-28T18:00:00+00:00", 1250, 375, 100, 20, 1),
            (102, "2026-03-29T18:00:00+00:00", 2200, 660, 220, None, 2),
            (103, "2026-03-29T18:00:00+00:00", 0, 0, 0, 0, 99),
            (104, "2026-03-30T08:00:00+00:00", -1, None, -1, None, None),
            # Fall-back local wall time goes backwards, UTC chronology does not.
            (105, "2026-10-25T00:45:00+00:00", 500, 150, 50, 10, 1),
            (106, "2026-10-25T01:15:00+00:00", 600, 180, 60, 12, 1),
        ]
        self.timestamps = {identifier: epoch(timestamp) for identifier, timestamp, *_ in workouts}
        connection.executemany(
            "INSERT INTO HUAWEI_WORKOUT_SUMMARY_SAMPLE VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(identifier, 1, 1, self.timestamps[identifier], self.timestamps[identifier] + (duration or 0),
              distance, duration, steps, calories, code)
             for identifier, _, distance, duration, steps, calories, code in workouts],
        )
        summary = {
            "averageHR": {"value": 125, "unit": "bpm"},
            "maxHR": {"value": 175, "unit": "bpm"},
            "averageKMPaceSeconds": {"value": 300, "unit": "seconds_km"},
            "elevationGain": {"value": 0, "unit": "meters"},
            "hrZoneWarmUp": {"value": 0, "unit": "seconds"},
            "paces_table_1": {"columns": [
                {"value": 1}, {"value": 1, "unit": "km"},
                {"value": 300, "unit": "seconds_km"},
            ]},
            "paces_table_2": {"columns": [
                {"value": 2}, {"value": 1, "unit": "mi"},
                {"value": 500, "unit": "seconds_mi"},
            ]},
        }
        connection.executemany("INSERT INTO BASE_ACTIVITY_SUMMARY VALUES (?,?,?,?)", [
            (self.timestamps[101] * 1000, 1, 1, json.dumps(summary)),
            (self.timestamps[102] * 1000, 1, 1, json.dumps({"averageHR": {"value": 9000, "unit": "seconds"}})),
            (self.timestamps[104] * 1000, 1, 1, "{broken-json"),
        ])
        self.insert_interval(connection, "2026-04-01T09:00:00+02:00", "2026-04-01T09:01:00+02:00", 11, 30, 60, 55)
        self.insert_interval(connection, "2026-04-01T09:01:00+02:00", "2026-04-01T09:02:00+02:00", 11, 10, -100, -1)
        self.insert_interval(connection, "2026-04-03T09:00:00+02:00", "2026-04-03T09:01:00+02:00", 11, 0, -1, -1)
        # Two overlapping sleep intervals plus one separated by a small gap.
        self.insert_interval(connection, "2026-04-01T22:00:00+02:00", "2026-04-02T00:00:00+02:00", 10)
        self.insert_interval(connection, "2026-04-01T23:00:00+02:00", "2026-04-02T01:00:00+02:00", 10)
        self.insert_interval(connection, "2026-04-02T01:02:00+02:00", "2026-04-02T02:00:00+02:00", 10)
        # Crossing the spring clock change is two elapsed hours, not three.
        self.insert_interval(connection, "2026-03-29T01:30:00+01:00", "2026-03-29T04:30:00+02:00", 10)
        self.insert_interval(connection, "2026-04-01T18:00:00+02:00", "2026-04-02T06:00:00+02:00", 13)
        connection.executemany("INSERT INTO HUAWEI_STRESS_SAMPLE VALUES (?,?)", [
            (epoch(f"2026-04-01T{hour:02d}:00:00+02:00") * 1000, value)
            for hour, value in enumerate([10, 30, 0, -1, 101, None], start=9)
        ])
        connection.executemany("INSERT INTO HUAWEI_WORKOUT_DATA_SAMPLE VALUES (?,?,?,?,?)", [
            (101, self.timestamps[101], -100, 25, 123),
            (101, self.timestamps[101] + 60, -1, 0, -1),
        ])
        connection.commit()
        connection.close()
        self.app = create_app({"TESTING": True, "GADGETBRIDGE_DB": self.path})
        self.client = self.app.test_client()

    @staticmethod
    def insert_interval(connection, start, end, source, steps=None, heart_rate=None, resting=None):
        begin, finish = epoch(start), epoch(end)
        # Gadgetbridge has matching start and end markers for the same interval.
        connection.executemany("INSERT INTO HUAWEI_ACTIVITY_SAMPLE VALUES (?,?,?,?,?,?,?,?)", [
            (begin, finish, 1, 1, source, steps, heart_rate, resting),
            (finish, begin, 1, 1, source, steps, heart_rate, resting),
        ])

    def rows(self, kind, query=""):
        response = self.client.get(f"/exports/{kind}.csv{query}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        return list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))

    def test_app_factory_configuration_and_connection_lifecycle(self):
        self.assertEqual(self.app.config["GADGETBRIDGE_DB"], self.path)
        default_app = create_app()
        self.assertEqual(Path(default_app.config["GADGETBRIDGE_DB"]), Path(default_app.instance_path) / "Gadgetbridge.db")
        with self.app.app_context():
            connection = database.get_db()
            self.assertIs(connection, database.get_db())
            self.assertIs(connection.row_factory, sqlite3.Row)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden (value TEXT)")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_connection_closes_after_http_request_and_export_is_unchanged(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        connections = []

        @self.app.after_request
        def capture_connection(response):
            from flask import g
            connections.append(g._database)
            return response

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/data_overview").status_code, 200)
        self.assertIsNot(connections[0], connections[1])
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_missing_database_is_503_without_accidental_creation(self):
        missing = Path(self.temporary.name) / "never-created.db"
        app = create_app({"TESTING": True, "GADGETBRIDGE_DB": missing})
        with self.assertLogs(app.logger, level="ERROR") as logged:
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("database is unavailable", response.get_data(as_text=True).lower())
        self.assertTrue(any("Gadgetbridge" in message for message in logged.output))
        self.assertFalse(missing.exists())
        self.assertEqual(app.test_client().get("/settings").status_code, 200)

    def test_missing_optional_tables_are_empty_with_clear_warnings(self):
        path = Path(self.temporary.name) / "empty-export.db"
        sqlite3.connect(path).close()
        app = create_app({"TESTING": True, "GADGETBRIDGE_DB": path})
        with app.app_context():
            data = analytics.load_data()
            for key in ["workouts", "daily", "sleep", "stress"]:
                self.assertEqual(data[key], [])
            self.assertTrue(any("HUAWEI_WORKOUT_SUMMARY_SAMPLE" in note for note in data["warnings"]))
        client = app.test_client()
        for route in ["/", "/data_overview", "/daily", "/sleep", "/stress", "/sources"]:
            with self.subTest(route=route):
                self.assertEqual(client.get(route).status_code, 200)

    def test_workout_units_berlin_time_missing_and_valid_zero(self):
        with self.app.app_context():
            workouts = {row["id"]: row for row in analytics.load_data()["workouts"]}
        first = workouts[101]
        self.assertEqual(first["start_iso"], "2026-03-28T19:00:00+01:00")
        self.assertEqual(workouts[102]["start_iso"], "2026-03-29T20:00:00+02:00")
        self.assertEqual(first["distance_km"], 1.25)
        self.assertEqual(first["duration_s"], 375)
        self.assertEqual(first["duration_label"], "6m 15s")
        self.assertEqual(first["type_label"], "Running")
        self.assertEqual(workouts[103]["type_label"], "Type 99")
        self.assertEqual(workouts[104]["type_label"], "Unknown type")
        for field in ["distance_km", "duration_s", "steps", "calories"]:
            self.assertEqual(workouts[103][field], 0)
            self.assertIsNone(workouts[104][field])
        self.assertEqual(first["avg_hr"], 125)
        self.assertIsNone(workouts[102]["avg_hr"])
        self.assertEqual(first["elevation_gain_m"], 0)

    def test_missing_workout_timestamp_retains_record_but_cannot_match_dates(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO HUAWEI_WORKOUT_SUMMARY_SAMPLE VALUES (?,?,?,?,?,?,?,?,?,?)",
                (107, 1, 1, None, None, 100, 20, 1, 2, 99),
            )
        with self.app.app_context():
            data = analytics.load_data()
            workout = next(row for row in data["workouts"] if row["id"] == 107)
            self.assertIsNone(workout["start_iso"])
            self.assertIsNone(workout["date"])
            self.assertEqual(workout["distance_km"], 0.1)
            self.assertTrue(any("timestamp" in warning.lower() for warning in data["warnings"]))
            self.assertTrue(all(row["date"] for row in data["daily"]))
        self.assertIn(107, [int(row["id"]) for row in self.rows("workouts")])
        self.assertNotIn(107, [int(row["id"]) for row in self.rows("workouts", "?start=2026-01-01")])
        self.assertEqual(self.client.get("/workouts/107").status_code, 200)

    def test_new_request_reads_updated_export_instead_of_stale_cached_data(self):
        initial = {int(row["id"]): row for row in self.rows("workouts")}
        self.assertEqual(float(initial[101]["distance_km"]), 1.25)
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE HUAWEI_WORKOUT_SUMMARY_SAMPLE SET DISTANCE = 2000 WHERE WORKOUT_ID = 101")
        refreshed = {int(row["id"]): row for row in self.rows("workouts")}
        self.assertEqual(float(refreshed[101]["distance_km"]), 2)

    def test_workout_sorting_uses_chronology_across_fall_back_and_id_ties(self):
        rows = self.rows("workouts")
        self.assertEqual([int(row["id"]) for row in rows], [106, 105, 104, 103, 102, 101])
        oldest = self.rows("workouts", "?sort=oldest")
        self.assertEqual([int(row["id"]) for row in oldest], [101, 102, 103, 104, 105, 106])
        distance = self.rows("workouts", "?sort=distance")
        self.assertEqual([int(row["id"]) for row in distance], [102, 101, 106, 105, 103, 104])

    def test_workout_filters_use_inclusive_local_dates_and_types(self):
        rows = self.rows("workouts", "?start=2026-03-29&end=2026-03-29")
        self.assertEqual([int(row["id"]) for row in rows], [103, 102])
        rows = self.rows("workouts", "?start=2026-03-29&end=2026-03-29&type=2")
        self.assertEqual([int(row["id"]) for row in rows], [102])
        self.assertEqual(self.rows("workouts", "?start=2027-01-01"), [])

    def test_paired_activity_does_not_double_steps_and_missing_day_is_not_zero(self):
        with self.app.app_context():
            daily = {row["date"]: row for row in analytics.load_data()["daily"]}
            details = analytics.get_day_details("2026-04-01")
        recorded = daily["2026-04-01"]
        self.assertEqual(recorded["steps"], 40)
        self.assertEqual(recorded["recorded_minutes"], 2)
        self.assertEqual(recorded["hr_count"], 2)
        self.assertEqual(recorded["hr_avg"], 108)
        self.assertIsNone(daily["2026-04-02"]["steps"])
        self.assertIsNone(daily["2026-04-02"]["recorded_minutes"])
        self.assertEqual(daily["2026-04-03"]["steps"], 0)
        self.assertEqual(len(details["activity"]), 2)
        self.assertEqual(details["activity"][1]["heart_rate"], 156)
        self.assertIsNone(details["activity"][1]["resting_hr"])

    def test_stress_millisecond_timestamps_counts_and_invalid_values(self):
        with self.app.app_context():
            data = analytics.load_data()
            details = analytics.get_day_details("2026-04-01")
        self.assertEqual([r["value"] for r in data["stress"]], [10, 30, 0])
        self.assertEqual(data["stress"][0]["timestamp_iso"], "2026-04-01T09:00:00+02:00")
        self.assertEqual(len(details["stress"]), 3)
        daily = next(d for d in data["daily"] if d["date"] == "2026-04-01")
        self.assertEqual(daily["stress_count"], 3)
        self.assertAlmostEqual(daily["stress_avg"], 40 / 3)
        self.assertEqual(daily["stress_min"], 0)
        self.assertEqual(daily["stress_max"], 30)
        self.assertEqual(self.rows("stress", "?start=2026-04-02"), [])

    def test_sleep_uses_interval_union_actual_elapsed_time_and_wake_date(self):
        with self.app.app_context():
            data = analytics.load_data()
        sleeps = {row["date"]: row for row in data["sleep"]}
        self.assertEqual(set(sleeps), {"2026-03-29", "2026-04-02"})
        self.assertEqual(sleeps["2026-03-29"]["duration_hours"], 2)
        self.assertEqual(sleeps["2026-04-02"]["start_iso"], "2026-04-01T22:00:00+02:00")
        self.assertEqual(sleeps["2026-04-02"]["end_iso"], "2026-04-02T02:00:00+02:00")
        self.assertAlmostEqual(sleeps["2026-04-02"]["duration_hours"], (4 * 3600 - 120) / 3600)
        daily = next(d for d in data["daily"] if d["date"] == "2026-04-02")
        self.assertEqual(daily["sleep_hours"], sleeps["2026-04-02"]["duration_hours"])

    def test_workout_samples_and_unit_bearing_splits(self):
        with self.app.app_context():
            details = analytics.get_workout_details(101)
        self.assertEqual(len(details["samples"]), 2)
        sample = details["samples"][0]
        self.assertEqual(sample["heart_rate"], 156)
        self.assertEqual(sample["speed_kmh"], 9)
        self.assertAlmostEqual(sample["pace_min_km"], 60 / 9)
        self.assertEqual(sample["altitude_m"], 12.3)
        self.assertIsNone(details["samples"][1]["pace_min_km"])
        self.assertIsNone(details["samples"][1]["altitude_m"])
        self.assertEqual(len(details["splits"]), 1)
        self.assertEqual(details["splits"][0]["distance_km"], 1)
        self.assertEqual(details["splits"][0]["pace_s"], 300)

    def test_csv_exports_preserve_numeric_values_offsets_and_blank_missing(self):
        workouts = {int(row["id"]): row for row in self.rows("workouts")}
        self.assertEqual(float(workouts[101]["distance_km"]), 1.25)
        self.assertEqual(float(workouts[101]["duration_s"]), 375)
        self.assertEqual(workouts[101]["timezone"], "Europe/Berlin")
        self.assertEqual(workouts[101]["start_iso"], "2026-03-28T19:00:00+01:00")
        for field in ["distance_km", "duration_s", "steps", "calories"]:
            self.assertEqual(float(workouts[103][field]), 0)
            self.assertEqual(workouts[104][field], "")
        daily = {row["date"]: row for row in self.rows("daily")}
        self.assertEqual(float(daily["2026-04-01"]["steps"]), 40)
        self.assertEqual(daily["2026-04-02"]["steps"], "")
        self.assertEqual(float(daily["2026-04-03"]["steps"]), 0)
        self.assertEqual(len(self.rows("sleep")), 2)
        self.assertEqual(len(self.rows("stress")), 3)

    def test_unknown_routes_and_bad_filters_return_clear_400_or_404(self):
        for route in ["/workouts/999999", "/exports/unknown.csv"]:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 404)
        for route in [
            "/data_overview?start=2026-02-30", "/data_overview?start=20260329",
            "/data_overview?start=2026-04-01&end=2026-03-01",
            "/data_overview?type=running", "/data_overview?sort=random",
            "/daily?date=invalid", "/sleep?end=2026-15-01",
            "/stress?start=invalid", "/exports/workouts.csv?start=invalid",
        ]:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 400)

    def test_pages_render_navigation_local_assets_and_private_response_headers(self):
        for route in ["/", "/data_overview", "/workouts/101", "/daily?date=2026-04-01", "/sleep", "/stress", "/sources", "/settings"]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
                html = response.get_data(as_text=True)
                self.assertIn('href="/data_overview"', html)
                self.assertIn('href="/settings"', html)
                parser = AssetParser()
                parser.feed(html)
                self.assertTrue(parser.assets)
                self.assertTrue(all(asset.startswith("/static/") for asset in parser.assets), parser.assets)
        self.assertIn('href="/workouts/101"', self.client.get("/data_overview").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
