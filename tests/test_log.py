"""The log, and the two silent deaths it exists to make audible.

Everything here is about the logon launch, where there is no console: what the
file says is the only evidence there will ever be.
"""

from __future__ import annotations

import logging

import pytest

from accesscam import log as log_module
from accesscam.log import log, start_logging


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Point the log at a temporary directory and hand back its path."""
    path = tmp_path / "accesscam.log"
    monkeypatch.setattr(log_module, "log_path", lambda: path)
    start_logging()
    yield path
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()


def test_it_writes_where_the_config_lives():
    # Somewhere findable by someone who has only ever opened their settings
    # file, since that is who will be asked for it.
    from accesscam.config import config_path

    assert log_module.log_path().parent == config_path().parent


def test_a_message_reaches_the_file(log_file):
    log.info("camera %d opened", 1)
    assert "camera 1 opened" in log_file.read_text(encoding="utf-8")


def test_an_unhandled_exception_lands_in_the_log(log_file):
    # The whole point. Under pythonw this traceback goes nowhere at all, and
    # the process exits 1 with the same code as every other failure.
    import sys

    try:
        raise ValueError("something nobody was watching")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    written = log_file.read_text(encoding="utf-8")
    assert "something nobody was watching" in written
    assert "Traceback" in written


def test_a_thread_dying_lands_in_the_log(log_file):
    import threading

    def explode() -> None:
        raise RuntimeError("the capture thread stopped")

    thread = threading.Thread(target=explode)
    thread.start()
    thread.join()

    assert "the capture thread stopped" in log_file.read_text(encoding="utf-8")


def test_an_unwritable_directory_is_not_fatal(tmp_path, monkeypatch):
    # A profile that cannot be written to must not stop the mouse working.
    # Losing the diary is a smaller problem than refusing to start.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(log_module, "log_path", lambda: blocked / "accesscam.log")

    assert start_logging() is None
    log.info("this simply goes nowhere")


def test_logging_does_not_reach_the_root_handler(log_file):
    # The root logger writes to stderr, which under pythonw is None - so a log
    # call would raise inside the code added to explain a crash.
    assert not log.propagate
    assert log.level == logging.INFO
