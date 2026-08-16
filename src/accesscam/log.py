"""A record of what happened, because at logon there is nobody watching.

Started from the Task Scheduler under `pythonw` there is no console attached:
`sys.stdout` and `sys.stderr` are None, every `print` in this program goes
nowhere, and an unhandled exception is swallowed whole. What is left is a
process that exits 1 - and 1 is also the exit code for a missing camera, an
unregisterable hotkey and every other failure, so `LastTaskResult` distinguishes
nothing. Two reboots were spent on that.

This module gives the silent case somewhere to speak. It writes beside the
config file, so anyone who can find their settings can find the log, and it is
installed as the first thing `main` does so that a failure during startup - the
window that never opens, the tray icon that never appears - lands in it too.

Nothing here may ever be fatal. Failing to keep a diary is not a reason to stop
being a mouse.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOGGER_NAME = "accesscam"

# Three files of a quarter megabyte: enough to hold weeks of starts and stops,
# small enough to read through or paste into a bug report.
_MAX_BYTES = 256 * 1024
_BACKUPS = 2

_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

log = logging.getLogger(LOGGER_NAME)


def log_path() -> Path:
    """Where the log lives: next to config.json.

    `config_dir` is imported here rather than at module scope because
    `accesscam.config` pulls in most of the package for its defaults, and this
    module is imported by some of those very modules.
    """
    from accesscam.config import config_dir

    return config_dir() / "accesscam.log"


def start_logging(level: int = logging.INFO) -> Path | None:
    """Open the log file and route crashes into it.

    Returns the path being written to, or None if it could not be opened. A
    caller should carry on either way.
    """
    log.setLevel(level)
    # The root logger's default handler writes to stderr, which under pythonw
    # is None - and a logging call that raises would be a spectacular way for a
    # diagnostic to break the thing it was added to diagnose.
    log.propagate = False

    _install_excepthooks()

    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        return None

    handler.setFormatter(logging.Formatter(_FORMAT, _TIME_FORMAT))
    for existing in list(log.handlers):
        log.removeHandler(existing)
        existing.close()
    log.addHandler(handler)
    return path


def _install_excepthooks() -> None:
    """Make an unhandled exception say so before the process disappears."""

    def handle(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("unhandled exception - exiting", exc_info=(exc_type, exc, tb))

    sys.excepthook = handle

    def handle_thread(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread is not None else "unnamed"
        log.critical(
            "unhandled exception in thread %s",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    # The capture thread dying leaves the cursor frozen with the window still
    # up, which looks like a tracking failure rather than a crash.
    threading.excepthook = handle_thread
