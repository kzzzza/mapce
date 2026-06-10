# 架构设计

## 索引流水线

### 论文分块（3 层 + 2 类 Special）

| 层级 | 内容 | 体量 | 用途 |
|-------|---------|------|---------|
| L1 | 标题 + 摘要 + 关键词 | ~200–500 tokens | 粗筛 |
| L2 | 章节级（沿 MinerU 章节边界） | ~500–2000 tokens | 精排 |
| L3 | 段落级 | ~200–500 tokens | 注入 prompt |
| Figure | 图片说明嵌入 + 图片路径 | — | 间接图片检索 |
| Table | 表格说明嵌入 + Markdown 表格 | — | Benchmark 检索 |

每个块携带 `paper_id`、`section_path`、`prev_chunk_id` / `next_chunk_id`，用于上下文展开。

### 代码分块（5 层 + Config）

| 层级 | 内容 | 用途 |
|-------|---------|---------|
| L1 | README 摘要 + 目录树 + 入口点 + 构建说明 | 了解仓库全貌 |
| L2 | 文件级：路径 + imports + 签名列表 + 导出符号 + 全局变量 | 定位文件 |
| L3 | 函数/类级：完整实现 + calls[] + called_by[] + 类型引用 | 注入 prompt |
| L4 | 模块级：顶层常量、registry、装饰器、`__main__` | 补全上下文 |
| L5 | 测试函数（关联被测符号） | 理解预期行为 |
| Config | YAML/JSON/TOML 超参数 | 超参检索 |

代码块携带 `calls[]`、`called_by[]`、`type_refs`、`imports`，支持调用链遍历。

### Paper ↔ Code 映射

子 Agent（或人工核对）建立论文方法与代码实现之间的结构化映射，存储在 `paper_code_mapping` 表中，支持双向查询。

映射策略：精确匹配 > 语义匹配 > 结构匹配 > README 线索，每条约带 confidence（high / medium / low）和 evidence 说明。

## 检索流水线

```
阶段 0：查询理解
  → 提取意图（paper_search / code_search / hybrid）
  → 子类型（general / figure_lookup / benchmark / formula）
  → 子类型仅影响阶段 3 的横向展开优先级

阶段 1：论文级粗筛
  → 在 L1 块（标题+摘要）上向量检索，取 top-20
  → 按 year、venue 等元数据硬过滤

阶段 2：章节/代码精排
  → 在 top-20 范围内进行 L2 向量检索
  → 论文检索走 paper L2，代码检索走 code L2
  → 混合检索并行查询后合并排序

阶段 3：上下文展开
  → 向下：获取匹配章节内的 L3 段落
  → 相邻：沿 prev / next 指针获取前后文
  → 横向：获取关联的 Figure、Table、Config 块
  → 调用链：沿 calls[] 做一跳代码展开

阶段 4：结果组装
  → 按 [Retrieved Context] 结构化组装
  → 根据问题类型选择 Jinja2 模板
  → 控制 token 预算（2000–4000 tokens）
```

## 数据库 Schema

LanceDB 三表：

- **chunks**（主表）：所有块类型共用基础字段，按 source_type 追加特定字段
- **paper_code_mapping**：Paper ↔ Code 双向关联，含 confidence 和 evidence
- **index_meta**：索引元信息，支撑增量更新和去重

关联靠 chunk_id 字符串引用，不依赖外键。

## 增量索引

- **去重**：arxiv_id 精确 → doi 精确 → title 向量相似度 > 0.95，三层防护
- **状态机**：pending → chunking → complete | code_pending | failed
- **删除**：级联检查，共享代码块保留、独有代码块删除
- LanceDB 原生支持增量写入，无需全量重建

## 项目目录

```
mapce/
├── pyproject.toml
├── .python-version
├── .env.example
├── README.md
├── scripts/init_db.py
├── docs/                        # 文档
│
├── src/mapce/
│   ├── core/                    # 核心引擎（无 MCP 依赖）
│   │   ├── embedding.py         # fastembed 封装
│   │   ├── indexing.py          # 索引编排
│   │   ├── retrieval.py         # 四阶段检索
│   │   ├── incremental.py       # 增量索引
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
│   ├── prompts/                 # Jinja2 模板（6 个）
│   └── sources/                 # 数据源适配器
│       ├── arxiv.py
│       ├── zotero.py
│       └── local.py
│
└── tests/
```
