<p align="center">
  <img src="img/logo.png" alt="MAPCE logo" width="100%">
</p>

[English](README_EN.md)

MAPCE是一个面向泛 CS 学术研究的个人 RAG 知识库。支持论文 PDF 解析、代码仓库结构化分块，通过向量+全文混合检索，以 MCP Server 形式为 AI Agent 提供可复用的学术知识检索能力。

### 适用场景

- 文献调研与 systematic review — 跨论文语义检索，按时间/会议过滤
- 算法实现参考 — 论文方法 ↔ 源代码的双向检索与调用链追踪
- 实验复现辅助 — 表格（benchmark 数据）、图片（架构图）、训练配置的定向检索
- 科研写作 — 快速定位相关工作的具体章节、方法和实验结论

## 安装

- Python ≥ 3.11 · [uv](https://astral.sh/uv) 包管理器 · [MinerU API Token](https://mineru.net/apiManage/token)（免费注册）
- macOS / Linux（推荐 Apple Silicon）· 16 GB 内存 · ~5 GB 磁盘

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 进入项目，同步依赖
cd mapce
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 MINERU_API_TOKEN
# 中国大陆用户取消代理变量的注释并填入代理地址

# 4. 初始化数据库并下载嵌入模型（仅首次，约 2 GB）
uv run --env-file .env python scripts/init_db.py
```

### .env 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINERU_API_TOKEN` | — | **必填**。MinerU API 密钥 |
| `MAPCE_DATA_DIR` | `~/.mapce/data` | LanceDB 数据目录 |
| `MAPCE_EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | 嵌入模型（fastembed） |
| `MAPCE_LOG_LEVEL` | `INFO` | 日志级别 |
| `http_proxy` / `https_proxy` | — | HTTP 代理（国内必填） |

### 代理配置（中国大陆用户）

编辑 `.env`，取消注释：

```bash
http_proxy=http://127.0.0.1:9674
https_proxy=http://127.0.0.1:9674
```

`uv run --env-file .env` 和 MCP Server 的 `--env-file` 参数自动加载，无需手动 export。

### 选择嵌入模型

```bash
# 查看可用模型
uv run python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"
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

重启 Claude Code，批准 MAPCE 服务器后即可自然语言交互：

> 搜索关于 diffusion policy 在机器人控制中的应用的论文
>
> 这篇论文有对应的开源代码吗？帮我索引
>
> 检索 transformer 架构中关于 attention 机制的相关论文和代码

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/usage.md](docs/usage.md) | Python SDK 用法、MCP 工具参考（8 个）、Claude Code 集成 |
| [docs/data-sources.md](docs/data-sources.md) | 数据源适配器（arXiv、Zotero、本地 PDF、目录批量） |
| [docs/storage.md](docs/storage.md) | 存储形式：LanceDB、模型缓存、临时文件、清理 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见问题与解决方案 |
| [docs/development.md](docs/development.md) | 开发指南（架构、分块策略、项目结构、添加数据源） |
