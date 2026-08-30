"""Persistent user configuration and default dotenv loading."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class EnvFileStatus:
    config_file: str
    env_file: str | None
    source: str | None
    configured: bool
    exists: bool
    loaded: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def config_file_path(path: str | Path | None = None) -> Path:
    """Return the global config path, with a test/advanced override."""
    if path is not None:
        return Path(path).expanduser().resolve()
    if override := os.environ.get("MAPCE_CONFIG_FILE"):
        return Path(os.path.expandvars(override)).expanduser().resolve()
    return (Path.home() / ".mapce" / "config.json").resolve()


def _read_config(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            "invalid_config",
            f"MAPCE config is not valid JSON: {path}: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise ConfigurationError(
            "invalid_config",
            f"MAPCE config must contain a JSON object: {path}",
        )
    return value


def _write_config(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _resolve_env_file(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().resolve()


def env_file_status(
    *,
    config_path: str | Path | None = None,
) -> EnvFileStatus:
    """Inspect the effective dotenv path without reading its values."""
    path = config_file_path(config_path)
    override = os.environ.get("MAPCE_ENV_FILE")
    if override:
        env_path = _resolve_env_file(override)
        source = "environment"
    else:
        configured = _read_config(path).get("env_file")
        env_path = _resolve_env_file(configured) if isinstance(configured, str) else None
        source = "config" if env_path is not None else None
    return EnvFileStatus(
        config_file=str(path),
        env_file=str(env_path) if env_path is not None else None,
        source=source,
        configured=env_path is not None,
        exists=bool(env_path is not None and env_path.is_file()),
        loaded=False,
    )


def load_configured_env(
    *,
    strict: bool = True,
    config_path: str | Path | None = None,
) -> EnvFileStatus:
    """Load the configured dotenv without replacing explicit process values."""
    status = env_file_status(config_path=config_path)
    if not status.configured:
        return status
    if not status.exists:
        if strict:
            raise ConfigurationError(
                "env_file_not_found",
                f"Configured MAPCE env file does not exist: {status.env_file}",
            )
        return status
    load_dotenv(status.env_file, override=False)
    return EnvFileStatus(**{**status.as_dict(), "loaded": True})


def set_default_env_file(
    env_file: str | Path,
    *,
    config_path: str | Path | None = None,
) -> EnvFileStatus:
    """Validate and persist one default dotenv path; never copy its contents."""
    env_path = _resolve_env_file(str(env_file))
    if not env_path.is_file():
        raise ConfigurationError(
            "env_file_not_found",
            f"MAPCE env file does not exist or is not a file: {env_path}",
        )
    path = config_file_path(config_path)
    value = _read_config(path)
    value["env_file"] = str(env_path)
    _write_config(path, value)
    return env_file_status(config_path=path)


def unset_default_env_file(
    *,
    config_path: str | Path | None = None,
) -> EnvFileStatus:
    """Remove only the saved dotenv path, preserving future config fields."""
    path = config_file_path(config_path)
    value = _read_config(path)
    value.pop("env_file", None)
    _write_config(path, value)
    return env_file_status(config_path=path)
