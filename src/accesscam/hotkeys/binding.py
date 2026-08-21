"""A pause hotkey that can be changed while AccessCam is running.

The listener itself is deliberately simple - it registers one combination and
stops. Changing the key therefore means tearing one down and standing another
up, and the interesting part is what happens when the new one will not
register: another application may already hold it, and Windows says so only by
refusing.

Failing back to the previous key matters more here than it looks. The pause
hotkey is the only way to park the cursor from the keyboard, and for someone
whose pointer *is* AccessCam, being left with no working hotkey because a
dropdown was changed is a considerably worse outcome than the change not
taking effect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from accesscam.hotkeys import create_listener, parse_hotkey
from accesscam.log import log


@dataclass(frozen=True)
class BindResult:
    """Whether the key changed, and something worth showing a person if not."""

    ok: bool
    message: str = ""


class HotkeyBinding:
    """Owns the live pause-hotkey listener and swaps it safely."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._listener = None
        self.label: str | None = None

    def bind(self, spec: str) -> BindResult:
        """Register `spec`, keeping the current key if it will not take."""
        try:
            hotkey = parse_hotkey(spec)
        except ValueError as exc:
            return BindResult(False, str(exc))

        previous, previous_label = self._listener, self.label

        # Release the old registration first: rebinding to the same key would
        # otherwise fail against ourselves, and that is the case a user hits by
        # reselecting what is already chosen.
        if previous is not None:
            with _suppressed():
                previous.stop()

        try:
            listener = create_listener(hotkey, self._on_trigger)
            listener.start()
        except Exception as exc:  # noqa: BLE001 - any failure must be recoverable
            log.warning("could not register hotkey %r: %s", spec, exc)
            self._listener = None
            restored = self._restore(previous_label)
            detail = (
                f"{spec.upper()} could not be registered - another program is probably holding it."
            )
            if restored:
                detail += f" {previous_label.upper()} is still in use."
            else:
                detail += " No pause hotkey is registered now, so the cursor cannot be parked "
                detail += "from the keyboard."
            return BindResult(False, detail)

        self._listener = listener
        self.label = spec
        log.info("pause hotkey bound to %r", spec)
        return BindResult(True)

    def stop(self) -> None:
        if self._listener is not None:
            with _suppressed():
                self._listener.stop()
            self._listener = None

    def _restore(self, label: str | None) -> bool:
        """Put the previous key back after a failed change."""
        if label is None:
            return False
        try:
            listener = create_listener(parse_hotkey(label), self._on_trigger)
            listener.start()
        except Exception:  # noqa: BLE001 - nothing left to fall back to
            log.error("could not restore the previous hotkey %r either", label)
            self.label = None
            return False
        self._listener = listener
        self.label = label
        return True


def _suppressed():
    import contextlib

    return contextlib.suppress(Exception)
