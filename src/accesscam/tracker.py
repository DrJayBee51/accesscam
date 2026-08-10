"""Locate the retroreflective marker in an IR frame.

With the IR LEDs lit and exposure driven low, the marker is by far the
brightest thing in frame, so a simple threshold plus contour search is both
sufficient and extremely cheap (well under a millisecond at 640x480). The
centroid is intensity-weighted rather than purely geometric, which yields
sub-pixel precision and materially reduces cursor jitter.

"Brightest" is not enough on its own, though. In daylight a sunlit patch can
clear the threshold too, and selecting purely by blob size then hands the track
to whichever bright thing happens to be biggest - which in a lit room is rarely
the marker. Candidates are therefore also filtered by shape (the marker is
round; slats, bezels and edge reflections are not) and ranked by brightness
rather than area.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np

DEFAULT_THRESHOLD = 200
DEFAULT_MIN_AREA = 4.0
DEFAULT_MAX_AREA = 5000.0
DEFAULT_MAX_JUMP = 120.0
# 4*pi*area/perimeter^2 is 1.0 for a circle and falls as a shape elongates. A
# retroreflective dot images as a near-circle; window slats and edge highlights
# do not. 0.5 rejects anything more elongated than roughly 4:1 while still
# admitting a dot foreshortened about 3:1 by a steep downward camera angle.
# Set to 0.0 to disable the shape test.
DEFAULT_MIN_CIRCULARITY = 0.5


@dataclass(frozen=True)
class TrackResult:
    """Where the marker was found this frame, if at all."""

    found: bool
    x: float = 0.0
    y: float = 0.0
    area: float = 0.0
    brightness: float = 0.0
    contour: np.ndarray | None = None

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)


class _Candidate(NamedTuple):
    """A blob that survived the size and shape filters."""

    contour: np.ndarray
    area: float
    brightness: float


class DotTracker:
    """Finds the brightest round blob that looks like the marker."""

    def __init__(
        self,
        threshold: int = DEFAULT_THRESHOLD,
        min_area: float = DEFAULT_MIN_AREA,
        max_area: float = DEFAULT_MAX_AREA,
        max_jump: float = DEFAULT_MAX_JUMP,
        min_circularity: float = DEFAULT_MIN_CIRCULARITY,
    ) -> None:
        self.threshold = threshold
        self.min_area = min_area
        self.max_area = max_area
        # Candidates further than this from the last known position are only
        # accepted once tracking has been lost, which keeps a bright window or
        # lamp from stealing the track mid-motion.
        self.max_jump = max_jump
        self.min_circularity = min_circularity
        self._last: tuple[float, float] | None = None

    def reset(self) -> None:
        self._last = None

    def process(self, gray: np.ndarray) -> TrackResult:
        """Locate the marker in a single-channel frame."""
        if gray.ndim != 2:
            raise ValueError("DotTracker.process expects a grayscale frame")

        _, mask = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[_Candidate] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if not self.min_area <= area <= self.max_area:
                continue
            if _circularity(contour, area) < self.min_circularity:
                continue
            candidates.append(_Candidate(contour, area, _mean_intensity(gray, contour)))

        if not candidates:
            self._last = None
            return TrackResult(found=False)

        chosen = self._select(candidates)
        x, y = _weighted_centroid(gray, chosen.contour)
        self._last = (x, y)
        return TrackResult(
            found=True,
            x=x,
            y=y,
            area=chosen.area,
            brightness=chosen.brightness,
            contour=chosen.contour,
        )

    def _select(self, candidates: list[_Candidate]) -> _Candidate:
        """Prefer continuity with the last frame, then the brightest candidate.

        Ranking by brightness rather than area is what stops a large but dimmer
        object - a sunlit wall, a monitor bezel - from outranking the marker,
        which returns the IR LEDs straight back at the lens and should be the
        brightest thing in frame once exposure is short. Area only breaks ties,
        which matters when two blobs are both saturated at 255 and brightness
        genuinely cannot separate them.
        """
        if self._last is not None:
            near = [
                candidate
                for candidate in candidates
                if _distance(_geometric_centroid(candidate.contour), self._last) <= self.max_jump
            ]
            if near:
                return max(near, key=_rank)
        return max(candidates, key=_rank)


def _rank(candidate: _Candidate) -> tuple[float, float]:
    return (candidate.brightness, candidate.area)


def _circularity(contour: np.ndarray, area: float) -> float:
    """4*pi*A/P^2 — 1.0 for a circle, falling towards 0 as the shape elongates."""
    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0.0:
        return 0.0
    return float(4.0 * np.pi * area / (perimeter * perimeter))


def _mean_intensity(gray: np.ndarray, contour: np.ndarray) -> float:
    """Average brightness of the pixels enclosed by the contour."""
    x, y, w, h = cv2.boundingRect(contour)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, cv2.FILLED, offset=(-x, -y))
    values = gray[y : y + h, x : x + w][mask > 0]
    return float(values.mean()) if values.size else 0.0


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
