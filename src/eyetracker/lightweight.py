"""Process settings that keep the CPU cost down.

On a typical laptop the face model spends far more time waking threads and
moving between cores than doing useful work. Keeping everything on one core
and turning off OpenCV's thread pool cuts CPU use roughly in half while still
analysing every frame.
"""

from __future__ import annotations

import os

import cv2


def limit_cpu_use() -> None:
    cv2.setNumThreads(1)
    os.sched_setaffinity(0, {max(os.sched_getaffinity(0))})
