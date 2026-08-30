"""MAPCE TUI pages."""

from .dashboard import DashboardPane
from .index import IndexPane
from .jobs import JobsPane
from .papers import PapersPane
from .system import SystemPane

__all__ = ["DashboardPane", "IndexPane", "JobsPane", "PapersPane", "SystemPane"]
