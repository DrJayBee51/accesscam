"""The logon task: what command it registers, and whether an existing one is current."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from accesscam import startup


def test_a_windowed_interpreter_is_preferred(tmp_path, monkeypatch):
    # python.exe is a console application, so Windows allocates a console window
    # for it - a black box behind the UI at every logon, for a program with a
    # GUI that never prints to it.
    console = tmp_path / "python.exe"
    console.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(console))

    assert "pythonw.exe" in startup.executable()
    assert "-m accesscam --ui" in startup.executable()


def test_the_console_interpreter_is_used_when_there_is_no_other(tmp_path, monkeypatch):
    console = tmp_path / "python.exe"
    console.write_text("")
    monkeypatch.setattr(sys, "executable", str(console))

    assert "python.exe" in startup.executable()


def test_a_console_script_launcher_is_run_directly(tmp_path, monkeypatch):
    launcher = tmp_path / "accesscam.exe"
    launcher.write_text("")
    monkeypatch.setattr(sys, "executable", str(launcher))

    command = startup.executable()
    assert command.startswith(f'"{launcher}" --ui')
    assert "-m accesscam" not in command


def test_the_logon_command_waits_for_the_camera(tmp_path, monkeypatch):
    # Without this the tray icon silently never appears: the logon trigger beats
    # a USB camera's enumeration, the open fails and AccessCam exits.
    console = tmp_path / "python.exe"
    console.write_text("")
    monkeypatch.setattr(sys, "executable", str(console))

    assert f"--wait-for-camera {startup.CAMERA_WAIT_SECONDS}" in startup.executable()
    assert startup.CAMERA_WAIT_SECONDS > 0


def test_the_command_is_quoted_so_spaces_survive(tmp_path, monkeypatch):
    spaced = tmp_path / "Program Files" / "python.exe"
    spaced.parent.mkdir()
    spaced.write_text("")
    monkeypatch.setattr(sys, "executable", str(spaced))

    assert startup.executable().startswith('"')


def test_no_task_means_not_enabled_and_not_stale(monkeypatch):
    monkeypatch.setattr(startup, "supported", lambda: True)
    monkeypatch.setattr(startup, "registered_command", lambda: None)

    current = startup.state()
    assert current.supported
    assert not current.enabled
    assert not current.stale


def test_a_task_running_the_current_command_is_not_stale(monkeypatch):
    monkeypatch.setattr(startup, "supported", lambda: True)
    monkeypatch.setattr(startup, "registered_command", startup.executable)

    current = startup.state()
    assert current.enabled
    assert not current.stale


def test_a_task_running_something_else_is_stale(monkeypatch):
    monkeypatch.setattr(startup, "supported", lambda: True)
    monkeypatch.setattr(startup, "registered_command", lambda: '"C:\\old\\python.exe" -m accesscam')

    current = startup.state()
    assert current.enabled
    assert current.stale


def test_the_xml_scraper_finds_the_command():
    xml = (
        "<Task><Actions><Exec>"
        "<Command>C:\\a\\pythonw.exe</Command>"
        "<Arguments>-m accesscam --ui</Arguments>"
        "</Exec></Actions></Task>"
    )
    assert startup._between(xml, "<Command>", "</Command>") == "C:\\a\\pythonw.exe"
    assert startup._between(xml, "<Arguments>", "</Arguments>") == "-m accesscam --ui"
    assert startup._between(xml, "<Missing>", "</Missing>") is None


def test_unsupported_platforms_report_rather_than_pretend(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "linux")

    assert not startup.supported()
    assert not startup.is_enabled()
    assert startup.registered_command() is None

    outcome = startup.enable()
    assert not outcome.ok
    assert "Windows" in outcome.message
    # Removing something that was never registered is not a failure.
    assert startup.disable().ok


def test_the_executable_path_is_absolute():
    assert Path(startup.executable().split('"')[1]).is_absolute()


# -- the packaged application ---------------------------------------------


def test_a_relaunch_carries_the_current_flags_and_waits_for_the_camera(tmp_path, monkeypatch):
    # The copy being replaced is still holding the camera for the second it
    # takes to quit, so the new one has to be willing to wait for it.
    console = tmp_path / "python.exe"
    console.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(startup.sys, "executable", str(console))
    monkeypatch.setattr(startup.sys, "argv", ["accesscam", "--ui", "--device", "3"])

    _exe, arguments = startup._current_invocation()

    assert "--device 3" in arguments
    assert f"--wait-for-camera {startup.RELAUNCH_WAIT_SECONDS}" in arguments


# -- coming up elevated without anyone being asked -------------------------


class FakeRun:
    """Stands in for `startup._run`, recording what schtasks was asked to do."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, stdout="", stderr="")


@pytest.fixture
def handover(tmp_path, monkeypatch):
    """A Windows-like world with a good task, ready for one thing to go wrong."""
    runner = FakeRun()
    # A launch with no flags on it - the shortcut, the pinned icon - which is
    # what the handover is for. Under pytest, sys.argv is full of pytest's own.
    monkeypatch.setattr(startup.sys, "argv", ["accesscam"])
    monkeypatch.setattr(startup, "supported", lambda: True)
    monkeypatch.setattr(startup, "_already_privileged", lambda: False)
    monkeypatch.setattr(startup, "_handoff_marker", lambda: tmp_path / "elevating")
    monkeypatch.setattr(
        startup, "state", lambda: startup.State(supported=True, enabled=True, stale=False)
    )
    monkeypatch.setattr(startup, "_run", runner)
    return runner


def test_an_unelevated_copy_starts_the_elevated_one_and_stands_down(handover):
    assert startup.take_over_elevated() is True
    assert handover.calls == [["schtasks", "/run", "/tn", startup.TASK_NAME]]


def test_an_elevated_copy_stays_where_it_is(handover, monkeypatch):
    # Also covers UIAccess, which reaches privileged windows without elevating.
    monkeypatch.setattr(startup, "_already_privileged", lambda: True)

    assert startup.take_over_elevated() is False
    assert handover.calls == []


def test_nothing_is_handed_over_to_when_no_task_is_registered(handover, monkeypatch):
    # The window's banner offers to register one. That is the only step that
    # spends a UAC prompt, and it must stay a deliberate click.
    monkeypatch.setattr(
        startup, "state", lambda: startup.State(supported=True, enabled=False, stale=False)
    )

    assert startup.take_over_elevated() is False
    assert handover.calls == []


def test_a_task_pointing_at_another_copy_is_left_alone(handover, monkeypatch):
    # Otherwise launching this build would silently start a different one - an
    # old checkout, a previous install - which is a baffling thing to debug.
    monkeypatch.setattr(
        startup, "state", lambda: startup.State(supported=True, enabled=True, stale=True)
    )
    monkeypatch.setattr(startup, "registered_command", lambda: "somewhere-else.exe")

    assert startup.take_over_elevated() is False
    assert handover.calls == []


def test_a_second_handover_in_a_row_is_refused(handover):
    # A task registered without /rl highest starts an unelevated copy, which
    # would hand over again, forever, with no window ever appearing.
    assert startup.take_over_elevated() is True
    assert startup.take_over_elevated() is False
    assert len(handover.calls) == 1


def test_handing_over_again_is_allowed_once_the_cooldown_has_passed(handover, monkeypatch):
    assert startup.take_over_elevated() is True

    marker = startup._handoff_marker()
    stale = time.time() - (startup.HANDOFF_COOLDOWN_SECONDS + 1)
    os.utime(marker, (stale, stale))

    assert startup.take_over_elevated() is True
    assert len(handover.calls) == 2


def test_a_task_that_will_not_start_leaves_this_copy_running(handover, monkeypatch):
    # Better an unelevated AccessCam that says so in its banner than no
    # AccessCam at all for someone who needs it to use their computer.
    monkeypatch.setattr(startup, "_run", FakeRun(returncode=1))

    assert startup.take_over_elevated() is False


def test_an_unwritable_config_directory_does_not_stop_the_handover(handover, tmp_path, monkeypatch):
    # The marker only guards against a loop that needs a broken task to happen
    # in the first place. Failing to write it must not cost someone AccessCam.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    monkeypatch.setattr(startup, "_handoff_marker", lambda: blocked / "elevating")

    assert startup.take_over_elevated() is True


def test_nothing_is_handed_over_where_scheduled_tasks_do_not_exist(monkeypatch):
    monkeypatch.setattr(startup, "supported", lambda: False)

    assert startup.take_over_elevated() is False


@pytest.mark.parametrize("argv", [[], ["--ui"], ["--ui", "--wait-for-camera", "60"]])
def test_a_plain_launch_hands_over(handover, argv):
    # The shortcut, the pinned icon, the double-clicked exe: nothing to lose.
    # One case per run - a second handover in the same 90 seconds is refused,
    # which is the cooldown doing its job rather than this failing.
    assert startup.take_over_elevated(argv) is True


def test_a_launch_carrying_settings_is_left_alone(handover):
    # The task runs one fixed command line. Handing over would drop these
    # silently, which is worse than an unelevated copy that says it is one.
    for argv in (
        ["--device", "2"],
        ["--headless"],
        ["--ui", "--gain", "150"],
        ["--config", "elsewhere.json"],
    ):
        assert startup.take_over_elevated(argv) is False, argv
    assert handover.calls == []
