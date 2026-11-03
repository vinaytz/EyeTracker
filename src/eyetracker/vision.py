"""Reduces a video frame to three numbers. The frame itself is never kept."""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from eyetracker.tracker import FaceSample

MODEL_PATH = Path(__file__).parent / "assets" / "face_landmarker.task"

RIGHT_EYE = (33, 160, 158, 133, 153, 144)
LEFT_EYE = (362, 385, 387, 263, 373, 380)
CHEEK_A, CHEEK_B = 234, 454
FOREHEAD, CHIN = 10, 152


def eye_aspect_ratio(points: np.ndarray, eye: tuple[int, ...]) -> float:
    p1, p2, p3, p4, p5, p6 = (points[i, :2] for i in eye)
    width = np.linalg.norm(p1 - p4)
    if width == 0:
        return 0.0
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * width))


def head_angles(points: np.ndarray) -> tuple[float, float]:
    across = points[CHEEK_B] - points[CHEEK_A]
    down = points[CHIN] - points[FOREHEAD]
    return (
        math.degrees(math.atan2(across[2], across[0])),
        math.degrees(math.atan2(down[2], down[1])),
    )


class FaceAnalyzer:
    def __init__(self) -> None:
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ts_ms = -1

    def analyze(self, rgb: np.ndarray, ts_ms: int) -> FaceSample | None:
        ts_ms = max(ts_ms, self._last_ts_ms + 1)  # the model rejects repeated timestamps
        self._last_ts_ms = ts_ms
        result = self._landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts_ms
        )
        if not result.face_landmarks:
            return None
        height, width = rgb.shape[:2]
        points = np.array([(p.x * width, p.y * height, p.z * width) for p in result.face_landmarks[0]])
        ear = (eye_aspect_ratio(points, RIGHT_EYE) + eye_aspect_ratio(points, LEFT_EYE)) / 2
        yaw, pitch = head_angles(points)
        return FaceSample(ear=ear, yaw=yaw, pitch=pitch)

    def close(self) -> None:
        self._landmarker.close()
