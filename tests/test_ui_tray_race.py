"""Starting before the shell does.

The logon task fires the moment the desktop appears - one second after the
logon notification on the machine this was found on - and Explorer has not yet
created the notification area. Asking once whether there is a tray meant there
was no tray icon for the rest of the session, on a launch nobody is watching.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from accesscam.ui import main_window

pytestmark = pytest.mark.usefixtures("qt_app")


class Shell:
    """A notification area that appears after a given number of questions."""

    def __init__(self, ready_after: int) -> None:
        self.ready_after = ready_after
        self.asked = 0

    def available(self) -> bool:
        self.asked += 1
        return self.asked > self.ready_after


@pytest.fixture
def shell_absent(monkeypatch):
    """Withhold the tray, and count how often it is asked for."""
    # A second between attempts is right against a real shell and far too slow
    # against a fake one.
    monkeypatch.setattr(main_window, "_TRAY_RETRY_INTERVAL", 0.02)

    def install(ready_after: int) -> Shell:
        shell = Shell(ready_after)
        monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(shell.available))
        return shell

    return install


def install(window, wait=5.0):
    """Run the real installer against a window with a stubbed-out app."""

    class FakeApp:
        def __init__(self) -> None:
            self.quit_on_last_window_closed = True

        def setQuitOnLastWindowClosed(self, value) -> None:  # noqa: N802 - Qt's naming
            self.quit_on_last_window_closed = value

        def quit(self) -> None:
            pass

    app = FakeApp()
    main_window._install_tray(app, window, window.engine, window.config, None, wait=wait)
    return app


def test_the_tray_is_taken_immediately_when_the_shell_is_up(window, shell_absent):
    shell_absent(ready_after=0)

    app = install(window)

    assert window.tray is not None
    assert window.hides_to_tray
    # Nothing may quit the process just because the window was closed now that
    # there is somewhere for it to hide.
    assert not app.quit_on_last_window_closed


def test_it_keeps_asking_until_the_shell_arrives(window, qt_app, shell_absent):
    shell = shell_absent(ready_after=2)

    install(window)
    assert window.tray is None  # not there yet, and not given up on

    _run_retries(qt_app, until=lambda: window.tray is not None)

    assert window.tray is not None
    assert shell.asked > 1
    assert window.hides_to_tray


def test_a_tray_that_never_arrives_leaves_a_window_to_use(window, qt_app, shell_absent):
    # The one outcome that must not happen is a running process with neither a
    # tray icon nor a window: nothing to reach, and no way to quit it.
    shell_absent(ready_after=10_000)
    window.hide()

    install(window, wait=0.0)
    _run_retries(qt_app, until=lambda: window.isVisible())

    assert window.tray is None
    assert window.isVisible()


def _run_retries(qt_app, until, limit=200) -> None:
    """Pump the event loop until the retry timer has had its way."""
    import time

    deadline = time.monotonic() + 5.0
    for _ in range(limit):
        qt_app.processEvents()
        if until() or time.monotonic() > deadline:
            return
        time.sleep(main_window._TRAY_RETRY_INTERVAL / 2)
