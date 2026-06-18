"""check_03 — e5 嵌入前缀 A/B 诊断实验.

intfloat/multilingual-e5-large 要求查询加 "query: "、文档加 "passage: " 前缀。
当前 mapce.core.embedding 的 embed()/embed_single() 都不加前缀（疑似 bug）。
本实验在脚本内自建两套嵌入、手算余弦相似，量化前缀缺失对"标题→论文"检索的影响。

  A（当前实现复刻）: query 与候选都无前缀
  B（e5 规范）       : query 用 "query: "，候选用 "passage: "

不改源码、不写库。

运行: uv run --env-file .env python tests/check_03_embedding_prefix_ab.py
"""

from __future__ import annotations

import random

import common as C

random.seed(7)

N_QUERIES = 60  # 标题查询子集规模


def _bad_title(t, pid, arxiv):
    t = (t or "").strip()
    return (not t) or t == pid or t == (arxiv or "") or t.replace(".", "").isdigit()


def _rank_by_cosine(q_emb, cand_embs: list, cand_pids: list[str], gold_pid: str) -> int | None:
    scored = sorted(
        ((C.cosine(q_emb, e), pid) for e, pid in zip(cand_embs, cand_pids)),
        key=lambda x: x[0], reverse=True,
    )
    for rank, (_, pid) in enumerate(scored, start=1):
        if pid == gold_pid:
            return rank
    return None


def _eval(query_texts, gold_pids, cand_texts, cand_pids, q_prefix, c_prefix):
    from mapce.core.embedding import embed
    cand_embs = embed([f"{c_prefix}{t}" for t in cand_texts])
    q_embs = embed([f"{q_prefix}{t}" for t in query_texts])
    ranks = [
        _rank_by_cosine(qe, cand_embs, cand_pids, gp)
        for qe, gp in zip(q_embs, gold_pids)
    ]
    return {
        "recall@1": round(C.recall_at_k(ranks, 1), 4),
        "recall@5": round(C.recall_at_k(ranks, 5), 4),
        "recall@10": round(C.recall_at_k(ranks, 10), 4),
        "mrr": round(C.mrr(ranks), 4),
    }, ranks


def run() -> dict:
    print("\n=== check_03 e5 前缀 A/B 诊断 ===")
    tbl = C.load_chunks_arrow()
    meta = C.load_meta()
    chunk_type = C.col(tbl, "chunk_type")
    paper_id = C.col(tbl, "paper_id")
    content = C.col(tbl, "content")

    # 候选集 = 每篇论文的 L1 内容
    l1_text: dict[str, str] = {}
    for i, ct in enumerate(chunk_type):
        if ct == "paper_l1":
            l1_text[paper_id[i]] = content[i]
    cand_pids = list(l1_text.keys())
    cand_texts = [l1_text[p] for p in cand_pids]

    # 查询集 = 有效标题论文的标题子集
    valid = [m for m in meta if not _bad_title(m["title"], m["paper_id"], m.get("arxiv_id"))
             and m["paper_id"] in l1_text]
    sample = random.sample(valid, min(N_QUERIES, len(valid)))
    query_texts = [m["title"] for m in sample]
    gold_pids = [m["paper_id"] for m in sample]

    print(f"  候选 L1={len(cand_pids)}, 查询标题={len(query_texts)}")

    print("  [A] 无前缀（复刻当前实现）…")
    a_metrics, _ = _eval(query_texts, gold_pids, cand_texts, cand_pids, "", "")
    print(f"      A: R@1={a_metrics['recall@1']:.0%} R@5={a_metrics['recall@5']:.0%} MRR={a_metrics['mrr']:.3f}")

    print("  [B] e5 规范前缀（query:/passage:）…")
    b_metrics, _ = _eval(query_texts, gold_pids, cand_texts, cand_pids, "query: ", "passage: ")
    print(f"      B: R@1={b_metrics['recall@1']:.0%} R@5={b_metrics['recall@5']:.0%} MRR={b_metrics['mrr']:.3f}")

    delta = {
        "d_recall@1": round(b_metrics["recall@1"] - a_metrics["recall@1"], 4),
        "d_recall@5": round(b_metrics["recall@5"] - a_metrics["recall@5"], 4),
        "d_mrr": round(b_metrics["mrr"] - a_metrics["mrr"], 4),
    }
    # 判定：B 明显优于 A（ΔMRR ≥ 0.05）→ 确认前缀缺失拉低检索 → 标 WARN（需修复）
    if delta["d_mrr"] >= 0.05:
        status = C.WARN
        note = f"加前缀后 MRR +{delta['d_mrr']:.3f} → 确认前缀缺失拉低检索，建议修复"
    elif delta["d_mrr"] <= -0.02:
        status = C.PASS
        note = f"前缀反而更差 ({delta['d_mrr']:.3f})，现状可接受"
    else:
        status = C.PASS
        note = f"差异不显著 (ΔMRR={delta['d_mrr']:.3f})"

    check = C.check("E1 e5 前缀 A/B", {"A_no_prefix": a_metrics, "B_e5_prefix": b_metrics, "delta": delta},
                    status, note)

    result = {
        "section": "embedding_prefix_ab",
        "overall": status,
        "n_queries": len(query_texts),
        "n_candidates": len(cand_pids),
        "checks": [check],
        "qualitative": {
            "hybrid_retrieval_status": "当前 retrieval.py 仅使用向量检索；fulltext_search(FTS) 列存在但从未被查询，README 宣称的‘向量+全文混合检索’暂未生效。",
        },
    }
    C.write_json("embedding_prefix_ab.json", result)
    print(f"  → 总体: {status}  (outputs/embedding_prefix_ab.json)")
    return result


if __name__ == "__main__":
    run()
