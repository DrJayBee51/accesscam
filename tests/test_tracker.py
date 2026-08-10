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
    # Both blobs are saturated, so brightness cannot separate them and area
    # breaks the tie.
    tracker = DotTracker()

    gray = frame_with_dot(100, 120, radius=4)
    cv2.circle(gray, (280, 60), 20, 255, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x == pytest.approx(280.0, abs=2.0)


def test_rejects_elongated_distractor():
    # A window slat is bright and larger than the marker, but nowhere near
    # round, so the shape filter should discard it on acquisition.
    tracker = DotTracker()

    gray = frame_with_dot(100, 120, radius=6)
    cv2.rectangle(gray, (200, 40), (260, 48), 255, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x == pytest.approx(100.0, abs=2.0)


def test_prefers_brighter_candidate_over_larger_one():
    # The marker returns the IR LEDs directly; a dimmer object that merely
    # clears the threshold should not win by being bigger.
    tracker = DotTracker()

    gray = frame_with_dot(100, 120, radius=5, brightness=255)
    cv2.circle(gray, (250, 60), 20, 220, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x == pytest.approx(100.0, abs=2.0)
    assert result.brightness == pytest.approx(255.0, abs=1.0)


def test_static_bright_distractor_does_not_capture_track():
    # The 2026-08-10 daylight failure: a stationary bright object present from
    # the first frame took the track, and max_jump then locked it there, so
    # head movement registered as ~1px of travel. The marker must win
    # acquisition and keep the track as it moves.
    tracker = DotTracker()

    seen = []
    for x in (100, 110, 120, 130, 140):
        gray = frame_with_dot(x, 120, radius=5, brightness=255)
        cv2.rectangle(gray, (200, 40), (280, 52), 240, cv2.FILLED)
        result = tracker.process(gray)
        assert result.found
        seen.append(result.x)

    assert seen[0] == pytest.approx(100.0, abs=2.0)
    assert seen[-1] == pytest.approx(140.0, abs=2.0)
    # Travel is what the bring-up tool measures; the distractor would flatten it.
    assert seen[-1] - seen[0] == pytest.approx(40.0, abs=3.0)


def test_shape_filter_can_be_disabled():
    tracker = DotTracker(min_circularity=0.0)

    gray = frame_with_dot(100, 120, radius=4)
    cv2.rectangle(gray, (200, 40), (280, 52), 255, cv2.FILLED)
    result = tracker.process(gray)

    assert result.found
    assert result.x > 150


def test_rejects_colour_frames():
    tracker = DotTracker()
    with pytest.raises(ValueError):
        tracker.process(np.zeros((240, 320, 3), dtype=np.uint8))
