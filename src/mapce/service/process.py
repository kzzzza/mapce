"""Start, inspect, and stop the local MAPCE service safely."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from mapce import __version__

from .runtime import ServiceInfo, normalize_data_dir, read_service_info, read_token, runtime_paths


class ServiceProcessError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _health(info: ServiceInfo, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{info.base_url}/health", timeout=timeout)
        payload = response.json()
    except (OSError, ValueError, httpx.HTTPError):
        return None
    if (
        response.status_code == 200
        and payload.get("status") == "ok"
        and payload.get("service_id") == info.service_id
        and payload.get("data_dir_hash") == info.data_dir_hash
    ):
        return payload
    return None


def get_service_status(data_dir: str | Path | None = None) -> dict[str, Any]:
    from mapce.configuration import load_configured_env

    load_configured_env(strict=True)
    info = read_service_info(data_dir)
    if info is None:
        return {"running": False, "status": "stopped", "info": None}
    health = _health(info)
    return {
        "running": health is not None,
        "status": "running" if health is not None else "stale",
        "info": info,
        "health": health,
    }


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _wait_for_service(
    data_dir: Path,
    deadline: float,
) -> ServiceInfo | None:
    while time.monotonic() < deadline:
        info = read_service_info(data_dir)
        if info is not None and _health(info) is not None:
            return info
        time.sleep(0.1)
    return None


def ensure_service(
    data_dir: str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    timeout: float = 15.0,
) -> ServiceInfo:
    from mapce.configuration import load_configured_env

    load_configured_env(strict=True)
    normalized = normalize_data_dir(data_dir)
    configured_port = port or int(os.environ.get("MAPCE_SERVICE_PORT", "8765"))
    existing = read_service_info(normalized)
    if existing is not None:
        health = _health(existing)
        if health is not None:
            if health.get("version") != __version__:
                raise ServiceProcessError(
                    "service_version_mismatch",
                    f"Running MAPCE service uses version {health.get('version')}; expected {__version__}.",
                )
            return existing

    if existing is not None and _port_is_open(host, configured_port):
        recovered = _wait_for_service(normalized, time.monotonic() + min(timeout, 2.0))
        if recovered is not None:
            return recovered

    if _port_is_open(host, configured_port):
        raise ServiceProcessError(
            "service_port_in_use",
            f"Port {host}:{configured_port} is occupied by another process.",
        )

    paths = runtime_paths(normalized)
    paths.directory.mkdir(parents=True, exist_ok=True)
    log_handle = paths.log.open("a", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "mapce.service.server",
        "--data-dir",
        str(normalized),
        "--host",
        host,
        "--port",
        str(configured_port),
    ]
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_handle.close()

    info = _wait_for_service(normalized, time.monotonic() + timeout)
    if info is not None:
        return info

    raise ServiceProcessError(
        "service_start_timeout",
        f"MAPCE service did not become healthy within {timeout:.1f} seconds. See {paths.log}.",
    )


def stop_service(
    data_dir: str | Path | None = None,
    *,
    force: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    status = get_service_status(data_dir)
    info = status.get("info")
    if info is None:
        return {"status": "ok", "stopped": False, "message": "MAPCE service is not running."}
    if not status.get("running"):
        return {
            "status": "error",
            "error_code": "stale_service_info",
            "message": "Service metadata exists, but its identity cannot be verified.",
        }

    try:
        token = read_token(Path(info.token_file))
        response = httpx.post(
            f"{info.base_url}/api/admin/shutdown",
            headers={"Authorization": f"Bearer {token}"},
            timeout=2.0,
        )
        response.raise_for_status()
    except (OSError, httpx.HTTPError):
        if not force:
            return {
                "status": "error",
                "error_code": "shutdown_failed",
                "message": "The verified service did not accept the shutdown request.",
            }

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(info, timeout=0.25) is None:
            return {"status": "ok", "stopped": True, "pid": info.pid}
        time.sleep(0.1)

    if not force:
        return {
            "status": "error",
            "error_code": "shutdown_timeout",
            "message": "The service is still running; use --force only after reviewing active jobs.",
        }

    if _health(info, timeout=0.5) is None:
        return {"status": "ok", "stopped": True, "pid": info.pid, "forced": True}
    try:
        os.kill(info.pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"status": "ok", "stopped": True, "pid": info.pid, "forced": True}
    except PermissionError as exc:
        return {
            "status": "error",
            "error_code": "signal_not_permitted",
            "message": str(exc),
        }
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if _health(info, timeout=0.25) is None:
            return {"status": "ok", "stopped": True, "pid": info.pid, "forced": True}
        time.sleep(0.1)
    if _health(info, timeout=0.5) is None:
        return {"status": "ok", "stopped": True, "pid": info.pid, "forced": True}
    try:
        os.kill(info.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        return {
            "status": "error",
            "error_code": "signal_not_permitted",
            "message": str(exc),
        }
    return {"status": "ok", "stopped": True, "pid": info.pid, "forced": True}


def service_logs_path(data_dir: str | Path | None = None) -> Path:
    return runtime_paths(data_dir).log
