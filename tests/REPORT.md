# MAPCE 索引库 数据质量 & 检索质量 测试报告

> 生成时间：2026-06-19 01:08  ·  脚本：`tests/check_0{1,2,3}.py`  ·  全程只读，未改动 `~/.mapce/data`

## 0. 总体结论

| 模块 | 结论 |
|------|------|
| 数据质量 (D1–D8) | ❌ FAIL |
| 检索质量 (R1–R8) | ❌ FAIL |
| e5 前缀 A/B 诊断 | ✅ PASS |

## 1. 索引概览

- 论文总数：**110**　chunk 总数：**68491**　带代码论文：**20**
- source 分布：{'paper': 27014, 'code': 41477}
- chunk 类型分布：{'paper_l1': 110, 'paper_l2': 3088, 'paper_l3': 22291, 'code_l1': 24, 'code_l2': 3724, 'code_l3': 36375, 'code_l4': 848, 'code_config': 372, 'code_l5': 134, 'figure': 1048, 'table': 477}

## 2. 数据质量结果 (D1–D8)

| 检查项 | 结论 | 关键指标 |
|--------|------|----------|
| D1 元数据完整性 | ⚠️ WARN | 6 篇标题=arxivID; authors 覆盖率 0% |
| D2 状态一致性 | ⚠️ WARN | 19 篇 code_pending (17%) |
| D3 chunk 完整性 | ⚠️ WARN | 缺 L1: 0; chunk_count 不一致: 20 |
| D4 内容健康 | ❌ FAIL | 重复 chunk_id 1067(硬缺陷); 空/超短 117 (0.17%); 完全重复内容 11141 |
| D5 嵌入健康 | ✅ PASS | 覆盖 100.00%; 坏向量 0 |
| D6 特殊块(图/表) | ⚠️ WARN | figure 1048 / table 477; 107/110 篇有图 |
| D7 代码图谱 | ⚠️ WARN | call-graph 边数 0; symbol 缺失率 9% |
| D8 Paper↔Code 映射表 | ❌ FAIL | paper_code_mapping 行数 = 0 (期望随 20 篇带代码论文填充) |

<details><summary>展开完整指标</summary>

**D1 元数据完整性** — ⚠️ WARN  
`title_valid_rate`=0.9455; `bad_title_count`=6; `year_coverage`=0.9636; `venue_coverage`=0.9636; `author_coverage`=0.0; `venue_distribution`={arXiv=106, =4}

**D2 状态一致性** — ⚠️ WARN  
`status_distribution`={complete=91, code_pending=19}; `code_pending_count`=19; `code_pending_rate`=0.1727; `has_code_indexed_inconsistent`=0

**D3 chunk 完整性** — ⚠️ WARN  
`papers_missing_l1`=0; `missing_l1_ids`=[]; `chunk_count_mismatch`=20; `l1`=110; `l2`=3088; `l3`=22291

**D4 内容健康** — ❌ FAIL  
`empty_or_short_chunks`=117; `empty_rate`=0.00171; `duplicate_chunk_ids`=1067; `exact_dup_content`=11141; `exact_dup_content_rate`=0.16266

**D5 嵌入健康** — ✅ PASS  
`embedding_coverage`=1.0; `null_embeddings`=0; `wrong_dim`=0; `zero_vectors`=0; `nan_inf_vectors`=0

**D6 特殊块(图/表)** — ⚠️ WARN  
`figure_chunks`=1048; `table_chunks`=477; `figures_missing_path`=1006; `papers_with_figures`=107; `papers_total`=110

**D7 代码图谱** — ⚠️ WARN  
`code_chunks`=41477; `symbol_missing_rate(l2-l5)`=0.0907; `chunks_with_calls`=0; `chunks_with_called_by`=0; `total_graph_edges`=0; `orphan_reference_rate`=0.0; `chunks_with_associated_test`=0; `callgraph_populated`=False

**D8 Paper↔Code 映射表** — ❌ FAIL  
`mapping_rows`=0; `papers_with_code_indexed`=20

</details>

## 3. 检索质量结果 (R1–R8)

| 检查项 | 结论 | 关键指标 |
|--------|------|----------|
| R1 标题→论文 | ✅ PASS | R@1=91% R@5=99% MRR=0.94 |
| R2 摘要首句→论文 | ✅ PASS | R@5=93% MRR=0.91 |
| R3 chunk 自检索 | ❌ FAIL | top1 论文命中=29% MRR=0.33 |
| R4 代码 known-item | ❌ FAIL | file R@5=0.175 |
| R5 过滤正确性 | ✅ PASS | year>=2025 违例 0; venue 仅 ['arXiv'] |
| R6 意图路由 | ✅ PASS | intent acc=96% subtype acc=100% |
| R7 鲁棒性/负样本 | ✅ PASS | 异常 0/4 |
| R8 检索延迟 | ✅ PASS | p50=0.987s p95=1.227s |

<details><summary>展开完整指标</summary>

**R1 标题→论文** — ✅ PASS  
`n`=104; `recall@1`=0.9135; `recall@5`=0.9904; `recall@10`=0.9904; `mrr`=0.9439

**R2 摘要首句→论文** — ✅ PASS  
`n`=103; `recall@1`=0.8932; `recall@5`=0.932; `recall@10`=0.9417; `mrr`=0.9142

**R3 chunk 自检索** — ❌ FAIL  
`n`=150; `top1_paper_hit`=0.2933; `recall@5`=0.38; `mrr`=0.3298

**R4 代码 known-item** — ❌ FAIL  
`n`=40; `file_recall@5`=0.175; `paper_recall@5`=0.175

**R5 过滤正确性** — ✅ PASS  
`year_coverage`=0.9636; `distinct_venues`=[arXiv]; `year_filter_min`=2025; `year_filter_results`=35; `year_filter_violations`=0; `year_filter_correct`=True; `venue_filter_testable`=False

**R6 意图路由** — ✅ PASS  
`n`=24; `intent_accuracy`=0.9583; `subtype_accuracy`=1.0; `confusion`={paper_search->paper_search=9, paper_search->hybrid=1, code_search->code_search=8, hybrid->hybrid=6}

**R7 鲁棒性/负样本** — ✅ PASS  
`queries`=4; `errors`=0; `detail`=[{'query': 'lattice quantum chromodynamics confineme', 'n_results': 39, 'top_paper': '2605.25546', 'error': ''}, {'query': 'asdkjh qweoiu zxcmnv random gibberish to', 'n_results': 38, 'top_paper': '2401.16889', 'error': ''}, {'query': '   ', 'n_results': 31, 'top_paper': '2401.16889', 'error': ''}, {'query': 'the', 'n_results': 34, 'top_paper': '2401.16889', 'error': ''}]

**R8 检索延迟** — ✅ PASS  
`n`=104; `p50_s`=0.987; `p95_s`=1.227; `max_s`=2.776; `mean_s`=1.033

</details>

## 4. e5 嵌入前缀 A/B 诊断

查询标题 60 条，候选 L1 110 篇，手算余弦相似排名：

| 方案 | Recall@1 | Recall@5 | Recall@10 | MRR |
|------|----------|----------|-----------|-----|
| A 无前缀（当前实现） | 98% | 100% | 100% | 0.989 |
| B e5 规范前缀 | 98% | 100% | 100% | 0.992 |
| **Δ (B−A)** | +0% | +0% | — | +0.003 |

结论：✅ PASS — 差异不显著 (ΔMRR=0.003)

> 当前 retrieval.py 仅使用向量检索；fulltext_search(FTS) 列存在但从未被查询，README 宣称的‘向量+全文混合检索’暂未生效。

## 5. 问题清单与优先级

| 优先级 | 问题 | 证据 | 影响 |
|--------|------|------|------|
| P0 | Paper↔Code 映射表为空 | paper_code_mapping 行数=0 | 双向映射/调用链追踪功能不可用；index_code 从不写映射表 |
| P1 | 代码调用图谱未填充 | calls/called_by 边数=0（41477 个 code chunk） | 检索的调用链扩展(Stage3)永不触发 |
| P0 | 存在重复 chunk_id | 1067 个重复 chunk_id（多为 code:* ，见 duplicate_chunk_ids.csv） | 代码仓库被重复索引、未去重；同 ID 多行污染检索与统计 |
| P1 | 论文标题提取失败 | 6 篇 title=arxivID（见 bad_titles.csv） | 标题→论文检索失败、列表可读性差 |
| P2 | 作者信息全缺失 | L1 authors 覆盖率 0% | 按作者检索/引用不可用 |
| P2 | 状态停留 code_pending | 19 篇 status=code_pending（见 code_pending.csv） | 状态机未收敛，统计口径混乱 |
| P2 | 混合检索未生效（实为纯向量） | retrieval.py 从不查询 fulltext_search 列 | 精确术语/符号召回偏弱，与 README 描述不符 |
| P0 | 细粒度(段落级)检索召回过低 | chunk 自检索 top1=29%, R@5=38%；诊断：仅约 57% 的 L3 段落，其所属论文能挺过 Stage1 的 top-20 L1(摘要)粗筛 | Stage1 用 L1 摘要粗筛+语料高度同质 → 深层段落在精排前就被丢弃，问具体细节常找错论文 |
| P1 | 代码检索召回过低 | file Recall@5=0.175 | search_code 同样先按论文摘要粗筛，代码类 query 与摘要语义错位 → 候选集常不含目标文件 |
| P2 | 无相关性下限(无 score floor) | 空串/乱码/停用词 query 仍返回 30+ 条结果且给出 top_paper | 对离题/空 query 也注入上下文，易产生无依据回答 |

## 6. 改进建议（仅建议，未实现）

- **P0 改 Stage1 粗筛策略（最影响检索质量）**：当前以 L1 摘要 top-20 粗筛，导致 ~43% 深层段落在精排前丢失（R3/R4 FAIL 根因）。建议直接对 L2/L3 全库向量检索，或放大粗筛 top-N、或对 L1 用‘paper 内最相关 chunk 的最大相似度’而非摘要相似度来排序候选论文。
- **P0 修复映射表**：在 `_handlers.index_code` 中实际写入 `paper_code_mapping`（或由 subagent 生成 method↔code 链接），否则双向检索特性形同虚设。
- **P0 代码重复索引去重**：`index_code` 在插入前应按 `repo_name`/`chunk_id` 先删后插（参考 `delete_chunks_by_repo_name`），消除 1067 个重复 chunk_id。
- **P1 调用图谱**：code_mapper 解析 tree-sitter 后填充 `calls/called_by`，让 Stage3 调用链扩展生效。
- **P1 标题提取**：MinerU 解析后回退到 arXiv API/PDF 元数据补全标题，避免 title=arxivID；对历史坏数据做一次性回填。
- **P2 混合检索**：在 retrieval 中加入 LanceDB FTS（BM25）并与向量分数融合（RRF），改善代码/精确术语/符号召回。
- **P2 相关性下限**：对检索结果加最低相似度阈值，空/离题 query 应返回空，避免无依据上下文注入。
- **P2 状态机 / 作者元数据**：清理 `code_pending` 转移逻辑；索引时写入 authors。
- **（已验证可不优先）e5 前缀**：A/B 显示加 `query:`/`passage:` 前缀对本库标题/摘要检索 ΔMRR 仅 +0.003，**未构成显著问题**，无需为此对全库重嵌入；若未来引入跨语言/非对称检索可再评估。
- 回归：每次新增论文/改检索后重跑 `uv run --env-file .env python tests/run_all.py`（或 `--render-only` 仅重渲染报告）对比指标。

---

原始数据：`tests/outputs/*.json`、问题明细 `tests/outputs/*.csv`。
