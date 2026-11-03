import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from eyetracker import guards
from eyetracker.config import Config


def fake_run(monkeypatch, stdout="", returncode=0, raises=None):
    def run(*args, **kwargs):
        if raises:
            raise raises
        return SimpleNamespace(stdout=stdout, returncode=returncode)

    monkeypatch.setattr(guards.subprocess, "run", run)


@pytest.mark.parametrize("output,expected", [("(true,)\n", True), ("(false,)\n", False)])
def test_screen_locked_reads_gnome_state(monkeypatch, output, expected):
    fake_run(monkeypatch, output)
    assert guards.screen_locked() is expected


def test_a_desktop_without_gnome_is_never_locked(monkeypatch):
    fake_run(monkeypatch, "", returncode=1)
    assert guards.screen_locked() is False


def test_mic_in_use_with_a_live_stream(monkeypatch):
    fake_run(monkeypatch, json.dumps([{"index": 7, "corked": False}]))
    assert guards.mic_in_use() is True


def test_a_corked_stream_is_not_in_use(monkeypatch):
    fake_run(monkeypatch, json.dumps([{"index": 7, "corked": True}]))
    assert guards.mic_in_use() is False


@pytest.mark.parametrize("output", ["[]", "", "not json"])
def test_no_or_unreadable_streams_mean_not_in_use(monkeypatch, output):
    fake_run(monkeypatch, output)
    assert guards.mic_in_use() is False


@pytest.mark.parametrize(
    "error", [FileNotFoundError("pactl"), subprocess.TimeoutExpired("pactl", 2)]
)
def test_missing_or_stuck_tools_do_not_crash_the_tracker(monkeypatch, error):
    fake_run(monkeypatch, raises=error)
    assert guards.mic_in_use() is False
    assert guards.screen_locked() is False


def test_pause_file(tmp_path):
    path = tmp_path / "pause_until"
    assert guards.paused_until(path) is None
    path.write_text(str(time.time() + 60))
    assert guards.paused_until(path) is not None
    path.write_text(str(time.time() - 60))
    assert guards.paused_until(path) is None
    path.write_text("garbage")
    assert guards.paused_until(path) is None


def test_blocked_reason_order_and_settings(monkeypatch, tmp_path):
    pause = tmp_path / "pause_until"
    monkeypatch.setattr(guards, "screen_locked", lambda: True)
    monkeypatch.setattr(guards, "mic_in_use", lambda: True)
    assert guards.blocked_reason(Config(), pause) == "screen-locked"
    assert guards.blocked_reason(Config(pause_when_locked=False), pause) == "mic-in-use"
    assert guards.blocked_reason(Config(pause_when_locked=False, pause_when_mic_active=False), pause) is None
    pause.write_text(str(time.time() + 60))
    assert guards.blocked_reason(Config(), pause) == "paused"
