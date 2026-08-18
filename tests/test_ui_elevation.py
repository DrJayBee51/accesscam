"""The standing warning that AccessCam has no administrator rights.

Worth a window banner rather than a dialog because of how the failure presents:
the cursor moves, so nothing looks broken, and every hover-driven window
silently ignores the pointer. A dialog is dismissed in the first minute and the
symptom is met an hour later with no way to connect the two.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from accesscam import startup
from accesscam.ui import main_window as main_window_module

pytestmark = pytest.mark.usefixtures("qt_app")


def test_the_banner_shows_when_not_elevated(window):
    # The conftest fixture pins elevation off, which is the case worth having
    # on by default: it is the taller layout and the one users hit.
    assert window.elevation_banner.isVisible()


def test_the_banner_is_absent_when_elevated(qt_app, monkeypatch, window):
    monkeypatch.setattr(main_window_module, "_is_elevated", lambda: True)
    elevated = main_window_module.MainWindow(window.engine, window.config)
    try:
        assert not elevated.elevation_banner.isVisible()
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
