[English](development_EN.md)<br>[← Back](../README.md)

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

## 架构总览

### 项目结构

```
mapce/
├── pyproject.toml
├── .env.example
├── README.md
├── img/                         # Logo 等静态资源
├── scripts/init_db.py
├── docs/
│
├── src/mapce/
│   ├── core/                    # 核心引擎（无 MCP 依赖）
│   │   ├── embedding.py         # fastembed 封装
│   │   ├── indexing.py          # 索引编排
│   │   ├── retrieval.py         # 四阶段检索
│   │   ├── incremental.py       # 增量索引（去重、状态机、删除）
│   │   ├── code_mapper.py       # Paper↔Code 映射
│   │   └── chunking/
│   │       ├── paper.py         # 论文分块
│   │       └── code.py          # 代码分块（AST 解析）
│   │
│   ├── db/                      # 数据访问层
│   │   ├── connection.py        # LanceDB 连接
│   │   ├── schema.py            # PyArrow Schema
│   │   └── operations.py        # CRUD
│   │
│   ├── mineru/                  # MinerU API 封装
│   │   ├── api.py               # httpx 实现
│   │   └── parser.py            # 输出解析
│   │
│   ├── mcp/                     # MCP Server 层
│   │   ├── server.py            # stdio 入口
│   │   ├── tools.py             # 工具定义
│   │   └── _handlers.py         # 异步 handler
│   │
│   ├── prompts/                 # Jinja2 模板
│   └── sources/                 # 数据源适配器
│       ├── arxiv.py
│       ├── zotero.py
│       └── local.py
│
└── tests/
```

### 索引流水线

```
PDF/arXiv → MinerU 解析 → chunking → embedding → LanceDB
                                ↓
                          figures + tables (图片路径、表格 HTML 持久缓存)
```

**论文分块（3 层 + 2 类 Special）**

| 层级 | 内容 | 体量 | 用途 |
|-------|---------|------|---------|
| L1 | 标题 + 摘要 + 关键词 | ~200–500 tokens | 粗筛 |
| L2 | 章节级（沿 MinerU 章节边界） | ~500–2000 tokens | 精排 |
| L3 | 段落级 | ~200–500 tokens | 注入 prompt |
| Figure | 图片标题 + 图片路径 | — | 间接图片检索 |
| Table | 表格标题 + HTML 内容 + 表格图片 | — | Benchmark 检索 |

**代码分块（5 层 + Config）**

| 层级 | 内容 | 用途 |
|-------|---------|---------|
| L1 | README 摘要 + 目录树 + 入口点 + 构建说明 | 仓库全貌 |
| L2 | 文件级：路径 + imports + 签名列表 + 导出符号 | 定位文件 |
| L3 | 函数/类级：完整实现 + calls[] + called_by[] | 注入 prompt |
| L4 | 模块级：顶层常量、registry、装饰器、`__main__` | 补全上下文 |
| L5 | 测试函数（关联被测符号） | 理解预期行为 |
| Config | YAML/JSON/TOML 超参数 | 超参检索 |

### 检索流水线

```
阶段 0：查询理解 → 提取意图（paper / code / hybrid）
阶段 1：论文级粗筛 → L1 向量检索 top-20 + 元数据过滤
阶段 2：章节/代码精排 → L2 向量检索，论文与代码并行
阶段 3：上下文展开 → L3 段落 + 相邻链 + Figure/Table 横向 + 调用链
阶段 4：结果组装 → 结构化注入 prompt，控制 token 预算
```

### 数据库

LanceDB 三表：`chunks`（主表）、`paper_code_mapping`（Paper↔Code 映射）、`index_meta`（索引元信息）。关联靠 chunk_id 字符串引用。

### 增量索引

- **去重**：arxiv_id 精确 → doi 精确 → title 向量相似度 > 0.95
- **状态机**：pending → chunking → complete | code_pending | failed
- **删除**：级联检查，共享代码块保留、独有代码块删除

## 添加新的数据源

1. 在 `sources/` 下新建文件，实现搜索/下载/导入逻辑
2. 核心索引统一走 `core/indexing.py` 的 `index_paper` 或 `_index_from_mineru_dir`
3. 持久缓存自动管理：MinerU 输出写入 `~/.mapce/data/papers/`，冗余文件自动清理（仅保留 `.md`、`_content_list_v2.json`、`images/`）

## 切换嵌入模型

修改 `.env` 中的 `MAPCE_EMBEDDING_MODEL` 值，然后重新初始化或调用 `re_embed_all()`：

```python
from mapce.core.incremental import re_embed_all
re_embed_all()
```
