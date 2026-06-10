[English](usage_EN.md)<br>[← Back](../README.md)

# 使用方法

可以通过 Python SDK 直接调用，或通过 Claude Code 自然语言交互。两种方式共享同一套 MCP 工具。

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
results, _ = search_code('self-attention implementation')

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

## MCP 工具参考

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

### 无参数工具

| 工具 | 说明 | 自然语言示例 |
|------|------|-------------|
| `list_indexed_papers` | 列出所有已索引论文及状态 | 索引库里有哪些论文 |
| `delete_paper` | 删除论文 (`paper_id`) | 把 2303.04137 删掉 |
| `get_stats` | 索引统计（论文数、代码数、chunk 数） | 索引库现在多大 |

## MCP Server（Claude Code 集成）

在项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "mapce": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--directory", "/path/to/mapce",
        "--env-file", "/path/to/mapce/.env",
        "python", "-m", "mapce.mcp.server"
      ]
    }
  }
}
```

`/path/to/mapce` 替换为实际路径。重启 Claude Code、批准服务器后即可直接用自然语言调用上述所有工具。

```bash
# 独立启动调试
uv run python -m mapce.mcp.server
```
