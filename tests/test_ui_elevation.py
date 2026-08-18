"""The standing warning that AccessCam has no administrator rights.

Worth a window banner rather than a dialog because of how the failure presents:
the cursor moves, so nothing looks broken, and every hover-driven window
silently ignores the pointer. A dialog is dismissed in the first minute and the
symptom is met an hour later with no way to connect the two.
"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QMessageBox

from accesscam import startup
from accesscam.ui import main_window as main_window_module

pytestmark = pytest.mark.usefixtures("qt_app")

# The two UIAccess tests below reach into accesscam.mouse.windows, which cannot
# even be imported off Windows - ctypes.WinDLL does not exist there. Same guard
# the equivalent tests in test_mouse.py already carry.
windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="UIPI and UIAccess are Windows mechanisms"
)


def test_the_banner_shows_when_not_elevated(window):
    # The conftest fixture pins elevation off, which is the case worth having
    # on by default: it is the taller layout and the one users hit.
    assert window.elevation_banner.isVisible()


def test_the_banner_is_absent_when_elevated(qt_app, monkeypatch, window):
    monkeypatch.setattr(main_window_module, "_can_reach_privileged_windows", lambda: True)
    elevated = main_window_module.MainWindow(window.engine, window.config)
    try:
        assert elevated.elevation_banner.isHidden()
        # And it costs nothing: the window is shorter without the strip.
        assert elevated.height() < window.height()
    finally:
        elevated.close()


def test_restarting_hands_over_and_quits(window, monkeypatch):
    # Quitting is half the job. A camera cannot be opened twice, and the
    # elevated copy is already waiting for this one to let go of it.
    quits = []
    monkeypatch.setattr(startup, "relaunch_elevated", lambda: startup.Outcome(True))
    monkeypatch.setattr(
        main_window_module.QApplication, "quit", staticmethod(lambda: quits.append(True))
    )

    window.elevate_button.click()

    assert window.quit_requested
    assert quits == [True]


def test_a_refused_restart_says_so_and_stays(window, monkeypatch):
    warned = []
    monkeypatch.setattr(
        startup,
        "relaunch_elevated",
        lambda: startup.Outcome(False, "The elevation prompt was declined"),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(
        main_window_module.QApplication,
        "quit",
        staticmethod(lambda: pytest.fail("must not quit when the restart failed")),
    )

    window.elevate_button.click()

    assert not window.quit_requested
    assert warned == ["The elevation prompt was declined"]


# -- UIAccess: the other way to reach a privileged window ------------------


@windows_only
def test_uiaccess_alone_is_enough_to_silence_the_banner(qt_app, monkeypatch, window):
    """A signed, properly installed AccessCam holding UIAccess is *not* running
    as administrator and does not need to be.

    This is how the SmartNav does it - `asInvoker` plus `uiAccess="true"` in its
    manifest - and telling that user to restart as administrator would be
    advice to fix something that is not broken.
    """
    from accesscam.mouse import windows as windows_backend

    monkeypatch.setattr(windows_backend, "is_elevated", lambda: False)
    monkeypatch.setattr(windows_backend, "has_uiaccess", lambda: True)
    monkeypatch.setattr(
        main_window_module,
        "_can_reach_privileged_windows",
        lambda: windows_backend.can_reach_privileged_windows(),
    )

    quiet = main_window_module.MainWindow(window.engine, window.config)
    try:
        # isHidden(), not isVisible(): a child of a window that was never
        # shown reports isVisible() False regardless, which would pass this
        # test for the wrong reason.
        assert quiet.elevation_banner.isHidden()
    finally:
        quiet.close()


@windows_only
def test_neither_route_available_still_warns(qt_app, monkeypatch, window):
    from accesscam.mouse import windows as windows_backend

    monkeypatch.setattr(windows_backend, "is_elevated", lambda: False)
    monkeypatch.setattr(windows_backend, "has_uiaccess", lambda: False)
    monkeypatch.setattr(
        main_window_module,
        "_can_reach_privileged_windows",
        lambda: windows_backend.can_reach_privileged_windows(),
    )

    warned = main_window_module.MainWindow(window.engine, window.config)
    try:
        assert not warned.elevation_banner.isHidden()
    finally:
        warned.close()
