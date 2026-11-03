"""SQLite storage. Holds per-minute totals and a few events, nothing else."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from eyetracker.tracker import Event, Minute

SCHEMA = """
CREATE TABLE IF NOT EXISTS minutes (
    ts INTEGER PRIMARY KEY,
    present_s REAL NOT NULL,
    screen_s REAL NOT NULL,
    blinks INTEGER NOT NULL,
    longest_gap_s REAL NOT NULL,
    look_aways INTEGER NOT NULL,
    frames INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)

    def save_minutes(self, minutes: Iterable[Minute]) -> None:
        rows = [
            (m.ts, m.present_s, m.screen_s, m.blinks, m.longest_gap_s, m.look_aways, m.frames)
            for m in minutes
        ]
        with self._db:
            self._db.executemany(
                """
                INSERT INTO minutes VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ts) DO UPDATE SET
                    present_s = present_s + excluded.present_s,
                    screen_s = screen_s + excluded.screen_s,
                    blinks = blinks + excluded.blinks,
                    longest_gap_s = MAX(longest_gap_s, excluded.longest_gap_s),
                    look_aways = look_aways + excluded.look_aways,
                    frames = frames + excluded.frames
                """,
                rows,
            )

    def save_events(self, events: Iterable[Event]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT INTO events VALUES (?, ?, ?)", [(e.ts, e.kind, e.value) for e in events]
            )

    def close(self) -> None:
        self._db.close()
