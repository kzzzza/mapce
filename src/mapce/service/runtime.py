"""Runtime identity, lock, token, and metadata helpers."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any


def normalize_data_dir(data_dir: str | Path | None = None) -> Path:
    if data_dir is not None:
        path = Path(data_dir).expanduser()
    elif configured := os.environ.get("MAPCE_DATA_DIR"):
        path = Path(configured).expanduser()
    else:
        path = Path.home() / ".mapce" / "data"
    return path.resolve()


def data_dir_hash(data_dir: str | Path | None = None) -> str:
    normalized = str(normalize_data_dir(data_dir))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class RuntimePaths:
    directory: Path
    lock: Path
    info: Path
    token: Path
    log: Path


def runtime_paths(data_dir: str | Path | None = None) -> RuntimePaths:
    root_env = os.environ.get("MAPCE_RUNTIME_DIR")
    root = Path(root_env).expanduser() if root_env else Path.home() / ".mapce" / "run"
    directory = root / data_dir_hash(data_dir)
    return RuntimePaths(
        directory=directory,
        lock=directory / "service.lock",
        info=directory / "service.json",
        token=directory / "service.token",
        log=directory / "service.log",
    )


@dataclass(frozen=True)
class ServiceInfo:
    service_id: str
    pid: int
    host: str
    port: int
    data_dir: str
    data_dir_hash: str
    version: str
    started_at: str
    token_file: str

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ServiceInfo":
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})


class ServiceLock:
    """Lifetime advisory lock for one normalized database directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: IO[str] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "ServiceLock":
        if not self.acquire():
            raise RuntimeError("MAPCE service lock is already held")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class DatabaseWriteBlockedError(RuntimeError):
    """Raised when a direct process attempts to bypass the running service."""


def assert_database_write_allowed(data_dir: str | Path | None = None) -> None:
    """Reject direct writes while another process owns the service lock."""
    if os.environ.get("MAPCE_SERVICE_OWNER_ID"):
        return
    probe = ServiceLock(runtime_paths(data_dir).lock)
    if not probe.acquire():
        raise DatabaseWriteBlockedError(
            "A MAPCE service is running for this data directory. Submit the write "
            "through the service, or stop it with `mapce serve-kill` first."
        )
    probe.release()


def write_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, token.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return token


def read_token(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_service_info(path: Path, info: ServiceInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_service_info(data_dir: str | Path | None = None) -> ServiceInfo | None:
    path = runtime_paths(data_dir).info
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return ServiceInfo.from_dict(value)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
