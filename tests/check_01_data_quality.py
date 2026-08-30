"""check_01 — MAPCE 索引数据质量静态检查 (D1–D8).

只读分析 chunks / index_meta / paper_code_repos / paper_code_mapping，不加载嵌入模型。
每项给出 PASS/WARN/FAIL 判定，问题明细写到 outputs/*.csv。

运行: uv run --env-file .env python tests/check_01_data_quality.py
"""

from __future__ import annotations

import collections

import common as C


def _is_bad_title(title: str, paper_id: str, arxiv_id: str | None) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if t == paper_id:
        return True
    if arxiv_id and t == arxiv_id:
        return True
    # pure-number arxiv-id-as-title, e.g. "2104.02180"
    if t.replace(".", "").isdigit():
        return True
    return False


def run() -> dict:
    print("\n=== check_01 数据质量 (D1–D8) ===")
    tbl = C.load_chunks_arrow([
        "chunk_type", "source_type", "paper_id", "content", "chunk_id",
        "embedding", "title", "year", "venue", "authors", "arxiv_id",
        "symbol_name", "signature", "calls", "called_by",
        "associated_test", "figure_path",
    ])
    meta = C.load_meta()
    n_papers = len(meta)
    n_chunks = tbl.num_rows

    chunk_type = C.col(tbl, "chunk_type")
    source_type = C.col(tbl, "source_type")
    paper_id = C.col(tbl, "paper_id")
    content = C.col(tbl, "content")
    chunk_id = C.col(tbl, "chunk_id")
    # Keep embeddings in Arrow's compact float32 buffers. Converting the whole
    # 88k x 1024 column with ``to_pylist`` creates tens of millions of Python
    # float objects and can multiply memory usage by an order of magnitude.
    embedding = tbl.column("embedding")
    title = C.col(tbl, "title")
    year = C.col(tbl, "year")
    venue = C.col(tbl, "venue")
    authors = C.col(tbl, "authors")
    arxiv_id = C.col(tbl, "arxiv_id")
    symbol_name = C.col(tbl, "symbol_name")
    signature = C.col(tbl, "signature")
    calls = C.col(tbl, "calls")
    called_by = C.col(tbl, "called_by")
    associated_test = C.col(tbl, "associated_test")
    figure_path = C.col(tbl, "figure_path")

    ct_counts = dict(collections.Counter(chunk_type))
    st_counts = dict(collections.Counter(source_type))
    checks: list[dict] = []

    # ---- D1 元数据完整性 ----
    bad_titles = [m for m in meta if _is_bad_title(m["title"], m["paper_id"], m.get("arxiv_id"))]
    title_valid_rate = 1 - len(bad_titles) / max(n_papers, 1)
    # per-paper L1 metadata coverage
    l1_idx = [i for i, c in enumerate(chunk_type) if c == "paper_l1"]
    year_cov = sum(1 for i in l1_idx if year[i] is not None) / max(len(l1_idx), 1)
    venue_cov = sum(1 for i in l1_idx if venue[i]) / max(len(l1_idx), 1)
    author_cov = sum(1 for i in l1_idx if authors[i]) / max(len(l1_idx), 1)
    venue_vals = dict(collections.Counter(venue[i] for i in l1_idx))
    d1_status = C.grade(title_valid_rate, 0.95, 0.85)
    # authors completely empty is itself a defect → at least WARN
    if author_cov == 0:
        d1_status = C.worst([d1_status, C.WARN])
    checks.append(C.check(
        "D1 元数据完整性", {
            "title_valid_rate": round(title_valid_rate, 4),
            "bad_title_count": len(bad_titles),
            "year_coverage": round(year_cov, 4),
            "venue_coverage": round(venue_cov, 4),
            "author_coverage": round(author_cov, 4),
            "venue_distribution": venue_vals,
        }, d1_status,
        f"{len(bad_titles)} 篇标题=arxivID; authors 覆盖率 {author_cov:.0%}",
    ))
    C.write_csv("bad_titles.csv", [
        {"paper_id": m["paper_id"], "arxiv_id": m.get("arxiv_id"), "title": m["title"], "status": m["status"]}
        for m in bad_titles
    ], ["paper_id", "arxiv_id", "title", "status"])

    # ---- D2 状态一致性 ----
    status_counts = dict(collections.Counter(m["status"] for m in meta))
    code_status_counts = dict(collections.Counter(
        m.get("code_status") or (
            "indexed" if m.get("code_indexed") else
            "pending" if m.get("status") == "code_pending" else "not_checked"
        )
        for m in meta
    ))
    code_pending = [m for m in meta if m["status"] == "code_pending"]
    cp_rate = len(code_pending) / max(n_papers, 1)
    # Legacy aggregate fields must agree with the new code state.
    inconsistent = [
        m for m in meta
        if (m.get("code_status") == "indexed") != bool(m.get("code_indexed"))
        or (m.get("code_status") == "no_code" and bool(m.get("has_code")))
    ]
    d2_status = C.grade(cp_rate, 0.05, 0.20, higher_is_better=False)
    checks.append(C.check(
        "D2 状态一致性", {
            "status_distribution": status_counts,
            "code_status_distribution": code_status_counts,
            "code_pending_count": len(code_pending),
            "code_pending_rate": round(cp_rate, 4),
            "has_code_indexed_inconsistent": len(inconsistent),
        }, d2_status,
        f"{len(code_pending)} 篇 code_pending ({cp_rate:.0%})",
    ))
    C.write_csv("code_pending.csv", [
        {"paper_id": m["paper_id"], "title": m["title"][:80], "has_code": m.get("has_code"),
         "code_indexed": m.get("code_indexed"), "indexed_at": m["indexed_at"]}
        for m in code_pending
    ], ["paper_id", "title", "has_code", "code_indexed", "indexed_at"])

    # ---- D3 chunk 完整性 ----
    papers_with_l1 = {paper_id[i] for i in l1_idx}
    all_paper_ids = {m["paper_id"] for m in meta}
    missing_l1 = sorted(all_paper_ids - papers_with_l1)
    # index_meta.chunk_count records paper chunks only. Code chunks are tracked
    # separately because one paper can own one or more large repositories.
    actual_counts = collections.Counter(
        pid for pid, source in zip(paper_id, source_type) if source == "paper"
    )
    code_counts = collections.Counter(
        pid for pid, source in zip(paper_id, source_type) if source == "code"
    )
    count_mismatch = []
    for m in meta:
        pid = m["paper_id"]
        actual = actual_counts.get(pid, 0)
        if actual != m["chunk_count"]:
            count_mismatch.append({"paper_id": pid, "meta_count": m["chunk_count"], "actual_count": actual})
    d3_status = C.grade(len(missing_l1), 0, 2, higher_is_better=False)
    if count_mismatch:
        d3_status = C.worst([d3_status, C.WARN])
    checks.append(C.check(
        "D3 chunk 完整性", {
            "papers_missing_l1": len(missing_l1),
            "missing_l1_ids": missing_l1[:20],
            "chunk_count_mismatch": len(count_mismatch),
            "paper_chunk_count": sum(actual_counts.values()),
            "code_chunk_count": sum(code_counts.values()),
            "l1": ct_counts.get("paper_l1", 0),
            "l2": ct_counts.get("paper_l2", 0),
            "l3": ct_counts.get("paper_l3", 0),
        }, d3_status,
        f"缺 L1: {len(missing_l1)}; chunk_count 不一致: {len(count_mismatch)}",
    ))
    C.write_csv("chunk_count_mismatch.csv", count_mismatch, ["paper_id", "meta_count", "actual_count"])

    # ---- D4 内容健康 ----
    empty_or_short = sum(1 for c in content if not c or len(c.strip()) < 10)
    empty_rate = empty_or_short / max(n_chunks, 1)
    dup_ids = [cid for cid, n in collections.Counter(chunk_id).items() if n > 1]
    # exact content duplicates (within paper chunks only, ignore tiny)
    content_counter = collections.Counter(c.strip() for c in content if c and len(c.strip()) >= 30)
    dup_content = sum(n - 1 for n in content_counter.values() if n > 1)
    dup_content_rate = dup_content / max(n_chunks, 1)
    d4_status = C.grade(empty_rate, 0.005, 0.02, higher_is_better=False)
    if dup_ids:
        d4_status = C.worst([d4_status, C.FAIL])  # duplicate chunk_id is a hard defect
    checks.append(C.check(
        "D4 内容健康", {
            "empty_or_short_chunks": empty_or_short,
            "empty_rate": round(empty_rate, 5),
            "duplicate_chunk_ids": len(dup_ids),
            "exact_dup_content": dup_content,
            "exact_dup_content_rate": round(dup_content_rate, 5),
        }, d4_status,
        f"重复 chunk_id {len(dup_ids)}(硬缺陷); 空/超短 {empty_or_short} ({empty_rate:.2%}); 完全重复内容 {dup_content}",
    ))
    C.write_csv("duplicate_chunk_ids.csv", [{"chunk_id": x} for x in dup_ids[:500]], ["chunk_id"])

    # ---- D5 嵌入健康 ----
    null_emb = embedding.null_count
    emb_cov = 1 - null_emb / max(n_chunks, 1)
    # Dimension + zero/NaN sanity over the full column, one Arrow chunk at a
    # time. NumPy views/copies are released per chunk instead of retaining a
    # Python list for every individual vector element.
    bad_dim = 0
    zero_vec = 0
    nan_vec = 0
    import numpy as np
    for arrow_chunk in embedding.chunks:
        list_size = getattr(arrow_chunk.type, "list_size", None)
        if list_size != 1024:
            bad_dim += len(arrow_chunk) - arrow_chunk.null_count
            continue
        valid = np.asarray(
            arrow_chunk.is_valid().to_numpy(zero_copy_only=False), dtype=bool
        )
        values = arrow_chunk.values.to_numpy(zero_copy_only=False).reshape(
            len(arrow_chunk), list_size
        )
        valid_values = values[valid]
        if not len(valid_values):
            continue
        finite = np.isfinite(valid_values).all(axis=1)
        nan_vec += int((~finite).sum())
        zero_vec += int((np.abs(valid_values[finite]).sum(axis=1) == 0).sum())
    d5_status = C.PASS
    if emb_cov < 0.99 or bad_dim or zero_vec or nan_vec:
        d5_status = C.FAIL if (bad_dim or zero_vec or nan_vec) else C.WARN
    checks.append(C.check(
        "D5 嵌入健康", {
            "embedding_coverage": round(emb_cov, 5),
            "null_embeddings": null_emb,
            "wrong_dim": bad_dim,
            "zero_vectors": zero_vec,
            "nan_inf_vectors": nan_vec,
        }, d5_status,
        f"覆盖 {emb_cov:.2%}; 坏向量 {bad_dim + zero_vec + nan_vec}",
    ))

    # ---- D6 特殊块 ----
    fig_idx = [i for i, c in enumerate(chunk_type) if c == "figure"]
    tbl_idx = [i for i, c in enumerate(chunk_type) if c == "table"]
    fig_missing_path = sum(1 for i in fig_idx if not figure_path[i])
    papers_with_fig = len({paper_id[i] for i in fig_idx})
    d6_status = C.WARN if (fig_missing_path or papers_with_fig < n_papers * 0.5) else C.PASS
    checks.append(C.check(
        "D6 特殊块(图/表)", {
            "figure_chunks": len(fig_idx),
            "table_chunks": len(tbl_idx),
            "figures_missing_path": fig_missing_path,
            "papers_with_figures": papers_with_fig,
            "papers_total": n_papers,
        }, d6_status,
        f"figure {len(fig_idx)} / table {len(tbl_idx)}; {papers_with_fig}/{n_papers} 篇有图",
    ))

    # ---- D7 代码图谱 ----
    code_idx = [i for i, c in enumerate(chunk_type) if c.startswith("code_")]
    n_code = len(code_idx)
    # symbol/signature coverage on l2..l5 (l1 is module-level, often no symbol)
    sym_idx = [i for i in code_idx if chunk_type[i] in ("code_l2", "code_l3", "code_l4", "code_l5")]
    sym_missing = sum(1 for i in sym_idx if not symbol_name[i])
    sym_missing_rate = sym_missing / max(len(sym_idx), 1)
    # call-graph population
    chunks_with_calls = sum(1 for i in code_idx if calls[i])
    chunks_with_called_by = sum(1 for i in code_idx if called_by[i])
    # orphan references: calls[]/called_by[] pointing to non-existent chunk_id
    id_set = set(chunk_id)
    total_refs = 0
    orphan_refs = 0
    for i in code_idx:
        for ref in (calls[i] or []):
            total_refs += 1
            if ref not in id_set:
                orphan_refs += 1
        for ref in (called_by[i] or []):
            total_refs += 1
            if ref not in id_set:
                orphan_refs += 1
    orphan_rate = orphan_refs / total_refs if total_refs else 0.0
    has_test = sum(1 for i in code_idx if associated_test[i])
    # call graph empty across all code chunks → feature unpopulated → WARN
    callgraph_populated = total_refs > 0
    d7_status = C.grade(orphan_rate, 0.10, 0.30, higher_is_better=False) if total_refs else C.WARN
    if sym_missing_rate > 0.5:
        d7_status = C.worst([d7_status, C.WARN])
    checks.append(C.check(
        "D7 代码图谱", {
            "code_chunks": n_code,
            "symbol_missing_rate(l2-l5)": round(sym_missing_rate, 4),
            "chunks_with_calls": chunks_with_calls,
            "chunks_with_called_by": chunks_with_called_by,
            "total_graph_edges": total_refs,
            "orphan_reference_rate": round(orphan_rate, 4),
            "chunks_with_associated_test": has_test,
            "callgraph_populated": callgraph_populated,
        }, d7_status,
        f"call-graph 边数 {total_refs}; symbol 缺失率 {sym_missing_rate:.0%}",
    ))

    # ---- D8 仓库关联完整性（方法—符号映射为可选指标） ----
    repo_rows = C.load_code_repos()
    mapping_rows = C.count_mapping_rows()
    papers_has_code = [m for m in meta if m.get("code_indexed")]
    known_papers = {m["paper_id"] for m in meta}
    orphan_associations = [row for row in repo_rows if row.get("paper_id") not in known_papers]
    duplicate_association_ids = [
        key for key, count in collections.Counter(row.get("association_id") for row in repo_rows).items()
        if key and count > 1
    ]
    duplicate_paper_urls = [
        key for key, count in collections.Counter(
            (row.get("paper_id"), row.get("repo_url")) for row in repo_rows
        ).items() if count > 1
    ]
    papers_with_multiple_primary = [
        paper for paper, count in collections.Counter(
            row.get("paper_id") for row in repo_rows if row.get("is_primary")
        ).items() if paper and count > 1
    ]
    associated_papers = {row.get("paper_id") for row in repo_rows if row.get("paper_id")}
    primary_papers = {row.get("paper_id") for row in repo_rows if row.get("is_primary")}
    papers_missing_primary = sorted(associated_papers - primary_papers)
    indexed_association_papers = {
        row.get("paper_id") for row in repo_rows if row.get("status") == "indexed"
    }
    missing_indexed_association = [
        m["paper_id"] for m in papers_has_code if m["paper_id"] not in indexed_association_papers
    ]
    hard_errors = (
        len(orphan_associations) + len(duplicate_association_ids)
        + len(duplicate_paper_urls) + len(papers_with_multiple_primary)
        + len(papers_missing_primary) + len(missing_indexed_association)
    )
    d8_status = C.FAIL if hard_errors else C.PASS
    checks.append(C.check(
        "D8 论文—代码仓库关联", {
            "repository_association_rows": len(repo_rows),
            "papers_with_code_indexed": len(papers_has_code),
            "missing_indexed_association": len(missing_indexed_association),
            "orphan_associations": len(orphan_associations),
            "duplicate_association_ids": len(duplicate_association_ids),
            "duplicate_paper_repo_urls": len(duplicate_paper_urls),
            "papers_with_multiple_primary": len(papers_with_multiple_primary),
            "papers_missing_primary": len(papers_missing_primary),
            "method_symbol_mapping_rows_optional": mapping_rows,
        }, d8_status,
        f"仓库关联 {len(repo_rows)} 行；缺失 indexed 关联 {len(missing_indexed_association)} 篇；"
        f"方法—符号映射 {mapping_rows} 行（可选）",
    ))

    overall = C.worst([c["status"] for c in checks])
    result = {
        "section": "data_quality",
        "overall": overall,
        "index_overview": {
            "total_papers": n_papers,
            "total_chunks": n_chunks,
            "chunk_type_distribution": ct_counts,
            "source_type_distribution": st_counts,
            "papers_with_code_indexed": len(papers_has_code),
        },
        "checks": checks,
    }
    C.write_json("data_quality.json", result)
    print(f"  → 总体: {overall}  (outputs/data_quality.json)")
    return result


if __name__ == "__main__":
    run()
