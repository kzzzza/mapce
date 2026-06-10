"""Helpers for safely constructing LanceDB SQL filter strings.

LanceDB's Python API takes WHERE clauses as raw strings, so any value
interpolated into one must be escaped. ``sql_str`` produces a single-quoted
SQL string literal with embedded quotes doubled (the SQL-standard escape),
which both prevents broken queries on values containing apostrophes and
closes the injection surface.
"""

from __future__ import annotations

from typing import Iterable


def sql_str(value: object) -> str:
    """Return a safe single-quoted SQL string literal for ``value``.

    Embedded single quotes are doubled per the SQL standard, e.g.
    ``sql_str("O'Reilly") == "'O''Reilly'"``.
    """
    return "'" + str(value).replace("'", "''") + "'"


def sql_in_list(values: Iterable[object]) -> str:
    """Return a comma-separated list of escaped literals for an ``IN (...)`` clause."""
    return ", ".join(sql_str(v) for v in values)
