from __future__ import annotations

import os
from pathlib import Path

import pytest

from mapce.service.runtime import (
    DatabaseWriteBlockedError,
    ServiceLock,
    assert_database_write_allowed,
    data_dir_hash,
    normalize_data_dir,
    read_token,
    runtime_paths,
    write_token,
)


def test_runtime_identity_uses_normalized_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPCE_RUNTIME_DIR", str(tmp_path / "run"))
    data_dir = tmp_path / "nested" / ".." / "data"

    normalized = normalize_data_dir(data_dir)
    paths = runtime_paths(data_dir)

    assert normalized == (tmp_path / "data").resolve()
    assert paths.directory.name == data_dir_hash(data_dir)
    assert paths.directory.parent == tmp_path / "run"


def test_service_lock_rejects_second_owner(tmp_path):
    first = ServiceLock(tmp_path / "service.lock")
    second = ServiceLock(tmp_path / "service.lock")

    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_service_token_is_private(tmp_path):
    path = tmp_path / "service.token"
    token = write_token(path)

    assert read_token(path) == token
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_direct_write_is_blocked_while_service_lock_is_held(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPCE_RUNTIME_DIR", str(tmp_path / "run"))
    data_dir = tmp_path / "data"
    owner = ServiceLock(runtime_paths(data_dir).lock)
    assert owner.acquire()

    try:
        with pytest.raises(DatabaseWriteBlockedError):
            assert_database_write_allowed(data_dir)
        monkeypatch.setenv("MAPCE_SERVICE_OWNER_ID", "verified-service")
        assert_database_write_allowed(data_dir)
    finally:
        owner.release()
