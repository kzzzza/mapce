from __future__ import annotations

import json
import os
import stat

import pytest

from mapce.configuration import (
    ConfigurationError,
    env_file_status,
    load_configured_env,
    set_default_env_file,
    unset_default_env_file,
)


def test_save_and_load_default_env_without_overriding_shell(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    env_file = tmp_path / "mapce.env"
    env_file.write_text(
        "MAPCE_CONFIG_TEST=from-file\nMAPCE_SERVICE_PORT=9012\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAPCE_CONFIG_TEST", "from-shell")
    monkeypatch.delenv("MAPCE_SERVICE_PORT", raising=False)

    saved = set_default_env_file(env_file, config_path=config)
    loaded = load_configured_env(config_path=config)

    assert saved.env_file == str(env_file)
    assert saved.source == "config"
    assert loaded.loaded is True
    assert os.environ["MAPCE_CONFIG_TEST"] == "from-shell"
    assert os.environ["MAPCE_SERVICE_PORT"] == "9012"
    assert json.loads(config.read_text(encoding="utf-8")) == {"env_file": str(env_file)}
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_process_env_file_override_has_priority(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    saved_env = tmp_path / "saved.env"
    override_env = tmp_path / "override.env"
    saved_env.write_text("MAPCE_OVERRIDE_TEST=saved\n", encoding="utf-8")
    override_env.write_text("MAPCE_OVERRIDE_TEST=override\n", encoding="utf-8")
    set_default_env_file(saved_env, config_path=config)
    monkeypatch.setenv("MAPCE_ENV_FILE", str(override_env))
    monkeypatch.delenv("MAPCE_OVERRIDE_TEST", raising=False)

    loaded = load_configured_env(config_path=config)

    assert loaded.source == "environment"
    assert loaded.env_file == str(override_env)
    assert os.environ["MAPCE_OVERRIDE_TEST"] == "override"


def test_missing_configured_env_fails_strictly(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"env_file": str(tmp_path / "missing.env")}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as error:
        load_configured_env(config_path=config)

    assert error.value.error_code == "env_file_not_found"
    assert load_configured_env(config_path=config, strict=False).loaded is False


def test_unset_env_preserves_other_configuration_fields(tmp_path):
    config = tmp_path / "config.json"
    env_file = tmp_path / ".env"
    env_file.write_text("MAPCE_TEST=1\n", encoding="utf-8")
    config.write_text(json.dumps({"future": True}), encoding="utf-8")
    set_default_env_file(env_file, config_path=config)

    status = unset_default_env_file(config_path=config)

    assert status.configured is False
    assert json.loads(config.read_text(encoding="utf-8")) == {"future": True}


def test_env_status_never_exposes_dotenv_values(tmp_path):
    config = tmp_path / "config.json"
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_TOKEN=do-not-display\n", encoding="utf-8")
    set_default_env_file(env_file, config_path=config)

    payload = env_file_status(config_path=config).as_dict()

    assert "do-not-display" not in json.dumps(payload)
