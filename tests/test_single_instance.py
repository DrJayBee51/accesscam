"""Only one AccessCam, and a way for the second to fetch the first.

The failure this replaces was quiet and misleading: a second copy waited out
`--wait-for-camera` for a camera the first copy held, then reported it as a
hardware problem - or, under the logon task with no console, said nothing.
"""

from __future__ import annotations

import sys
import uuid

import pytest

from accesscam import single_instance

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the mutex guard is a Windows mechanism"
)


@pytest.fixture
def private_name():
    """A claim name of this test's own.

    The production name belongs to the running application. Borrowing it makes
    these tests pass or fail according to whether AccessCam happens to be open
    on the machine running them, which is not a property of the code.
    """
    return f"Local{chr(92)}AccessCam.Test.{uuid.uuid4()}"


@windows_only
def test_a_second_claim_is_refused(private_name):
    first = single_instance.claim(private_name)
    try:
        assert first is not None
        assert single_instance.claim(private_name) is None
    finally:
        first.release()


@windows_only
def test_releasing_frees_the_claim(private_name):
    # A leaked handle would keep a dead AccessCam looking alive to the next
    # launch, which is worse than no guard at all.
    first = single_instance.claim(private_name)
    first.release()

    second = single_instance.claim(private_name)
    assert second is not None
    second.release()


@windows_only
def test_the_claim_releases_itself_as_a_context_manager(private_name):
    with single_instance.claim(private_name) as claimed:
        assert claimed is not None
        assert single_instance.claim(private_name) is None

    again = single_instance.claim(private_name)
    assert again is not None
    again.release()


@windows_only
def test_the_reveal_message_is_the_same_number_every_time():
    # Every AccessCam process has to derive the same id from the same name;
    # that is the whole reason for a registered message rather than a title
    # lookup, since titles are localised and duplicated.
    first = single_instance.reveal_message()
    assert first != 0
    assert single_instance.reveal_message() == first


def test_claiming_never_blocks_a_platform_without_the_guard(monkeypatch, private_name):
    # Refusing to start because the guard is unavailable would cost the user
    # their pointer to protect them from a duplicate window.
    monkeypatch.setattr(single_instance.sys, "platform", "linux")
    claimed = single_instance.claim(private_name)
    assert claimed is not None
    claimed.release()  # a no-op, and must not raise
