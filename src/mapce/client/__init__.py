"""Shared local HTTP client used by CLI, TUI, and the stdio proxy."""

from .http import MapceClient, ServiceClientError

__all__ = ["MapceClient", "ServiceClientError"]
