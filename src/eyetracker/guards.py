"""Reasons to let go of the camera: a call, a locked screen, or a manual pause."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from eyetracker.config import Config


def _run(*args: str) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def screen_locked() -> bool:
    out = _run(
        "gdbus", "call", "--session",
        "--dest", "org.gnome.ScreenSaver",
        "--object-path", "/org/gnome/ScreenSaver",
        "--method", "org.gnome.ScreenSaver.GetActive",
    )
    return out is not None and "true" in out


def mic_in_use() -> bool:
    out = _run("pactl", "-f", "json", "list", "source-outputs")
    if not out:
        return False
    try:
        streams = json.loads(out)
    except json.JSONDecodeError:
        return False
    return any(not s.get("corked", False) for s in streams)


def paused_until(path: Path, now: float | None = None) -> float | None:
    try:
        until = float(path.read_text())
    except (OSError, ValueError):
        return None
    return until if until > (time.time() if now is None else now) else None


def blocked_reason(config: Config, pause_file: Path) -> str | None:
    if paused_until(pause_file) is not None:
        return "paused"
    if config.pause_when_locked and screen_locked():
        return "screen-locked"
    if config.pause_when_mic_active and mic_in_use():
        return "mic-in-use"
    return None
