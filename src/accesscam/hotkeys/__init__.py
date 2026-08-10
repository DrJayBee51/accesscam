"""Global pause/resume hotkey.

`windows` is imported lazily so the package can be imported on Linux, where
the tests run in CI.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from accesscam.hotkeys.base import Hotkey, PauseController, parse_hotkey

# A bare F9, chosen for reachability rather than convention. The fallback input
# when the cursor is unusable is a mouth-operated QuadStick with F9 already
# mapped to an easy action; a modifier combination would not be reachable from
# it, which would make the pause control useless exactly when it is needed
# most. The cost is that nothing else on the system sees F9 while AccessCam is
# running.
DEFAULT_HOTKEY = "f9"

__all__ = [
    "DEFAULT_HOTKEY",
    "Hotkey",
    "PauseController",
    "create_listener",
    "parse_hotkey",
]


def create_listener(hotkey: Hotkey, on_trigger: Callable[[], None]):
    """Return the hotkey listener for this platform."""
    if sys.platform == "win32":
        from accesscam.hotkeys.windows import WindowsHotkeyListener

        return WindowsHotkeyListener(hotkey, on_trigger)
    raise NotImplementedError(
        f"No hotkey listener for {sys.platform!r} yet. Linux is M6, macOS is M7."
    )
