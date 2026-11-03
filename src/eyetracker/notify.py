"""Desktop notifications for alerts."""

from __future__ import annotations

import logging
import subprocess

from eyetracker.tracker import Event

log = logging.getLogger(__name__)

_MESSAGES = {
    "stare_alert": ("Blink!", "No blink for {value:.0f} seconds. Close your eyes slowly a few times."),
    "break_alert": ("Rest your eyes", "{minutes:.0f} minutes of screen time. Look far away for 20 seconds."),
}


def send(event: Event) -> None:
    template = _MESSAGES.get(event.kind)
    if template is None:
        return
    title, body = template
    args = {"value": event.value, "minutes": event.value / 60}
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=Eye Tracker",
                "--icon=weather-clear-night-symbolic",
                "--expire-time=7000",
                "--hint=string:x-canonical-private-synchronous:eyetracker",
                title,
                body.format(**args),
            ],
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        log.warning("could not show notification: %s", err)
