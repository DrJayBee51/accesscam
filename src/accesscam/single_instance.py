"""One AccessCam at a time, and a way for the second to fetch the first.

A camera cannot be opened twice. Without this, launching a second copy - by
double-clicking the shortcut again, or by starting one by hand when the logon
task already did - produces a copy that waits out `--wait-for-camera` and then
reports the camera as unavailable, which reads as a hardware fault. Under the
logon task, with `pythonw` and no console, it produced nothing at all.

Exiting quietly would fix the misleading error and leave a worse problem: the
user asked for AccessCam, and nothing happened. So the second copy hands the
foreground to the first before it goes. Clicking a shortcut twice means "show
me AccessCam", not "run two of them".

Scoped to the login session (`Local\\`) rather than the machine. Two people on
one computer through fast user switching each get their own instance, each with
their own camera - and an elevated copy and a normal one in the *same* session
still collide, which is the case that matters.
"""

from __future__ import annotations

import sys

MUTEX_NAME = r"Local\AccessCam.SingleInstance"
REVEAL_MESSAGE_NAME = "AccessCam.Reveal"

_ERROR_ALREADY_EXISTS = 183
_HWND_BROADCAST = 0xFFFF
_MSGFLT_ALLOW = 1


class Claim:
    """Ownership of the single-instance mutex, held for the process lifetime.

    Kept as an object rather than a bare handle so that letting it fall out of
    scope releases the claim: a leaked handle would keep a *dead* AccessCam
    looking alive to the next launch.
    """

    def __init__(self, handle: int | None) -> None:
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        import ctypes

        ctypes.windll.kernel32.CloseHandle(self._handle)
        self._handle = None

    def __enter__(self) -> Claim:
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def claim(name: str = MUTEX_NAME) -> Claim | None:
    """Take the single-instance claim, or None if another copy holds it.

    Always succeeds off Windows: the ports have no camera backend yet, and
    inventing a lock file for a platform that cannot run the program would be
    guessing at a problem nobody has met.

    `name` exists so the tests can take a claim of their own. Left at the
    default they would contend with a *running* AccessCam and pass or fail
    according to whether the developer happened to have it open.
    """
    if sys.platform != "win32":
        return Claim(None)

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Never refuse to start because the guard itself failed. A missing
        # guard costs a confusing second instance; a refusal costs the pointer.
        return Claim(None)

    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None

    return Claim(handle)


def reveal_message() -> int:
    """The broadcast message id, identical in every AccessCam process."""
    if sys.platform != "win32":
        return 0

    import ctypes

    return ctypes.windll.user32.RegisterWindowMessageW(REVEAL_MESSAGE_NAME)


def reveal_running_instance() -> None:
    """Ask the copy that is already running to show itself."""
    if sys.platform != "win32":
        return

    import ctypes

    ctypes.windll.user32.PostMessageW(_HWND_BROADCAST, reveal_message(), 0, 0)


def accept_reveal_from_lesser_processes(window_id: int) -> None:
    """Let an unelevated copy's broadcast reach this elevated window.

    UIPI drops messages sent from a lower integrity level to a higher one, and
    the running copy is normally the elevated one - started by the logon task -
    while the second copy is someone double-clicking a shortcut. Without this
    the broadcast is discarded in exactly the arrangement it exists for.
    """
    if sys.platform != "win32":
        return

    import ctypes

    # Present since Windows 7; absent only on versions this cannot run on.
    changer = getattr(ctypes.windll.user32, "ChangeWindowMessageFilterEx", None)
    if changer is not None:
        changer(window_id, reveal_message(), _MSGFLT_ALLOW, None)
