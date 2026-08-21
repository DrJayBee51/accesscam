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


def test_choosing_a_camera_swaps_it(window, monkeypatch, fake_camera):
    replacement = fake_camera()
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


def test_the_engine_refuses_a_camera_swap_while_running(window, fake_camera):
    window.engine.start()
    try:
        with pytest.raises(RuntimeError):
            window.engine.use_camera(fake_camera())
    finally:
        window.engine.stop()


def test_swapping_clears_the_stale_marker_position(window, fake_camera):
    # The previous position describes a frame that no longer exists; carried
    # over it would deliver one enormous displacement on the first frame.
    window.engine.step(fake_camera().read())
    assert window.engine.status().position is not None

    window.engine.use_camera(fake_camera())

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


# -- handing a camera back the way it was found ---------------------------


def test_switching_away_restores_the_old_camera_to_auto_exposure(window, monkeypatch, fake_camera):
    """The bug this guards, found 2026-08-20 on a real LifeCam.

    AccessCam forces manual exposure, the *driver* stores it, and it outlives
    the process - so a camera merely tried and abandoned stays black in every
    other application, with nothing connecting that to an accessibility tool
    installed hours earlier. The camera actually in use keeps manual exposure;
    the one being dropped must not.
    """
    abandoned = window.engine.camera
    monkeypatch.setattr(window, "_open_camera", lambda device: fake_camera())

    window.camera_choice.addItem("Camera 3", 3)
    window.camera_choice.setCurrentIndex(window.camera_choice.findData(3))
    window._on_camera_chosen(window.camera_choice.currentIndex())

    assert abandoned.closed_with_restore is True


def test_the_camera_being_kept_is_not_reset(window, monkeypatch, fake_camera):
    # Restoring auto-exposure on the camera AccessCam is about to track with
    # would undo the very setting that makes marker tracking work.
    replacement = fake_camera()
    monkeypatch.setattr(window, "_open_camera", lambda device: replacement)

    window.camera_choice.addItem("Camera 3", 3)
    window.camera_choice.setCurrentIndex(window.camera_choice.findData(3))
    window._on_camera_chosen(window.camera_choice.currentIndex())

    assert window.engine.camera is replacement
    assert replacement.closed_with_restore is None  # never closed at all


# -- the pause hotkey ------------------------------------------------------


class _Binding:
    """Stands in for the live registration, refusing keys on demand."""

    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.label = "f9"
        self.bound: list[str] = []

    def bind(self, spec):
        from accesscam.hotkeys.binding import BindResult

        if spec in self.refuse:
            return BindResult(False, f"{spec.upper()} is held by another program.")
        self.label = spec
        self.bound.append(spec)
        return BindResult(True)


def test_the_hotkey_list_offers_only_function_keys(window):
    keys = [window.hotkey_choice.itemData(i) for i in range(window.hotkey_choice.count())]

    assert keys[0] == "f1"
    assert "f9" in keys
    # F13-F24 are worth offering precisely because nothing else claims them.
    assert "f24" in keys
    assert all(k.startswith("f") and k[1:].isdigit() for k in keys)


def test_it_opens_on_the_configured_key(window):
    assert window.hotkey_choice.currentData() == window.config.hotkey


def test_choosing_a_key_rebinds_and_records_it(window):
    window.hotkey = _Binding()

    window.hotkey_choice.setCurrentIndex(window.hotkey_choice.findData("f8"))
    window._on_hotkey_chosen(window.hotkey_choice.currentIndex())

    assert window.hotkey.bound == ["f8"]
    assert window.config.hotkey == "f8"


def test_a_key_another_program_holds_is_refused_and_the_old_one_kept(window, monkeypatch):
    # The property that matters: a change that cannot take effect must leave a
    # working hotkey behind, not a broken selection.
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    window.config.hotkey = "f9"
    window.hotkey = _Binding(refuse={"f8"})

    window.hotkey_choice.setCurrentIndex(window.hotkey_choice.findData("f8"))
    window._on_hotkey_chosen(window.hotkey_choice.currentIndex())

    assert window.config.hotkey == "f9"
    assert window.hotkey_choice.currentData() == "f9", "the dropdown must not lie"
    assert warned and "F8" in warned[0]


def test_a_hand_written_chord_is_not_silently_replaced(window):
    # A config edited by hand can hold ctrl+alt+p, which is legal and not in
    # the list. Snapping the dropdown to something else would rebind the key
    # the moment the window opened.
    window.config.hotkey = "ctrl+alt+p"
    window._select_hotkey("ctrl+alt+p")
    window._refresh_hotkey_note()

    assert "CTRL+ALT+P" in window.hotkey_note.text()
    assert "config file" in window.hotkey_note.text()
