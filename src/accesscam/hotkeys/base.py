"""Hotkey parsing and pause state — no OS calls, so this is testable anywhere."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# Win32 modifier bits.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# Without this, holding the combination repeats the trigger many times a
# second, which for a toggle means the pause state flutters.
MOD_NOREPEAT = 0x4000

_MODIFIERS: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

_NAMED_KEYS: dict[str, int] = {
    "space": 0x20,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "pause": 0x13,
    "scrolllock": 0x91,
}


def _is_function_key(name: str) -> bool:
    return name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24


def _key_code(name: str) -> int:
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    if _is_function_key(name):
        return 0x70 + int(name[1:]) - 1
    raise ValueError(f"Unrecognised key {name!r}")


@dataclass(frozen=True)
class Hotkey:
    """A modifier combination plus one key, in Win32 terms."""

    modifiers: int
    key_code: int
    # Kept for error messages and display only. Excluded from equality: two
    # hotkeys that register the same combination are the same hotkey, however
    # the user happened to spell it.
    label: str = field(compare=False)

    def registration(self) -> tuple[int, int]:
        """The (fsModifiers, vk) pair RegisterHotKey wants."""
        return (self.modifiers | MOD_NOREPEAT, self.key_code)


def parse_hotkey(spec: str) -> Hotkey:
    """Parse a combination such as 'f9', 'ctrl+alt+p' or 'shift+f8'.

    A bare **function** key is allowed; a bare letter, digit or named key is
    not. The distinction matters for accessibility rather than tidiness: the
    fallback input for this user is a mouth-operated QuadStick, which has F9
    mapped to a single accessible action and cannot readily produce modifier
    combinations. The pause control has to be reachable from the fallback
    device, or it is not a fallback.

    Bare alphanumerics stay rejected because a global hotkey swallows the key
    from every other application - claiming 'p' would remove it from all
    typing, system-wide.

    Note the same swallowing applies to a bare function key: while the listener
    runs, nothing else on the system receives it.
    """
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError(f"Hotkey {spec!r} is empty")

    *modifier_names, key_name = parts
    modifiers = 0
    for name in modifier_names:
        if name not in _MODIFIERS:
            raise ValueError(f"Unrecognised modifier {name!r} in {spec!r}")
        modifiers |= _MODIFIERS[name]

    if not modifier_names and not _is_function_key(key_name):
        raise ValueError(
            f"Hotkey {spec!r} needs a modifier: only function keys may be used unmodified"
        )

    return Hotkey(modifiers=modifiers, key_code=_key_code(key_name), label=spec)


@dataclass
class PauseController:
    """Whether the tracker is currently allowed to drive the cursor.

    Starts paused. The pipeline takes over the mouse with no window to click
    on, so it should never begin moving the pointer the instant it launches -
    the user opts in once they are ready.
    """

    paused: bool = True
    _listeners: list[Callable[[bool], None]] = field(default_factory=list)

    def on_change(self, callback: Callable[[bool], None]) -> None:
        self._listeners.append(callback)

    def toggle(self) -> bool:
        self._set(not self.paused)
        return self.paused

    def pause(self) -> None:
        self._set(True)

    def resume(self) -> None:
        self._set(False)

    @property
    def active(self) -> bool:
        return not self.paused

    def _set(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        for callback in self._listeners:
            callback(paused)
