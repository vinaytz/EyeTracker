from dataclasses import replace

import pytest

from eyetracker.config import Config
from eyetracker.tracker import FaceSample, Tracker

FPS = 20
START = 1_800_000_000.0  # exactly on a minute boundary
OPEN = FaceSample(ear=0.30, yaw=0.0, pitch=5.0)
CLOSED = replace(OPEN, ear=0.10)
TURNED = replace(OPEN, yaw=45.0)
CONFIG = Config(stare_alert_s=10, stare_alert_cooldown_s=60, break_alert_min=2, break_alert_cooldown_min=1)


class Clock:
    def __init__(self, tracker):
        self.tracker = tracker
        self.t = START
        self.events = []

    def play(self, seconds, sample=OPEN):
        for _ in range(round(seconds * FPS)):
            self.t += 1 / FPS
            self.events += self.tracker.update(self.t, sample)

    def blink(self):
        self.play(0.15, CLOSED)

    def kinds(self):
        return [e.kind for e in self.events]


def minutes(tracker):
    tracker.suspend()
    return tracker.take_completed()


@pytest.fixture
def clock():
    tracker = Tracker(CONFIG)
    c = Clock(tracker)
    c.play(10)  # settle the pose reference and blink baseline
    return c


def test_counts_screen_time_and_blinks(clock):
    for _ in range(4):
        clock.blink()
        clock.play(3)
    rows = minutes(clock.tracker)
    assert sum(m.blinks for m in rows) == 4
    assert sum(m.screen_s for m in rows) == pytest.approx(22.6, abs=0.5)
    assert sum(m.frames for m in rows) == pytest.approx(22.6 * FPS, abs=5)


def test_splits_stats_across_minutes():
    tracker = Tracker(CONFIG)
    clock = Clock(tracker)
    clock.play(130)
    rows = minutes(tracker)
    assert [m.ts for m in rows] == [int(START), int(START) + 60, int(START) + 120]
    assert rows[1].screen_s == pytest.approx(60, abs=0.2)


def test_longest_gap_tracks_time_between_blinks(clock):
    clock.play(9)
    clock.blink()
    clock.play(4)
    clock.blink()
    assert max(m.longest_gap_s for m in minutes(clock.tracker)) >= 18


def test_stare_alert_then_cooldown(clock):
    clock.play(1)
    assert clock.kinds().count("stare_alert") == 1
    clock.play(59 - 12)
    assert clock.kinds().count("stare_alert") == 1
    clock.play(13)
    assert clock.kinds().count("stare_alert") == 2


def test_blinking_prevents_stare_alert():
    clock = Clock(Tracker(CONFIG))
    for _ in range(10):
        clock.play(5)
        clock.blink()
    assert "stare_alert" not in clock.kinds()


def test_looking_away_is_counted_and_stops_the_stare_timer(clock):
    clock.tracker.config = replace(CONFIG, stare_alert_s=12)
    clock.play(1)
    clock.play(5, TURNED)
    assert clock.tracker.on_screen is False
    clock.play(8)
    assert "stare_alert" not in clock.kinds()
    assert sum(m.look_aways for m in minutes(clock.tracker)) == 1


def test_a_quick_glance_is_not_a_look_away(clock):
    clock.play(0.5, TURNED)
    clock.play(3)
    assert sum(m.look_aways for m in minutes(clock.tracker)) == 0


def test_face_dropout_under_a_second_does_not_end_screen_time(clock):
    clock.play(0.5, None)
    assert clock.tracker.on_screen is True


def test_leaving_for_a_while_is_a_break_and_resets_screen_streak():
    clock = Clock(Tracker(replace(CONFIG, stare_alert_s=1000)))
    clock.play(100)
    clock.play(25, None)
    clock.play(2)
    assert clock.kinds() == ["break"]
    assert clock.events[0].value == pytest.approx(25, abs=1.5)
    clock.play(100)
    assert "break_alert" not in clock.kinds()


def test_a_short_absence_is_not_a_break():
    clock = Clock(Tracker(replace(CONFIG, stare_alert_s=1000)))
    clock.play(30)
    clock.play(10, None)
    clock.play(2)
    assert "break" not in clock.kinds()
    assert sum(m.look_aways for m in minutes(clock.tracker)) == 1


def test_break_alert_after_long_screen_time_with_cooldown():
    clock = Clock(Tracker(replace(CONFIG, stare_alert_s=1000)))
    clock.play(121)
    assert clock.kinds() == ["break_alert"]
    clock.play(50)
    assert clock.kinds() == ["break_alert"]
    clock.play(15)
    assert clock.kinds() == ["break_alert", "break_alert"]


def test_blinks_while_looking_away_do_not_count(clock):
    clock.play(4, TURNED)
    clock.play(0.15, replace(TURNED, ear=0.10))
    clock.play(1, TURNED)
    assert sum(m.blinks for m in minutes(clock.tracker)) == 0


def test_pose_center_adapts_to_an_off_axis_camera():
    clock = Clock(Tracker(CONFIG))
    side_on = replace(OPEN, yaw=35.0, pitch=-20.0)
    clock.play(20, side_on)
    assert clock.tracker.on_screen is True


def test_blinks_count_while_the_head_is_moving():
    clock = Clock(Tracker(CONFIG))
    clock.play(5)
    clock.play(0.05, replace(OPEN, yaw=6.0, ear=0.10))
    clock.play(0.05, replace(OPEN, yaw=0.0, ear=0.10))
    clock.play(2)
    assert sum(m.blinks for m in minutes(clock.tracker)) == 1


def test_resting_the_eyes_clears_the_stare_timer():
    clock = Clock(Tracker(replace(CONFIG, stare_alert_s=12)))
    clock.play(9)
    clock.play(2, replace(OPEN, ear=0.05))
    clock.play(6)
    assert "stare_alert" not in clock.kinds()


def test_suspend_clears_live_state_without_inventing_a_break(clock):
    clock.tracker.suspend()
    clock.play(3)
    assert "break" not in clock.kinds()
    assert clock.tracker.on_screen is True


def test_a_wall_clock_jump_adds_at_most_two_seconds(clock):
    before = sum(m.screen_s for m in clock.tracker.take_completed())
    clock.t += 3600
    clock.play(1)
    total = before + sum(m.screen_s for m in minutes(clock.tracker))
    assert total < 14
