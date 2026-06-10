"""Database subpackage."""

from ._sql import sql_in_list, sql_str
from .connection import get_connection
from .operations import (
    init_chunks,
    init_mapping,
    init_index_meta,
    insert_chunks,
    delete_chunks_by_paper,
    delete_chunks_by_repo,
    delete_chunks_by_repo_name,
    insert_mappings,
    delete_mappings_by_paper,
    upsert_meta,
    get_meta,
    list_all_meta,
)

__all__ = [
    "get_connection",
    "init_chunks",
    "init_mapping",
    "init_index_meta",
    "insert_chunks",
    "delete_chunks_by_paper",
    "delete_chunks_by_repo",
    "delete_chunks_by_repo_name",
    "insert_mappings",
    "delete_mappings_by_paper",
    "upsert_meta",
    "get_meta",
    "list_all_meta",
    "sql_str",
    "sql_in_list",
]
