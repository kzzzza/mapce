# MCP 工具参考

每个工具提供两种调用方式：Claude Code 中自然语言交互，以及 Python SDK 直接调用。

---

## search_papers — 四阶段论文检索

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 自然语言或关键词 |
| `top_k` | int | 否 | 最大结果数（默认 10） |
| `year_min` | int | 否 | 最早发表年份 |
| `year_max` | int | 否 | 最晚发表年份 |
| `venue` | string | 否 | 发表来源（如 CoRL、ICRA、RSS） |

**自然语言（Claude Code）**

> 搜索关于 diffusion policy 的论文
> 搜索 2024 年之后发表在 CVPR 的 image generation 论文

**Python SDK**

```python
from mapce.core.retrieval import search_papers

results, intent = search_papers('diffusion models generative modeling')
for r in results:
    print(f'[{r.year}] {r.title}')
    print(f'  {r.section_path}')
    print(f'  {r.content[:200]}')

# 带过滤条件
results, _ = search_papers('image generation', year_min=2024, venue='CVPR')
```

---

## search_code — 代码检索

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 函数名、类名、功能描述等 |
| `top_k` | int | 否 | 最大结果数（默认 10） |
| `repo_name` | string | 否 | 限定仓库名 |

**自然语言（Claude Code）**

> BFM-Zero 里的 FBModel 是怎么实现的
> 找一下 reward_inference 这个函数

**Python SDK**

```python
from mapce.core.retrieval import search_code

results, _ = search_code('FBModel forward backward', top_k=10)
for r in results:
    print(f'{r.repo_name}/{r.file_path}')
    print(f'  symbol: {r.symbol_name}')
    print(f'  language: {r.language}')
    print(f'  {r.content[:200]}')
```

---

## index_paper — 索引新论文

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | PDF 路径、arXiv ID 或 URL |
| `source_type` | string | 否 | `"local"` / `"arxiv"` / `"url"`（默认 `"local"`） |
| `language` | string | 否 | `"en"` 或 `"ch"`（默认 `"en"`） |

**自然语言（Claude Code）**

> 帮我索引这篇论文 https://arxiv.org/abs/2303.04137
> 索引我下载目录里的 diffusion_policy.pdf

**Python SDK**

```python
from mapce.core.indexing import index_paper, index_paper_from_arxiv
from pathlib import Path

# arXiv
paper_id = index_paper_from_arxiv('2303.04137')

# 本地 PDF
paper_id = index_paper(Path.home() / 'Downloads' / 'paper.pdf')

# 本地 PDF 带元数据
paper_id = index_paper(
    Path.home() / 'Downloads' / 'paper.pdf',
    metadata={'title': 'Diffusion Policy', 'authors': ['Chi C'], 'year': 2023},
    language='en',
)
```

---

## index_code — 克隆并索引代码仓库

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repo_url` | string | 是 | Git 仓库 URL |
| `paper_id` | string | 是 | 要关联的论文 ID |

**自然语言（Claude Code）**

> 把 BFM-Zero 的代码库索引到论文 2511.04131

**Python SDK**

```python
import asyncio
from mapce.mcp._handlers import index_code

result = asyncio.run(index_code(
    repo_url='https://github.com/LeCAR-Lab/BFM-Zero',
    paper_id='2511.04131',
))
print(result)
```

---

## list_indexed_papers — 列出已索引论文

无参数。

**自然语言（Claude Code）**

> 索引库里有哪些论文

**Python SDK**

```python
import asyncio
from mapce.mcp._handlers import list_indexed_papers

result = asyncio.run(list_indexed_papers())
print(result)
```

---

## get_paper_overview — 查看论文详情

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | 论文 ID |

**自然语言（Claude Code）**

> 帮我看看 2511.04131 这篇论文的章节结构

**Python SDK**

```python
from mapce.core.retrieval import get_paper_overview

overview = get_paper_overview('2511.04131')
print(f"Title: {overview['title']}")
print(f"Sections: {len(overview['sections'])}")
print(f"Figures: {len(overview['figures'])}")
print(f"Tables: {len(overview['tables'])}")
```

---

## delete_paper — 删除论文

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `paper_id` | string | 是 | 要删除的论文 ID |

**自然语言（Claude Code）**

> 把 2303.04137 这篇论文从索引库删掉

**Python SDK**

```python
from mapce.core.incremental import delete_paper_safe

summary = delete_paper_safe('2303.04137')
print(f"Deleted: {summary['chunks_deleted']} chunks, {summary['mappings_deleted']} mappings")
```

---

## get_stats — 索引统计

无参数。

**自然语言（Claude Code）**

> 索引库现在多大

**Python SDK**

```python
import asyncio
from mapce.mcp._handlers import get_stats

result = asyncio.run(get_stats())
print(result)
```
