# MAPCE 索引质量测试

对**已建索引**（`~/.mapce/data`）做数据质量与检索质量评估。全程**只读**，不改动库、不写修复。

## 运行

```bash
# 一键：跑全部 + 生成报告
uv run --env-file .env python tests/run_all.py

# 或单独运行某一模块
uv run --env-file .env python tests/check_01_data_quality.py       # 数据质量（快，不加载模型）
uv run --env-file .env python tests/check_02_retrieval_quality.py  # 检索质量（需 e5 模型）
uv run --env-file .env python tests/check_03_embedding_prefix_ab.py# e5 前缀 A/B 诊断
```

> 用 `check_*` 前缀而非 `test_*`，避免被 pytest 自动收集（这些是测量脚本，不是断言用例）。

## 脚本

| 脚本 | 内容 | 依赖嵌入模型 |
|------|------|--------------|
| `common.py` | 共享：连库、阈值判定器(grade)、Recall/MRR、JSON/CSV 写出 | 否 |
| `check_01_data_quality.py` | D1 元数据 / D2 状态一致性 / D3 chunk 完整性 / D4 内容健康 / D5 嵌入健康 / D6 图表 / D7 代码图谱 / D8 映射表 | 否 |
| `check_02_retrieval_quality.py` | R1 标题→论文 / R2 摘要→论文 / R3 chunk 自检索 / R4 代码 / R5 过滤 / R6 意图 / R7 鲁棒性 / R8 延迟 | 是 |
| `check_03_embedding_prefix_ab.py` | e5 `query:`/`passage:` 前缀 A/B 对比 | 是 |
| `run_all.py` | 编排三者 + 渲染 `REPORT.md` | 是 |

## 阈值（PASS / WARN / FAIL）

判定逻辑见 `common.grade()`。关键阈值：

- D1 标题有效率 ≥0.95 / ≥0.85；D2 code_pending 占比 ≤0.05 / ≤0.20；D3 缺 L1 =0 / ≤2；
  D4 空内容率 ≤0.5% / ≤2%；D5 嵌入覆盖 ≥0.99 且 0 坏向量；D7 孤儿引用率 ≤0.10 / ≤0.30；
  D8 映射表 0 行直接 FAIL。
- R1 Recall@5 ≥0.85 / ≥0.70；R2 Recall@5 ≥0.70 / ≥0.50；R3 top1 论文命中 ≥0.90 / ≥0.75；
  R4 file Recall@5 ≥0.70 / ≥0.50；R6 意图准确率 ≥0.80 / ≥0.65；R8 p95 延迟 ≤2s / ≤5s。
- E1 前缀 A/B：加前缀后 ΔMRR ≥0.05 → WARN（确认需修复）。

## 产物

```
tests/REPORT.md                  # 中文测试报告（人读）
tests/outputs/
  data_quality.json              # D1–D8 指标
  retrieval_quality.json         # R1–R8 指标
  embedding_prefix_ab.json       # A/B 指标
  summary.json                   # 全量汇总
  bad_titles.csv / code_pending.csv / chunk_count_mismatch.csv
  r1_title_misses.csv / r6_intent.csv
```

## Ground truth 说明

无需人工标注：known-item（标题/摘要→对应论文）、chunk 自检索（chunk 内容→所属论文）均由
索引自身派生，故指标可复现、可回归。R3 自检索接近满分是脚本/嵌入健康的 sanity 基线。
