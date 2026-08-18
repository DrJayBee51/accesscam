"""When a run of readings becomes something worth showing a person.

The judgement, not the measurement. Getting this wrong in the noisy direction
is worse than not having it: an indicator that cries wolf teaches you to ignore
it, and it will be ignored on the one occasion it is right.
"""

from __future__ import annotations

import pytest

from accesscam.engine import EngineStatus
from accesscam.health import Health


def status(fps=30.0, tracking=True, paused=False):
    return EngineStatus(fps=fps, tracking=tracking, paused=paused)


def test_a_healthy_run_reports_nothing():
    health = Health()
    assert health.update(status(), now=0.0) is None
    assert health.update(status(), now=60.0) is None


# -- the camera ------------------------------------------------------------


def test_a_dead_camera_is_reported_once_it_has_lasted():
    health = Health(no_frames_after=3.0)

    assert health.update(status(fps=0.0), now=0.0) is None  # not yet
    assert health.update(status(fps=0.0), now=2.9) is None
    trouble = health.update(status(fps=0.0), now=3.0)

    assert trouble is not None
    assert trouble.reason == "camera"
    assert "plugged in" in trouble.detail


def test_a_brief_stall_is_not_reported_at_all():
    # A USB hub stalls for a moment when something else is plugged into it.
    # That is not worth a red icon.
    health = Health(no_frames_after=3.0)

    health.update(status(fps=0.0), now=0.0)
    health.update(status(fps=0.0), now=1.5)
    assert health.update(status(fps=30.0), now=2.0) is None
    # And the clock restarts rather than resuming where it left off.
    health.update(status(fps=0.0), now=2.1)
    assert health.update(status(fps=0.0), now=4.5) is None


def test_recovery_clears_the_report_immediately():
    # Slow to complain, quick to forgive: the moment frames return, the user
    # can see that it is working, and a stale warning contradicts them.
    health = Health(no_frames_after=1.0)

    health.update(status(fps=0.0), now=0.0)
    assert health.update(status(fps=0.0), now=1.0) is not None
    assert health.update(status(fps=30.0), now=1.1) is None


# -- the marker, which is deliberately not a fault ------------------------


def test_losing_the_marker_is_never_reported():
    """The change that came out of real use, 2026-08-18.

    John leaves his desk to eat and comes back to a tracker that picks up where
    it left off - which is what the SmartNav does, and what AccessCam already
    did. A red icon through every lunch would have been the clearest possible
    example of an indicator that teaches you to ignore it.
    """
    health = Health()

    for moment in (0.0, 10.0, 60.0, 3600.0):
        assert health.update(status(tracking=False), now=moment) is None


# -- the hotkey ------------------------------------------------------------


def test_an_unregisterable_hotkey_is_reported_and_stays_reported():
    # It will not start working later in the session, and it means the cursor
    # cannot be parked - the one control that has to work.
    health = Health()
    health.note_hotkey_failure("F9 could not be registered.")

    trouble = health.update(status(), now=0.0)

    assert trouble is not None
    assert trouble.reason == "hotkey"
    assert health.update(status(), now=500.0) is not None


def test_a_dead_camera_outranks_a_missing_hotkey():
    # Ordered by how completely each one stops AccessCam working, because only
    # one of them fits in a tooltip.
    health = Health(no_frames_after=0.0)
    health.note_hotkey_failure("F9 could not be registered.")

    assert health.update(status(fps=0.0), now=0.0).reason == "camera"


@pytest.mark.parametrize("reason", ["camera", "hotkey"])
def test_every_report_says_what_to_do_about_it(reason):
    # A tooltip that says "error" is only marginally better than a blank icon.
    health = Health(no_frames_after=0.0)
    if reason == "hotkey":
        health.note_hotkey_failure("F9 could not be registered.")

    trouble = health.update(status(fps=0.0 if reason == "camera" else 30.0), now=0.0)

    assert trouble.reason == reason
    assert len(trouble.detail) > 30
