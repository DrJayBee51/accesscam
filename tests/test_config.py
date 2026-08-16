"""Config tests. Everything writes to tmp_path, never the real config dir."""

import json

from accesscam.config import Config, config_dir, config_path
from accesscam.hotkeys import DEFAULT_HOTKEY


def test_defaults_are_sourced_from_the_owning_modules():
    config = Config()

    assert config.hotkey == DEFAULT_HOTKEY
    assert config.threshold == 200
    assert config.invert_x is True


def test_missing_file_yields_defaults(tmp_path):
    assert Config.load(tmp_path / "absent.json") == Config()


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    original = Config(device=1, h_gain=42.0, hotkey="f8", invert_y=True)
    original.save(path)

    assert Config.load(path) == original


def test_save_creates_the_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "config.json"
    Config().save(path)

    assert path.exists()


def test_partial_file_fills_in_defaults(tmp_path):
    # A user editing the file by hand should be able to set one value without
    # having to restate everything else.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"h_gain": 12.5}), encoding="utf-8")

    config = Config.load(path)

    assert config.h_gain == 12.5
    assert config.v_gain == Config().v_gain
    assert config.hotkey == DEFAULT_HOTKEY


def test_unknown_keys_are_ignored_rather_than_fatal(tmp_path, capsys):
    # Being locked out by your own settings file is a bad failure for a tool
    # someone relies on to use their computer.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"h_gain": 5.0, "from_the_future": True}), encoding="utf-8")

    config = Config.load(path)

    assert config.h_gain == 5.0
    assert "from_the_future" in capsys.readouterr().out


def test_saved_file_is_human_editable(tmp_path):
    path = tmp_path / "config.json"
    Config().save(path)
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert '"h_gain"' in text
    # Sorted keys keep diffs readable when the file is edited by hand.
    data = json.loads(text)
    assert list(data) == sorted(data)


def test_roi_defaults_to_the_whole_frame():
    # There is no disabled state - the region is always in force, and unset
    # means the frame rather than nothing.
    config = Config()
    assert config.roi() == (0, 0, config.width, config.height)
    assert config.roi_is_whole_frame()


def test_roi_returns_the_box_when_sized():
    config = Config(roi_x=10, roi_y=20, roi_w=100, roi_h=80)
    assert config.roi() == (10, 20, 100, 80)
    assert not config.roi_is_whole_frame()


def test_a_zero_dimension_means_the_whole_frame_not_a_dead_box():
    # A degenerate box would reject every blob and stop tracking outright.
    config = Config(roi_x=10, roi_y=20, roi_w=0, roi_h=80)
    assert config.roi() == (0, 0, config.width, config.height)
    assert Config(roi_x=10, roi_y=20, roi_w=100, roi_h=0).roi_is_whole_frame()


def test_set_roi_clamps_to_the_frame():
    config = Config()
    config.set_roi(600, 400, 400, 400)

    x, y, w, h = config.roi()
    assert x + w <= config.width
    assert y + h <= config.height


def test_set_roi_never_produces_an_empty_box():
    config = Config()
    config.set_roi(100, 100, 0, 0)

    _, _, w, h = config.roi()
    assert w >= 1
    assert h >= 1


def test_set_roi_rejects_a_negative_origin():
    config = Config()
    config.set_roi(-50, -20, 200, 200)

    assert config.roi()[:2] == (0, 0)


def test_config_path_is_under_the_config_dir():
    assert config_path().parent == config_dir()
    assert config_path().name == "config.json"
