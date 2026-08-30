"""Local singleton service for MAPCE database access."""

from .runtime import ServiceInfo, normalize_data_dir, runtime_paths

__all__ = ["ServiceInfo", "normalize_data_dir", "runtime_paths"]
