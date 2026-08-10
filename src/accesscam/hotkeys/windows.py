"""Global hotkey via RegisterHotKey.

RegisterHotKey rather than a WH_KEYBOARD_LL hook: the hook would see every
keystroke on the system, which is both more than this needs and an unpleasant
thing to ship in an accessibility tool. RegisterHotKey claims exactly one
combination and is told about nothing else.

Win32 delivers WM_HOTKEY to the thread that registered it, so registration and
the message loop both live on this listener's own thread.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

from accesscam.hotkeys.base import Hotkey

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
_HOTKEY_ID = 1

user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class HotkeyError(RuntimeError):
    """Raised when a hotkey cannot be registered."""


class WindowsHotkeyListener:
    """Calls `on_trigger` whenever the hotkey is pressed, from a background thread.

    The callback runs on the listener thread, not the caller's, so whatever it
    touches must be safe to touch from there. Toggling a flag is fine; anything
    heavier should hand off.
    """

    def __init__(self, hotkey: Hotkey, on_trigger: Callable[[], None]) -> None:
        self.hotkey = hotkey
        self._on_trigger = on_trigger
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 2.0) -> None:
        """Register the hotkey and start pumping messages.

        Blocks until registration has either succeeded or failed, so a clash
        with another application is reported here rather than silently leaving
        the user without a way to stop the cursor.
        """
        if self.running:
            return

        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout):
            raise HotkeyError(f"Timed out registering {self.hotkey.label!r}")
        if self._error is not None:
            raise HotkeyError(self._error)

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        modifiers, key = self.hotkey.registration()

        if not user32.RegisterHotKey(None, _HOTKEY_ID, modifiers, key):
            code = ctypes.get_last_error()
            # 1409 is ERROR_HOTKEY_ALREADY_REGISTERED: another application owns
            # this combination, and Windows will not share it.
            detail = " (already claimed by another application)" if code == 1409 else ""
            self._error = f"Could not register {self.hotkey.label!r}: error {code}{detail}"
            self._ready.set()
            return

        self._ready.set()
        try:
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):  # WM_QUIT, or an error
                    break
                if message.message == WM_HOTKEY:
                    self._on_trigger()
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)
