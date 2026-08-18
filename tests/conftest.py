"""Shared fixtures, including a real Qt window driven without a display.

The UI tests build an actual `MainWindow` and send it real mouse and key
events. That needs a Qt platform plugin, and CI has no display, so everything
runs on the offscreen platform - which lays out, paints and delivers synthetic
events exactly as the real one does. It is set here rather than in the workflow
so the tests behave the same way on a developer's machine as they do in CI.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402 - must follow the platform choice above
import pytest  # noqa: E402


class FakeCamera:
    """Stands in for `CameraSource` with a marker the tests can move."""

    def __init__(self, marker: tuple[int, int] | None = (320, 240)) -> None:
        self.measured_fps = 29.4
        self.exposure = -9
        self.marker = marker
        self.exposures_set: list[int] = []

    def read(self) -> np.ndarray:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if self.marker is not None:
            x, y = self.marker
            ys, xs = np.ogrid[:480, :640]
            frame[(xs - x) ** 2 + (ys - y) ** 2 <= 36] = 245
        return frame

    def set_exposure(self, value: int) -> int:
        self.exposure = value
        self.exposures_set.append(value)
        return value

    def close(self) -> None:
        pass


@pytest.fixture
def fake_camera():
    """The stand-in camera class, for tests that build their own.

    A fixture rather than an import. `conftest.py` is *loaded* by pytest, not
    imported by name, so `from tests.conftest import FakeCamera` only works
    when the repository root happens to be on `sys.path` - which it is under
    `python -m pytest`, and is not under a bare `pytest`. Every local run
    passed and CI failed for two days on exactly that difference.
    """
    return FakeCamera


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole run - Qt permits no more than one."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, monkeypatch):
    """A live window over a fake camera, torn down after each test.

    The logon-task query is stubbed out. Left real it would spawn `schtasks`
    for every test, and worse, the results would depend on whether the machine
    running the suite happens to have AccessCam registered - so the tests would
    pass or fail according to a setting on the developer's desktop.
    """
    from accesscam import startup

    monkeypatch.setattr(
        startup, "state", lambda: startup.State(supported=True, enabled=False, stale=False)
    )

    from accesscam.config import Config
    from accesscam.engine import Engine
    from accesscam.mouse import CursorController
    from accesscam.mouse.base import ScreenBounds
    from accesscam.mouse.fake import RecordingMouse
    from accesscam.ui import main_window as main_window_module
    from accesscam.ui.main_window import MainWindow

    # Pin the elevation warning on. Left to the real answer the layout tests
    # would depend on whether the suite happens to be run from an elevated
    # terminal, and the banner is the taller of the two cases - so testing it
    # is testing the one that can overflow a small screen.
    monkeypatch.setattr(main_window_module, "_is_elevated", lambda: False)

    config = Config()
    engine = Engine(
        config,
        FakeCamera(),
        CursorController(RecordingMouse(bounds=ScreenBounds(0, 0, 2560, 1440), start=(0, 0))),
    )
    main = MainWindow(engine, config)
    main.show()
    qt_app.processEvents()

    # Give the preview a frame so its geometry is the real one: the region maths
    # is all in frame pixels, and an unpainted preview has no frame to map onto.
    main.preview.update_frame(FakeCamera().read(), None, False, config.roi())

    # Show both tabs once. A tab that has never been current has not been laid
    # out, and reports its pre-layout size.
    for index in (1, 0):
        main.tabs.setCurrentIndex(index)
        qt_app.processEvents()

    yield main

    engine.stop()
    main.close()
    qt_app.processEvents()
