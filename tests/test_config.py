import pytest

from eyetracker.cli import duration
from eyetracker.config import Config, Paths, load_config


def test_missing_file_uses_defaults(tmp_path):
    assert load_config(tmp_path / "config.toml") == Config()


def test_file_overrides_only_what_it_sets(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("stare_alert_s = 45\nalerts_enabled = false\n")
    config = load_config(path)
    assert config.stare_alert_s == 45
    assert config.alerts_enabled is False
    assert config.target_fps == Config().target_fps


def test_a_misspelled_setting_is_reported(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("stare_alert_seconds = 45\n")
    with pytest.raises(SystemExit, match="stare_alert_seconds"):
        load_config(path)


def test_paths_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "r"))
    paths = Paths.default()
    assert paths.config_file == tmp_path / "c/eyetracker/config.toml"
    assert paths.db == tmp_path / "d/eyetracker/eyetracker.db"
    assert paths.status == tmp_path / "r/eyetracker/status.json"


def test_data_folder_is_private(tmp_path):
    paths = Paths(tmp_path / "c.toml", tmp_path / "data", tmp_path / "run")
    paths.ensure()
    assert (paths.data_dir.stat().st_mode & 0o777) == 0o700


def test_durations_read_naturally():
    assert duration(38) == "38s"
    assert duration(192) == "3m 12s"
    assert duration(15120) == "4h 12m"
