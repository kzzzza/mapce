"""MAPCE — MCP-based Agent for Paper and Code Exploration.

A reusable academic knowledge base for general CS research.
Index papers and code repositories, serve via MCP protocol for AI agents.
"""

import os

# LanceDB 0.33 can materialize IVF centroids while reporting index statistics.
# MAPCE never consumes them, and excluding them avoids a large transient memory
# allocation in CLI, test, and MCP entry points alike.
os.environ.setdefault("LANCE_INCLUDE_VECTOR_CENTROIDS", "false")

__version__ = "0.1.0"

__all__ = ["__version__"]
