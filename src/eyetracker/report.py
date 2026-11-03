"""Read-only summaries of the stored data, in the machine's local time."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

MIN_SCREEN_S_FOR_RATE = 30.0
STALE_STATUS_S = 20.0


def _day_start(day: date) -> int:
    return int(datetime(day.year, day.month, day.day).timestamp())


def _rate(blinks: int, screen_s: float) -> float | None:
    if screen_s < MIN_SCREEN_S_FOR_RATE:
        return None
    return round(blinks / (screen_s / 60), 1)


class Report:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _rows(self, query: str, *params) -> list[tuple]:
        if not self.db_path.exists():
            return []
        db = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            return db.execute(query, params).fetchall()
        finally:
            db.close()

    def summary(self, day: date) -> dict:
        start, end = _day_start(day), _day_start(day + timedelta(days=1))
        (present_s, screen_s, blinks, longest, look_aways, frames), = self._rows(
            """
            SELECT COALESCE(SUM(present_s), 0), COALESCE(SUM(screen_s), 0), COALESCE(SUM(blinks), 0),
                   COALESCE(MAX(longest_gap_s), 0), COALESCE(SUM(look_aways), 0), COALESCE(SUM(frames), 0)
            FROM minutes WHERE ts >= ? AND ts < ?
            """,
            start, end,
        ) or [(0, 0, 0, 0, 0, 0)]
        events = dict(
            self._rows(
                "SELECT kind, COUNT(*) FROM events WHERE ts >= ? AND ts < ? GROUP BY kind", start, end
            )
        )
        return {
            "day": day.isoformat(),
            "screen_min": round(screen_s / 60, 1),
            "blinks": blinks,
            "blink_rate": _rate(blinks, screen_s),
            "longest_gap_s": round(longest, 1),
            "look_aways": look_aways,
            "breaks": events.get("break", 0),
            "stare_alerts": events.get("stare_alert", 0),
            "break_alerts": events.get("break_alert", 0),
            "fps": round(frames / present_s, 1) if present_s else None,
        }

    def timeline(self, day: date, bucket_min: int = 10) -> list[dict]:
        start, end = _day_start(day), _day_start(day + timedelta(days=1))
        size = bucket_min * 60
        buckets: dict[int, list[float]] = {}
        for ts, screen_s, blinks, longest in self._rows(
            "SELECT ts, screen_s, blinks, longest_gap_s FROM minutes WHERE ts >= ? AND ts < ? ORDER BY ts",
            start, end,
        ):
            bucket = buckets.setdefault((ts - start) // size, [0.0, 0, 0.0])
            bucket[0] += screen_s
            bucket[1] += blinks
            bucket[2] = max(bucket[2], longest)
        return [
            {
                "ts": start + index * size,
                "screen_min": round(screen_s / 60, 1),
                "blink_rate": _rate(blinks, screen_s),
                "longest_gap_s": round(longest, 1),
            }
            for index, (screen_s, blinks, longest) in sorted(buckets.items())
            if screen_s > 0
        ]

    def history(self, last_day: date, days: int = 14) -> list[dict]:
        out = []
        for offset in range(days - 1, -1, -1):
            s = self.summary(last_day - timedelta(days=offset))
            out.append(
                {key: s[key] for key in ("day", "screen_min", "blink_rate", "longest_gap_s", "breaks")}
            )
        return out


def read_status(path: Path, paused_until: float | None = None) -> dict:
    """The daemon's last status, or "not-running" once it has stopped updating."""
    try:
        status = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"state": "not-running"}
    if status.get("state") == "stopped" or time.time() - status.get("updated_at", 0) > STALE_STATUS_S:
        return {"state": "not-running"}
    if paused_until is not None:
        status["paused_until"] = paused_until
    return status
