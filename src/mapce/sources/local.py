"""Local PDF data source adapter.

Handles recursively scanning directories for PDF files and batch-indexing them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def scan_pdfs(
    directory: Path,
    recursive: bool = True,
    exclude_dirs: list[str] | None = None,
) -> list[Path]:
    """Scan a directory for PDF files.

    Args:
        directory: Directory to scan.
        recursive: If True, scan subdirectories.
        exclude_dirs: Directory name patterns to skip.

    Returns:
        Sorted list of PDF Paths.
    """
    if exclude_dirs is None:
        exclude_dirs = ["__pycache__", ".git", ".DS_Store", "node_modules"]

    directory = Path(directory).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdfs = []
    if recursive:
        for dirpath_str, dirnames, filenames in directory.walk():
            # Filter excluded dirs in-place
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith(".")]
            dirpath = Path(dirpath_str)
            for fname in filenames:
                if fname.lower().endswith(".pdf"):
                    pdfs.append(dirpath / fname)
    else:
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() == ".pdf":
                pdfs.append(f)

    return sorted(pdfs)


def index_directory(
    directory: Path,
    recursive: bool = True,
    language: str = "en",
    on_progress: Any = None,
) -> list[dict[str, Any]]:
    """Scan and index all PDFs in a directory.

    Args:
        directory: Directory containing PDFs.
        recursive: Scan subdirectories.
        language: Paper language.
        on_progress: Optional progress callback(current, total, path).

    Returns:
        List of {"pdf": str, "paper_id": str|None, "status": str, "error": str|None}.
    """
    from mapce.core.indexing import index_paper
    from mapce.core.incremental import check_duplicate

    pdfs = scan_pdfs(directory, recursive=recursive)
    total = len(pdfs)
    results = []

    for i, pdf_path in enumerate(pdfs):
        if on_progress:
            on_progress(i + 1, total, str(pdf_path))

        try:
            # Check duplicate first
            from mapce.core.indexing import _extract_arxiv_id_from_pdf
            arxiv_id = _extract_arxiv_id_from_pdf(pdf_path)
            is_dup, existing_id = check_duplicate(arxiv_id=arxiv_id)

            if is_dup:
                results.append({
                    "pdf": str(pdf_path),
                    "paper_id": existing_id,
                    "status": "skipped",
                    "error": "duplicate",
                })
                continue

            paper_id = index_paper(pdf_path=pdf_path, language=language)
            results.append({
                "pdf": str(pdf_path),
                "paper_id": paper_id,
                "status": "ok",
                "error": None,
            })
        except Exception as e:
            results.append({
                "pdf": str(pdf_path),
                "paper_id": None,
                "status": "failed",
                "error": str(e),
            })

    return results
