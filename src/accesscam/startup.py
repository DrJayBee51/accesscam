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
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from accesscam.log import log

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


# The logon trigger fires the moment the desktop is up, which beats a USB
# camera's enumeration. Opening it then fails, and AccessCam exited - so the
# tray icon never appeared, on a camera that was working fine by the time
# anyone looked. Waiting a minute costs nothing at logon and covers a slow hub.
CAMERA_WAIT_SECONDS = 60

# How long a relaunched copy waits for the camera. It only has to outlast the
# copy that is quitting to make room for it, which takes about a second.
RELAUNCH_WAIT_SECONDS = 20


def executable() -> str:
    """The command the task should run.

    Prefers `pythonw.exe` over `python.exe` where both exist. `python.exe` is a
    console application, so Windows allocates a console window for it - which
    means a black box appearing behind the settings window at every single
    logon, for a program that has a GUI and never prints anything to it.
    """
    flags = f"--ui --wait-for-camera {CAMERA_WAIT_SECONDS}"
    exe = Path(sys.executable)
    if exe.stem.lower() not in {"python", "pythonw"}:
        return f'"{exe}" {flags}'

    windowed = exe.with_name("pythonw.exe")
    interpreter = windowed if windowed.exists() else exe
    return f'"{interpreter}" -m accesscam {flags}'


def registered_command() -> str | None:
    """What the existing task actually runs, or None if there is no task.

    Worth checking rather than assuming: a task registered by an older version
    keeps whatever command it was created with, and `is_enabled` alone would
    report everything fine while the wrong thing ran at logon.
    """
    if not supported():
        return None

    result = _run(["schtasks", "/query", "/tn", TASK_NAME, "/xml"])
    if result.returncode != 0:
        return None

    command = _between(result.stdout, "<Command>", "</Command>")
    arguments = _between(result.stdout, "<Arguments>", "</Arguments>")
    if command is None:
        return None
    return f"{command} {arguments}".strip() if arguments else command


def _between(text: str, opening: str, closing: str) -> str | None:
    start = text.find(opening)
    if start < 0:
        return None
    end = text.find(closing, start)
    if end < 0:
        return None
    return text[start + len(opening) : end].strip()


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
        check=False,
    )


@dataclass(frozen=True)
class State:
    """Everything worth knowing about the logon task, from one query.

    Grouped rather than exposed as three functions because each of those would
    spawn its own `schtasks`, and asking Windows the same question three times
    every time a window opens is both slow and able to disagree with itself.
    """

    supported: bool
    enabled: bool
    stale: bool


def state() -> State:
    if not supported():
        return State(supported=False, enabled=False, stale=False)

    command = registered_command()
    if command is None:
        return State(supported=True, enabled=False, stale=False)
    return State(supported=True, enabled=True, stale=command != executable())


def is_enabled() -> bool:
    """Whether the logon task exists. False on anything but Windows."""
    return state().enabled


def is_stale() -> bool:
    """Whether a registered task runs something other than what we register now."""
    return state().stale


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


def _current_invocation() -> tuple[str, str]:
    """The executable and arguments that would start this program again.

    Mirrors how it is actually running rather than how the logon task starts
    it: a relaunch should carry the flags the user is already using.
    """
    import subprocess as _sp

    exe = Path(sys.executable)
    arguments = sys.argv[1:]

    # A camera cannot be opened twice, and the copy being replaced is still
    # holding it for the moment it takes this one to quit. argparse takes the
    # last occurrence, so appending overrides whatever was there.
    arguments = [*arguments, "--wait-for-camera", str(RELAUNCH_WAIT_SECONDS)]

    if exe.stem.lower() not in {"python", "pythonw"}:
        return str(exe), _sp.list2cmdline(arguments)

    windowed = exe.with_name("pythonw.exe")
    interpreter = windowed if windowed.exists() else exe
    return str(interpreter), _sp.list2cmdline(["-m", "accesscam", *arguments])


def relaunch_elevated() -> Outcome:
    """Start an elevated copy of AccessCam. The caller is expected to quit.

    Prefers the scheduled task. Task Scheduler runs it at highest privileges
    and asks nobody, whereas every other route to administrator raises a UAC
    prompt on the secure desktop - which a head-tracked cursor cannot reach,
    because this process is not elevated at that moment by definition. For the
    person this application exists for, an unanswerable prompt is worse than no
    offer at all, so the prompting route is the fallback rather than the plan.
    """
    if not supported():
        return Outcome(False, "Relaunching elevated is only wired up for Windows so far.")

    if is_enabled():
        result = _run(["schtasks", "/run", "/tn", TASK_NAME])
        if result.returncode == 0:
            return Outcome(True)

    import ctypes

    exe, arguments = _current_invocation()
    # ShellExecuteW returns a value above 32 on success. It is the documented
    # way to ask for elevation; CreateProcess cannot raise a UAC prompt.
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, arguments, None, 1)
    if code > 32:
        return Outcome(True)
    if code == 1223:  # ERROR_CANCELLED - the user said no to UAC
        return Outcome(
            False,
            "The elevation prompt was declined, so AccessCam is still running "
            "without administrator rights.",
        )
    return Outcome(
        False,
        "Could not start an elevated copy of AccessCam. Registering the logon task from "
        "this tab makes this work without a prompt at all.",
    )


# --- Coming up elevated without anyone being asked --------------------------

# A copy that hands over to an elevated one, only for that copy to come back
# unelevated too, would hand over again - forever, invisibly, at every launch.
# A task can be registered without /rl highest, and policy can decline to
# honour one that has it; neither says so out loud. This marker lets the copy
# that is about to hand over see that the last attempt did not take.
HANDOFF_COOLDOWN_SECONDS = 90


def _already_privileged() -> bool:
    """Whether this copy can already reach a higher-integrity window.

    Elevation is one way; UIAccess is the other, and the better one - it is
    what the SmartNav uses and needs no administrator rights at all. Either
    means there is nothing to hand over for. Imported here rather than at
    module scope so that the rest of this module, and its tests, stay usable
    off Windows.
    """
    from accesscam.mouse.windows import has_uiaccess, is_elevated

    return is_elevated() or has_uiaccess()


def _handoff_marker() -> Path:
    from accesscam.config import config_dir

    return config_dir() / "elevating"


def _handed_over_recently() -> bool:
    try:
        age = time.time() - _handoff_marker().stat().st_mtime
    except OSError:
        return False
    return 0 <= age < HANDOFF_COOLDOWN_SECONDS


def _record_handover() -> None:
    marker = _handoff_marker()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError as exc:
        # Not fatal: the marker only guards against a loop that needs a broken
        # task to happen at all. Losing it must not stop AccessCam starting.
        log.warning("could not record the handover attempt: %s", exc)


def carries_settings(argv: Sequence[str]) -> bool:
    """Whether this launch asked for something the startup task would not do.

    The task runs one fixed command line, so anything typed on this one is
    lost in the handover. A plain launch has nothing to lose - the shortcut,
    the pinned icon, the double-clicked exe, which is the case all of this
    exists for. A launch carrying `--device 2` or `--headless` is someone
    being specific, and quietly starting a copy without those flags would be a
    worse failure than staying unelevated and saying so in the banner.
    """
    skip_value = False
    for item in argv:
        if skip_value:
            skip_value = False
            continue
        if item == "--wait-for-camera":
            # The task waits for the camera itself, and for longer.
            skip_value = True
            continue
        if item == "--ui" or item.startswith("--wait-for-camera="):
            continue
        return True
    return False


def take_over_elevated(argv: Sequence[str] | None = None) -> bool:
    """Start an elevated copy, and report whether this one should now quit.

    AccessCam is worth very little unelevated - UIPI drops its input on the
    floor for on-screen keyboards and for anything else running as
    administrator - and where the task exists, an elevated copy costs a
    `schtasks /run` and asks nobody. So an unelevated launch is treated as a
    mistake to correct rather than a state to report, whichever shortcut,
    pinned icon or terminal it came from.

    Deliberately never falls back to a UAC prompt, unlike `relaunch_elevated`:
    this runs at every launch without being asked for, and a prompt nobody
    invited is both a surprise and, for someone driving the pointer with their
    head, unanswerable.
    """
    if not supported() or _already_privileged():
        return False

    argv = sys.argv[1:] if argv is None else argv
    if carries_settings(argv):
        log.info("started with %s - staying unelevated rather than dropping them", " ".join(argv))
        return False

    status = state()
    if not status.enabled:
        # Nothing to hand over to. The window's banner says so and offers to
        # register the task, which is the one step that does need a prompt.
        return False
    if status.stale:
        # The task runs some other copy - an old checkout, a previous install.
        # Starting that instead of this one would be a baffling way to launch
        # the wrong AccessCam, so say so and stay put.
        log.warning("the logon task runs %s - not handing over to it", registered_command())
        return False
    if _handed_over_recently():
        log.warning(
            "handed over less than %ds ago and this copy is still not elevated - "
            "carrying on unelevated rather than looping",
            HANDOFF_COOLDOWN_SECONDS,
        )
        return False

    _record_handover()
    result = _run(["schtasks", "/run", "/tn", TASK_NAME])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        log.warning(
            "the logon task would not start: %s", detail[-1] if detail else "no detail given"
        )
        return False

    log.info("started an elevated copy through the logon task - quitting to make room")
    return True
