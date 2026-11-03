"""Blink detection from the eye aspect ratio (EAR).

A blink is a sharp dip below the recent open-eye level followed by a recovery.
Measuring against a rolling baseline rather than a fixed value lets the detector
work for any eye shape and absorbs slow changes from head position and
expression. Recovery is judged against the bottom of the dip, not the baseline,
so a blink still ends promptly when the eye settles at a slightly lower level.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Blink:
    t: float
    duration: float


class BlinkDetector:
    def __init__(
        self,
        close_ratio: float = 0.80,
        recovery: float = 0.65,
        baseline_window_s: float = 3.0,
        baseline_percentile: float = 0.8,
        warmup_s: float = 0.4,
        max_closure_s: float = 0.8,
        rest_ratio: float = 0.5,
    ) -> None:
        self.close_ratio = close_ratio
        self.recovery = recovery
        self.baseline_window_s = baseline_window_s
        self.baseline_percentile = baseline_percentile
        self.warmup_s = warmup_s
        self.max_closure_s = max_closure_s
        self.rest_ratio = rest_ratio
        self._history: deque[tuple[float, float]] = deque()
        self._closed_at: float | None = None
        self._lowest = 0.0

    @property
    def baseline(self) -> float | None:
        if not self._history:
            return None
        if self._history[-1][0] - self._history[0][0] < self.warmup_s:
            return None
        ears = sorted(ear for _, ear in self._history)
        return ears[int(len(ears) * self.baseline_percentile)]

    def update(self, t: float, ear: float) -> Blink | None:
        baseline = self.baseline
        if self._closed_at is not None:
            self._lowest = min(self._lowest, ear)
            if t - self._closed_at > self.max_closure_s:
                # Eyes held properly shut still count as rest. A shallow lasting
                # drop is a change of pose or expression, so start over from it.
                rested = baseline is not None and self._lowest < baseline * self.rest_ratio
                blink = Blink(t, t - self._closed_at) if rested else None
                self.reset()
                return blink
            if baseline is not None and ear >= self._lowest + self.recovery * (baseline - self._lowest):
                blink = Blink(t, t - self._closed_at)
                self._closed_at = None
                return blink
            return None

        if baseline is not None and ear < baseline * self.close_ratio:
            self._closed_at = t
            self._lowest = ear
            return None
        self._remember(t, ear)
        return None

    def reset(self) -> None:
        self._history.clear()
        self._closed_at = None

    def _remember(self, t: float, ear: float) -> None:
        self._history.append((t, ear))
        while t - self._history[0][0] > self.baseline_window_s:
            self._history.popleft()
