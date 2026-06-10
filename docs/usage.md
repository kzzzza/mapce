# 使用方法

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
print(result)
```

### 检索

```python
# 论文检索
from mapce.core.retrieval import search_papers
results, intent = search_papers('transformer attention mechanism efficiency')
for r in results:
    print(f'[{r.year}] {r.title}')
    print(f'  {r.section_path}')
    print(f'  {r.content[:200]}')
    print()

# 代码检索
from mapce.core.retrieval import search_code
results, _ = search_code('self-attention flash attention implementation')
for r in results:
    print(f'{r.repo_name}/{r.file_path} :: {r.symbol_name}')

# 混合检索（论文+代码）
from mapce.core.retrieval import search, SearchIntent
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

## MCP Server（Claude Code 集成）

### 配置

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
      ],
    }
  }
}
```

`"/path/to/mapce"` 替换为实际路径。代理和其他环境变量统一在 `.env` 中配置，`--env-file` 自动加载。

### 使用

重启 Claude Code，批准 MAPCE 服务器后，直接用自然语言交互：

> 搜索关于扩散策略（diffusion policy）的最新论文
>
> 帮我索引这篇论文 https://arxiv.org/abs/2303.04137
>
> 看看我的索引库有哪些论文
>
> 为论文 2303.04137 索引它的代码仓库
>
> BFM-Zero 的 Forward-Backward 模型是怎么实现的？

### 调试

```bash
# 独立启动 MCP Server，查看日志
uv run python -m mapce.mcp.server
# Ctrl+C 停止
```
