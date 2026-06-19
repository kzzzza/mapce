"""run_all — 依次执行 check_01/02/03，汇总并渲染 tests/REPORT.md。

运行: uv run --env-file .env python tests/run_all.py
"""

from __future__ import annotations

import datetime as dt

import common as C
import check_01_data_quality as d
import check_02_retrieval_quality as r
import check_03_embedding_prefix_ab as e

ICON = {"PASS": "✅ PASS", "WARN": "⚠️ WARN", "FAIL": "❌ FAIL"}

# --- 新手友好说明（折叠块，保持报告简洁） ---

_GLOSSARY = """<details><summary>📖 新手名词速查（不懂 RAG/数据库先看这里）</summary>

- **chunk（块）**：论文/代码被切成的小片段，是检索的最小单位。一篇论文会切成 L1=标题+摘要、L2=章节、L3=段落，外加图、表；代码切成文件/类/函数等。
- **嵌入 / 向量（embedding）**：把一段文字用 AI 模型转成一串 1024 个数字。语义相近的文字，数字也相近——这就是"语义搜索"的基础。
- **向量检索**：把你的问题也转成向量，再找库里数字最接近的 chunk。靠"意思像"而非"字一样"。
- **Recall@k（召回率）**：正确答案出现在返回结果**前 k 条**里的比例。越高越好（如 R@5=99% 表示几乎每次正确答案都在前 5 条内）。
- **MRR（平均倒数排名）**：正确答案排第 1 得 1 分、第 2 得 0.5 分、第 3 得 0.33……再求平均。越接近 1 表示排得越靠前。
- **PASS / WARN / FAIL**：每项指标设了及格线，绿=达标、黄=偏低需关注、红=不合格。判定逻辑见 `tests/common.py` 的 `grade()`。
</details>
"""

_DQ_GUIDE = """<details><summary>❓ 这 8 项数据质量检查分别在看什么</summary>

> 数据质量 = "存进库里的东西本身干不干净、全不全"，与"搜得准不准"是两回事。

- **D1 元数据完整性**：每篇论文的档案信息（标题/作者/年份/会议）是否齐全、正确。标题若错成一串编号，按标题就搜不到。
- **D2 状态一致性**：每篇论文有个处理进度标记，检查是否有卡在"半成品"状态（如 code_pending）的。
- **D3 chunk 完整性**：每篇是否都成功切出了"摘要块"，且记录的块数与实际存的对得上。
- **D4 内容健康**：有没有空块、超短块，以及**重复的 chunk_id**（相当于数据库主键撞车，属硬伤）。
- **D5 嵌入健康**：每个块的 1024 维向量是否都正常生成、没有缺失/全零/坏值——向量坏了语义搜索就废了。
- **D6 特殊块**：论文里的图、表是否被正确提取并能定位到图片文件。
- **D7 代码图谱**：代码块之间"谁调用谁"的关系是否被记录（用于顺着调用链扩展上下文）。
- **D8 Paper↔Code 映射表**：论文里的"方法"与代码里的"实现"之间的对应关系表是否建立（双向检索特性的基础）。
</details>
"""

_RQ_GUIDE = """<details><summary>❓ 这 8 项检索检查分别在看什么</summary>

> 检索质量 = "给一个查询，库能不能把对的内容捞到、并排在前面"。这里用"已知正确答案"的查询来自动打分。

- **R1 标题→论文**：拿论文标题当搜索词，看能否搜回这篇论文本身。最基本的"已知答案"测试。
- **R2 摘要首句→论文**：拿摘要开头当搜索词（不含标题原词），测**语义理解**而非字面重复。
- **R3 chunk 自检索**：拿某个段落的原文当搜索词，看能否定位回它所在的论文。测**细粒度（段落级）检索**。
- **R4 代码 known-item**：拿代码符号/文件名当搜索词，看能否找到对应的代码文件。
- **R5 过滤正确性**：加上"年份≥2025"这类筛选后，返回结果是否真的都满足条件。
- **R6 意图路由**：系统能否判断你这句是想搜"论文"还是搜"代码"，并据此走不同检索路径。
- **R7 鲁棒性/负样本**：输入乱码、空串、停用词时系统会不会报错、会不会乱返回一堆无关结果。
- **R8 检索延迟**：一次搜索要多久（p50=一半查询快于此，p95=95% 查询快于此）。
</details>
"""

_AB_GUIDE = """<details><summary>❓ 这个 A/B 实验在验证什么</summary>

所用嵌入模型（e5）官方要求：搜索词前面加 `query: `、被检索文档前面加 `passage: `。当前代码两者都没加。
本实验同一批查询各跑一遍"不加前缀（A）"和"加前缀（B）"，对比谁的 Recall/MRR 更高，来判断这个"缺前缀"到底有没有实质伤害。
**结论是差异极小**，所以不必为它大动干戈（重嵌入全库）。
</details>
"""

_REMEDIATION = """## 0.5 修复进度

针对首轮测试发现的问题，已落地的修复（均**不需重跑论文解析、不重嵌入**）：

| 状态 | 修复 | 解决的问题 | 改动/脚本 | 提交 |
|------|------|-----------|-----------|------|
| ✅ 已修 | F1 检索粗筛改造 | R3 段落自检索 29%→85%、R4 代码 17.5%→65%（去掉 L1 top-20 候选门，改全库检索+相似度/已知项融合） | `core/retrieval.py` | `1ff9465` |
| ✅ 已修 | F5 代码去重 | D4 重复 chunk_id 1067→0（index_code 改幂等 + 一次性清理） | `mcp/_handlers.py`、`scripts/dedup_code_chunks.py` | `7ef6607` |
| ✅ 已修 | 图片路径回填 | D6 图片缺路径 1006→66 / 1048（从磁盘 MinerU 输出回填 figure_path/table_image） | `scripts/backfill_figure_paths.py` | `c8cac99` |

尚未修复（本轮未选；保留为已知问题）：

| 状态 | 问题 | 对应检查 | 建议修复 |
|------|------|----------|----------|
| ⏳ 待修 | Paper↔Code 映射表为空 | D8 (FAIL) | F7：index_code 调用 mapper subagent 写映射表 |
| ⏳ 待修 | 代码调用图谱未填充 | D7 (WARN) | F6：chunker 解析并解析 calls/called_by 到 chunk_id |
| ⏳ 待修 | 标题(6 篇)/作者(全缺) | D1 (WARN) | F4：索引时调 get_arxiv_metadata 并回填 |
| ⏳ 待修 | 19 篇卡 code_pending | D2 (WARN) | F8：收敛状态机 + 回填 status |
| ⏳ 待修 | 图片剩 66 张/表 47 张无路径 | D6 (WARN) | 调整少数论文的图注/图片匹配规则 |
| ⊘ 主动跳过 | e5 query/passage 前缀 | E1 (PASS) | A/B 实测 ΔMRR 仅 ~0.01，不显著，跳过 |

> 注：本节由 `tests/run_all.py` 渲染。修复用脚本 `scripts/dedup_code_chunks.py`、`scripts/backfill_figure_paths.py`
> 会改动 `~/.mapce/data`（执行前已备份）；而三个 `check_0*.py` 测试脚本本身只读。
"""


def _metrics_str(m: dict) -> str:
    parts = []
    for k, v in m.items():
        if isinstance(v, dict):
            v = "{" + ", ".join(f"{kk}={vv}" for kk, vv in v.items()) + "}"
        elif isinstance(v, list):
            v = "[" + ", ".join(map(str, v[:6])) + ("…" if len(v) > 6 else "") + "]"
        parts.append(f"`{k}`={v}")
    return "; ".join(parts)


def render_report(dq: dict, rq: dict, ab: dict) -> str:
    ov = dq["index_overview"]
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L: list[str] = []
    L.append("# MAPCE 索引库 数据质量 & 检索质量 测试报告\n")
    L.append(f"> 生成时间：{now}  ·  测试脚本：`tests/check_0{{1,2,3}}.py`（只读）  ·  修复进度见 §0.5\n")

    # 总体红绿灯
    L.append("## 0. 总体结论\n")
    L.append("| 模块 | 结论 |")
    L.append("|------|------|")
    L.append(f"| 数据质量 (D1–D8) | {ICON[dq['overall']]} |")
    L.append(f"| 检索质量 (R1–R8) | {ICON[rq['overall']]} |")
    L.append(f"| e5 前缀 A/B 诊断 | {ICON[ab['overall']]} |")
    L.append("")
    L.append(_REMEDIATION)

    # 索引概览
    L.append("## 1. 索引概览\n")
    L.append(f"- 论文总数：**{ov['total_papers']}**　chunk 总数：**{ov['total_chunks']}**　带代码论文：**{ov['papers_with_code_indexed']}**")
    L.append(f"- source 分布：{ov['source_type_distribution']}")
    L.append(f"- chunk 类型分布：{ov['chunk_type_distribution']}")
    L.append("")
    L.append(_GLOSSARY)

    # 数据质量
    L.append("## 2. 数据质量结果 (D1–D8)\n")
    L.append("| 检查项 | 结论 | 关键指标 |")
    L.append("|--------|------|----------|")
    for c in dq["checks"]:
        L.append(f"| {c['name']} | {ICON[c['status']]} | {c['note']} |")
    L.append("")
    L.append(_DQ_GUIDE)
    L.append("<details><summary>展开完整指标</summary>\n")
    for c in dq["checks"]:
        L.append(f"**{c['name']}** — {ICON[c['status']]}  \n{_metrics_str(c['metrics'])}\n")
    L.append("</details>\n")

    # 检索质量
    L.append("## 3. 检索质量结果 (R1–R8)\n")
    L.append("| 检查项 | 结论 | 关键指标 |")
    L.append("|--------|------|----------|")
    for c in rq["checks"]:
        L.append(f"| {c['name']} | {ICON[c['status']]} | {c['note']} |")
    L.append("")
    L.append(_RQ_GUIDE)
    L.append("<details><summary>展开完整指标</summary>\n")
    for c in rq["checks"]:
        L.append(f"**{c['name']}** — {ICON[c['status']]}  \n{_metrics_str(c['metrics'])}\n")
    L.append("</details>\n")

    # A/B
    L.append("## 4. e5 嵌入前缀 A/B 诊断\n")
    abc = ab["checks"][0]
    m = abc["metrics"]
    L.append(f"查询标题 {ab['n_queries']} 条，候选 L1 {ab['n_candidates']} 篇，手算余弦相似排名：\n")
    L.append("| 方案 | Recall@1 | Recall@5 | Recall@10 | MRR |")
    L.append("|------|----------|----------|-----------|-----|")
    a, b = m["A_no_prefix"], m["B_e5_prefix"]
    L.append(f"| A 无前缀（当前实现） | {a['recall@1']:.0%} | {a['recall@5']:.0%} | {a['recall@10']:.0%} | {a['mrr']:.3f} |")
    L.append(f"| B e5 规范前缀 | {b['recall@1']:.0%} | {b['recall@5']:.0%} | {b['recall@10']:.0%} | {b['mrr']:.3f} |")
    L.append(f"| **Δ (B−A)** | {m['delta']['d_recall@1']:+.0%} | {m['delta']['d_recall@5']:+.0%} | — | {m['delta']['d_mrr']:+.3f} |")
    L.append(f"\n结论：{ICON[ab['overall']]} — {abc['note']}\n")
    L.append(f"> {ab['qualitative']['hybrid_retrieval_status']}\n")
    L.append(_AB_GUIDE)

    # 问题清单
    L.append("## 5. 问题清单与优先级\n")
    findings = _collect_findings(dq, rq, ab)
    L.append("| 优先级 | 问题 | 证据 | 影响 |")
    L.append("|--------|------|------|------|")
    for f in findings:
        L.append(f"| {f['prio']} | {f['title']} | {f['evidence']} | {f['impact']} |")
    L.append("")

    # 建议
    L.append("## 6. 改进建议（仅建议，未实现）\n")
    for s in _recommendations():
        L.append(f"- {s}")
    L.append("")
    L.append("---\n")
    L.append("原始数据：`tests/outputs/*.json`、问题明细 `tests/outputs/*.csv`。\n")
    return "\n".join(L)


def _collect_findings(dq, rq, ab):
    F = []
    cmap = {c["name"].split()[0]: c for c in dq["checks"]}
    rmap = {c["name"].split()[0]: c for c in rq["checks"]}

    # D8 mapping empty
    if cmap.get("D8", {}).get("status") == "FAIL":
        F.append({"prio": "P0", "title": "Paper↔Code 映射表为空",
                  "evidence": f"paper_code_mapping 行数={cmap['D8']['metrics']['mapping_rows']}",
                  "impact": "双向映射/调用链追踪功能不可用；index_code 从不写映射表"})
    # D7 callgraph
    d7 = cmap.get("D7", {}).get("metrics", {})
    if d7 and not d7.get("callgraph_populated"):
        F.append({"prio": "P1", "title": "代码调用图谱未填充",
                  "evidence": f"calls/called_by 边数={d7.get('total_graph_edges')}（{d7.get('code_chunks')} 个 code chunk）",
                  "impact": "检索的调用链扩展(Stage3)永不触发"})
    # D4 duplicate chunk_id
    d4 = cmap.get("D4", {}).get("metrics", {})
    if d4.get("duplicate_chunk_ids"):
        F.append({"prio": "P0", "title": "存在重复 chunk_id",
                  "evidence": f"{d4['duplicate_chunk_ids']} 个重复 chunk_id（多为 code:* ，见 duplicate_chunk_ids.csv）",
                  "impact": "代码仓库被重复索引、未去重；同 ID 多行污染检索与统计"})

    # D1 titles + authors
    d1 = cmap.get("D1", {}).get("metrics", {})
    if d1.get("bad_title_count"):
        F.append({"prio": "P1", "title": "论文标题提取失败",
                  "evidence": f"{d1['bad_title_count']} 篇 title=arxivID（见 bad_titles.csv）",
                  "impact": "标题→论文检索失败、列表可读性差"})
    if d1.get("author_coverage") == 0:
        F.append({"prio": "P2", "title": "作者信息全缺失",
                  "evidence": "L1 authors 覆盖率 0%",
                  "impact": "按作者检索/引用不可用"})
    # D2 code_pending
    d2 = cmap.get("D2", {}).get("metrics", {})
    if d2.get("code_pending_count"):
        F.append({"prio": "P2", "title": "状态停留 code_pending",
                  "evidence": f"{d2['code_pending_count']} 篇 status=code_pending（见 code_pending.csv）",
                  "impact": "状态机未收敛，统计口径混乱"})
    # e5 prefix
    if ab["overall"] == "WARN":
        d = ab["checks"][0]["metrics"]["delta"]
        F.append({"prio": "P1", "title": "e5 嵌入缺少 query/passage 前缀",
                  "evidence": f"加前缀后 ΔMRR={d['d_mrr']:+.3f}, ΔR@5={d['d_recall@5']:+.0%}",
                  "impact": "检索召回与排序低于模型应有水平"})
    # FTS
    F.append({"prio": "P2", "title": "混合检索未生效（实为纯向量）",
              "evidence": "retrieval.py 从不查询 fulltext_search 列",
              "impact": "精确术语/符号召回偏弱，与 README 描述不符"})
    # R1 known item
    r1 = rmap.get("R1", {})
    if r1.get("status") in ("WARN", "FAIL"):
        F.append({"prio": "P1", "title": "标题→论文 known-item 召回偏低",
                  "evidence": f"R@1={r1['metrics']['recall@1']:.0%}, R@5={r1['metrics']['recall@5']:.0%}",
                  "impact": "用精确标题也难稳定定位到目标论文"})
    # R3 chunk-level retrieval
    r3 = rmap.get("R3", {})
    if r3.get("status") in ("WARN", "FAIL"):
        F.append({"prio": "P0", "title": "细粒度(段落级)检索召回过低",
                  "evidence": f"chunk 自检索 top1={r3['metrics']['top1_paper_hit']:.0%}, R@5={r3['metrics']['recall@5']:.0%}；"
                              f"诊断：仅约 57% 的 L3 段落，其所属论文能挺过 Stage1 的 top-20 L1(摘要)粗筛",
                  "impact": "Stage1 用 L1 摘要粗筛+语料高度同质 → 深层段落在精排前就被丢弃，问具体细节常找错论文"})
    # R4 code retrieval
    r4 = rmap.get("R4", {})
    if r4.get("status") in ("WARN", "FAIL"):
        F.append({"prio": "P1", "title": "代码检索召回过低",
                  "evidence": f"file Recall@5={r4['metrics'].get('file_recall@5','NA')}",
                  "impact": "search_code 同样先按论文摘要粗筛，代码类 query 与摘要语义错位 → 候选集常不含目标文件"})
    # R7 no relevance floor
    r7 = rmap.get("R7", {})
    if r7 and r7.get("metrics", {}).get("errors", 0) == 0:
        det = r7["metrics"].get("detail", [])
        nonsense_hits = [d for d in det if d.get("n_results", 0) > 0]
        if nonsense_hits:
            F.append({"prio": "P2", "title": "无相关性下限(无 score floor)",
                      "evidence": "空串/乱码/停用词 query 仍返回 30+ 条结果且给出 top_paper",
                      "impact": "对离题/空 query 也注入上下文，易产生无依据回答"})
    return F


def _recommendations():
    return [
        "**P0 改 Stage1 粗筛策略（最影响检索质量）**：当前以 L1 摘要 top-20 粗筛，导致 ~43% 深层段落在精排前丢失（R3/R4 FAIL 根因）。建议直接对 L2/L3 全库向量检索，或放大粗筛 top-N、或对 L1 用‘paper 内最相关 chunk 的最大相似度’而非摘要相似度来排序候选论文。",
        "**P0 修复映射表**：在 `_handlers.index_code` 中实际写入 `paper_code_mapping`（或由 subagent 生成 method↔code 链接），否则双向检索特性形同虚设。",
        "**P0 代码重复索引去重**：`index_code` 在插入前应按 `repo_name`/`chunk_id` 先删后插（参考 `delete_chunks_by_repo_name`），消除 1067 个重复 chunk_id。",
        "**P1 调用图谱**：code_mapper 解析 tree-sitter 后填充 `calls/called_by`，让 Stage3 调用链扩展生效。",
        "**P1 标题提取**：MinerU 解析后回退到 arXiv API/PDF 元数据补全标题，避免 title=arxivID；对历史坏数据做一次性回填。",
        "**P2 混合检索**：在 retrieval 中加入 LanceDB FTS（BM25）并与向量分数融合（RRF），改善代码/精确术语/符号召回。",
        "**P2 相关性下限**：对检索结果加最低相似度阈值，空/离题 query 应返回空，避免无依据上下文注入。",
        "**P2 状态机 / 作者元数据**：清理 `code_pending` 转移逻辑；索引时写入 authors。",
        "**（已验证可不优先）e5 前缀**：A/B 显示加 `query:`/`passage:` 前缀对本库标题/摘要检索 ΔMRR 仅 +0.003，**未构成显著问题**，无需为此对全库重嵌入；若未来引入跨语言/非对称检索可再评估。",
        "回归：每次新增论文/改检索后重跑 `uv run --env-file .env python tests/run_all.py`（或 `--render-only` 仅重渲染报告）对比指标。",
    ]


def _render_only():
    import json
    s = json.loads((C.OUTPUTS_DIR / "summary.json").read_text(encoding="utf-8"))
    dq, rq, ab = s["data_quality"], s["retrieval_quality"], s["embedding_prefix_ab"]
    (C.TESTS_DIR / "REPORT.md").write_text(render_report(dq, rq, ab), encoding="utf-8")
    print("已从 outputs/summary.json 重渲染 tests/REPORT.md")


def main():
    import sys
    if "--render-only" in sys.argv:
        _render_only()
        return
    print("######## MAPCE 索引质量测试 ########")
    dq = d.run()
    rq = r.run()
    ab = e.run()

    summary = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "overall": {"data_quality": dq["overall"], "retrieval_quality": rq["overall"],
                    "embedding_prefix_ab": ab["overall"]},
        "data_quality": dq,
        "retrieval_quality": rq,
        "embedding_prefix_ab": ab,
    }
    C.write_json("summary.json", summary)

    report = render_report(dq, rq, ab)
    (C.TESTS_DIR / "REPORT.md").write_text(report, encoding="utf-8")
    print("\n######## 完成 ########")
    print(f"汇总: tests/outputs/summary.json")
    print(f"报告: tests/REPORT.md")


if __name__ == "__main__":
    main()
