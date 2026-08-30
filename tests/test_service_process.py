from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mapce import __version__
from mapce.service import process
from mapce.service.runtime import ServiceInfo


def _info(tmp_path, *, version: str = __version__) -> ServiceInfo:
    return ServiceInfo(
        service_id="service-id",
        pid=123,
        host="127.0.0.1",
        port=8765,
        data_dir=str(tmp_path),
        data_dir_hash="hash",
        version=version,
        started_at=datetime.now(timezone.utc).isoformat(),
        token_file=str(tmp_path / "token"),
    )


def test_ensure_service_reuses_verified_instance(tmp_path, monkeypatch):
    info = _info(tmp_path)
    monkeypatch.setattr(process, "read_service_info", lambda _: info)
    monkeypatch.setattr(
        process,
        "_health",
        lambda _: {"status": "ok", "version": __version__},
    )

    assert process.ensure_service(tmp_path) is info


def test_ensure_service_rejects_version_mismatch(tmp_path, monkeypatch):
    info = _info(tmp_path, version="old")
    monkeypatch.setattr(process, "read_service_info", lambda _: info)
    monkeypatch.setattr(
        process,
        "_health",
        lambda _: {"status": "ok", "version": "old"},
    )

    with pytest.raises(process.ServiceProcessError) as caught:
        process.ensure_service(tmp_path)

    assert caught.value.error_code == "service_version_mismatch"


def test_ensure_service_does_not_take_unknown_process_port(tmp_path, monkeypatch):
    monkeypatch.setattr(process, "read_service_info", lambda _: None)
    monkeypatch.setattr(process, "_port_is_open", lambda host, port: True)

    with pytest.raises(process.ServiceProcessError) as caught:
        process.ensure_service(tmp_path)

    assert caught.value.error_code == "service_port_in_use"


def test_stop_service_refuses_unverified_stale_pid(tmp_path, monkeypatch):
    info = _info(tmp_path)
    monkeypatch.setattr(
        process,
        "get_service_status",
        lambda _: {"running": False, "status": "stale", "info": info},
    )

    result = process.stop_service(tmp_path, force=True)

    assert result["error_code"] == "stale_service_info"
