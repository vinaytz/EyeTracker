import json
import time
from datetime import date, datetime, timedelta

import pytest

from eyetracker.report import Report, read_status
from eyetracker.store import Store
from eyetracker.tracker import Event, Minute

DAY = date(2026, 3, 10)


def at(day, hour, minute=0):
    return int(datetime(day.year, day.month, day.day, hour, minute).timestamp())


@pytest.fixture
def db(tmp_path):
    return tmp_path / "test.db"


def fill(db, minutes=(), events=()):
    store = Store(db)
    store.save_minutes(minutes)
    store.save_events(events)
    store.close()


def test_missing_database_reports_an_empty_day(db):
    report = Report(db)
    summary = report.summary(DAY)
    assert summary["screen_min"] == 0
    assert summary["blink_rate"] is None
    assert report.timeline(DAY) == []
    assert len(report.history(DAY, days=3)) == 3


def test_summary_adds_up_a_day(db):
    fill(
        db,
        [
            Minute(at(DAY, 9, 0), 60, 60, 12, 14.0, 1, 1200),
            Minute(at(DAY, 9, 1), 60, 30, 3, 35.0, 2, 1200),
        ],
        [
            Event(at(DAY, 9, 1), "break", 40),
            Event(at(DAY, 9, 1), "stare_alert", 31),
            Event(at(DAY, 9, 1), "stare_alert", 33),
            Event(at(DAY, 9, 1), "break_alert", 1200),
        ],
    )
    s = Report(db).summary(DAY)
    assert s["screen_min"] == 1.5
    assert s["blinks"] == 15
    assert s["blink_rate"] == 10
    assert s["longest_gap_s"] == 35
    assert s["look_aways"] == 3
    assert (s["breaks"], s["stare_alerts"], s["break_alerts"]) == (1, 2, 1)
    assert s["fps"] == 20


def test_a_rate_needs_enough_screen_time_to_mean_anything(db):
    fill(db, [Minute(at(DAY, 9), 10, 10, 2, 5.0, 0, 200)])
    assert Report(db).summary(DAY)["blink_rate"] is None


def test_days_split_at_local_midnight(db):
    next_day = DAY + timedelta(days=1)
    fill(db, [Minute(at(DAY, 23, 59), 60, 60, 5, 9, 0, 1), Minute(at(next_day, 0, 0), 60, 60, 7, 9, 0, 1)])
    report = Report(db)
    assert report.summary(DAY)["blinks"] == 5
    assert report.summary(next_day)["blinks"] == 7


def test_timeline_groups_into_ten_minute_buckets(db):
    fill(
        db,
        [
            Minute(at(DAY, 9, 0), 60, 60, 10, 12.0, 0, 1),
            Minute(at(DAY, 9, 9), 60, 60, 6, 20.0, 0, 1),
            Minute(at(DAY, 9, 10), 60, 60, 8, 7.0, 0, 1),
            Minute(at(DAY, 11, 0), 5, 0, 0, 0.0, 0, 1),
        ],
    )
    rows = Report(db).timeline(DAY)
    assert [r["ts"] for r in rows] == [at(DAY, 9, 0), at(DAY, 9, 10)]
    assert rows[0] == {"ts": at(DAY, 9, 0), "screen_min": 2.0, "blink_rate": 8.0, "longest_gap_s": 20.0}


def test_history_runs_oldest_to_newest_with_gaps(db):
    fill(db, [Minute(at(DAY, 9), 60, 60, 9, 9, 0, 1)])
    rows = Report(db).history(DAY + timedelta(days=2), days=3)
    assert [r["day"] for r in rows] == ["2026-03-10", "2026-03-11", "2026-03-12"]
    assert [r["blink_rate"] for r in rows] == [9.0, None, None]


def test_saving_the_same_minute_twice_merges_it(db):
    ts = at(DAY, 9)
    fill(db, [Minute(ts, 20, 20, 4, 10, 1, 400)])
    fill(db, [Minute(ts, 30, 30, 5, 8, 0, 600)])
    s = Report(db).summary(DAY)
    assert s["blinks"] == 9
    assert s["screen_min"] == pytest.approx(50 / 60, abs=0.05)
    assert s["longest_gap_s"] == 10


def test_a_reader_works_while_the_tracker_has_the_database_open(db):
    store = Store(db)
    store.save_minutes([Minute(at(DAY, 9), 60, 60, 9, 9, 0, 1)])
    assert Report(db).summary(DAY)["blinks"] == 9
    store.close()


def status_file(tmp_path, **fields):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"updated_at": time.time(), **fields}))
    return path


def test_status_missing_or_corrupt_means_not_running(tmp_path):
    path = tmp_path / "status.json"
    assert read_status(path)["state"] == "not-running"
    path.write_text("{ not json")
    assert read_status(path)["state"] == "not-running"


def test_fresh_status_is_returned(tmp_path):
    assert read_status(status_file(tmp_path, state="tracking"))["state"] == "tracking"


def test_a_crashed_tracker_is_not_reported_as_running(tmp_path):
    for state in ("tracking", "paused", "mic-in-use"):
        path = status_file(tmp_path, state=state, updated_at=time.time() - 60)
        assert read_status(path)["state"] == "not-running"


def test_stopped_means_not_running(tmp_path):
    assert read_status(status_file(tmp_path, state="stopped"))["state"] == "not-running"


def test_pause_time_is_shown_only_while_running(tmp_path):
    assert read_status(status_file(tmp_path, state="paused"), 123.0)["paused_until"] == 123.0
    assert "paused_until" not in read_status(tmp_path / "missing.json", 123.0)
