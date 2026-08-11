"""Windows cursor backend built on SendInput.

Absolute positioning is used rather than relative deltas. `MOUSEEVENTF_MOVE`
without `MOUSEEVENTF_ABSOLUTE` is reshaped by the pointer-speed slider and by
Enhanced Pointer Precision, so the gains configured in this application would
be silently multiplied by whatever the user's mouse settings happen to be, and
would behave differently on another machine. Absolute motion bypasses both.

`SetCursorPos` would be simpler still, but it does not generate a real input
event, so applications reading raw input or DirectInput never see the movement.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from accesscam.mouse.base import ScreenBounds, to_absolute

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, which is defined as (HANDLE)-4.
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

# ULONG_PTR is pointer-sized and absent from ctypes.wintypes.
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class MONITORINFO(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    )


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class INPUT(ctypes.Structure):
    # The real INPUT union also covers KEYBDINPUT and HARDWAREINPUT, but
    # MOUSEINPUT is the largest of the three, so a mouse-only union still
    # yields the size SendInput expects in cbSize.
    class _Union(ctypes.Union):
        _fields_ = (("mi", MOUSEINPUT),)

    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _Union))


def is_elevated() -> bool:
    """Whether this process is running with administrator rights.

    It matters for more than convenience. UIPI stops a medium-integrity
    process delivering input to a higher-integrity one: the cursor still moves,
    because the cursor is global, but the target window never receives the
    mouse messages. Anything that reacts to hovering - an on-screen keyboard
    highlighting the key under the pointer, a UAC prompt, an application
    running as administrator - simply does not respond.
    """
    try:
        return bool(ctypes.WinDLL("shell32", use_last_error=True).IsUserAnAdmin())
    except OSError:  # pragma: no cover - shell32 is always present in practice
        return False


def enable_dpi_awareness() -> bool:
    """Opt into per-monitor DPI awareness. Must run before any metrics call.

    Without this Windows hands a scaled, virtualised coordinate space to the
    process: on a 3840x2160 display at 150% the desktop reports as 2560x1440,
    and the error differs per monitor when their scaling differs, so the cursor
    lands somewhere other than intended. Returns whether the request was
    granted - it fails harmlessly if awareness was already set for the process.
    """
    try:
        return bool(user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2))
    except AttributeError:  # pragma: no cover - pre-1703 Windows
        return bool(user32.SetProcessDPIAware())


class WindowsMouse:
    """Drives the Windows cursor through SendInput."""

    def __init__(self, dpi_aware: bool = True) -> None:
        if dpi_aware:
            enable_dpi_awareness()

    def bounds(self) -> ScreenBounds:
        return ScreenBounds(
            left=user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            top=user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            width=user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            height=user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )

    def monitors(self) -> list[ScreenBounds]:
        """Every display's rectangle, which is not the same as their bounding box.

        The controller needs these to avoid walking the cursor into a region
        that belongs to no screen - see CursorController._constrain.
        """
        found: list[ScreenBounds] = []

        def collect(handle, _hdc, _rect, _param) -> int:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                area = info.rcMonitor
                found.append(
                    ScreenBounds(
                        left=area.left,
                        top=area.top,
                        width=area.right - area.left,
                        height=area.bottom - area.top,
                    )
                )
            return True

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(collect), 0)
        return found

    def position(self) -> tuple[int, int]:
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
        return (point.x, point.y)

    def move_to(self, x: int, y: int) -> None:
        nx, ny = to_absolute(x, y, self.bounds())
        event = INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(
                dx=nx,
                dy=ny,
                mouseData=0,
                dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            ),
        )
        sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if sent != 1:
            # The usual cause is UIPI: a normal-integrity process cannot inject
            # input while an elevated window holds the foreground.
            raise OSError(ctypes.get_last_error(), "SendInput was blocked")
