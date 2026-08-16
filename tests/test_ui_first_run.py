"""The camera picker that a first run lands in.

The case this exists for: `device` is 0 in a fresh config, 0 is the laptop's
built-in webcam, and the IR camera is at 1. Before this, that ended the launch.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QDialog

from accesscam import camera as camera_module
from accesscam.camera import CameraError, DeviceInfo
from accesscam.config import Config
from accesscam.ui import first_run

pytestmark = pytest.mark.usefixtures("qt_app")

WEBCAM = DeviceInfo(index=0, width=640, height=480, codec="YUY2")
ARDUCAM = DeviceInfo(index=1, width=1920, height=1080, codec="MJPG")


@pytest.fixture
def probe(monkeypatch):
    """Control what the camera probe reports."""

    def install(found):
        monkeypatch.setattr(camera_module, "probe_devices", lambda *a, **k: list(found))

    return install


@pytest.fixture
def opens(monkeypatch):
    """Control which device indices will actually open."""

    def install(working):
        import accesscam.app as app_module

        def build(config, wait=0.0):
            if config.device not in working:
                raise CameraError(f"Could not open camera device {config.device}.")
            return f"camera {config.device}"

        monkeypatch.setattr(app_module, "build_camera", build)

    return install


def test_it_lists_what_answered(probe, opens):
    probe([WEBCAM, ARDUCAM])
    opens({1})

    picker = first_run.CameraPicker(Config(device=0))
    picker.scan()

    labels = [picker.devices.item(row).text() for row in range(picker.devices.count())]
    assert len(labels) == 2
    assert "likely the Arducam" in labels[1]
    assert "other webcam" in labels[0]


def test_it_starts_on_the_likely_arducam_not_the_first_row(probe, opens):
    # Preselecting row 0 would put the cursor on the laptop's webcam, which is
    # the exact wrong answer this dialog exists to correct.
    probe([WEBCAM, ARDUCAM])
    opens({1})

    picker = first_run.CameraPicker(Config(device=0))
    picker.scan()

    assert picker.devices.currentItem().text().startswith("1:")


def test_nothing_connected_says_so_and_offers_another_scan(probe, opens):
    probe([])
    opens(set())

    picker = first_run.CameraPicker(Config(device=0))
    picker.scan()

    assert not picker.use_button.isEnabled()
    assert picker.scan_button.isEnabled()
    assert "USB" in picker.note.text()


def test_a_camera_that_will_not_open_leaves_the_dialog_up(probe, opens):
    # Something else on the machine may hold a camera the probe could open a
    # moment earlier. The answer is to pick another, not to start over.
    probe([WEBCAM, ARDUCAM])
    opens(set())

    picker = first_run.CameraPicker(Config(device=0))
    picker.scan()
    picker._use()

    assert picker.camera is None
    assert picker.result() != QDialog.DialogCode.Accepted
    assert "would not open" in picker.note.text()
    assert picker.use_button.isEnabled()  # still usable for a second try


def test_choosing_opens_it_and_remembers_the_answer(tmp_path, monkeypatch, probe, opens):
    probe([WEBCAM, ARDUCAM])
    opens({1})
    config = Config(device=0)
    config_file = tmp_path / "config.json"

    def choose(self):
        self.scan()
        self._use()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(first_run.CameraPicker, "exec", choose)

    camera = first_run.choose_camera(config, config_file)

    assert camera == "camera 1"
    assert config.device == 1
    # Saved, or the same dialog appears at every launch for the same reason.
    assert json.loads(config_file.read_text(encoding="utf-8"))["device"] == 1


def test_quitting_changes_nothing(tmp_path, monkeypatch, probe, opens):
    probe([WEBCAM, ARDUCAM])
    opens({1})
    config = Config(device=0)
    config_file = tmp_path / "config.json"

    monkeypatch.setattr(first_run.CameraPicker, "exec", lambda self: QDialog.DialogCode.Rejected)

    assert first_run.choose_camera(config, config_file) is None
    assert config.device == 0
    assert not config_file.exists()


def test_an_unsaveable_config_still_starts(tmp_path, monkeypatch, probe, opens):
    # Losing the setting is a smaller problem than refusing to open a camera
    # that is sitting there working.
    probe([ARDUCAM])
    opens({1})
    config = Config(device=0)

    def choose(self):
        self.scan()
        self._use()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(first_run.CameraPicker, "exec", choose)
    monkeypatch.setattr(
        Config, "save", lambda self, path=None: (_ for _ in ()).throw(OSError("read-only"))
    )

    assert first_run.choose_camera(config, tmp_path / "config.json") == "camera 1"
    assert config.device == 1
