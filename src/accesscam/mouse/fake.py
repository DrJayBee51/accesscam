"""An in-memory backend that records moves instead of touching the cursor.

Used by the tests, and useful for tuning the mapper by hand: the pipeline can
be run end to end against this and the resulting cursor path inspected without
the real pointer running away while a bug is being found.
"""

from __future__ import annotations

from accesscam.mouse.base import ScreenBounds

# Deliberately not (0, 0)-anchored. The development machine has monitors above
# and to the left of the primary one, so the origin is negative there and the
# default here mirrors that rather than the easy case.
DEFAULT_BOUNDS = ScreenBounds(left=-2560, top=-2160, width=7680, height=3600)


class RecordingMouse:
    """A MouseBackend that keeps every move it is given."""

    def __init__(
        self,
        bounds: ScreenBounds | None = None,
        start: tuple[int, int] = (0, 0),
    ) -> None:
        self._bounds = bounds if bounds is not None else DEFAULT_BOUNDS
        self._position = start
        self.moves: list[tuple[int, int]] = []

    def bounds(self) -> ScreenBounds:
        return self._bounds

    def position(self) -> tuple[int, int]:
        return self._position

    def move_to(self, x: int, y: int) -> None:
        self._position = (x, y)
        self.moves.append((x, y))
