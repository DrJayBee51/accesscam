"""Tracker tests. These run without a camera so CI can execute them."""

import cv2
import numpy as np
import pytest

from accesscam.tracker import DotTracker


def frame_with_dot(x: int, y: int, radius: int = 6, brightness: int = 255) -> np.ndarray:
    gray = np.zeros((240, 320), dtype=np.uint8)
    cv2.circle(gray, (x, y), radius, brightness, cv2.FILLED)
    return gray


def test_finds_dot_near_true_centre():
    tracker = DotTracker()
    result = tracker.process(frame_with_dot(160, 120))

    assert result.found
    assert result.x == pytest.approx(160.0, abs=1.0)
    assert result.y == pytest.approx(120.0, abs=1.0)
    assert result.area > 0


def test_reports_not_found_on_dark_frame():
    tracker = DotTracker()
    result = tracker.process(np.zeros((240, 320), dtype=np.uint8))

    assert not result.found


def test_ignores_blobs_below_min_area():
    tracker = DotTracker(min_area=500.0)
    result = tracker.process(frame_with_dot(160, 120, radius=3))

    assert not result.found


def test_prefers_candidate_near_last_position():
    # A large distractor appears after the marker is already being tracked;
    # continuity should keep the track on the smaller, closer blob.
    tracker = DotTracker()
    tracker.process(frame_with_dot(100, 120, radius=6))

    gray = frame_with_dot(104, 120, radius=6)
    cv2.circle(gray, (280, 60), 20, 255, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x < 150


def test_largest_blob_wins_when_track_is_lost():
    tracker = DotTracker()

    gray = frame_with_dot(100, 120, radius=4)
    cv2.circle(gray, (280, 60), 20, 255, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x == pytest.approx(280.0, abs=2.0)


def test_rejects_colour_frames():
    tracker = DotTracker()
    with pytest.raises(ValueError):
        tracker.process(np.zeros((240, 320, 3), dtype=np.uint8))
