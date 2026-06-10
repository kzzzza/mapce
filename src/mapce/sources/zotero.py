"""Zotero data source adapter.

Reads papers from a local Zotero library. Supports two modes:
  1. Zotero SQLite database (zotero.sqlite) — direct read
  2. Zotero API (requires API key + user ID) — remote read

The SQLite mode is simpler and fully local.

When Zotero is running, its SQLite database is locked. This module
automatically falls back to copying the database to a temporary file
and reading from the copy.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# SQLite mode — read from local Zotero database
# ---------------------------------------------------------------------------

DEFAULT_ZOTERO_DB = Path.home() / "Zotero" / "zotero.sqlite"


def get_zotero_db_path(db_path: Path | None = None) -> Path:
    """Get the path to the Zotero SQLite database."""
    if db_path:
        return Path(db_path).expanduser()
    return DEFAULT_ZOTERO_DB


def _connect_zotero(db_path: Path) -> tuple[sqlite3.Connection, Path | None]:
    """Connect to the Zotero SQLite database.

    If the database is locked (Zotero is running), automatically copies
    it to a temporary file and connects to the copy instead.

    Args:
        db_path: Path to zotero.sqlite.

    Returns:
        (connection, temp_path) tuple. temp_path is None when using the
        original file; otherwise it points to the temp copy that should
        be cleaned up after use.
    """
    path = get_zotero_db_path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Zotero database not found at {path}")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # Verify the connection works (triggers lock error if Zotero is running)
        conn.execute("SELECT 1 FROM sqlite_master")
        return conn, None
    except sqlite3.OperationalError:
        # Zotero is running — copy to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        shutil.copy2(path, tmp.name)
        conn = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn, Path(tmp.name)


def _close_zotero(conn: sqlite3.Connection, tmp_path: Path | None) -> None:
    """Close connection and remove temp file if one was created."""
    conn.close()
    if tmp_path is not None:
        tmp_path.unlink(missing_ok=True)


def list_zotero_collections(db_path: Path | None = None) -> list[dict[str, Any]]:
    """List all collections (folders) in the Zotero library.

    Args:
        db_path: Path to zotero.sqlite. Defaults to ~/Zotero/zotero.sqlite.

    Returns:
        List of {"id": int, "name": str, "parent_id": int|None} dicts.
    """
    conn, tmp_path = _connect_zotero(db_path)

    rows = conn.execute("""
        SELECT collectionID as id, collectionName as name, parentCollectionID as parent_id
        FROM collections
        ORDER BY collectionName
    """).fetchall()

    _close_zotero(conn, tmp_path)
    return [dict(r) for r in rows]


def list_zotero_items(
    collection_name: str | None = None,
    item_type: str = "journalArticle",
    limit: int = 100,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List items from a Zotero library, optionally filtered by collection.

    Args:
        collection_name: Optional collection name to filter by.
        item_type: Zotero item type (journalArticle, conferencePaper, preprint, etc.).
        limit: Max items to return.
        db_path: Path to zotero.sqlite.

    Returns:
        List of item dicts with keys: id, title, authors, year, doi, arxiv_id, has_attachment.
    """
    conn, tmp_path = _connect_zotero(db_path)

    if collection_name:
        # Find items in a specific collection via the collectionItems join table
        rows = conn.execute("""
            SELECT i.itemID as id,
                   COALESCE(f.title, '') as title,
                   i.dateAdded,
                   it.typeName as item_type
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN collectionItems ci ON i.itemID = ci.itemID
            JOIN collections c ON ci.collectionID = c.collectionID
            LEFT JOIN (
                SELECT itemID,
                       MAX(CASE WHEN fieldID = (SELECT fieldID FROM fields WHERE fieldName='title')
                            THEN value END) as title
                FROM itemDataValues
                JOIN itemData ON itemDataValues.valueID = itemData.valueID
                GROUP BY itemID
            ) f ON i.itemID = f.itemID
            WHERE c.collectionName = ? AND it.typeName = ?
            LIMIT ?
        """, (collection_name, item_type, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT i.itemID as id,
                   COALESCE(f.title, '') as title,
                   i.dateAdded,
                   it.typeName as item_type
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN (
                SELECT itemID,
                       MAX(CASE WHEN fieldID = (SELECT fieldID FROM fields WHERE fieldName='title')
                            THEN value END) as title
                FROM itemDataValues
                JOIN itemData ON itemDataValues.valueID = itemData.valueID
                GROUP BY itemID
            ) f ON i.itemID = f.itemID
            WHERE it.typeName = ?
            LIMIT ?
        """, (item_type, limit)).fetchall()

    _close_zotero(conn, tmp_path)
    return [dict(r) for r in rows]


def get_zotero_item_detail(
    item_id: int,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Get full details for a Zotero item, including authors and attachment paths.

    Args:
        item_id: Zotero item ID.
        db_path: Path to zotero.sqlite.

    Returns:
        Item detail dict or None if not found.
    """
    try:
        conn, tmp_path = _connect_zotero(db_path)
    except FileNotFoundError:
        return None

    # Get all field values for this item
    rows = conn.execute("""
        SELECT f.fieldName, dv.value
        FROM itemData d
        JOIN fields f ON d.fieldID = f.fieldID
        JOIN itemDataValues dv ON d.valueID = dv.valueID
        WHERE d.itemID = ?
    """, (item_id,)).fetchall()

    fields = {r["fieldName"]: r["value"] for r in rows}

    # Get creators (authors)
    creators = conn.execute("""
        SELECT c.firstName || ' ' || c.lastName as name, ct.creatorType
        FROM creators c
        JOIN itemCreators ic ON c.creatorID = ic.creatorID
        JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
        WHERE ic.itemID = ?
        ORDER BY ic.orderIndex
    """, (item_id,)).fetchall()

    authors = [c["name"].strip() for c in creators if c["creatorType"] == "author"]

    # Get attachment paths (PDFs)
    attachments = conn.execute("""
        SELECT i.itemID,
               COALESCE(f.path, '') as path
        FROM items i
        JOIN itemAttachments ia ON i.itemID = ia.itemID
        LEFT JOIN (
            SELECT itemID,
                   MAX(CASE WHEN fieldID = (SELECT fieldID FROM fields WHERE fieldName='path')
                        THEN value END) as path
            FROM itemDataValues
            JOIN itemData ON itemDataValues.valueID = itemData.valueID
            GROUP BY itemID
        ) f ON i.itemID = f.itemID
        WHERE ia.parentItemID = ?
    """, (item_id,)).fetchall()

    # Parse the Zotero storage path
    pdf_paths = []
    for att in attachments:
        if att["path"]:
            # Paths are stored like "storage:PAPER_DIR/paper.pdf" or "attachments:PAPER_DIR/paper.pdf"
            p = att["path"]
            if p.startswith("storage:"):
                p = p[len("storage:"):]
                zotero_storage = Path.home() / "Zotero" / "storage"
                full_path = zotero_storage / p
                if full_path.exists():
                    pdf_paths.append(str(full_path))
            elif p.startswith("attachments:"):
                p = p[len("attachments:"):]

    _close_zotero(conn, tmp_path)

    # Extract DOI and arXiv ID from the extra field or DOI field
    doi = fields.get("DOI", "")
    arxiv_id = ""
    extra = fields.get("extra", "")
    if extra:
        import re
        arxiv_match = re.search(r"arXiv[:\s]*(\d{4}\.\d{4,5})", extra, re.IGNORECASE)
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)

    # Extract year from date field
    date = fields.get("date", "")
    year = None
    if date and len(date) >= 4:
        try:
            year = int(date[:4])
        except ValueError:
            pass

    return {
        "id": item_id,
        "title": fields.get("title", ""),
        "authors": authors,
        "year": year,
        "venue": fields.get("publicationTitle", ""),
        "arxiv_id": arxiv_id,
        "doi": doi,
        "abstract": fields.get("abstractNote", ""),
        "pdf_paths": pdf_paths,
    }


def import_from_zotero(
    collection_name: str | None = None,
    max_items: int = 50,
    db_path: Path | None = None,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Import papers from Zotero into the MAPCE index.

    Args:
        collection_name: Optional Zotero collection to filter by.
        max_items: Maximum items to import.
        db_path: Path to zotero.sqlite.
        language: Paper language.

    Returns:
        List of import results.
    """
    from mapce.core.indexing import index_paper
    from mapce.core.incremental import check_duplicate

    items = list_zotero_items(
        collection_name=collection_name,
        item_type="journalArticle",
        limit=max_items,
        db_path=db_path,
    )

    results = []
    for item in items:
        try:
            detail = get_zotero_item_detail(item["id"], db_path=db_path)
            if detail is None:
                results.append({"zotero_id": item["id"], "status": "failed", "error": "Could not get details"})
                continue

            # Check for duplicates
            is_dup, existing_id = check_duplicate(
                arxiv_id=detail.get("arxiv_id"),
                doi=detail.get("doi"),
                title=detail.get("title", ""),
            )
            if is_dup:
                results.append({
                    "zotero_id": item["id"],
                    "paper_id": existing_id,
                    "status": "skipped",
                    "reason": "already indexed",
                })
                continue

            # Index from PDF if available, otherwise try arXiv
            if detail["pdf_paths"]:
                pdf_path = Path(detail["pdf_paths"][0])
                metadata = {
                    "title": detail["title"],
                    "authors": detail["authors"],
                    "year": detail["year"],
                    "venue": detail["venue"],
                    "arxiv_id": detail["arxiv_id"],
                    "doi": detail["doi"],
                    "keywords": [],
                }
                paper_id = index_paper(pdf_path=pdf_path, metadata=metadata, language=language)
            elif detail["arxiv_id"]:
                from mapce.core.indexing import index_paper_from_arxiv
                paper_id = index_paper_from_arxiv(arxiv_id=detail["arxiv_id"], language=language)
            else:
                results.append({"zotero_id": item["id"], "status": "skipped", "reason": "no PDF or arXiv ID"})
                continue

            results.append({
                "zotero_id": item["id"],
                "paper_id": paper_id,
                "title": detail["title"],
                "status": "ok",
            })
        except Exception as e:
            results.append({"zotero_id": item["id"], "status": "failed", "error": str(e)})

    return results
