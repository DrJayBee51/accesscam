"""The Application tab: camera choice, startup options and quitting."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from accesscam import startup
from accesscam.camera import DeviceInfo

pytestmark = pytest.mark.usefixtures("qt_app")


def test_there_are_three_tabs(window):
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert names == ["Camera && Marker", "Cursor Movement", "Application"]


def test_the_window_is_sized_for_every_tab(window):
    # Sizing to the first tab alone would clip whichever of the others needs
    # more room, and the window cannot be resized out of it.
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        page = window.tabs.widget(index)
        assert page.sizeHint().height() <= window.height()


# -- camera ---------------------------------------------------------------


def test_the_camera_box_opens_on_the_configured_device(window):
    assert window.camera_choice.currentData() == window.config.device


def test_scanning_lists_what_was_found(window, monkeypatch):
    found = [
        DeviceInfo(index=0, width=640, height=480, codec="MJPG"),
        DeviceInfo(index=1, width=1920, height=1080, codec="MJPG"),
    ]
    monkeypatch.setattr("accesscam.camera.probe_devices", lambda *a, **k: found)
    monkeypatch.setattr(window, "_open_camera", lambda device: window.engine.camera)

    window._rescan_cameras()

    labels = [window.camera_choice.itemText(i) for i in range(window.camera_choice.count())]
    assert len(labels) == 2
    assert "likely the Arducam" in labels[1]
    assert "other webcam" in labels[0]
    assert "Found 2 cameras" in window.camera_note.text()


def test_scanning_says_so_when_nothing_answers(window, monkeypatch):
    monkeypatch.setattr("accesscam.camera.probe_devices", lambda *a, **k: [])
    monkeypatch.setattr(window, "_open_camera", lambda device: window.engine.camera)

    window._rescan_cameras()

    assert "No cameras answered" in window.camera_note.text()


def test_choosing_a_camera_swaps_it(window, monkeypatch):
    from tests.conftest import FakeCamera

    replacement = FakeCamera()
    monkeypatch.setattr(window, "_open_camera", lambda device: replacement)
    window.camera_choice.addItem("Camera 3", 3)
    window.camera_choice.setCurrentIndex(window.camera_choice.findData(3))

    window._on_camera_chosen(window.camera_choice.currentIndex())

    assert window.config.device == 3
    assert window.engine.camera is replacement


def test_a_camera_that_will_not_open_puts_the_old_one_back(window, monkeypatch):
    # Leaving the user with no tracking *and* a dialog to dismiss using a
    # cursor that has just stopped working is the failure worth avoiding.
    original = window.engine.camera
    before = window.config.device

    def refuse_new(device):
        return None if device == 7 else original

    monkeypatch.setattr(window, "_open_camera", refuse_new)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    window.camera_choice.addItem("Camera 7", 7)
    window.camera_choice.setCurrentIndex(window.camera_choice.findData(7))
    window._on_camera_chosen(window.camera_choice.currentIndex())

    assert window.config.device == before
    assert window.engine.camera is original
    assert window.camera_choice.currentData() == before


def test_the_engine_refuses_a_camera_swap_while_running(window):
    from tests.conftest import FakeCamera

    window.engine.start()
    try:
        with pytest.raises(RuntimeError):
            window.engine.use_camera(FakeCamera())
    finally:
        window.engine.stop()


def test_swapping_clears_the_stale_marker_position(window):
    # The previous position describes a frame that no longer exists; carried
    # over it would deliver one enormous displacement on the first frame.
    from tests.conftest import FakeCamera

    window.engine.step(FakeCamera().read())
    assert window.engine.status().position is not None

    window.engine.use_camera(FakeCamera())

    assert window.engine.status().position is None
    assert window.engine.latest_frame() is None


# -- startup --------------------------------------------------------------


def test_start_minimised_writes_through_to_the_config(window):
    window.start_minimised_box.setChecked(True)
    assert window.config.start_minimized is True

    window.start_minimised_box.setChecked(False)
    assert window.config.start_minimized is False


def test_a_failed_logon_task_puts_the_checkbox_back(window, monkeypatch):
    # The box reports what is registered, not what was wanted - creating the
    # task needs administrator rights and can simply refuse.
    monkeypatch.setattr(
        startup, "enable", lambda: startup.Outcome(False, "needs administrator rights")
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window.run_at_logon_box.setChecked(False)

    window.run_at_logon_box.setChecked(True)

    assert not window.run_at_logon_box.isChecked()


def test_a_successful_logon_task_leaves_the_checkbox_set(window, monkeypatch):
    monkeypatch.setattr(startup, "enable", lambda: startup.Outcome(True))
    window.run_at_logon_box.setChecked(False)

    window.run_at_logon_box.setChecked(True)

    assert window.run_at_logon_box.isChecked()


def test_a_stale_task_is_reported_rather_than_left_looking_fine(window):
    # A task made by an older version keeps its original command, so the box
    # can read "on" while the wrong thing runs at logon.
    window._refresh_logon_note(startup.State(supported=True, enabled=True, stale=True))

    assert "older command" in window.logon_note.text()


def test_a_current_task_says_it_is_elevated(window):
    window._refresh_logon_note(startup.State(supported=True, enabled=True, stale=False))

    assert "elevated" in window.logon_note.text()


def test_an_unsupported_platform_says_so(window):
    window._refresh_logon_note(startup.State(supported=False, enabled=False, stale=False))

    assert "Windows" in window.logon_note.text()


# -- quitting -------------------------------------------------------------


def test_quitting_asks_first(window, monkeypatch):
    asked = {}

    def cancel(*args, **kwargs):
        asked["shown"] = True
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)

    window._confirm_quit()

    assert asked["shown"]
    assert not window.quit_requested


def test_confirming_marks_the_window_as_really_quitting(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.quit", lambda *a: None)

    window._confirm_quit()

    assert window.quit_requested
