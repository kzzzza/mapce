<p align="center">
  <img src="img/logo.png" alt="MAPCE logo" width="100%">
</p>


MAPCE是一个面向泛 CS 学术研究的个人 RAG 知识库。支持论文 PDF 解析、代码仓库结构化分块，通过向量+全文混合检索，以 MCP Server 形式为 AI Agent 提供可复用的学术知识检索能力。

### 适用场景

- 文献调研与 systematic review — 跨论文语义检索，按时间/会议过滤
- 算法实现参考 — 论文方法 ↔ 源代码的双向检索与调用链追踪
- 实验复现辅助 — 表格（benchmark 数据）、图片（架构图）、训练配置的定向检索
- 科研写作 — 快速定位相关工作的具体章节、方法和实验结论

## 快速开始

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 进入项目，同步依赖
cd mapce
uv sync

# 3. 配置 MinerU 密钥
cp .env.example .env
# 编辑 .env → 填入 MINERU_API_TOKEN（从 https://mineru.net/apiManage/token 获取）

# 4. 初始化数据库和嵌入模型（仅首次）
uv run python scripts/init_db.py
```

## 接入 Claude Code

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

代理配置在 `.env` 中（见 `cp .env.example .env`），无需在 `.mcp.json` 中重复设置。

重启 Claude Code，批准 MAPCE 服务器后即可自然语言交互：

> 搜索关于 diffusion policy 在机器人控制中的应用的论文
>
> 这篇论文有对应的开源代码吗？帮我索引
>
> 检索 transformer 架构中关于 attention 机制的相关论文和代码

## Python SDK 速览

```python
# 索引论文
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')

# 索引代码
import asyncio
from mapce.mcp._handlers import index_code
result = asyncio.run(index_code(repo_url='https://github.com/...', paper_id='2511.04131'))

# 检索
from mapce.core.retrieval import search_papers, search_code
results, _ = search_papers('diffusion policy visuomotor control')
results, _ = search_code('self-attention transformer implementation')
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/installation.md](docs/installation.md) | 详细安装步骤、环境配置、代理设置 |
| [docs/usage.md](docs/usage.md) | Python SDK 完整用法、MCP Server 配置与调试 |
| [docs/mcp-tools.md](docs/mcp-tools.md) | 8 个 MCP 工具参考（参数、返回值、示例） |
| [docs/data-sources.md](docs/data-sources.md) | 数据源适配器（arXiv、Zotero、本地 PDF、目录批量） |
| [docs/architecture.md](docs/architecture.md) | 索引流水线、检索流水线、分块策略、项目结构 |
| [docs/storage.md](docs/storage.md) | 存储形式：LanceDB、模型缓存、临时文件、清理 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见问题与解决方案 |
| [docs/development.md](docs/development.md) | 开发指南（测试、添加依赖） |

## 运行环境

- Python ≥ 3.11 · [uv](https://astral.sh/uv) 包管理器 · [MinerU API Token](https://mineru.net/apiManage/token)
- macOS / Linux · 16 GB RAM · ~5 GB 磁盘
