[English summary](../README_EN.md#research-workflow-skills)<br>[← 返回](../README.md)

# MAPCE 科研工作流 Skills

这套 Skill 位于仓库根目录 `skills/`，由一个总入口和五个专用 Skill 组成。Agent 负责研究过程和写作，MAPCE 负责本地论文、代码、引用元数据和正文证据定位。TUI 仍只用于数据库管理。

## 安装

```bash
mapce skills list
mapce skills install --target codex
mapce skills install --target claude
mapce skills install --target agents
mapce skills install --path /custom/skill-directory
```

目标目录分别为 `~/.codex/skills`、`~/.claude/skills` 和 `~/.agents/skills`。`--target` 与 `--path` 必须二选一。

```bash
mapce skills status --target codex
mapce skills install --target codex --update
```

安装器在目标目录保存 `.mapce-research-skills.json`，其中只有 Skill 版本和文件校验值，不含论文、密钥或用户内容。普通安装不覆盖不同内容；`--update` 只更新上次由 MAPCE 安装且此后未修改的文件。

## 六个 Skill

| Skill | 使用场景 |
|---|---|
| `mapce-research-workflow` | 一个请求跨越调研、阅读、实验或写作两个以上阶段 |
| `mapce-literature-discovery` | 检索本地与外部论文、去重、筛选和准备索引清单 |
| `mapce-paper-reading` | 深读单篇论文、图表、方法、代码和复现信息 |
| `mapce-literature-review` | 快速综述、PRISMA 式综述、方法比较和发展历史 |
| `mapce-experimental-design` | CS、AI 和机器人实验的基线、指标、消融、复现与安全设计 |
| `mapce-scientific-writing` | 使用证据台账撰写和审计 Markdown/LaTeX 论文 |

## 启动研究项目

总入口会先确认研究问题、输出目录、综述模式和论文索引授权。用户没有指定目录时，推荐实际运行目录下的 `research/<项目名>/`，获得确认后才写入。

论文索引授权有两种模式。`autonomous` 表示用户明确允许 Agent 在当前项目中自主索引经过筛选、身份核验且可公开访问的相关论文；`per_paper` 表示每篇论文调用 `index_paper` 前都要单独确认。没有回答、无人值守执行或仅允许外部检索时，默认使用 `per_paper`。授权不会跨项目继承，也不包含删除论文或索引代码仓库。

综述模式包括：

- 快速综述，用于低成本了解领域，仍保留查询、筛选和证据记录。
- PRISMA 式综述，用于协议驱动的检索与筛选，额外记录流程计数、排除原因和质量评价。

工作区主要文件为：

```text
project.json
search/search_log.jsonl
papers/candidates.csv
papers/screening.csv
evidence/source_manifest.json
evidence/evidence_ledger.csv
evidence/claims.csv
notes/
design/
manuscript/review.md
manuscript/review.tex
manuscript/references.bib
```

## 论文发现和索引

发现流程先调用 MAPCE `search_papers`，再按需查询 arXiv 和 OpenAlex，并使用 Crossref 核对 DOI 元数据。候选按 DOI、arXiv ID、规范化标题和年份去重。

外部候选会先写入清单。逐篇授权模式下，用户选择后才调用 `index_paper`；自主授权模式下，Agent 可以索引符合项目范围的候选，但仍须先核对标题与 arXiv ID 或 DOI，并检查本地是否已经存在。任务逐篇执行。arXiv ID 使用 `source_type=arxiv`；开放论文 URL 使用 `source_type=url`。只有 DOI、摘要页或付费页面的候选不会伪装成可索引 PDF。

## 证据和写作状态

论文主张通过 `paper_id + chunk_id + section_path` 定位。MAPCE 没有可靠页码时不生成页码。

引用和证据状态包括：

- `stored_metadata_only`，来自 MAPCE 本地元数据。
- `authority_checked`，引用元数据经过权威来源核对。
- `human_verified`，用户已经打开原文并核对主张和位置。
- `missing`、`conflicting` 或 `retracted`，需要继续处理。

Crossref 核对 DOI 不能代替正文证据核验。存在未核验来源时，Markdown 和 LaTeX 保留 `DRAFT — NOT FOR SUBMISSION`。

## 资源与内存边界

Skill 只通过 MCP 使用现有单例服务，不直接导入 MAPCE 数据库模块。外部搜索脚本只处理元数据。论文索引串行执行，避免同时运行多个解析任务或重复加载嵌入模型。
