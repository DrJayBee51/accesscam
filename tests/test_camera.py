"""Opening the camera, including waiting for one that is not there yet."""

from __future__ import annotations

import pytest

from accesscam import camera as camera_module
from accesscam.camera import CameraError, CameraSource


class FakeCapture:
    """Just enough of cv2.VideoCapture for open() to run against."""

    def __init__(self, opened: bool) -> None:
        self._opened = opened
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - matches the OpenCV name
        return self._opened

    def set(self, prop: int, value: float) -> bool:
        return True

    def release(self) -> None:
        self.released = True


@pytest.fixture
def captures(monkeypatch):
    """Hand out cameras from a script of open/not-open, recording each attempt."""
    made: list[FakeCapture] = []

    def install(results: list[bool]) -> list[FakeCapture]:
        pending = list(results)

        def factory(device: int, backend: int) -> FakeCapture:
            cap = FakeCapture(pending.pop(0) if pending else False)
            made.append(cap)
            return cap

        monkeypatch.setattr(camera_module.cv2, "VideoCapture", factory)
        return made

    # Nothing here should actually spend the retry interval sleeping.
    monkeypatch.setattr(camera_module.time, "sleep", lambda _seconds: None)
    return install


def test_a_camera_that_is_there_opens_first_time(captures):
    made = captures([True])
    CameraSource().open()

    assert len(made) == 1


def test_waiting_retries_until_the_camera_appears(captures):
    # The logon case: the desktop is up before the USB camera has enumerated,
    # so the first attempts fail on a camera that is about to work.
    made = captures([False, False, True])
    CameraSource().open(wait=30)

    assert len(made) == 3


def test_not_waiting_fails_on_the_first_attempt(captures):
    # Someone at a terminal who mistyped the device index wants telling now.
    made = captures([False, True])

    with pytest.raises(CameraError):
        CameraSource().open()

    assert len(made) == 1


def test_giving_up_once_the_wait_is_spent(captures, monkeypatch):
    clock = iter([0.0, 0.0, 5.0, 10.0, 20.0])
    monkeypatch.setattr(camera_module.time, "monotonic", lambda: next(clock))
    captures([False, False, False, False])

    with pytest.raises(CameraError, match="Could not open camera device"):
        CameraSource().open(wait=10)


def test_failed_attempts_do_not_leak_their_handle(captures):
    # A VideoCapture that failed to open still holds a handle, and retrying for
    # a minute makes that add up.
    made = captures([False, False, True])
    CameraSource().open(wait=30)

    assert [cap.released for cap in made] == [True, True, False]
