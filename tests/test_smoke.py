from accesscam import __version__


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
