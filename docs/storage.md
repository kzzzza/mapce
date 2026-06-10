[English](storage_EN.md)<br>[← Back](../README.md)

# 存储说明

## 总览

```
~/.mapce/data/                    ← LanceDB 索引库（持久）
  ├── chunks.lance/               # 主表
  ├── paper_code_mapping.lance/   # Paper ↔ Code 映射
  ├── index_meta.lance/           # 索引元信息
  └── papers/                     # MinerU 解析结果（持久，不删除）
      ├── 2510.02252/
      ├── 2603.22201/
      └── ...
/var/folders/.../T/fastembed_cache/  ← 嵌入模型缓存（持久）
/tmp/mapce_repo_<random>/         ← 代码 clone 临时目录（索引后自动删除）
```

---

## 1. LanceDB 索引库（持久）

**位置**：`~/.mapce/data/`（可通过 `MAPCE_DATA_DIR` 环境变量修改）

索引完成后所有数据驻留在此，是 MAPCE 的核心存储。

### 目录结构

```
~/.mapce/data/
├── chunks.lance/                  # 主表：所有分块（论文 + 代码）
│   ├── data/                      # Lance 列存数据文件
│   ├── _versions/                 # 版本化数据（支持增量写入）
│   └── _indices/                  # 向量索引（IVF-PQ 等）
├── paper_code_mapping.lance/      # Paper ↔ Code 映射表
├── index_meta.lance/              # 索引元信息表
└── _metadata.db                   # LanceDB 内部元数据（SQLite）
```

### 磁盘占用估算

| 数据 | 单篇论文 |
|------|---------|
| 论文 chunks (~220 条 × 1024-d) | ~5–10 MB |
| 代码 chunks (~1300 条 × 1024-d) | ~30–50 MB |
| 元数据 + 映射 | < 1 MB |
| **单篇论文 + 代码合计** | **~40–60 MB** |

### 生命周期

- **写入**：`index_paper` / `index_code` 时追加
- **删除**：`delete_paper` 时标记删除，数据仍占磁盘
- **回收**：调用 `compact_database()` 释放已删除数据的空间
- **迁移**：复制整个 `~/.mapce/data/` 目录即可迁移索引库

---

## 2. 嵌入模型缓存（持久）

**位置**：由 `fastembed` 管理，通常在系统临时目录下。

```
/var/folders/.../T/fastembed_cache/
└── models--qdrant--multilingual-e5-large-onnx/
    └── snapshots/<hash>/
        ├── model.onnx           # ONNX 模型权重（~2.2 GB）
        ├── tokenizer.json       # 分词器
        └── config.json          # 模型配置
```

**生命周期**：首次 `embed()` 调用时自动下载，之后从缓存加载。系统重启后缓存通常保留（macOS 不自动清理 `T/fastembed_cache/`），但极端情况下可能被系统清理。如被清理，下次运行时会自动重新下载。

**手动管理**：如需释放磁盘空间，直接删除 `T/fastembed_cache/` 目录。

---

## 3. 临时目录（索引后自动清理）

### 3.1 代码 clone 临时目录

**位置**：`/tmp/mapce_repo_<random>/`

```
/tmp/mapce_repo_abc123/
└── <repo_name>/                 # git clone --depth 1 的仓库
    ├── .git/
    ├── *.py
    └── ...
```

**索引流程**：
1. `git clone --depth 1` → `/tmp/mapce_repo_xxx/<repo>/`
2. AST 解析 → 分块 → 嵌入
3. 数据写入 LanceDB
4. `shutil.rmtree()` 删除整个临时目录

**保留条件**：无论索引成功或失败，临时目录都会被删除（`try/finally` 块保证）。

### 3.2 MinerU 解析结果（持久缓存）

**位置**：`~/.mapce/data/papers/<paper_id>/`

MinerU 的解析结果是图片和表格数据的唯一来源。索引完成后**不再删除**，图片路径（`figure_path`）和表格图片（`table_image`）指向该目录，确保重启后仍然可用。

```
~/.mapce/data/papers/
└── 2510.02252/                  # 以 paper_id 命名
    ├── 2510.02252.md            # Markdown 正文（公式 $$..$$）
    ├── images/                  # 图片文件（SHA256 哈希命名）
    │   ├── dab63539...jpg
    │   └── ...
    └── <uuid>_content_list_v2.json  # 结构化内容块（含表格 HTML）
```

**保留策略**：索引完成后自动删除冗余文件（原始 PDF、`layout.json`、`model.json`、v1 `content_list.json`），仅保留上述三类数据。

**索引流程**：
1. PDF 上传至 MinerU → 解析 → 下载 zip → 解压到 `~/.mapce/data/papers/<paper_id>/`
2. 读取 `.md`、`layout.json`、`images/` 进行分块
3. 图片路径和表格数据写入 LanceDB（`figure_path`、`table_markdown`、`table_image`）
4. **目录保留**，不删除

**磁盘占用**：

| 论文 | 原始输出 | 清理后（保留 md + v2 json + images） |
|------|---------|--------------------------------------|
| 纯文本论文（少量图） | 3–8 MB | ~0.5–1.5 MB |
| 图文丰富的论文 | 15–25 MB | ~1–2 MB |
| **单篇论文平均** | **~13 MB** | **~1.3 MB** |

索引完成后自动删除原始 PDF（`*_origin.pdf`）、`layout.json`、`*_model.json`、v1 `content_list.json`，只保留分块和检索所需的核心文件。

**生命周期**：与 LanceDB 索引库一致，随论文持久保留。删除论文时可通过 `shutil.rmtree(~/.mapce/data/papers/<paper_id>/)` 清理对应目录。

### 3.3 Zotero 数据库临时副本

**位置**：`/tmp/<random>.sqlite`

当 Zotero 桌面端正在运行时，其 SQLite 数据库（`~/Zotero/zotero.sqlite`）会被锁定，导致直接读取失败。MAPCE 的 Zotero 适配器会**自动检测锁状态**并在需要时创建临时副本：

```
/tmp/tmpXXXXXX.sqlite    ← zotero.sqlite 的副本（只读，读取后立即删除）
```

**工作流程**：

1. 调用 `list_zotero_items()` 或 `get_zotero_item_detail()` 等函数
2. 尝试直接连接 `~/Zotero/zotero.sqlite`（只读模式）
3. 如果数据库被锁定 → `shutil.copy2()` 到 `/tmp/tmpXXXXXX.sqlite`
4. 从副本读取数据
5. 连接关闭后立即 `unlink()` 删除副本

```python
# 无需用户干预，自动处理
from mapce.sources.zotero import list_zotero_items

# Zotero 运行中也正常工作
items = list_zotero_items(collection_name='EAI')
for item in items:
    print(item['title'])
```

**磁盘占用**：副本与原始数据库大小相同（通常 20–50 MB），仅在读取期间短暂存在（毫秒级）。如果 Zotero 未运行，则不创建副本，零额外开销。

---

## 4. 磁盘清理

### 查看占用

```bash
du -sh ~/.mapce/data/
du -sh ~/.mapce/data/papers/   # MinerU 解析结果
```

### 清理单篇论文的 MinerU 缓存

```bash
rm -rf ~/.mapce/data/papers/<paper_id>/
```

### 压缩索引（释放删除空间）

```python
from mapce.core.incremental import compact_database
compact_database()
```

### 完全重置

```bash
rm -rf ~/.mapce/data/
rm -rf /var/folders/*/T/fastembed_cache/
```
