"""The background loop: read the camera, update stats, save, alert."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import time
from pathlib import Path

from eyetracker import guards, notify
from eyetracker.camera import Camera
from eyetracker.config import Config, Paths
from eyetracker.lightweight import limit_cpu_use
from eyetracker.store import Store
from eyetracker.tracker import Tracker

log = logging.getLogger(__name__)

PAUSE_POLL_S = 1.0
GUARD_POLL_S = 5.0
STATUS_EVERY_S = 2.0
SAVE_EVERY_S = 30.0
CAMERA_RETRY_S = 10.0
RELEASE_SETTLE_S = 1.0
MAX_GRAB_FAILURES = 5


def write_status(path: Path, state: str, **fields) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, "updated_at": time.time(), "pid": os.getpid(), **fields}))
    tmp.replace(path)


class Daemon:
    def __init__(self, config: Config, paths: Paths) -> None:
        from eyetracker.vision import FaceAnalyzer  # slow import, only needed here

        self.config = config
        self.paths = paths
        self.store = Store(paths.db)
        self.tracker = Tracker(config)
        self.camera = Camera(config.camera_index)
        self.analyzer = FaceAnalyzer()
        self.stopping = False

    def request_stop(self, *_) -> None:
        self.stopping = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        log.info("started")
        try:
            while not self.stopping:
                reason = guards.blocked_reason(self.config, self.paths.pause)
                if reason is not None:
                    self._wait_while_blocked(reason)
                elif self.camera.open():
                    log.info("camera on")
                    self._track()
                    self.camera.release()
                    self.tracker.suspend()
                    self._save()
                    log.info("camera off")
                    self._sleep(RELEASE_SETTLE_S)
                else:
                    log.info("camera unavailable, retrying in %.0fs", CAMERA_RETRY_S)
                    self._status("camera-unavailable")
                    self._sleep(CAMERA_RETRY_S)
        finally:
            self.camera.release()
            self.tracker.suspend()
            self._save()
            self.store.close()
            self.analyzer.close()
            self._status("stopped")
            log.info("stopped")

    def _wait_while_blocked(self, reason: str) -> None:
        self._status(reason)
        deadline = time.monotonic() + GUARD_POLL_S
        while not self.stopping and time.monotonic() < deadline:
            self._sleep(PAUSE_POLL_S)
            if reason == "paused" and guards.paused_until(self.paths.pause) is None:
                return

    def _track(self) -> None:
        config = self.config
        started = time.monotonic()
        last_face = started
        next_frame = started
        next_pause_check = started + PAUSE_POLL_S
        next_guard_check = started + GUARD_POLL_S
        next_status = started
        next_save = started + SAVE_EVERY_S
        failures = 0

        while not self.stopping:
            if not self.camera.grab():
                failures += 1
                if failures >= MAX_GRAB_FAILURES:
                    log.warning("camera stopped delivering frames")
                    return
                continue
            failures = 0
            mono = time.monotonic()

            if mono >= next_pause_check:
                next_pause_check = mono + PAUSE_POLL_S
                if guards.paused_until(self.paths.pause) is not None:
                    return
            if mono >= next_guard_check:
                next_guard_check = mono + GUARD_POLL_S
                if guards.blocked_reason(config, self.paths.pause) is not None:
                    return

            if mono < next_frame:
                continue
            idle = mono - last_face > config.idle_after_s
            interval = 1 / (config.idle_fps if idle else config.target_fps)
            next_frame = max(next_frame + interval, mono)

            frame = self.camera.retrieve_rgb()
            if frame is None:
                continue
            sample = self.analyzer.analyze(frame, int(mono * 1000))
            del frame
            if sample is not None:
                last_face = mono

            now = time.time()
            events = self.tracker.update(now, sample)
            if events:
                self.store.save_events(events)
                if config.alerts_enabled:
                    for event in events:
                        notify.send(event)

            if mono >= next_status:
                next_status = mono + STATUS_EVERY_S
                self._status("idle" if idle else "tracking", **self.tracker.snapshot(now))
            if mono >= next_save:
                next_save = mono + SAVE_EVERY_S
                self._save()

    def _save(self) -> None:
        minutes = self.tracker.take_completed()
        if minutes:
            self.store.save_minutes(minutes)

    def _status(self, state: str, **fields) -> None:
        write_status(self.paths.status, state, **fields)

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.stopping and time.monotonic() < deadline:
            time.sleep(min(0.25, seconds))


def run(config: Config, paths: Paths) -> int:
    paths.ensure()
    lock = paths.lock.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Eye tracker is already running.")
        return 1
    limit_cpu_use()
    Daemon(config, paths).run()
    return 0
