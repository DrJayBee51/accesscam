"""Running AccessCam at logon, on Windows.

Not the usual `HKCU\\...\\Run` key. AccessCam wants to be elevated - UIPI stops a
normal-privilege process delivering input to a higher-privilege window, so
on-screen keyboards silently stop responding to hover - and a Run entry cannot
elevate. A scheduled task registered with highest privileges can, which is why
RUNNING.md has always documented `schtasks` rather than a registry edit.

The catch is that *creating* such a task itself needs administrator rights. So
this reports honestly rather than failing quietly: callers are expected to tell
the user to relaunch elevated rather than leaving them wondering why a checkbox
did not stick.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TASK_NAME = "AccessCam"

# schtasks writes its complaints to stdout, and a console window would flash up
# on every call without this.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass(frozen=True)
class Outcome:
    """What happened, and something worth showing a person if it did not work."""

    ok: bool
    message: str = ""


def supported() -> bool:
    return sys.platform == "win32"


def executable() -> str:
    """The command the task should run.

    `sys.executable` is the launcher when installed as a console script, so this
    prefers that and falls back to running the module through the interpreter.
    """
    exe = Path(sys.executable)
    if exe.stem.lower() in {"python", "pythonw"}:
        return f'"{exe}" -m accesscam --ui'
    return f'"{exe}" --ui'


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
        check=False,
    )


def is_enabled() -> bool:
    """Whether the logon task exists. False on anything but Windows."""
    if not supported():
        return False
    return _run(["schtasks", "/query", "/tn", TASK_NAME]).returncode == 0


def enable() -> Outcome:
    """Register the logon task, running with highest privileges."""
    if not supported():
        return Outcome(False, "Starting at logon is only wired up for Windows so far.")

    result = _run(
        [
            "schtasks",
            "/create",
            "/tn",
            TASK_NAME,
            "/tr",
            executable(),
            "/sc",
            "onlogon",
            "/rl",
            "highest",
            "/f",
        ]
    )
    if result.returncode == 0:
        return Outcome(True)

    detail = (result.stderr or result.stdout).strip().splitlines()
    return Outcome(
        False,
        "Could not create the logon task. It runs with highest privileges, so "
        "creating it needs administrator rights — relaunch AccessCam as "
        "administrator and try again." + (f"\n\n{detail[-1]}" if detail else ""),
    )


def disable() -> Outcome:
    if not supported():
        return Outcome(True)

    result = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
    if result.returncode == 0 or not is_enabled():
        return Outcome(True)

    detail = (result.stderr or result.stdout).strip().splitlines()
    return Outcome(
        False,
        "Could not remove the logon task. Removing it needs the same "
        "administrator rights that creating it did." + (f"\n\n{detail[-1]}" if detail else ""),
    )
