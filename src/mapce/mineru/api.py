"""MinerU API Python wrapper.

Replaces the shell-script-based parse-batch.sh from paper-research-blog
with a pure Python httpx implementation suitable for embedding in the
MCP Server. Preserves the same API logic: get signed URLs → upload →
poll batch → download & unpack zips.
"""

from __future__ import annotations

import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://mineru.net/api/v4"
POLL_INTERVAL = 15  # seconds

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    token = os.environ.get("MINERU_API_TOKEN")
    if not token:
        raise RuntimeError(
            "MINERU_API_TOKEN is not set. "
            "Get your token at https://mineru.net/apiManage/token"
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _client(timeout: float = 120) -> httpx.Client:
    return httpx.Client(timeout=timeout)


# ---------------------------------------------------------------------------
# batch upload flow (for local PDFs)
# ---------------------------------------------------------------------------


def request_batch_upload(
    file_paths: list[Path],
    language: str = "en",
    enable_formula: bool = True,
    enable_table: bool = True,
    model_version: str = "pipeline",
) -> dict[str, Any]:
    """POST /file-urls/batch — get pre-signed S3 URLs and a batch_id.

    Args:
        file_paths: List of local PDF file paths.
        language: "en" or "ch".
        enable_formula: Extract LaTeX formulas.
        enable_table: Extract tables.
        model_version: "pipeline" (default), "vlm", or "MinerU-HTML".

    Returns:
        {"batch_id": str, "file_urls": [str, ...]}  (file_urls[i] ↔ file_paths[i])
    """
    files_payload = [
        {"name": p.name, "data_id": p.stem, "is_ocr": False}
        for p in file_paths
    ]
    body: dict[str, Any] = {
        "files": files_payload,
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    with _client() as client:
        resp = client.post(f"{BASE_URL}/file-urls/batch", json=body, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU batch-url error: {data.get('msg', data)}")
        return data["data"]


def upload_files(file_paths: list[Path], signed_urls: list[str]) -> None:
    """PUT each local file to its corresponding pre-signed S3 URL.

    No auth header — the signature is embedded in the URL.
    """
    if len(file_paths) != len(signed_urls):
        raise ValueError("file_paths and signed_urls must have the same length")

    with _client(timeout=300) as client:
        for path, url in zip(file_paths, signed_urls):
            with open(path, "rb") as f:
                resp = client.put(url, content=f.read())
                resp.raise_for_status()


def poll_batch(batch_id: str, poll_interval: float = POLL_INTERVAL) -> list[dict]:
    """Poll GET /extract-results/batch/{batch_id} until all entries are terminal.

    Returns the full extract_result list.
    """
    TERMINAL = {"done", "failed"}
    with _client() as client:
        while True:
            resp = client.get(
                f"{BASE_URL}/extract-results/batch/{batch_id}",
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"MinerU poll error: {data.get('msg', data)}")
            results = data["data"]["extract_result"]
            states = {r["state"] for r in results}
            if states <= TERMINAL:
                return results
            time.sleep(poll_interval)


def download_and_unpack(result: dict, output_dir: Path) -> Path:
    """Download a single result's full_zip_url and unpack into output_dir/<data_id>/.

    Args:
        result: Single entry from extract_result with "data_id" and "full_zip_url".
        output_dir: Parent directory for unpacked paper directories.

    Returns:
        The unpacked paper directory path.
    """
    zip_url = result.get("full_zip_url")
    data_id = result.get("data_id", "unknown")
    if not zip_url:
        raise RuntimeError(f"No zip_url for {data_id}: state={result.get('state')}")

    paper_dir = output_dir / data_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # Bypass proxy for CDN downloads — SOCKS proxy often breaks TLS
    # to cdn-mineru.openxlab.org.cn. Use a direct transport.
    with httpx.Client(timeout=300, trust_env=False) as client:
        resp = client.get(zip_url)
        resp.raise_for_status()

    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        zf.extractall(paper_dir)

    # Normalize: rename the main .md to match the directory name for consistency
    for f in paper_dir.iterdir():
        if f.suffix == ".md" and f.stem != data_id:
            target = paper_dir / f"{data_id}.md"
            if target.exists():
                target.unlink()
            f.rename(target)
            break

    # Remove redundant files — keep only .md, *_content_list_v2.json, and images/
    _cleanup_mineru_output(paper_dir)

    return paper_dir


def _cleanup_mineru_output(paper_dir: Path) -> None:
    """Remove MinerU output files that are no longer needed after chunking.

    Keeps:
      - <paper_id>.md          (markdown text)
      - *_content_list_v2.json (structured content with table HTML)
      - images/                (figure and table images, referenced by DB)

    Removes:
      - *_origin.pdf           (original PDF, already parsed)
      - layout.json            (bounding boxes, used during chunking only)
      - *_model.json           (model metadata)
      - *_content_list.json    (v1 content list, redundant with v2)
    """
    import fnmatch

    patterns_to_remove = [
        "*_origin.pdf",
        "layout.json",
        "*_model.json",
        "*_content_list.json",       # v1
        # keep *_content_list_v2.json
    ]

    for item in paper_dir.iterdir():
        if item.is_dir():
            continue
        for pat in patterns_to_remove:
            if fnmatch.fnmatch(item.name, pat):
                # Skip v2
                if "v2" in item.name:
                    continue
                item.unlink(missing_ok=True)
                break


# ---------------------------------------------------------------------------
# convenience: end-to-end batch parse
# ---------------------------------------------------------------------------


def batch_parse(
    file_paths: list[Path],
    output_dir: Path,
    language: str = "en",
    enable_formula: bool = True,
    enable_table: bool = True,
    poll_interval: float = POLL_INTERVAL,
    on_progress: Any = None,
) -> list[Path]:
    """End-to-end: upload → poll → download → unpack for a batch of PDFs.

    Args:
        file_paths: Local PDF paths.
        output_dir: Where to create per-paper directories.
        language: "en" or "ch".
        enable_formula: Extract LaTeX formulas.
        enable_table: Extract tables.
        poll_interval: Seconds between status polls.
        on_progress: Optional callback(status_dict) called after each poll.

    Returns:
        List of unpacked paper directory paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Get signed URLs
    batch = request_batch_upload(
        file_paths, language=language,
        enable_formula=enable_formula, enable_table=enable_table,
    )

    # 2. Upload
    upload_files(file_paths, batch["file_urls"])

    # 3. Poll
    results = poll_batch(batch["batch_id"], poll_interval=poll_interval)

    # 4. Download & unpack
    paper_dirs = []
    for result in results:
        if result["state"] == "done":
            paper_dir = download_and_unpack(result, output_dir)
            paper_dirs.append(paper_dir)
        else:
            if on_progress:
                on_progress({
                    "data_id": result.get("data_id"),
                    "state": result["state"],
                    "error": result.get("err_msg"),
                })

    return paper_dirs


# ---------------------------------------------------------------------------
# single-file parse from URL (e.g., arXiv)
# ---------------------------------------------------------------------------


def parse_from_url(
    url: str,
    language: str = "en",
    enable_formula: bool = True,
    enable_table: bool = True,
    model_version: str = "pipeline",
) -> dict:
    """Submit a single parse task from a public URL and poll until done.

    Returns the final task status dict (includes full_zip_url when done).
    """
    body = {
        "url": url,
        "model_version": model_version,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "language": language,
    }
    with _client() as client:
        # submit
        resp = client.post(f"{BASE_URL}/extract/task", json=body, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU task error: {data.get('msg', data)}")
        task_id = data["data"]["task_id"]

        # poll
        while True:
            resp = client.get(
                f"{BASE_URL}/extract/task/{task_id}", headers=_headers()
            )
            resp.raise_for_status()
            task_data = resp.json()
            if task_data.get("code") != 0:
                raise RuntimeError(f"MinerU poll error: {task_data.get('msg', task_data)}")
            state = task_data["data"]
            if state["state"] in ("done", "failed"):
                return state
            time.sleep(POLL_INTERVAL)
