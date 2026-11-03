"""Drives the real loop with a stand-in camera and face model."""

import fcntl
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import date
from types import SimpleNamespace

import cv2
import pytest

from eyetracker import daemon as daemon_module
from eyetracker import guards
from eyetracker.config import Config, Paths
from eyetracker.lightweight import limit_cpu_use
from eyetracker.report import Report
from eyetracker.tracker import FaceSample


class FakeCamera:
    opens_ok = True
    grabs_ok = True

    def __init__(self, index=0):
        self.is_open = False
        self.opened = 0
        self.released = 0

    def open(self):
        if not self.opens_ok:
            return False
        self.is_open = True
        self.opened += 1
        return True

    def grab(self):
        time.sleep(0.002)
        return self.grabs_ok

    def retrieve_rgb(self):
        return b"frame"

    def release(self):
        self.is_open = False
        self.released += 1


class FakeAnalyzer:
    sample = FaceSample(ear=0.3, yaw=0.0, pitch=0.0)

    def __init__(self):
        self.closed = False
        self.frames = 0

    def analyze(self, rgb, ts_ms):
        self.frames += 1
        return self.sample

    def close(self):
        self.closed = True


@pytest.fixture
def world(monkeypatch, tmp_path):
    paths = Paths(tmp_path / "config.toml", tmp_path / "data", tmp_path / "run")
    paths.ensure()
    notes = []
    monkeypatch.setattr(daemon_module, "Camera", FakeCamera)
    monkeypatch.setitem(sys.modules, "eyetracker.vision", SimpleNamespace(FaceAnalyzer=FakeAnalyzer))
    monkeypatch.setattr(daemon_module.notify, "send", notes.append)
    monkeypatch.setattr(guards, "screen_locked", lambda: False)
    monkeypatch.setattr(guards, "mic_in_use", lambda: False)
    monkeypatch.setattr(daemon_module, "PAUSE_POLL_S", 0.01)
    monkeypatch.setattr(daemon_module, "GUARD_POLL_S", 0.02)
    monkeypatch.setattr(daemon_module, "STATUS_EVERY_S", 0.01)
    monkeypatch.setattr(daemon_module, "CAMERA_RETRY_S", 0.02)
    monkeypatch.setattr(daemon_module, "RELEASE_SETTLE_S", 0.01)
    monkeypatch.setattr(daemon_module.signal, "signal", lambda *a: None)
    return SimpleNamespace(paths=paths, notes=notes)


class Running:
    def __init__(self, world, config=None):
        self.world = world
        self.config = config or Config(target_fps=200)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._main)

    def _main(self):
        self.d = daemon_module.Daemon(self.config, self.world.paths)
        self.ready.set()
        self.d.run()

    def __enter__(self):
        self.thread.start()
        assert self.ready.wait(timeout=5)
        return self.d

    def __exit__(self, *exc):
        self.d.stopping = True
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


def state(world):
    try:
        return json.loads(world.paths.status.read_text())["state"]
    except (OSError, ValueError):
        return None


def test_tracks_then_shuts_down_cleanly_and_saves(world):
    with Running(world) as d:
        assert wait_for(lambda: state(world) == "tracking")
        assert wait_for(lambda: d.analyzer.frames > 50)
    assert d.camera.is_open is False
    assert d.analyzer.closed is True
    assert state(world) == "stopped"
    assert Report(world.paths.db).summary(date.today())["screen_min"] >= 0


def test_pause_releases_the_camera_and_resume_takes_it_back(world):
    with Running(world) as d:
        assert wait_for(lambda: d.camera.is_open)
        world.paths.pause.write_text(str(time.time() + 60))
        assert wait_for(lambda: state(world) == "paused")
        assert d.camera.is_open is False
        world.paths.pause.unlink()
        assert wait_for(lambda: d.camera.is_open and d.camera.opened == 2)


def test_a_microphone_going_live_releases_the_camera(world, monkeypatch):
    live = {"mic": False}
    monkeypatch.setattr(guards, "mic_in_use", lambda: live["mic"])
    with Running(world) as d:
        assert wait_for(lambda: d.camera.is_open)
        live["mic"] = True
        assert wait_for(lambda: state(world) == "mic-in-use")
        assert d.camera.is_open is False
        live["mic"] = False
        assert wait_for(lambda: d.camera.is_open)


def test_locking_the_screen_releases_the_camera(world, monkeypatch):
    live = {"locked": False}
    monkeypatch.setattr(guards, "screen_locked", lambda: live["locked"])
    with Running(world) as d:
        assert wait_for(lambda: d.camera.is_open)
        live["locked"] = True
        assert wait_for(lambda: state(world) == "screen-locked")
        assert d.camera.is_open is False


def test_a_busy_camera_is_retried_until_it_frees_up(world, monkeypatch):
    monkeypatch.setattr(FakeCamera, "opens_ok", False)
    with Running(world) as d:
        assert wait_for(lambda: state(world) == "camera-unavailable")
        monkeypatch.setattr(FakeCamera, "opens_ok", True)
        assert wait_for(lambda: d.camera.is_open)


def test_a_dead_camera_is_reopened_without_spinning(world, monkeypatch):
    monkeypatch.setattr(FakeCamera, "grabs_ok", False)
    monkeypatch.setattr(daemon_module, "RELEASE_SETTLE_S", 0.05)
    with Running(world) as d:
        assert wait_for(lambda: d.camera.opened >= 2)
        time.sleep(0.1)
        assert d.camera.opened < 10


def test_an_alert_is_saved_and_shown(world):
    with Running(world, Config(target_fps=200, stare_alert_s=0.15)):
        assert wait_for(lambda: world.notes)
    assert world.notes[0].kind == "stare_alert"
    assert Report(world.paths.db).summary(date.today())["stare_alerts"] == 1


def test_alerts_can_be_switched_off_without_losing_the_record(world):
    report = Report(world.paths.db)
    with Running(world, Config(target_fps=200, stare_alert_s=0.15, alerts_enabled=False)):
        assert wait_for(lambda: report.summary(date.today())["stare_alerts"] == 1)
    assert world.notes == []


def test_drops_to_a_slow_frame_rate_when_nobody_is_there(world, monkeypatch):
    monkeypatch.setattr(FakeAnalyzer, "sample", None)
    config = Config(target_fps=200, idle_fps=5, idle_after_s=0.1)
    with Running(world, config) as d:
        assert wait_for(lambda: state(world) == "idle")
        before = d.analyzer.frames
        time.sleep(0.4)
        assert d.analyzer.frames - before <= 4


def test_nobody_present_writes_no_rows(world, monkeypatch):
    monkeypatch.setattr(FakeAnalyzer, "sample", None)
    with Running(world) as d:
        assert wait_for(lambda: d.analyzer.frames > 30)
    assert sqlite3.connect(world.paths.db).execute("SELECT COUNT(*) FROM minutes").fetchone()[0] == 0


def test_a_second_copy_refuses_to_start(world, capsys):
    holder = world.paths.lock.open("w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert daemon_module.run(Config(), world.paths) == 1
    assert "already running" in capsys.readouterr().out


def test_cpu_limit_keeps_the_process_on_one_core():
    cores = os.sched_getaffinity(0)
    threads = cv2.getNumThreads()
    try:
        limit_cpu_use()
        assert len(os.sched_getaffinity(0)) == 1
        assert os.sched_getaffinity(0) <= cores
        assert cv2.getNumThreads() == 1
    finally:
        os.sched_setaffinity(0, cores)
        cv2.setNumThreads(threads)
