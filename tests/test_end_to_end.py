"""Runs generated video through the real landmark model and blink detector."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from eyetracker.config import Config
from eyetracker.tracker import Tracker
from eyetracker.vision import FaceAnalyzer

DATA = Path(__file__).parent / "data"
FPS = 20
FAST_BLINK = ["half", "closed"]
NORMAL_BLINK = ["half", "closed", "half"]
SLOW_BLINK = ["half", "closed", "closed", "closed", "half"]


@pytest.fixture(scope="module")
def frames():
    return {
        name: cv2.cvtColor(cv2.imread(str(DATA / f"face_{name}.jpg")), cv2.COLOR_BGR2RGB)
        for name in ("open", "half", "closed")
    }


def sway(frame, t):
    """Slow natural head movement, in the same way for every eye state."""
    dx, dy = 8 * np.sin(t * 0.9), 5 * np.sin(t * 1.3)
    scale = 1 + 0.025 * np.sin(t * 0.5)
    matrix = cv2.getRotationMatrix2D((320, 240), 1.5 * np.sin(t * 0.7), scale)
    matrix[:, 2] += (dx, dy)
    return cv2.warpAffine(frame, matrix, (640, 480), borderMode=cv2.BORDER_REPLICATE)


def darken(frame, rng):
    gain = 25 / frame.mean()
    return np.clip(frame.astype(np.float32) * gain + rng.normal(0, 4, frame.shape), 0, 255).astype(np.uint8)


def script(blinks, gap_s):
    states = ["open"] * (gap_s * FPS)
    for shape in blinks:
        states += shape + ["open"] * (gap_s * FPS)
    return states


def count_blinks(frames, states, transform=lambda f, t: f):
    analyzer = FaceAnalyzer()
    tracker = Tracker(Config(stare_alert_s=1000, break_alert_min=1000))
    try:
        for index, state in enumerate(states):
            t = 1_800_000_000 + index / FPS
            sample = analyzer.analyze(transform(frames[state], t), int(index * 1000 / FPS))
            assert sample is not None, f"lost the face at frame {index}"
            tracker.update(t, sample)
    finally:
        analyzer.close()
    tracker.suspend()
    return sum(m.blinks for m in tracker.take_completed())


BLINKS = [NORMAL_BLINK, FAST_BLINK, SLOW_BLINK, NORMAL_BLINK, FAST_BLINK, NORMAL_BLINK]


def test_no_false_blinks_while_swaying(frames):
    assert count_blinks(frames, ["open"] * (30 * FPS), lambda f, t: sway(f, t)) == 0


def test_counts_every_blink_on_a_steady_face(frames):
    assert count_blinks(frames, script(BLINKS, 3)) == len(BLINKS)


def test_counts_every_blink_while_swaying(frames):
    assert count_blinks(frames, script(BLINKS, 3), lambda f, t: sway(f, t)) == len(BLINKS)


def test_counts_nearly_every_blink_in_a_dark_noisy_frame(frames):
    # Painted lids fall well short of a real blink in this light, and the weakest
    # one here only reaches 0.81x. tests/test_real_blinks.py covers real eyelids.
    rng = np.random.default_rng(0)
    assert count_blinks(frames, script(BLINKS, 3), lambda f, t: darken(sway(f, t), rng)) >= 5


def test_half_closed_lids_are_not_blinks(frames):
    assert count_blinks(frames, script([["half"], ["half", "half"]], 3)) == 0
