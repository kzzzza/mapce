[English](usage_EN.md)<br>[← Back](../README.md)

# 使用方法

MAPCE 提供 TUI 数据库管理界面、可脚本化 CLI、Agent 使用的 MCP 工具和 Python SDK。TUI、CLI 与 MCP 共用一个本地后台服务；Python SDK 仍可用于开发与维护脚本。

## TUI 数据库管理

```bash
mapce
```

TUI 定位为数据库管理与状态可视化界面，论文理解和笔记撰写仍由通过 MCP 调用 MAPCE 的 Agent 完成。

| 页签 | 功能 |
|------|------|
| 总览 | 服务内存、论文/chunk 数量、数据库大小、代码状态和辅助索引状态 |
| 论文库 | 列表与筛选、内部 ID/arXiv ID 精确查找、语义检索、摘要/目录/仓库查看、删除确认 |
| 索引 | 提交论文与代码索引任务，审核、忽略或指定候选仓库，删除某个仓库的代码索引 |
| 任务 | 查看串行写任务，取消排队任务，重试失败任务 |
| 系统 | 服务路径、内存、索引诊断、最近日志、重新连接和确认后重启 |

界面要求至少 76×22 的终端尺寸。按 `q` 只退出 TUI，不会停止后台服务；需要停止服务时使用 `mapce serve-kill`。

## CLI 管理命令

首次全局安装后保存默认环境文件，之后命令可以在任意目录运行：

```bash
uv tool install /path/to/mapce
mapce config set-env /path/to/mapce/.env
mapce config show
```

```bash
mapce papers list
mapce papers find 2412.04368 --json
mapce papers show 2412.04368
mapce search paper "diffusion policy" --top-k 10
mapce search content 2412.04368 "training objective"
mapce index paper 2501.00001 --type arxiv
mapce index code https://github.com/owner/repo --paper 2501.00001
mapce jobs list
mapce stats
mapce doctor
```

科研工作流 Skill 可以独立安装，不需要先加载 `.env` 或启动后台服务：

```bash
mapce skills list
mapce skills install --target codex
mapce skills status --target codex
mapce skills install --target codex --update
```

也可以使用 `--target claude`、`--target agents` 或 `--path` 指定其他 Agent 的 Skill 目录。安装完整说明见 [research-skills.md](research-skills.md)。

索引和删除通过后台任务队列串行执行。带 `--json` 的命令适合脚本读取；完整参数使用 `mapce <命令> --help` 查看。

## Python SDK

```bash
cd mapce
uv run python
```

### 索引论文

```python
# 从 arXiv 索引
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')

# 索引本地 PDF
from mapce.core.indexing import index_paper
from pathlib import Path
paper_id = index_paper(Path.home() / 'Downloads' / 'paper.pdf')
```

### 索引代码

新论文完成正文索引后，会从 Markdown 正文和 arXiv comment 中识别 GitHub 仓库。高可信仓库自动索引；歧义链接仅记录为候选；未发现仓库时标记为 `no_code`，论文内容仍可正常检索。用户明确提供的仓库按高可信来源处理。

```python
import asyncio
from mapce.mcp._handlers import index_code
result = asyncio.run(index_code(
    repo_url='https://github.com/LeCAR-Lab/BFM-Zero',
    paper_id='2511.04131'
))
```

### 检索

```python
from mapce.core.retrieval import search_papers, search_code, search, SearchIntent

# 论文
results, intent = search_papers('transformer attention mechanism efficiency')
for r in results:
    print(f'[{r.year}] {r.title} — {r.section_path}')

# 代码
results, _ = search_code(
    'self-attention implementation',
    paper_id='2511.04131',
    repo_url='https://github.com/LeCAR-Lab/BFM-Zero',
)

# 混合检索
intent = SearchIntent(intent='hybrid', sub_type='general')
results, _ = search('graph neural network message passing', intent=intent)
```

### 查看索引

```python
import asyncio
from mapce.mcp._handlers import get_stats, list_indexed_papers
print(asyncio.run(get_stats()))
print(asyncio.run(list_indexed_papers()))
```

`get_stats` 的 `vector_index` 字段会返回 IVF_PQ/标量索引、已覆盖行数、未覆盖行数和当前查询参数。命令行也可以只读检查：

```bash
.venv/bin/python scripts/manage_vector_index.py
```

## MCP 工具参考

所有工具都声明 `outputSchema`。新版 MCP 客户端可读取 `structuredContent`；兼容旧客户端的 JSON `TextContent` 仍会同时返回。失败结果设置 `isError=true`，并包含稳定的 `error_code`。

### search_papers

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 自然语言或关键词 |
| `top_k` | int | 否 | 最大结果数（默认 10） |
| `year_min` | int | 否 | 最早发表年份 |
| `year_max` | int | 否 | 最晚发表年份 |
| `venue` | string | 否 | 发表来源（如 CVPR、NeurIPS） |

> 搜索 2024 年之后发表在 CVPR 的 image generation 论文

### search_code

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 函数名、类名、功能描述等 |
| `top_k` | int | 否 | 最大结果数（默认 10） |
| `repo_name` | string | 否 | 限定仓库名 |
| `paper_id` | string | 否 | 限定为某篇论文关联的代码 |
| `repo_url` | string | 否 | 限定规范化的 GitHub 仓库 URL |

> 找一下 BFM-Zero 里的 FBModel 实现

### index_paper

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | PDF 路径、arXiv ID 或 URL |
| `source_type` | string | 否 | `local` / `arxiv` / `url`（默认 `local`） |
| `language` | string | 否 | `en` 或 `ch`（默认 `en`） |

> 帮我索引这篇论文 https://arxiv.org/abs/2303.04137

### index_code

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repo_url` | string | 是 | Git 仓库 URL |
| `paper_id` | string | 是 | 关联的论文 ID |

> 为论文 2511.04131 索引它的代码仓库

### get_paper_overview

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | 论文 ID |

> 帮我看看这篇论文的章节结构、图表清单

论文概览还会返回 `citation` 字段，内容与 `get_paper_citation` 一致。TUI 论文详情会直接展示标准文本、BibTeX、CSL-JSON、DOI、URL、缺失字段和核验状态。

### get_paper_citation

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | 已索引论文的统一 ID |

返回本地索引中已有的标题、作者、年份、venue、DOI 和 arXiv ID，并生成稳定的 citation key、标准文本、BibTeX 和 CSL-JSON。该工具不联网，`verification_status=stored_metadata_only` 表示引用仍需由作者对照原始论文或权威元数据源核验。

> 导出论文 2412.04368 的 BibTeX 和 CSL-JSON

### resolve_paper

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `identifier` | string | 是 | 内部论文 ID、arXiv ID、带版本号 ID、`arXiv:` 前缀或 arXiv URL |

该工具只查询本地 `index_meta`，不会联网，也不会加载嵌入模型。版本号会被移除，旧式 ID（如 `hep-th/9901001`）同样支持。

### read_paper_section

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | `resolve_paper` 返回的统一论文 ID |
| `section_path` | string | 二选一 | 精确章节路径 |
| `chunk_id` | string | 二选一 | 目录或检索结果中的 chunk ID |
| `include_subsections` | bool | 否 | 是否包含下级章节，默认 `false` |
| `limit` | int | 否 | 每页 1–20 个 chunk，默认 10 |
| `cursor` | string | 否 | 上一页返回的游标 |

章节读取优先返回 L3 段落，避免重复附带含有相同正文的 L2 大块。结果包含章节、层级、顺序、前后 chunk 和正文，不包含 embedding。

### search_paper_content

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | 要检索的单篇论文 |
| `query` | string | 是 | 论文内部问题或关键词 |
| `top_k` | int | 否 | 返回 1–20 个相关 chunk，默认 10 |

该工具只检索指定论文，可以返回多个正文 chunk；它与 `search_papers` 的“每篇论文最多返回一次”语义相互独立。

### Agent 深度阅读顺序

```text
resolve_paper
  → get_paper_overview
  → get_paper_citation
  → read_paper_section / search_paper_content
  → search_code（论文存在已索引代码时）
  → Agent 组织理解结果或论文笔记
```

MAPCE 返回正文和来源定位，笔记撰写仍由调用它的 Agent 完成。

### 无参数工具

| 工具 | 说明 | 自然语言示例 |
|------|------|-------------|
| `list_indexed_papers` | 列出所有已索引论文及状态 | 索引库里有哪些论文 |
| `delete_paper` | 删除论文 (`paper_id`) | 把 2303.04137 删掉 |
| `get_stats` | 索引统计（论文、代码、chunk、向量索引覆盖率） | 索引库现在多大 |

## MCP Server（Claude Code 集成）

全局安装会同时提供轻量 stdio 命令 `mapce-mcp`。在项目根目录创建 `.mcp.json`，并把命令路径替换为 `command -v mapce-mcp` 的输出：

```json
{
  "mcpServers": {
    "mapce": {
      "command": "/path/to/mapce-mcp",
      "args": []
    }
  }
}
```

重启 Claude Code、批准服务器后即可直接用自然语言调用上述所有工具。stdio 入口只转发请求，不加载 LanceDB 和嵌入模型；同一个 `MAPCE_DATA_DIR` 的客户端会复用唯一后台服务。

```bash
# 服务管理
mapce serve
mapce serve-status
mapce serve-logs
mapce serve-kill

# 调试 stdio 代理
mapce-mcp
```
