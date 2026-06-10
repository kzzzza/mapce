# 安装

## 运行环境

- Python ≥ 3.11
- [uv](https://astral.sh/uv) 包管理器
- [MinerU API Token](https://mineru.net/apiManage/token)（免费注册）
- macOS / Linux（推荐 Apple Silicon）
- 16 GB 内存，约 5 GB 磁盘（嵌入模型 + 索引数据）

## 安装步骤

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 进入项目
cd mapce

# 3. 同步依赖（创建虚拟环境并安装所有包）
uv sync

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 MINERU_API_TOKEN
# 如在中国大陆，取消代理变量的注释并填入地址

# 5. 初始化数据库并下载嵌入模型（仅首次运行，约 2 GB）
uv run --env-file .env python scripts/init_db.py
```

## `.env` 环境变量

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `MINERU_API_TOKEN` | — | **必填**。MinerU API 密钥 |
| `MAPCE_DATA_DIR` | `~/.mapce/data` | LanceDB 数据目录 |
| `MAPCE_EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | 嵌入模型（fastembed 格式） |
| `MAPCE_LOG_LEVEL` | `INFO` | 日志级别 |
| `http_proxy` | — | HTTP 代理地址（可选，国内用户必填） |
| `https_proxy` | — | HTTPS 代理地址（可选，国内用户必填） |
| `all_proxy` | — | SOCKS5 代理地址（可选） |

## 代理配置（中国大陆用户）

编辑 `.env`，取消注释并填入代理地址：

```bash
http_proxy=http://127.0.0.1:9674
https_proxy=http://127.0.0.1:9674
all_proxy=socks5://127.0.0.1:9674
```

所有命令通过 `uv run --env-file .env` 执行时自动加载，无需手动 `export`。
MCP Server 同样通过 `.mcp.json` 中的 `--env-file` 参数加载，不再需要额外配置。

## 嵌入模型

默认使用 `intfloat/multilingual-e5-large`（1024 维，中英双语）。查看其他可用模型：

```bash
uv run python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"
```
