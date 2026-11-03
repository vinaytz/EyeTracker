"""Turns per-frame face samples into per-minute statistics and alerts.

Everything here is driven by the timestamps passed in, so it runs the same on
live frames and in tests.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass

from eyetracker.blink import BlinkDetector
from eyetracker.config import Config

YAW_LIMIT_DEG = 22.0
PITCH_LIMIT_DEG = 18.0
LEAVE_DEBOUNCE_S = 1.0
RETURN_DEBOUNCE_S = 0.3
LOOK_AWAY_MIN_S = 2.0
POSE_WINDOW_S = 600
POSE_WARMUP_SAMPLES = 5
MAX_FRAME_GAP_S = 2.0


@dataclass(frozen=True)
class FaceSample:
    ear: float
    yaw: float
    pitch: float


@dataclass(frozen=True)
class Event:
    ts: float
    kind: str  # "break", "stare_alert" or "break_alert"
    value: float


@dataclass
class Minute:
    ts: int
    present_s: float = 0.0
    screen_s: float = 0.0
    blinks: int = 0
    longest_gap_s: float = 0.0
    look_aways: int = 0
    frames: int = 0


class Tracker:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._blink = BlinkDetector()
        self.total_blinks = 0
        self._completed: list[Minute] = []
        self._minute: Minute | None = None
        self._last_t: float | None = None

        self._pose_samples: deque[tuple[float, float]] = deque(maxlen=POSE_WINDOW_S)
        self._pose_center: tuple[float, float] | None = None
        self._last_pose_sample_t = float("-inf")

        self._on_screen = False
        self._looking_since: float | None = None
        self._not_looking_since: float | None = None
        self._away_since: float | None = None

        self._gap_start: float | None = None
        self._streak_s = 0.0
        self._recent_blinks: deque[float] = deque()
        self._last_stare_alert = float("-inf")
        self._last_break_alert = float("-inf")

    @property
    def on_screen(self) -> bool:
        return self._on_screen

    def snapshot(self, now: float) -> dict:
        while self._recent_blinks and now - self._recent_blinks[0] > 60:
            self._recent_blinks.popleft()
        return {
            "on_screen": self._on_screen,
            "blinks_last_minute": len(self._recent_blinks),
            "seconds_since_blink": round(now - self._gap_start, 1) if self._on_screen and self._gap_start else None,
            "screen_streak_s": round(self._streak_s),
        }

    def update(self, now: float, sample: FaceSample | None) -> list[Event]:
        dt = min(now - self._last_t, MAX_FRAME_GAP_S) if self._last_t is not None else 0.0
        self._last_t = now
        minute = self._current_minute(now)
        events: list[Event] = []

        looking = False
        blink = None
        if sample is not None:
            minute.frames += 1
            minute.present_s += dt
            self._note_pose(now, sample)
            looking = self._facing_screen(sample)
            blink = self._blink.update(now, sample.ear)
        self._update_attention(now, looking, minute, events)

        if self._on_screen:
            minute.screen_s += dt
            self._streak_s += dt
            if blink is not None:
                minute.blinks += 1
                self.total_blinks += 1
                self._recent_blinks.append(now)
                self._gap_start = now
            gap = now - self._gap_start
            minute.longest_gap_s = max(minute.longest_gap_s, gap)
            self._check_alerts(now, gap, events)
        return events

    def take_completed(self) -> list[Minute]:
        done, self._completed = self._completed, []
        return done

    def suspend(self) -> None:
        """Close out the current minute and forget live state, e.g. when the camera is released."""
        self._finish_minute()
        self._blink.reset()
        self._last_t = None
        self._on_screen = False
        self._looking_since = None
        self._not_looking_since = None
        self._away_since = None
        self._gap_start = None
        self._streak_s = 0.0
        self._recent_blinks.clear()

    def _current_minute(self, now: float) -> Minute:
        ts = int(now // 60) * 60
        if self._minute is None or self._minute.ts != ts:
            self._finish_minute()
            self._minute = Minute(ts)
        return self._minute

    def _finish_minute(self) -> None:
        if self._minute is not None and self._minute.frames:  # empty minutes are not worth a row
            self._completed.append(self._minute)
        self._minute = None

    def _note_pose(self, now: float, sample: FaceSample) -> None:
        if now - self._last_pose_sample_t < 1.0:
            return
        self._last_pose_sample_t = now
        self._pose_samples.append((sample.yaw, sample.pitch))
        if len(self._pose_samples) >= POSE_WARMUP_SAMPLES:
            self._pose_center = (
                statistics.median(y for y, _ in self._pose_samples),
                statistics.median(p for _, p in self._pose_samples),
            )

    def _facing_screen(self, sample: FaceSample) -> bool:
        if self._pose_center is None:
            return True
        yaw, pitch = self._pose_center
        return abs(sample.yaw - yaw) <= YAW_LIMIT_DEG and abs(sample.pitch - pitch) <= PITCH_LIMIT_DEG

    def _update_attention(self, now: float, looking: bool, minute: Minute, events: list[Event]) -> None:
        if looking:
            self._not_looking_since = None
            if self._on_screen:
                return
            if self._looking_since is None:
                self._looking_since = now
            if now - self._looking_since < RETURN_DEBOUNCE_S:
                return
            self._on_screen = True
            self._gap_start = now
            if self._away_since is not None:
                away = now - self._away_since
                if away >= LOOK_AWAY_MIN_S:
                    minute.look_aways += 1
                if away >= self.config.break_min_s:
                    events.append(Event(now, "break", away))
                    self._streak_s = 0.0
                self._away_since = None
            return

        self._looking_since = None
        if not self._on_screen:
            return
        if self._not_looking_since is None:
            self._not_looking_since = now
        if now - self._not_looking_since >= LEAVE_DEBOUNCE_S:
            self._on_screen = False
            self._away_since = self._not_looking_since
            self._not_looking_since = None
            self._gap_start = None

    def _check_alerts(self, now: float, gap: float, events: list[Event]) -> None:
        cfg = self.config
        if gap >= cfg.stare_alert_s and now - self._last_stare_alert >= cfg.stare_alert_cooldown_s:
            self._last_stare_alert = now
            events.append(Event(now, "stare_alert", gap))
        if (
            self._streak_s >= cfg.break_alert_min * 60
            and now - self._last_break_alert >= cfg.break_alert_cooldown_min * 60
        ):
            self._last_break_alert = now
            events.append(Event(now, "break_alert", self._streak_s))
