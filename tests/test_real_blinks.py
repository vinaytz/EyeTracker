"""Replays model output from real human blinks through the tracker. See data/README.md."""

from pathlib import Path

import numpy as np
import pytest

from eyetracker.config import Config
from eyetracker.tracker import FaceSample, Tracker

DATA = np.load(Path(__file__).parent / "data" / "real_blinks.npz")
START = 1_800_000_000


def detected_times(trace):
    tracker = Tracker(Config(stare_alert_s=1e9, break_alert_min=1e9))
    times = []
    for t, ear, yaw, pitch in trace:
        before = tracker.total_blinks
        sample = None if np.isnan(ear) else FaceSample(float(ear), float(yaw), float(pitch))
        tracker.update(START + float(t), sample)
        if tracker.total_blinks > before:
            times.append(float(t))
    return times


def score(detected, times, clear):
    """Pairs each detection with one labelled blink. A detection lands as the lid reopens."""
    used = np.zeros(len(times), dtype=bool)
    false_alarms = 0
    for t in detected:
        offsets = t - times
        candidates = np.where(~used & (offsets >= -0.15) & (offsets <= 0.75))[0]
        if len(candidates) == 0:
            false_alarms += 1
        else:
            used[candidates[np.argmin(np.abs(offsets[candidates]))]] = True
    recall = (used & clear).sum() / clear.sum()
    precision = 1 - false_alarms / len(detected)
    return recall, precision


@pytest.mark.parametrize("video", ["a", "b"])
@pytest.mark.parametrize("quality", ["clean", "night"])
def test_real_blinks_are_caught_with_few_false_alarms(video, quality):
    detected = detected_times(DATA[f"{video}_{quality}"])
    recall, precision = score(detected, DATA[f"{video}_times"], DATA[f"{video}_clear"])
    assert recall >= 0.85
    assert precision >= 0.92


@pytest.mark.parametrize("video", ["a", "b"])
def test_blink_rate_is_close_to_the_true_rate(video):
    detected = detected_times(DATA[f"{video}_clean"])
    labelled = DATA[f"{video}_clear"].sum()
    assert abs(len(detected) - labelled) / labelled <= 0.12
