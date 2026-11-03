"""Settings and on-disk locations."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    camera_index: int = 0
    target_fps: float = 20.0  # frames analysed per second while a face is visible
    idle_fps: float = 1.0  # frames analysed per second while nobody is there
    idle_after_s: float = 10.0  # seconds without a face before dropping to idle_fps

    pause_when_mic_active: bool = True  # releases the camera so calls can use it
    pause_when_locked: bool = True

    alerts_enabled: bool = True
    stare_alert_s: float = 30.0  # warn after this long without a blink
    stare_alert_cooldown_s: float = 300.0
    break_alert_min: float = 20.0  # warn after this much screen time without a break
    break_alert_cooldown_min: float = 5.0
    break_min_s: float = 20.0  # time away from the screen that counts as a real break


@dataclass(frozen=True)
class Paths:
    config_file: Path
    data_dir: Path
    runtime_dir: Path

    @classmethod
    def default(cls) -> Paths:
        home = Path.home()
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        return cls(
            config_file=config / "eyetracker/config.toml",
            data_dir=data / "eyetracker",
            runtime_dir=Path(runtime) / "eyetracker" if runtime else data / "eyetracker/run",
        )

    @property
    def db(self) -> Path:
        return self.data_dir / "eyetracker.db"

    @property
    def status(self) -> Path:
        return self.runtime_dir / "status.json"

    @property
    def pause(self) -> Path:
        return self.runtime_dir / "pause_until"

    @property
    def lock(self) -> Path:
        return self.runtime_dir / "daemon.lock"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        values = tomllib.load(f)
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise SystemExit(f"Unknown setting(s) in {path}: {', '.join(unknown)}")
    return Config(**values)
