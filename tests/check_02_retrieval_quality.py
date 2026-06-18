"""check_02 — MAPCE 检索质量检查 (R1–R8).

用索引自身派生的 ground truth（标题/摘要/chunk 自检索/代码），调用现有
mapce.core.retrieval API，计算 Recall@k / MRR / 延迟，给出阈值判定。
需要加载 e5 嵌入模型。

运行: uv run --env-file .env python tests/check_02_retrieval_quality.py
"""

from __future__ import annotations

import collections
import random
import re
import time

import common as C

random.seed(42)

# 样本规模上限（控制总耗时；每次 search ~0.9s）
N_R3_SELF = 150
N_R4_CODE = 40


def _paper_rank(results, gold_paper_id: str) -> int | None:
    """Paper-level rank (1-indexed) of gold paper among ordered unique paper_ids."""
    seen: list[str] = []
    for r in results:
        if r.paper_id not in seen:
            seen.append(r.paper_id)
        if r.paper_id == gold_paper_id:
            return seen.index(gold_paper_id) + 1
    return None


def _first_sentences(text: str, n: int = 2) -> str:
    # drop leading markdown title line "# ..."
    body = re.sub(r"^#.*\n", "", text, count=1).strip()
    parts = re.split(r"(?<=[.!?])\s+", body)
    return " ".join(parts[:n]).strip()


def run() -> dict:
    print("\n=== check_02 检索质量 (R1–R8) ===")
    from mapce.core.retrieval import search_papers, search_code, parse_intent

    tbl = C.load_chunks_arrow()
    meta = C.load_meta()
    chunk_type = C.col(tbl, "chunk_type")
    paper_id = C.col(tbl, "paper_id")
    content = C.col(tbl, "content")
    title = C.col(tbl, "title")
    year = C.col(tbl, "year")
    venue = C.col(tbl, "venue")
    chunk_id = C.col(tbl, "chunk_id")
    repo_name = C.col(tbl, "repo_name")
    file_path = C.col(tbl, "file_path")
    symbol_name = C.col(tbl, "symbol_name")

    # paper_id -> L1 content & title
    l1_by_pid: dict[str, str] = {}
    title_by_pid: dict[str, str] = {}
    for i, ct in enumerate(chunk_type):
        if ct == "paper_l1":
            l1_by_pid[paper_id[i]] = content[i]
            title_by_pid[paper_id[i]] = title[i]

    def _bad_title(t, pid, m):
        t = (t or "").strip()
        return (not t) or t == pid or t == (m.get("arxiv_id") or "") or t.replace(".", "").isdigit()

    valid_papers = [m for m in meta if not _bad_title(m["title"], m["paper_id"], m)]
    checks: list[dict] = []

    # ---- R1 已知项: 标题 -> 论文 ----
    print("  [R1] 标题→论文 known-item …")
    r1_ranks: list[int | None] = []
    r1_latency: list[float] = []
    r1_miss = []
    for m in valid_papers:
        q = m["title"]
        t0 = time.perf_counter()
        results, _ = search_papers(q, top_k=10)
        r1_latency.append(time.perf_counter() - t0)
        rank = _paper_rank(results, m["paper_id"])
        r1_ranks.append(rank)
        if rank is None or rank > 1:
            r1_miss.append({"paper_id": m["paper_id"], "title": m["title"][:70], "rank": rank})
    r1 = {
        "n": len(r1_ranks),
        "recall@1": round(C.recall_at_k(r1_ranks, 1), 4),
        "recall@5": round(C.recall_at_k(r1_ranks, 5), 4),
        "recall@10": round(C.recall_at_k(r1_ranks, 10), 4),
        "mrr": round(C.mrr(r1_ranks), 4),
    }
    checks.append(C.check("R1 标题→论文", r1, C.grade(r1["recall@5"], 0.85, 0.70),
                          f"R@1={r1['recall@1']:.0%} R@5={r1['recall@5']:.0%} MRR={r1['mrr']:.2f}"))
    C.write_csv("r1_title_misses.csv", r1_miss, ["paper_id", "title", "rank"])

    # ---- R2 语义: 摘要首句 -> 论文 ----
    print("  [R2] 摘要首句→论文 semantic …")
    r2_ranks: list[int | None] = []
    for m in valid_papers:
        l1 = l1_by_pid.get(m["paper_id"], "")
        q = _first_sentences(l1, 2)
        if len(q) < 30:
            continue
        results, _ = search_papers(q, top_k=10)
        r2_ranks.append(_paper_rank(results, m["paper_id"]))
    r2 = {
        "n": len(r2_ranks),
        "recall@1": round(C.recall_at_k(r2_ranks, 1), 4),
        "recall@5": round(C.recall_at_k(r2_ranks, 5), 4),
        "recall@10": round(C.recall_at_k(r2_ranks, 10), 4),
        "mrr": round(C.mrr(r2_ranks), 4),
    }
    checks.append(C.check("R2 摘要首句→论文", r2, C.grade(r2["recall@5"], 0.70, 0.50),
                          f"R@5={r2['recall@5']:.0%} MRR={r2['mrr']:.2f}"))

    # ---- R3 chunk 自检索 ----
    print(f"  [R3] chunk 自检索 (sample {N_R3_SELF}) …")
    pool = [i for i, ct in enumerate(chunk_type) if ct in ("paper_l2", "paper_l3") and content[i] and len(content[i]) > 80]
    sample = random.sample(pool, min(N_R3_SELF, len(pool)))
    r3_ranks: list[int | None] = []
    for i in sample:
        q = content[i][:256]
        results, _ = search_papers(q, top_k=10)
        r3_ranks.append(_paper_rank(results, paper_id[i]))
    r3 = {
        "n": len(r3_ranks),
        "top1_paper_hit": round(C.recall_at_k(r3_ranks, 1), 4),
        "recall@5": round(C.recall_at_k(r3_ranks, 5), 4),
        "mrr": round(C.mrr(r3_ranks), 4),
    }
    checks.append(C.check("R3 chunk 自检索", r3, C.grade(r3["top1_paper_hit"], 0.90, 0.75),
                          f"top1 论文命中={r3['top1_paper_hit']:.0%} MRR={r3['mrr']:.2f}"))

    # ---- R4 代码已知项 ----
    print(f"  [R4] 代码 known-item (sample {N_R4_CODE}) …")
    code_pool = [i for i, ct in enumerate(chunk_type)
                 if ct in ("code_l2", "code_l3") and file_path[i] and content[i] and len(content[i]) > 80]
    r4 = {"n": 0, "note": "无代码 chunk 样本"}
    r4_status = C.WARN
    if code_pool:
        csample = random.sample(code_pool, min(N_R4_CODE, len(code_pool)))
        file_hit = 0
        paper_hit = 0
        n = 0
        for i in csample:
            q = symbol_name[i] or file_path[i].split("/")[-1].replace(".py", "").replace("_", " ")
            if not q or len(q) < 3:
                q = content[i][:120]
            results, _ = search_code(q, top_k=5)
            n += 1
            if any(getattr(r, "file_path", None) == file_path[i] for r in results):
                file_hit += 1
            if any(r.paper_id == paper_id[i] for r in results):
                paper_hit += 1
        r4 = {
            "n": n,
            "file_recall@5": round(file_hit / max(n, 1), 4),
            "paper_recall@5": round(paper_hit / max(n, 1), 4),
        }
        r4_status = C.grade(r4["file_recall@5"], 0.70, 0.50)
    checks.append(C.check("R4 代码 known-item", r4, r4_status,
                          f"file R@5={r4.get('file_recall@5','NA')}"))

    # ---- R5 过滤正确性 ----
    print("  [R5] 过滤正确性 …")
    years = [year[i] for i, ct in enumerate(chunk_type) if ct == "paper_l1" and year[i] is not None]
    year_cov = len(years) / max(sum(1 for ct in chunk_type if ct == "paper_l1"), 1)
    venue_vals = set(v for i, ct in enumerate(chunk_type) if ct == "paper_l1" and (v := venue[i]))
    # year filter test
    cutoff = 2025
    results, _ = search_papers("humanoid whole-body control", top_k=10, year_min=cutoff)
    yr_ok = all((r.year is None) or (r.year >= cutoff) for r in results)
    yr_violations = sum(1 for r in results if r.year is not None and r.year < cutoff)
    # venue filter (degenerate if only one venue)
    venue_testable = len(venue_vals) > 1
    r5 = {
        "year_coverage": round(year_cov, 4),
        "distinct_venues": sorted(venue_vals),
        "year_filter_min": cutoff,
        "year_filter_results": len(results),
        "year_filter_violations": yr_violations,
        "year_filter_correct": yr_ok,
        "venue_filter_testable": venue_testable,
    }
    r5_status = C.PASS if yr_ok else C.FAIL
    checks.append(C.check("R5 过滤正确性", r5, r5_status,
                          f"year>={cutoff} 违例 {yr_violations}; venue 仅 {sorted(venue_vals)}"))

    # ---- R6 意图路由 ----
    print("  [R6] 意图路由 …")
    labeled = [
        ("how does ASAP align simulation and real-world physics", "paper_search", "general"),
        ("explain the loss function used for motion tracking", "paper_search", "formula"),
        ("benchmark results comparison of humanoid controllers", "paper_search", "benchmark"),
        ("show me the architecture diagram of the policy network", "paper_search", "figure_lookup"),
        ("what is a behavioral foundation model", "paper_search", "general"),
        ("derivation of the forward-backward representation objective", "paper_search", "formula"),
        ("table of success rates across tasks", "paper_search", "benchmark"),
        ("pipeline figure of the retargeting method", "paper_search", "figure_lookup"),
        ("compare DeepMimic and AMP", "paper_search", "general"),
        ("theorem about successor features convergence", "paper_search", "formula"),
        ("implement the PPO training loop in python", "code_search", "general"),
        ("how to run the training script", "code_search", "general"),
        ("class definition of the motion retargeting module", "code_search", "general"),
        ("github repository for OmniH2O", "code_search", "general"),
        ("the function that computes reward in pytorch", "code_search", "general"),
        ("clone and execute the repo", "code_search", "general"),
        ("write a script to load the checkpoint", "code_search", "general"),
        ("repository implementation of diffusion policy", "code_search", "general"),
        ("motion tracking", "hybrid", "general"),
        ("humanoid", "hybrid", "general"),
        ("retargeting", "hybrid", "general"),
        ("zero-shot reinforcement learning", "hybrid", "general"),
        ("loco-manipulation", "hybrid", "general"),
        ("sim-to-real transfer", "hybrid", "general"),
    ]
    intent_correct = 0
    subtype_correct = 0
    confusion = collections.Counter()
    intent_rows = []
    for q, gold_intent, gold_sub in labeled:
        si = parse_intent(q)
        ok_i = si.intent == gold_intent
        ok_s = si.sub_type == gold_sub
        intent_correct += ok_i
        subtype_correct += ok_s
        confusion[f"{gold_intent}->{si.intent}"] += 1
        intent_rows.append({"query": q, "gold_intent": gold_intent, "pred_intent": si.intent,
                            "gold_sub": gold_sub, "pred_sub": si.sub_type, "intent_ok": ok_i})
    r6 = {
        "n": len(labeled),
        "intent_accuracy": round(intent_correct / len(labeled), 4),
        "subtype_accuracy": round(subtype_correct / len(labeled), 4),
        "confusion": dict(confusion),
    }
    checks.append(C.check("R6 意图路由", r6, C.grade(r6["intent_accuracy"], 0.80, 0.65),
                          f"intent acc={r6['intent_accuracy']:.0%} subtype acc={r6['subtype_accuracy']:.0%}"))
    C.write_csv("r6_intent.csv", intent_rows,
                ["query", "gold_intent", "pred_intent", "gold_sub", "pred_sub", "intent_ok"])

    # ---- R7 鲁棒性/负样本 ----
    print("  [R7] 鲁棒性/负样本 …")
    neg_queries = [
        "lattice quantum chromodynamics confinement",
        "asdkjh qweoiu zxcmnv random gibberish tokens",
        "   ",
        "the",
    ]
    r7_rows = []
    errors = 0
    for q in neg_queries:
        try:
            results, _ = search_papers(q, top_k=5)
            r7_rows.append({"query": q[:40], "n_results": len(results),
                            "top_paper": results[0].paper_id if results else None,
                            "error": ""})
        except Exception as e:
            errors += 1
            r7_rows.append({"query": q[:40], "n_results": -1, "top_paper": None, "error": str(e)[:80]})
    r7 = {"queries": len(neg_queries), "errors": errors, "detail": r7_rows}
    r7_status = C.PASS if errors == 0 else C.FAIL
    checks.append(C.check("R7 鲁棒性/负样本", r7, r7_status, f"异常 {errors}/{len(neg_queries)}"))

    # ---- R8 延迟 ----
    r8 = {
        "n": len(r1_latency),
        "p50_s": round(C.percentile(r1_latency, 50), 3),
        "p95_s": round(C.percentile(r1_latency, 95), 3),
        "max_s": round(max(r1_latency), 3) if r1_latency else 0,
        "mean_s": round(sum(r1_latency) / max(len(r1_latency), 1), 3),
    }
    r8_status = C.grade(r8["p95_s"], 2.0, 5.0, higher_is_better=False)
    checks.append(C.check("R8 检索延迟", r8, r8_status,
                          f"p50={r8['p50_s']}s p95={r8['p95_s']}s"))

    overall = C.worst([c["status"] for c in checks])
    result = {"section": "retrieval_quality", "overall": overall, "checks": checks}
    C.write_json("retrieval_quality.json", result)
    print(f"  → 总体: {overall}  (outputs/retrieval_quality.json)")
    return result


if __name__ == "__main__":
    run()
