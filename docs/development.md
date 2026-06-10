# 开发

## 环境

```bash
uv sync        # 含 dev 依赖
uv run pytest  # 运行测试
```

## 依赖管理

```bash
uv add <package>        # 添加运行时依赖
uv add --dev <package>   # 添加开发依赖
```

## 项目结构速览

- `core/` — 纯 Python 库，不依赖 MCP，可独立在 Jupyter / 脚本中使用
- `mcp/` — 薄封装层，调用 core 并注册为 MCP 工具
- `db/` — LanceDB 连接与 CRUD，PyArrow Schema
- `mineru/` — MinerU API 的 httpx 封装，替代原 paper-research-blog 的 shell 脚本
- `prompts/` — Jinja2 提示词模板，可独立迭代而不改代码
- `sources/` — 适配器模式，可扩展新的数据源

## 添加新的数据源

1. 在 `sources/` 下新建文件，实现搜索/下载/导入逻辑
2. 核心索引统一走 `core/indexing.py` 的 `index_paper` 或 `_index_from_mineru_dir`

## 切换嵌入模型

修改 `.env` 中的 `MAPCE_EMBEDDING_MODEL` 值，然后重新初始化或调用 `re_embed_all()`：

```python
from mapce.core.incremental import re_embed_all
re_embed_all()
```
