<p align="center">
  <img src="img/logo.png" alt="MAPCE logo" width="100%">
</p>

[English](README_EN.md)

**MAPCE** 是一个面向泛 CS 学术研究的个人 RAG 知识库。支持论文 PDF 解析、代码仓库结构化分块，通过向量+全文混合检索，以 MCP Server 形式为 AI Agent 提供可复用的学术知识检索能力。

> [关于这个项目的bolg](https://kzzzza.github.io/2026/06/09/Tool_agent_paper_research/)

### 适用场景

- 文献调研与 systematic review — 跨论文语义检索，按时间/会议过滤
- 算法实现参考 — 论文方法 ↔ 源代码的双向检索与调用链追踪
- 实验复现辅助 — 表格（benchmark 数据）、图片（架构图）、训练配置的定向检索
- 科研写作 — 快速定位相关工作的具体章节、方法和实验结论

## 安装

- Python ≥ 3.11 · [uv](https://astral.sh/uv) 包管理器 · [MinerU API Token](https://mineru.net/apiManage/token)（免费注册）
- macOS / Linux（推荐 Apple Silicon）· 16 GB 内存 · ~3 GB 磁盘

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 进入项目，同步依赖
git clone https://github.com/kzzzza/mapce.git
cd mapce
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 MINERU_API_TOKEN
# 中国大陆用户取消代理变量的注释并填入代理地址

# 4. 初始化数据库并下载嵌入模型（仅首次，约 2.1 GB）
uv run --env-file .env python scripts/init_db.py
```

### .env 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINERU_API_TOKEN` | — | **必填**。MinerU API 密钥 |
| `MAPCE_DATA_DIR` | `~/.mapce/data` | LanceDB 数据目录 |
| `MAPCE_EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | 嵌入模型（fastembed） |
| `MAPCE_EMBEDDING_CACHE_DIR` | `$MAPCE_DATA_DIR/models/fastembed` | 嵌入模型持久缓存目录 |
| `MAPCE_SERVICE_PORT` | `8765` | 本地单实例后台服务端口，仅监听 `127.0.0.1` |
| `MAPCE_WARMUP_EMBEDDING` | `0` | 是否在服务启动时预加载嵌入模型；默认按需加载 |
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

MAPCE 通过一个本地后台服务集中持有 LanceDB 连接和嵌入模型。同一个 `MAPCE_DATA_DIR` 只运行一个服务；Claude Code 启动的 stdio 进程是轻量代理，会自动启动或复用后台服务。原有 MCP 配置不需要改变。

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

### 后台服务管理

```bash
uv run --env-file .env mapce serve          # 启动或复用后台服务
uv run --env-file .env mapce serve-status   # 查看 PID、端口和模型加载状态
uv run --env-file .env mapce serve-logs     # 查看日志路径
uv run --env-file .env mapce serve-kill     # 在安全点正常停止
uv run --env-file .env mapce serve-restart  # 重启服务
```

退出 MCP 客户端不会停止后台服务。只有 `serve-kill` 会请求停止；`serve-kill --force` 只用于已经通过健康检查验证身份的准确进程。

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/usage.md](docs/usage.md) | Python SDK 用法、MCP 工具参考（11 个）、论文深度读取、Claude Code 集成 |
| [docs/data-sources.md](docs/data-sources.md) | 数据源适配器（arXiv、Zotero、本地 PDF、目录批量） |
| [docs/storage.md](docs/storage.md) | 存储形式：LanceDB、模型缓存、临时文件、清理 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见问题与解决方案 |
| [docs/development.md](docs/development.md) | 开发指南（架构、分块策略、项目结构、添加数据源） |

## MAPCE TODO

- [x] **论文检索广度与内存安全**：加入向量与全文混合召回，按论文去重并返回最佳证据片段；使用 IVF-PQ 索引、连接复用和按需加载嵌入模型，降低重复检索与多个 MCP 进程带来的内存占用
- [x] **论文—代码仓库关联**：论文状态与代码状态分离，支持一篇论文关联多个仓库、自动发现官方仓库、记录待审核候选，并明确标记未发现代码仓库的论文
- [ ] **代码检索排序**：当前代码文件 `Recall@5` 基线约为 0.65。后续需要融合仓库、文件路径、代码符号和调用关系等信号，并为不同编程语言建立更细的评测集
- [ ] **代码分析增强**：Python 使用 AST 解析，C++/CUDA 仍依赖正则，暂不能可靠处理模板元编程和复杂宏展开。后续考虑接入 Tree-sitter 或语言服务器，并支持 Makefile、Dockerfile、Shell 等文件
- [ ] **自动更新机制**：检测 arXiv 新版本和代码仓库新 commit，先展示变化，再由用户确认是否增量同步；同时加入辅助索引刷新和失败任务重试
- [ ] **前端界面**：目前以 MCP 和命令行为主，后续提供论文、章节、图表、仓库关联和索引状态的浏览界面
- [ ] **Zotero 深度集成**：在 PDF 导入之外，同步 Zotero 笔记、标签和集合，或提供 Zotero Agent 插件

## 许可

[MIT](LICENSE)
