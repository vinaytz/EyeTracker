import random

import pytest

from eyetracker.blink import BlinkDetector

FPS = 20
OPEN_EAR = 0.30


def signal(seconds, fps=FPS, noise=0.003, base=OPEN_EAR, seed=1):
    rng = random.Random(seed)
    return [[i / fps, base + rng.gauss(0, noise)] for i in range(int(seconds * fps))]


def dip(samples, at_s, frames, depth, fps=FPS):
    start = int(at_s * fps)
    for i in range(frames):
        samples[start + i][1] *= depth


def run(samples, detector=None):
    detector = detector or BlinkDetector()
    return [b for t, ear in samples if (b := detector.update(t, ear))]


def test_steady_open_eyes_are_not_blinks():
    assert run(signal(60)) == []


def test_counts_each_blink_once():
    samples = signal(30)
    moments = [2, 5, 7.5, 11, 14, 19, 22, 27]
    for at in moments:
        dip(samples, at, frames=4, depth=0.55)
    blinks = run(samples)
    assert len(blinks) == len(moments)
    assert [round(b.t) for b in blinks] == pytest.approx([m + 0.2 for m in moments], abs=0.6)


@pytest.mark.parametrize("frames,depth", [(1, 0.68), (2, 0.56), (3, 0.57), (5, 0.43)])
def test_blink_shapes_measured_from_the_landmark_model(frames, depth):
    samples = signal(10)
    dip(samples, 5, frames=frames, depth=depth)
    assert len(run(samples)) == 1


def test_half_closed_lids_do_not_count():
    samples = signal(10)
    dip(samples, 5, frames=3, depth=0.85)
    assert run(samples) == []


def test_works_at_ten_fps():
    samples = signal(20, fps=10)
    for at in (3, 8, 13):
        dip(samples, at, frames=2, depth=0.6, fps=10)
    assert len(run(samples)) == 3


def test_adapts_to_different_eye_shapes():
    for base in (0.18, 0.40):
        samples = signal(10, base=base, noise=base * 0.01)
        dip(samples, 5, frames=3, depth=0.6)
        assert len(run(samples)) == 1


def test_slow_drift_from_head_position_is_ignored():
    samples = [[t, ear - 0.004 * t] for t, ear in signal(20)]
    assert run(samples) == []


def test_lasting_step_down_is_not_a_blink_and_detection_recovers():
    samples = signal(30)
    for sample in samples[int(5 * FPS) :]:
        sample[1] *= 0.6
    dip(samples, 20, frames=3, depth=0.55)
    blinks = run(samples)
    assert len(blinks) == 1
    assert blinks[0].t > 19


def test_eyes_held_shut_count_once_as_rest():
    samples = signal(12)
    dip(samples, 5, frames=int(3 * FPS), depth=0.3)
    assert len(run(samples)) == 1


def test_a_lingering_shallow_drop_is_not_a_blink():
    samples = signal(12)
    dip(samples, 5, frames=int(3 * FPS), depth=0.65)
    assert run(samples) == []


def test_a_blink_ends_even_if_the_eye_settles_lower_than_before():
    samples = signal(12)
    dip(samples, 5, frames=3, depth=0.3)
    for sample in samples[int(5 * FPS) + 3 :]:
        sample[1] *= 0.86
    dip(samples, 8, frames=3, depth=0.3)
    blinks = run(samples)
    assert len(blinks) == 2
    assert blinks[0].duration < 0.3


def test_quick_double_blinks_count_twice():
    samples = signal(10)
    dip(samples, 5.0, frames=2, depth=0.4)
    dip(samples, 5.4, frames=2, depth=0.4)
    assert len(run(samples)) == 2


def test_no_detection_before_baseline_warms_up():
    samples = signal(5)
    dip(samples, 0.1, frames=2, depth=0.5)
    assert run(samples) == []
