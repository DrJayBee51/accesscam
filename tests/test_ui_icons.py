"""Supplied artwork replaces the drawn glyph, and its absence changes nothing.

The drawn ring-and-dot was only ever a stand-in that could carry state. Art
that someone designed should win, and a missing or unreadable file must fall
back rather than leave a blank square in the tray.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from accesscam import assets
from accesscam.ui import tray as tray_module

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    """An assets directory of this test's own."""
    monkeypatch.setattr(assets, "asset_root", lambda: tmp_path)
    return tmp_path


def write_square(path, colour):
    """A recognisable one-colour icon, so the loader can be caught using it."""
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(32, 32)
    pixmap.fill(colour)
    assert pixmap.save(str(path))


def test_without_artwork_the_glyph_is_drawn(art_dir):
    parked = tray_module.tray_icon(paused=True)
    driving = tray_module.tray_icon(paused=False)

    centre = parked.pixmap(64, 64).toImage().pixel(32, 32)
    assert QColor(centre) == tray_module.PAUSED
    assert QColor(driving.pixmap(64, 64).toImage().pixel(32, 32)) == tray_module.ACTIVE


def test_supplied_artwork_is_used_for_both_states(art_dir):
    write_square(art_dir / "tray-active.png", QColor(10, 20, 30))
    write_square(art_dir / "tray-paused.png", QColor(200, 100, 50))

    assert QColor(tray_module.tray_icon(False).pixmap(32, 32).toImage().pixel(16, 16)) == QColor(
        10, 20, 30
    )
    assert QColor(tray_module.tray_icon(True).pixmap(32, 32).toImage().pixel(16, 16)) == QColor(
        200, 100, 50
    )


def test_one_state_supplied_does_not_break_the_other(art_dir):
    # Half-finished artwork is a normal state to be in for a while.
    write_square(art_dir / "tray-active.png", QColor(10, 20, 30))

    assert QColor(tray_module.tray_icon(True).pixmap(64, 64).toImage().pixel(32, 32)) == (
        tray_module.PAUSED
    )


def test_an_unreadable_file_falls_back_rather_than_showing_nothing(art_dir):
    # A blank square in the tray would be worse than the drawn glyph, and this
    # is what a truncated copy or a renamed .psd looks like.
    (art_dir / "tray-active.png").write_bytes(b"not an image")

    icon = tray_module.tray_icon(paused=False)

    assert not icon.isNull()
    assert QColor(icon.pixmap(64, 64).toImage().pixel(32, 32)) == tray_module.ACTIVE


def test_the_application_icon_carries_every_size_when_drawn(art_dir):
    # Windows picks the nearest size; a single 256px image smears at 16.
    icon = tray_module.app_icon()
    assert not icon.isNull()
    assert {size.width() for size in icon.availableSizes()} >= {16, 32, 256}
