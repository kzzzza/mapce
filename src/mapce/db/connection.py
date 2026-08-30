"""Database connection management."""

import os
from functools import lru_cache
from pathlib import Path

import lancedb

DEFAULT_DATA_DIR = Path.home() / ".mapce" / "data"


def _get_data_dir() -> Path:
    env_dir = os.environ.get("MAPCE_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return DEFAULT_DATA_DIR


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=4)
def _connect_cached(path: str) -> lancedb.DBConnection:
    """Reuse LanceDB connections instead of accumulating per-query runtimes."""
    return lancedb.connect(path)


def get_connection(data_dir: Path | None = None) -> lancedb.DBConnection:
    """Get a LanceDB connection, creating the data directory if needed.

    Args:
        data_dir: Optional override for the data directory.
                  Defaults to MAPCE_DATA_DIR env var or ~/.mapce/data.

    Returns:
        A LanceDB DBConnection instance.
    """
    path = (data_dir or _get_data_dir()).expanduser().resolve()
    _ensure_dir(path)
    return _connect_cached(str(path))
