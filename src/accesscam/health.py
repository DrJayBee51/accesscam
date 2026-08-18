"""Is AccessCam actually working right now, and if not, why.

Separate from the engine because it is a judgement rather than a measurement.
The engine reports what happened - frames, marker found or not - and this
decides when a run of those readings has become something worth putting in
front of a person.

The bar is high, and it moved higher once. Losing the marker is *normal* - not
only glancing at the keyboard, but leaving the desk for a meal and coming back
to a tracker that picks up where it left off, which is what the SmartNav does
and what AccessCam already did. Reporting that as a fault would have painted
the tray red through every lunch. It is no longer reported at all; the window
says whether the marker is currently visible, for anyone who is actually asking.

What is left is hysteresis on the conditions that *are* faults. Each has to
persist before it is shown and clears the moment it stops - slow to complain,
quick to forgive - because an indicator that cries wolf gets ignored on the one
occasion it is right.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# The camera has stopped delivering. Unplugged, driver fallen over, or taken by
# another application. Three seconds is long enough to outlast the stall a USB
# hub produces when something else is plugged into it.
NO_FRAMES_AFTER = 3.0
NO_FRAMES_BELOW_FPS = 5.0


@dataclass(frozen=True)
class Trouble:
    """Something a person would want to know about, and what to tell them."""

    reason: str
    detail: str


class Health:
    """Watches a stream of engine statuses and reports sustained problems."""

    def __init__(self, no_frames_after: float = NO_FRAMES_AFTER) -> None:
        self._no_frames_after = no_frames_after
        self._starved_since: float | None = None
        # Set once at startup and never cleared: a hotkey that would not
        # register will not start working later in the session, and it means
        # the cursor cannot be parked, which is the one control that matters.
        self.hotkey_problem: str | None = None

    def note_hotkey_failure(self, detail: str) -> None:
        self.hotkey_problem = detail

    def update(self, status, now: float | None = None) -> Trouble | None:
        """Judge the current status. None means nothing worth reporting."""
        now = time.monotonic() if now is None else now

        starved = status.fps < NO_FRAMES_BELOW_FPS
        self._starved_since = self._track(starved, self._starved_since, now)

        # Ordered by how completely each one stops AccessCam working, since
        # only one of them fits on an icon. A dead camera makes the other moot.
        if self._held(self._starved_since, now, self._no_frames_after):
            return Trouble(
                "camera",
                "No frames from the camera. Check that it is still plugged in "
                "and that nothing else has taken it.",
            )
        if self.hotkey_problem is not None:
            return Trouble(
                "hotkey",
                f"The pause hotkey is not available, so the cursor cannot be "
                f"parked from the keyboard. {self.hotkey_problem}",
            )
        return None

    @staticmethod
    def _track(active: bool, since: float | None, now: float) -> float | None:
        """Start the clock on a condition, or clear it the moment it goes away."""
        if not active:
            return None
        return now if since is None else since

    @staticmethod
    def _held(since: float | None, now: float, threshold: float) -> bool:
        return since is not None and now - since >= threshold
