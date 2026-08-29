"""LanceDB vector/scalar index lifecycle management.

The production table uses a 1024-dimensional embedding column.  IVF_PQ
reduces query-time work by routing each query to a small subset of partitions,
while ``refine_factor`` re-ranks a wider candidate pool with original vectors.
Scalar indices keep the prefilters used by paper/code search inexpensive.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("mapce.vector_index")

# LanceDB 0.33 otherwise materializes IVF centroids while collecting index
# statistics. They are not needed for coverage reporting and can noticeably
# increase memory use during maintenance/status checks.
os.environ.setdefault("LANCE_INCLUDE_VECTOR_CENTROIDS", "false")

VECTOR_COLUMN = "embedding"
VECTOR_INDEX_NAME = "embedding_ivf_pq"
VECTOR_INDEX_TYPE = "IVF_PQ"
VECTOR_DISTANCE = "l2"

# 88,351 rows / ~4,096 rows per partition ~= 22.  Twenty-four leaves modest
# growth headroom without making each query probe an excessive number of tiny
# partitions.  1024 / 8 = 128 is LanceDB's recommended PQ starting point and
# divides the embedding dimension exactly.
DEFAULT_NUM_PARTITIONS = 24
DEFAULT_NUM_SUB_VECTORS = 128
DEFAULT_NUM_BITS = 8
# A 40-query exact-vs-ANN sweep on the current corpus found 16/8 preserved
# 98.25% of exact top-k candidates and every measured known-item hit, while
# still halving vector-search latency. Lower 6/4 settings kept only 85.75%.
DEFAULT_NPROBES = 16
DEFAULT_REFINE_FACTOR = 8
DEFAULT_MIN_INDEX_ROWS = 4096

SCALAR_INDICES = (
    ("chunk_type", "BITMAP", "chunk_type_bitmap"),
    ("paper_id", "BTREE", "paper_id_btree"),
    ("repo_name", "BTREE", "repo_name_btree"),
    ("repo_url", "BTREE", "repo_url_btree"),
    ("year", "BTREE", "year_btree"),
    ("venue", "BITMAP", "venue_bitmap"),
)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning("Ignoring %s=%d below minimum %d; using %d", name, value, minimum, default)
        return default
    return value


def vector_index_config() -> dict[str, int | str]:
    """Return the effective index-build configuration."""
    return {
        "name": VECTOR_INDEX_NAME,
        "type": VECTOR_INDEX_TYPE,
        "column": VECTOR_COLUMN,
        "distance": VECTOR_DISTANCE,
        "num_partitions": _env_int(
            "MAPCE_VECTOR_NUM_PARTITIONS", DEFAULT_NUM_PARTITIONS
        ),
        "num_sub_vectors": _env_int(
            "MAPCE_VECTOR_NUM_SUB_VECTORS", DEFAULT_NUM_SUB_VECTORS
        ),
        "num_bits": _env_int("MAPCE_VECTOR_NUM_BITS", DEFAULT_NUM_BITS),
    }


def vector_search_config() -> dict[str, int]:
    """Return effective ANN query parameters."""
    return {
        "nprobes": _env_int("MAPCE_VECTOR_NPROBES", DEFAULT_NPROBES),
        "refine_factor": _env_int(
            "MAPCE_VECTOR_REFINE_FACTOR", DEFAULT_REFINE_FACTOR
        ),
    }


def _indices_by_name(table: Any) -> dict[str, Any]:
    return {index.name: index for index in table.list_indices()}


def has_vector_index(table: Any) -> bool:
    """Return whether the embedding column has a completed vector index."""
    return any(
        VECTOR_COLUMN in (getattr(index, "columns", None) or [])
        and str(getattr(index, "index_type", "")).lower() not in {
            "btree", "bitmap", "labellist", "fts"
        }
        for index in table.list_indices()
    )


def index_report(table: Any) -> dict[str, Any]:
    """Return serializable index coverage and configuration information."""
    rows = []
    for index in table.list_indices():
        stats = table.index_stats(index.name)
        rows.append({
            "name": index.name,
            "type": str(index.index_type),
            "columns": list(index.columns),
            "num_indexed_rows": getattr(stats, "num_indexed_rows", None),
            "num_unindexed_rows": getattr(stats, "num_unindexed_rows", None),
            "distance_type": getattr(stats, "distance_type", None),
        })
    return {
        "row_count": table.count_rows(),
        "vector_index_present": has_vector_index(table),
        "build_config": vector_index_config(),
        "search_config": vector_search_config(),
        "indices": rows,
    }


def create_vector_indices(
    table: Any,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Create the IVF_PQ index and all scalar prefilter indices.

    Existing indices are left intact unless ``replace`` is explicitly set.
    This builds auxiliary index files from stored vectors; it never recomputes
    embeddings or rewrites chunk content.
    """
    existing = _indices_by_name(table)
    config = vector_index_config()
    if VECTOR_INDEX_NAME not in existing or replace:
        table.create_index(
            metric=str(config["distance"]),
            vector_column_name=str(config["column"]),
            index_type=str(config["type"]),
            num_partitions=int(config["num_partitions"]),
            num_sub_vectors=int(config["num_sub_vectors"]),
            num_bits=int(config["num_bits"]),
            name=VECTOR_INDEX_NAME,
            replace=replace,
        )

    existing = _indices_by_name(table)
    for column, index_type, name in SCALAR_INDICES:
        if name in existing and not replace:
            continue
        table.create_scalar_index(
            column,
            index_type=index_type,
            name=name,
            replace=replace,
        )
    return index_report(table)


def refresh_vector_indices(table: Any) -> dict[str, Any]:
    """Add appended rows to existing indices when coverage is incomplete."""
    report = index_report(table)
    if not report["vector_index_present"]:
        return report
    if any(
        int(item.get("num_unindexed_rows") or 0) > 0
        for item in report["indices"]
    ):
        table.optimize()
        report = index_report(table)
    return report


def maintain_vector_indices_after_write(table: Any) -> dict[str, Any] | None:
    """Create or refresh indices after a successful chunk append.

    Index maintenance is best-effort: stored paper/code chunks remain valid if
    maintenance fails, and normal LanceDB search still includes unindexed rows.
    Set ``MAPCE_AUTO_VECTOR_INDEX=0`` to disable automatic maintenance.
    """
    if os.environ.get("MAPCE_AUTO_VECTOR_INDEX", "1").lower() in {
        "0", "false", "no", "off"
    }:
        return None
    try:
        row_count = table.count_rows()
        if has_vector_index(table):
            # A partially configured database may have the vector index but be
            # missing one or more scalar prefilter indices. This call is
            # idempotent and creates only the missing pieces.
            create_vector_indices(table, replace=False)
            return refresh_vector_indices(table)
        minimum_rows = _env_int(
            "MAPCE_VECTOR_MIN_ROWS", DEFAULT_MIN_INDEX_ROWS
        )
        if row_count >= minimum_rows:
            return create_vector_indices(table, replace=False)
    except Exception:
        logger.exception(
            "Chunk write succeeded, but automatic vector-index maintenance failed"
        )
    return None


def configure_vector_query(query: Any, *, indexed: bool) -> Any:
    """Apply ANN search parameters only when a vector index is available."""
    if os.environ.get("MAPCE_BYPASS_VECTOR_INDEX", "0").lower() in {
        "1", "true", "yes", "on"
    }:
        return query.bypass_vector_index()
    if not indexed:
        return query
    config = vector_search_config()
    return query.nprobes(config["nprobes"]).refine_factor(
        config["refine_factor"]
    )
