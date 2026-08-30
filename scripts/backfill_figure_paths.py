"""Backfill missing figure_path / table_image on figure & table chunks.

Most papers were indexed by an earlier figure-linking version and stored
figure/table chunks with an empty image path, even though MinerU's images and
the markdown/content_list references are still on disk. This re-runs the current
extractor against each paper's on-disk MinerU output and fills the missing image
paths in the DB. No PDF re-parsing, no re-embedding (existing embeddings and all
other fields are preserved; only figure_path/table_image are set).

Usage:
    python scripts/backfill_figure_paths.py            # dry-run: report only
    python scripts/backfill_figure_paths.py --apply     # write the paths

Tip: back up first with  cp -r ~/.mapce/data ~/.mapce/data.bak
"""

import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_dotenv = Path(__file__).resolve().parents[1] / ".env"
if _dotenv.exists():
    load_dotenv(_dotenv)


def _resolve(paper_dir: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    return ref if ref.startswith("/") else str(paper_dir / ref)


def _maps_for_paper(paper_dir: Path):
    """Return (fig_by_index, tbl_by_index) image-path maps from on-disk output."""
    from mapce.mineru.parser import MinerUOutput

    m = MinerUOutput(paper_dir)
    fig_by_index: dict[int, str] = {}
    tbl_by_index: dict[int, str] = {}
    try:
        ft = m.extract_figures_and_tables()
    except Exception:
        ft = {"figures": [], "tables": []}
    for f in ft.get("figures", []):
        if f.get("image_ref") and f.get("index") is not None:
            fig_by_index.setdefault(int(f["index"]), _resolve(paper_dir, f["image_ref"]))
    # Tables: prefer content_list image_source, fall back to markdown image_ref
    try:
        td = m.extract_table_data()
    except Exception:
        td = {}
    for idx, data in td.items():
        p = _resolve(paper_dir, data.get("image_path"))
        if p:
            tbl_by_index.setdefault(int(idx), p)
    for t in ft.get("tables", []):
        if t.get("image_ref") and t.get("index") is not None:
            tbl_by_index.setdefault(int(t["index"]), _resolve(paper_dir, t["image_ref"]))
    return fig_by_index, tbl_by_index


def main(apply: bool) -> None:
    from mapce.db import get_connection, init_chunks, sql_str
    from mapce.db.connection import _get_data_dir
    from mapce.service.runtime import assert_database_write_allowed

    if apply:
        assert_database_write_allowed()

    db = get_connection()
    table = init_chunks(db)
    papers_dir = _get_data_dir() / "papers"

    arrow = table.to_arrow()
    ct = arrow.column("chunk_type").to_pylist()
    pid = arrow.column("paper_id").to_pylist()
    fp = arrow.column("figure_path").to_pylist()
    ti = arrow.column("table_image").to_pylist()

    # Papers that have at least one figure/table chunk missing its image path
    target_papers = sorted({
        pid[i] for i, c in enumerate(ct)
        if (c == "figure" and not fp[i]) or (c == "table" and not ti[i])
    })

    fig_fixed = tbl_fixed = 0
    no_dir = 0
    per_paper: list[tuple[str, int, int]] = []

    for p in target_papers:
        pdir = papers_dir / p
        if not pdir.exists():
            no_dir += 1
            continue
        fig_map, tbl_map = _maps_for_paper(pdir)
        if not fig_map and not tbl_map:
            continue

        rows = (
            table.search()
            .where(f"paper_id = {sql_str(p)} AND chunk_type IN ('figure', 'table')")
            .limit(100000)
            .to_list()
        )
        updated = []
        pf = pt = 0
        for r in rows:
            r.pop("_distance", None)
            if r["chunk_type"] == "figure" and not r.get("figure_path"):
                # figure_index is None on legacy chunks; parse the figure number
                # from section_path ("Figure N"), same as tables.
                m = re.search(r"Figure\s*(\d+)", r.get("section_path") or "")
                new = fig_map.get(int(m.group(1))) if m else None
                if new:
                    r["figure_path"] = new
                    updated.append(r)
                    pf += 1
            elif r["chunk_type"] == "table" and not r.get("table_image"):
                m = re.search(r"Table\s*(\d+)", r.get("section_path") or "")
                new = tbl_map.get(int(m.group(1))) if m else None
                if new:
                    r["table_image"] = new
                    updated.append(r)
                    pt += 1

        if updated:
            per_paper.append((p, pf, pt))
            fig_fixed += pf
            tbl_fixed += pt
            if apply:
                for r in updated:
                    table.delete(f"chunk_id = {sql_str(r['chunk_id'])}")
                table.add(updated)

    print("=== Figure/table image-path backfill ===")
    print(f"Target papers (missing some image path): {len(target_papers)}")
    print(f"Papers with no on-disk dir (skipped):    {no_dir}")
    print(f"Papers updated:                          {len(per_paper)}")
    print(f"Figure paths {'set' if apply else 'recoverable'}: {fig_fixed}")
    print(f"Table images {'set' if apply else 'recoverable'}: {tbl_fixed}")
    if not apply:
        print("\n[dry-run] No changes made. Re-run with --apply to write the paths.")
    else:
        print("\n[apply] Done. Re-run check_01 (D6) or get_paper_overview to confirm.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
