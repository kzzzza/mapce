"""Shared helpers for MAPCE index quality tests.

Read-only utilities: DB access, threshold grading, and JSON/CSV writers.
No third-party deps beyond what mapce already requires (pyarrow). pandas is
deliberately avoided (not a project dependency).
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Sequence

TESTS_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = TESTS_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# DB access (read-only)
# ---------------------------------------------------------------------------

def get_db():
    from mapce.db import get_connection
    return get_connection()


def load_chunks_arrow():
    """Load the full chunks table as a pyarrow Table (read-only)."""
    from mapce.db import init_chunks
    return init_chunks(get_db()).to_arrow()


def load_meta() -> list[dict]:
    """Load all non-deleted index_meta rows (read-only)."""
    from mapce.db import init_index_meta, list_all_meta
    return list_all_meta(init_index_meta(get_db()))


def count_mapping_rows() -> int:
    from mapce.db.operations import init_mapping
    return init_mapping(get_db()).count_rows()


def col(tbl, name: str) -> list:
    """Return a column from a pyarrow Table as a python list."""
    return tbl.column(name).to_pylist()


# ---------------------------------------------------------------------------
# Threshold grading
# ---------------------------------------------------------------------------

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def grade(value: float, pass_at: float, warn_at: float, higher_is_better: bool = True) -> str:
    """Grade a metric into PASS/WARN/FAIL.

    higher_is_better=True : value >= pass_at -> PASS, >= warn_at -> WARN, else FAIL
    higher_is_better=False: value <= pass_at -> PASS, <= warn_at -> WARN, else FAIL
    """
    if higher_is_better:
        if value >= pass_at:
            return PASS
        if value >= warn_at:
            return WARN
        return FAIL
    else:
        if value <= pass_at:
            return PASS
        if value <= warn_at:
            return WARN
        return FAIL


def worst(grades: Sequence[str]) -> str:
    order = {PASS: 0, WARN: 1, FAIL: 2}
    if not grades:
        return PASS
    return max(grades, key=lambda g: order.get(g, 0))


def check(name: str, metrics: dict[str, Any], status: str, note: str = "") -> dict:
    """Build a standard check-result record and print a one-line summary."""
    icon = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌"}.get(status, "  ")
    print(f"  {icon} [{status}] {name}" + (f" — {note}" if note else ""))
    return {"name": name, "status": status, "metrics": metrics, "note": note}


# ---------------------------------------------------------------------------
# Metrics helpers (no numpy dependency required for the simple ones)
# ---------------------------------------------------------------------------

def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Fraction of queries whose gold item appears within top-k (1-indexed rank)."""
    if not ranks:
        return 0.0
    hit = sum(1 for r in ranks if r is not None and r <= k)
    return hit / len(ranks)


def mrr(ranks: list[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum((1.0 / r) if r else 0.0 for r in ranks) / len(ranks)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[idx]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_json(filename: str, data: dict) -> Path:
    path = OUTPUTS_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_csv(filename: str, rows: list[dict], fieldnames: list[str] | None = None) -> Path:
    path = OUTPUTS_DIR / filename
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fieldnames = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    return path


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t0
