"""Locate the retroreflective marker in an IR frame.

With the IR LEDs lit and exposure driven low, the marker is by far the
brightest thing in frame, so a simple threshold plus contour search is both
sufficient and extremely cheap (well under a millisecond at 640x480). The
centroid is intensity-weighted rather than purely geometric, which yields
sub-pixel precision and materially reduces cursor jitter.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

DEFAULT_THRESHOLD = 200
DEFAULT_MIN_AREA = 4.0
DEFAULT_MAX_AREA = 5000.0
DEFAULT_MAX_JUMP = 120.0


@dataclass(frozen=True)
class TrackResult:
    """Where the marker was found this frame, if at all."""

    found: bool
    x: float = 0.0
    y: float = 0.0
    area: float = 0.0
    contour: np.ndarray | None = None

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)


class DotTracker:
    """Finds the brightest blob that looks like the marker."""

    def __init__(
        self,
        threshold: int = DEFAULT_THRESHOLD,
        min_area: float = DEFAULT_MIN_AREA,
        max_area: float = DEFAULT_MAX_AREA,
        max_jump: float = DEFAULT_MAX_JUMP,
    ) -> None:
        self.threshold = threshold
        self.min_area = min_area
        self.max_area = max_area
        # Candidates further than this from the last known position are only
        # accepted once tracking has been lost, which keeps a bright window or
        # lamp from stealing the track mid-motion.
        self.max_jump = max_jump
        self._last: tuple[float, float] | None = None

    def reset(self) -> None:
        self._last = None

    def process(self, gray: np.ndarray) -> TrackResult:
        """Locate the marker in a single-channel frame."""
        if gray.ndim != 2:
            raise ValueError("DotTracker.process expects a grayscale frame")

        _, mask = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = [
            (contour, area)
            for contour in contours
            if self.min_area <= (area := cv2.contourArea(contour)) <= self.max_area
        ]
        if not candidates:
            self._last = None
            return TrackResult(found=False)

        contour, area = self._select(candidates)
        x, y = _weighted_centroid(gray, contour)
        self._last = (x, y)
        return TrackResult(found=True, x=x, y=y, area=area, contour=contour)

    def _select(self, candidates: list[tuple[np.ndarray, float]]) -> tuple[np.ndarray, float]:
        """Prefer continuity with the last frame, falling back to the largest blob."""
        if self._last is not None:
            last_x, last_y = self._last
            near = [
                (contour, area)
                for contour, area in candidates
                if _distance(_geometric_centroid(contour), (last_x, last_y)) <= self.max_jump
            ]
            if near:
                return max(near, key=lambda item: item[1])
        return max(candidates, key=lambda item: item[1])


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def _geometric_centroid(contour: np.ndarray) -> tuple[float, float]:
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        point = contour[0][0]
        return (float(point[0]), float(point[1]))
    return (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])


def _weighted_centroid(gray: np.ndarray, contour: np.ndarray) -> tuple[float, float]:
    """Intensity-weighted centre of the blob, accurate to a fraction of a pixel."""
    x, y, w, h = cv2.boundingRect(contour)
    roi = gray[y : y + h, x : x + w].astype(np.float32)

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, cv2.FILLED, offset=(-x, -y))
    weights = np.where(mask > 0, roi, 0.0)

    total = float(weights.sum())
    if total <= 0.0:
        return _geometric_centroid(contour)

    rows, cols = np.mgrid[0:h, 0:w]
    cx = x + float((weights * cols).sum()) / total
    cy = y + float((weights * rows).sum()) / total
    return (cx, cy)
