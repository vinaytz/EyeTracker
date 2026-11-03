"""Installs the tracker as a systemd user service that follows your desktop session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

NAME = "eyetracker.service"

UNIT = """\
[Unit]
Description=Eye Tracker (local blink and screen-time tracking)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart={python} -m eyetracker run
Restart=on-failure
RestartSec=10
Nice=10
MemoryMax=500M
PrivateUsers=yes
PrivateNetwork=yes

[Install]
WantedBy=graphical-session.target
"""


def unit_path() -> Path:
    return Path.home() / ".config/systemd/user" / NAME


def _systemctl(*args: str) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True)


def install() -> None:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(UNIT.format(python=sys.executable))
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", NAME)


def uninstall() -> None:
    path = unit_path()
    if path.exists():
        _systemctl("disable", "--now", NAME)
        path.unlink()
        _systemctl("daemon-reload")
