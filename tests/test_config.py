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


def test_roi_is_none_when_unset():
    assert Config().roi() is None


def test_roi_returns_the_box_when_sized():
    config = Config(roi_x=10, roi_y=20, roi_w=100, roi_h=80)
    assert config.roi() == (10, 20, 100, 80)


def test_roi_is_none_when_width_or_height_is_zero():
    # A degenerate box would reject every blob; treat it as disabled instead.
    assert Config(roi_x=10, roi_y=20, roi_w=0, roi_h=80).roi() is None
    assert Config(roi_x=10, roi_y=20, roi_w=100, roi_h=0).roi() is None


def test_config_path_is_under_the_config_dir():
    assert config_path().parent == config_dir()
    assert config_path().name == "config.json"
