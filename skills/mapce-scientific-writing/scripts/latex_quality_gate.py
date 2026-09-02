#!/usr/bin/env python3
"""Compile, preflight, render, and record visual QA for LaTeX manuscripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_VISUAL_ATTEMPTS = 3  # Initial inspection plus two repair-and-recheck cycles.
DEFAULT_OVERFULL_TOLERANCE_PT = 2.0
OVERFULL_RE = re.compile(
    r"Overfull \\([hv])box \(([0-9]+(?:\.[0-9]+)?)pt too (wide|high)\)",
    re.IGNORECASE,
)
UNRESOLVED_RE = re.compile(
    r"(?:Citation [`'].+?[`'] on page .+? undefined|"
    r"Reference [`'].+?[`'] on page .+? undefined|"
    r"There were undefined references|"
    r"There were undefined citations)",
    re.IGNORECASE,
)
LAYOUT_ENVIRONMENTS = (
    "table",
    "table*",
    "figure",
    "figure*",
    "longtable",
    "tabular",
    "tabular*",
    "tabularx",
)
INCLUDE_GRAPHICS_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", re.DOTALL
)
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
GRAPHICSPATH_RE = re.compile(r"\\graphicspath\{((?:\{[^{}]*\})+)\}")
GRAPHIC_DIR_RE = re.compile(r"\{([^{}]*)\}")
GRAPHIC_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_latex_log(
    text: str,
    *,
    overfull_tolerance_pt: float = DEFAULT_OVERFULL_TOLERANCE_PT,
) -> dict[str, Any]:
    overfull = [
        {
            "box": match.group(1).lower(),
            "amount_pt": float(match.group(2)),
            "direction": match.group(3).lower(),
            "message": match.group(0),
        }
        for match in OVERFULL_RE.finditer(text)
    ]
    failures = [item for item in overfull if item["amount_pt"] > overfull_tolerance_pt]
    unresolved = sorted({match.group(0) for match in UNRESOLVED_RE.finditer(text)})
    return {
        "status": "failed" if failures or unresolved else "passed",
        "overfull_tolerance_pt": overfull_tolerance_pt,
        "overfull": overfull,
        "overfull_failures": failures,
        "unresolved_references": unresolved,
    }


def _resolve_dependency(
    base_dir: Path,
    name: str,
    extensions: tuple[str, ...],
) -> Path | None:
    candidate = (base_dir / name).resolve()
    candidates = [candidate]
    if not candidate.suffix:
        candidates.extend(candidate.with_suffix(extension) for extension in extensions)
    return next((path for path in candidates if path.is_file()), None)


def _layout_parts(
    tex_source: str,
    *,
    base_dir: Path | None,
    seen: set[Path],
) -> list[str]:
    parts: list[str] = []
    graphic_dirs = [base_dir] if base_dir is not None else []
    if base_dir is not None:
        for path_group in GRAPHICSPATH_RE.findall(tex_source):
            graphic_dirs.extend(
                (base_dir / value).resolve()
                for value in GRAPHIC_DIR_RE.findall(path_group)
            )
    for environment in LAYOUT_ENVIRONMENTS:
        escaped = re.escape(environment)
        pattern = re.compile(
            rf"\\begin\{{{escaped}\}}.*?\\end\{{{escaped}\}}",
            re.DOTALL,
        )
        parts.extend(match.group(0) for match in pattern.finditer(tex_source))
    for match in INCLUDE_GRAPHICS_RE.finditer(tex_source):
        part = match.group(0)
        if base_dir is not None:
            dependency = next(
                (
                    resolved
                    for directory in graphic_dirs
                    if directory is not None
                    for resolved in [
                        _resolve_dependency(directory, match.group(1), GRAPHIC_EXTENSIONS)
                    ]
                    if resolved is not None
                ),
                None,
            )
            if dependency is not None:
                part += f":sha256={sha256_file(dependency)}"
        parts.append(part)
    if base_dir is not None:
        for match in INPUT_RE.finditer(tex_source):
            dependency = _resolve_dependency(base_dir, match.group(1), (".tex",))
            if dependency is None or dependency in seen:
                continue
            seen.add(dependency)
            nested = _layout_parts(
                dependency.read_text(encoding="utf-8", errors="replace"),
                base_dir=dependency.parent,
                seen=seen,
            )
            if nested:
                parts.append(
                    f"input={dependency}:sha256={_sha256_bytes(chr(10).join(nested).encode('utf-8'))}"
                )
    return parts


def layout_signature(
    tex_source: str,
    *,
    base_dir: Path | None = None,
) -> tuple[str, bool]:
    parts = _layout_parts(tex_source, base_dir=base_dir, seen=set())
    normalized = "\n".join(parts).encode("utf-8")
    return _sha256_bytes(normalized), bool(parts)


def visual_reasons(
    *,
    final: bool,
    force_visual: bool,
    page_count: int,
    table_figure_signature: str,
    has_layout_content: bool,
    last_approved: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if final:
        reasons.append("final_delivery")
    if force_visual:
        reasons.append("explicit_visual_request")
    if has_layout_content and not last_approved:
        reasons.append("new_tables_or_figures")
    elif last_approved and table_figure_signature != str(
        last_approved.get("table_figure_signature") or ""
    ):
        reasons.append("tables_or_figures_changed")
    previous_pages = (last_approved or {}).get("page_count")
    if previous_pages is not None and int(previous_pages) != page_count:
        reasons.append("page_count_changed")
    return list(dict.fromkeys(reasons))


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return payload if isinstance(payload, dict) else default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _document_paths(workspace: Path, tex: Path) -> dict[str, Path]:
    workspace = workspace.expanduser().resolve()
    tex = tex.expanduser()
    if not tex.is_absolute():
        tex = workspace / tex
    tex = tex.resolve()
    try:
        relative = tex.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("LaTeX source must be inside the research workspace") from exc
    key = f"{tex.stem}-{hashlib.sha256(relative.as_posix().encode()).hexdigest()[:10]}"
    qa_root = workspace / "build/latex-quality" / key
    return {
        "workspace": workspace,
        "tex": tex,
        "qa_root": qa_root,
        "compile_dir": qa_root / "compile",
        "pages_dir": qa_root / "pages",
        "report": qa_root / "report.json",
        "state": qa_root / "state.json",
        "output_pdf": tex.with_suffix(".pdf"),
        "qa_record": tex.with_suffix(".layout-qa.json"),
    }


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 240,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )


def _page_count(pdf: Path) -> int:
    executable = shutil.which("pdfinfo")
    if not executable:
        raise RuntimeError("pdfinfo is required for PDF page-count validation")
    result = _run([executable, str(pdf)], cwd=pdf.parent)
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, re.MULTILINE)
    if result.returncode != 0 or not match:
        raise RuntimeError("pdfinfo could not determine the PDF page count")
    return int(match.group(1))


def _render_pages(pdf: Path, pages_dir: Path, *, dpi: int, page_count: int) -> list[str]:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("pdftoppm is required for visual layout review")
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("page-*.png"):
        old.unlink()
    rendered: list[str] = []
    for page in range(1, page_count + 1):
        prefix = pages_dir / f"page-{page:04d}"
        result = _run(
            [
                executable,
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                str(pdf),
                str(prefix),
            ],
            cwd=pages_dir,
        )
        image = prefix.with_suffix(".png")
        if result.returncode != 0 or not image.is_file():
            raise RuntimeError(f"failed to render PDF page {page}")
        rendered.append(str(image))
    return rendered


def build_document(
    workspace: Path,
    tex: Path,
    *,
    final: bool = False,
    force_visual: bool = False,
    overfull_tolerance_pt: float = DEFAULT_OVERFULL_TOLERANCE_PT,
    dpi: int = 144,
) -> dict[str, Any]:
    paths = _document_paths(workspace, tex)
    source = paths["tex"]
    if not source.is_file():
        raise FileNotFoundError(f"LaTeX source not found: {source}")
    latexmk = shutil.which("latexmk")
    if not latexmk:
        raise RuntimeError("latexmk is required for deterministic LaTeX compilation")

    compile_dir = paths["compile_dir"]
    compile_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = _run(
        [
            latexmk,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={compile_dir}",
            source.name,
        ],
        cwd=source.parent,
    )
    elapsed = round(time.monotonic() - started, 3)
    log_path = compile_dir / f"{source.stem}.log"
    candidate_pdf = compile_dir / f"{source.stem}.pdf"
    log_text = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.is_file()
        else ""
    )
    log_check = parse_latex_log(
        log_text,
        overfull_tolerance_pt=overfull_tolerance_pt,
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "generated_at": _now(),
        "compile": {
            "command": "latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error",
            "returncode": result.returncode,
            "duration_seconds": elapsed,
            "log": str(log_path),
            "candidate_pdf": str(candidate_pdf),
            "log_tail": result.stdout[-4000:],
        },
        "log_check": log_check,
    }
    if result.returncode != 0 or not candidate_pdf.is_file() or not log_path.is_file():
        report["status"] = "compile_failed"
        _write_json(paths["report"], report)
        return report
    if log_check["status"] != "passed":
        report["status"] = "preflight_failed"
        _write_json(paths["report"], report)
        return report

    page_count = _page_count(candidate_pdf)
    signature, has_layout_content = layout_signature(
        source.read_text(encoding="utf-8"),
        base_dir=source.parent,
    )
    state = _read_json(paths["state"], {"schema_version": 1, "visual_failures": 0})
    reasons = visual_reasons(
        final=final,
        force_visual=force_visual,
        page_count=page_count,
        table_figure_signature=signature,
        has_layout_content=has_layout_content,
        last_approved=state.get("last_approved"),
    )
    report.update(
        {
            "page_count": page_count,
            "table_figure_signature": signature,
            "has_layout_content": has_layout_content,
        }
    )
    if not reasons:
        report["status"] = "preflight_passed"
        report["visual_review"] = {"status": "not_required", "reasons": []}
        _write_json(paths["report"], report)
        return report

    failures = int(state.get("visual_failures") or 0)
    if failures >= MAX_VISUAL_ATTEMPTS:
        report["status"] = "repair_limit_reached"
        report["visual_review"] = {
            "status": "blocked",
            "reasons": reasons,
            "attempt": failures,
            "max_attempts": MAX_VISUAL_ATTEMPTS,
        }
        _write_json(paths["report"], report)
        return report
    rendered = _render_pages(
        candidate_pdf,
        paths["pages_dir"],
        dpi=dpi,
        page_count=page_count,
    )
    report["status"] = "visual_pending"
    report["visual_review"] = {
        "status": "pending",
        "reasons": reasons,
        "attempt": failures + 1,
        "max_attempts": MAX_VISUAL_ATTEMPTS,
        "dpi": dpi,
        "pages": rendered,
    }
    _write_json(paths["report"], report)
    return report


def record_visual_review(
    workspace: Path,
    tex: Path,
    *,
    result: str,
    reviewed_pages: str,
    issues: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    paths = _document_paths(workspace, tex)
    report = _read_json(paths["report"], {})
    if report.get("status") != "visual_pending":
        raise ValueError("current LaTeX build is not awaiting visual review")
    if reviewed_pages.strip().lower() != "all":
        raise ValueError(
            "visual review must inspect every rendered page; use --reviewed-pages all"
        )
    issues = [value.strip() for value in (issues or []) if value.strip()]
    attempt = int(report.get("visual_review", {}).get("attempt") or 1)
    state = _read_json(paths["state"], {"schema_version": 1, "visual_failures": 0})
    candidate_pdf = Path(report["compile"]["candidate_pdf"])
    source = paths["tex"]
    rendered_pages = [
        Path(value)
        for value in report.get("visual_review", {}).get("pages", [])
    ]
    if len(rendered_pages) != int(report.get("page_count") or 0) or any(
        not page.is_file() for page in rendered_pages
    ):
        raise FileNotFoundError("the complete rendered page set is missing")

    if result == "fail":
        if not issues:
            raise ValueError("a failed visual review must record at least one issue")
        state["visual_failures"] = attempt
        state["last_failed_at"] = _now()
        _write_json(paths["state"], state)
        report["status"] = "visual_failed"
        report["visual_review"].update(
            {
                "status": "failed",
                "reviewed_pages": "all",
                "issues": issues,
                "notes": notes,
                "automatic_repair_rounds_remaining": max(
                    0, MAX_VISUAL_ATTEMPTS - attempt
                ),
            }
        )
        _write_json(paths["report"], report)
        return report

    if result != "pass":
        raise ValueError("result must be 'pass' or 'fail'")
    if issues:
        raise ValueError("a passed visual review cannot retain unresolved layout issues")
    if not candidate_pdf.is_file():
        raise FileNotFoundError("compiled candidate PDF is missing")
    paths["output_pdf"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_pdf, paths["output_pdf"])
    approved_at = _now()
    qa_record = {
        "schema_version": 1,
        "status": "layout_approved",
        "approved_at": approved_at,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "pdf": str(paths["output_pdf"]),
        "pdf_sha256": sha256_file(paths["output_pdf"]),
        "page_count": int(report["page_count"]),
        "overfull_tolerance_pt": report["log_check"]["overfull_tolerance_pt"],
        "visual_review": {
            "reviewed_pages": "all",
            "attempt": attempt,
            "issues": issues,
            "notes": notes,
            "rendered_page_sha256": [sha256_file(page) for page in rendered_pages],
        },
    }
    _write_json(paths["qa_record"], qa_record)
    state.update(
        {
            "schema_version": 1,
            "visual_failures": 0,
            "last_approved": {
                "approved_at": approved_at,
                "source_sha256": qa_record["source_sha256"],
                "pdf_sha256": qa_record["pdf_sha256"],
                "page_count": qa_record["page_count"],
                "table_figure_signature": report["table_figure_signature"],
            },
        }
    )
    _write_json(paths["state"], state)
    report["status"] = "layout_approved"
    report["visual_review"].update(
        {
            "status": "passed",
            "reviewed_pages": "all",
            "issues": issues,
            "notes": notes,
            "qa_record": str(paths["qa_record"]),
            "output_pdf": str(paths["output_pdf"]),
        }
    )
    _write_json(paths["report"], report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--workspace", required=True, type=Path)
    build.add_argument("--tex", required=True, type=Path)
    build.add_argument("--final", action="store_true")
    build.add_argument("--force-visual", action="store_true")
    build.add_argument(
        "--overfull-tolerance-pt",
        type=float,
        default=DEFAULT_OVERFULL_TOLERANCE_PT,
    )
    build.add_argument("--dpi", type=int, default=144)

    review = subparsers.add_parser("review")
    review.add_argument("--workspace", required=True, type=Path)
    review.add_argument("--tex", required=True, type=Path)
    review.add_argument("--result", required=True, choices=("pass", "fail"))
    review.add_argument("--reviewed-pages", required=True)
    review.add_argument("--issue", action="append", default=[])
    review.add_argument("--notes", default="")
    args = parser.parse_args()

    try:
        if args.command == "build":
            payload = build_document(
                args.workspace,
                args.tex,
                final=args.final,
                force_visual=args.force_visual,
                overfull_tolerance_pt=args.overfull_tolerance_pt,
                dpi=args.dpi,
            )
            failed = payload["status"] in {
                "compile_failed",
                "preflight_failed",
                "repair_limit_reached",
            }
        else:
            payload = record_visual_review(
                args.workspace,
                args.tex,
                result=args.result,
                reviewed_pages=args.reviewed_pages,
                issues=args.issue,
                notes=args.notes,
            )
            failed = payload["status"] == "visual_failed"
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        payload = {"status": "error", "error": str(exc)}
        failed = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
