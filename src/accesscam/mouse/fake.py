"""An in-memory backend that records moves instead of touching the cursor.

Used by the tests, and useful for tuning the mapper by hand: the pipeline can
be run end to end against this and the resulting cursor path inspected without
the real pointer running away while a bug is being found.
"""

from __future__ import annotations

from accesscam.mouse.base import ScreenBounds

# The development machine's real layout: a 4K display above the primary and two
# more either side. Deliberately not the easy case - the origin is negative, the
# displays are not all the same size, and they do not tile their own bounding
# box, which leaves regions belonging to no screen.
DEFAULT_MONITORS = [
    ScreenBounds(left=0, top=-2160, width=3840, height=2160),  # top, 4K
    ScreenBounds(left=-2560, top=0, width=2560, height=1440),  # left
    ScreenBounds(left=0, top=0, width=2560, height=1440),  # primary
    ScreenBounds(left=2560, top=0, width=2560, height=1440),  # right
]
DEFAULT_BOUNDS = ScreenBounds(left=-2560, top=-2160, width=7680, height=3600)


class RecordingMouse:
    """A MouseBackend that keeps every move it is given."""

    def __init__(
        self,
        bounds: ScreenBounds | None = None,
        start: tuple[int, int] = (0, 0),
        monitors: list[ScreenBounds] | None = None,
    ) -> None:
        self._bounds = bounds if bounds is not None else DEFAULT_BOUNDS
        # A caller that supplies custom bounds but no monitor list almost
        # always means "one screen exactly this size".
        if monitors is not None:
            self._monitors = monitors
        elif bounds is not None:
            self._monitors = [bounds]
        else:
            self._monitors = list(DEFAULT_MONITORS)
        self._position = start
        self.moves: list[tuple[int, int]] = []

    def bounds(self) -> ScreenBounds:
        return self._bounds

    def monitors(self) -> list[ScreenBounds]:
        return self._monitors

    def position(self) -> tuple[int, int]:
        return self._position

    def move_to(self, x: int, y: int) -> None:
        self._position = (x, y)
        self.moves.append((x, y))
