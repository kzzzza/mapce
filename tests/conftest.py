from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_mapce_user_configuration(monkeypatch, tmp_path):
    """Never let tests read or modify the user's real MAPCE config."""
    monkeypatch.setenv("MAPCE_CONFIG_FILE", str(tmp_path / "mapce-config.json"))
    monkeypatch.delenv("MAPCE_ENV_FILE", raising=False)
