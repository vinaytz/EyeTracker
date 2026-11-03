"""Webcam access, tuned for catching blinks.

Many UVC webcams drop to about 10 fps in dim rooms because of "dynamic
framerate" auto-exposure, which is too slow for blinks. OpenCV cannot change
that control, so it is set directly over V4L2 and restored on release so other
apps get the camera as they found it.
"""

from __future__ import annotations

import fcntl
import logging
import os
import struct

import cv2
import numpy as np

log = logging.getLogger(__name__)

_V4L2_CID_EXPOSURE_AUTO_PRIORITY = 0x009A0903


def _iowr(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("V") << 8) | nr


_VIDIOC_G_CTRL = _iowr(27, 8)
_VIDIOC_S_CTRL = _iowr(28, 8)


def _get_control(fd: int, control: int) -> int:
    buf = bytearray(struct.pack("Ii", control, 0))
    fcntl.ioctl(fd, _VIDIOC_G_CTRL, buf)
    return struct.unpack("Ii", bytes(buf))[1]


def _set_control(fd: int, control: int, value: int) -> None:
    fcntl.ioctl(fd, _VIDIOC_S_CTRL, bytearray(struct.pack("Ii", control, value)))


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480) -> None:
        self.index = index
        self.width = width
        self.height = height
        self._cap: cv2.VideoCapture | None = None
        self._fd: int | None = None
        self._saved_priority: int | None = None
        self._raw_yuyv = False

    @property
    def is_open(self) -> bool:
        return self._cap is not None

    def open(self) -> bool:
        cap = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))  # no JPEG decoding per frame
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._raw_yuyv = bool(cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)) and self._is_yuyv(cap)
        if not self._raw_yuyv:
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)
        if not cap.grab():
            cap.release()  # opened, but another app holds the stream
            return False
        self._cap = cap
        self._hold_frame_rate()
        return True

    def grab(self) -> bool:
        return self._cap is not None and self._cap.grab()

    def retrieve_rgb(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, frame = self._cap.retrieve()
        if not ok or frame is None:
            return None
        code = cv2.COLOR_YUV2RGB_YUYV if self._raw_yuyv else cv2.COLOR_BGR2RGB
        return cv2.cvtColor(frame, code)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._restore_frame_rate()

    @staticmethod
    def _is_yuyv(cap: cv2.VideoCapture) -> bool:
        return int(cap.get(cv2.CAP_PROP_FOURCC)) == cv2.VideoWriter_fourcc(*"YUYV")

    def _hold_frame_rate(self) -> None:
        try:
            self._fd = os.open(f"/dev/video{self.index}", os.O_RDWR | os.O_NONBLOCK)
            self._saved_priority = _get_control(self._fd, _V4L2_CID_EXPOSURE_AUTO_PRIORITY)
            _set_control(self._fd, _V4L2_CID_EXPOSURE_AUTO_PRIORITY, 0)
        except OSError as err:
            log.debug("dynamic framerate control unavailable: %s", err)
            self._saved_priority = None

    def _restore_frame_rate(self) -> None:
        if self._fd is None:
            return
        try:
            if self._saved_priority is not None:
                _set_control(self._fd, _V4L2_CID_EXPOSURE_AUTO_PRIORITY, self._saved_priority)
        except OSError as err:
            log.debug("could not restore dynamic framerate: %s", err)
        finally:
            os.close(self._fd)
            self._fd = None
            self._saved_priority = None
