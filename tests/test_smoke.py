import sys

from accesscam import __version__, app, startup


def test_version():
    assert __version__


# -- what a double-clicked application does -------------------------------


class _Args:
    def __init__(self, ui=False, headless=False):
        self.ui = ui
        self.headless = headless


def test_a_packaged_build_opens_its_window_by_default(monkeypatch):
    from accesscam import app

    monkeypatch.setattr(app, "frozen", lambda: True)
    assert app.wants_ui(_Args())


def test_a_source_checkout_stays_headless_by_default(monkeypatch):
    # `python -m accesscam` is how the pipeline is exercised with no UI in the
    # way, and that has been the default since M2.
    from accesscam import app

    monkeypatch.setattr(app, "frozen", lambda: False)
    assert not app.wants_ui(_Args())
    assert app.wants_ui(_Args(ui=True))


def test_headless_wins_even_when_packaged(monkeypatch):
    from accesscam import app

    monkeypatch.setattr(app, "frozen", lambda: True)
    assert not app.wants_ui(_Args(headless=True))


# -- and what it does about not being elevated ----------------------------


def _without_a_log_file(monkeypatch):
    # main() opens the real %APPDATA% log first thing, which a test has no
    # business appending to.
    monkeypatch.setattr(app, "start_logging", lambda: None)


def test_an_unelevated_launch_hands_over_and_quits(monkeypatch):
    # Returning 0 here is the whole assertion: it means main() stopped before
    # reading the config or opening the camera, which is the point of doing
    # this first - the elevated copy is waiting for the camera this one holds.
    _without_a_log_file(monkeypatch)
    handed_over = []
    monkeypatch.setattr(
        startup, "take_over_elevated", lambda: bool(handed_over.append(True)) or True
    )
    monkeypatch.setattr(sys, "argv", ["accesscam"])

    assert app.main() == 0
    assert handed_over == [True]


def test_no_elevate_gets_you_the_copy_you_asked_for(tmp_path, monkeypatch):
    # For working on the pipeline, and for seeing the banner the way someone
    # without a registered task sees it.
    _without_a_log_file(monkeypatch)

    def refuse():
        raise AssertionError("--no-elevate must not hand over")

    monkeypatch.setattr(startup, "take_over_elevated", refuse)
    monkeypatch.setattr(
        sys,
        "argv",
        ["accesscam", "--no-elevate", "--write-config", "--config", str(tmp_path / "c.json")],
    )

    assert app.main() == 0
