"""The logon task: what command it registers, and whether an existing one is current."""

from __future__ import annotations

import sys
from pathlib import Path

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
