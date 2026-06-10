# 数据源

所有导入统一通过 `index_paper` 工具或对应的 Python API。

## arXiv

```python
from mapce.core.indexing import index_paper_from_arxiv
paper_id = index_paper_from_arxiv('2511.04131')
```

通过 MinerU URL 解析接口，自动下载并索引。

### 批量搜索并索引

```python
from mapce.sources.arxiv import search_and_index_arxiv
results = search_and_index_arxiv("diffusion models image generation", max_results=10)
```

## 本地 PDF

```python
from mapce.core.indexing import index_paper
from pathlib import Path
paper_id = index_paper(Path.home() / 'Downloads' / 'paper.pdf')
```

通过 MinerU 批量上传接口解析。

### 目录批量导入

```python
from mapce.sources.local import index_directory
results = index_directory(Path.home() / "Papers" / "cvpr2024")
```

递归扫描目录下所有 PDF 并索引，自动去重。

## URL

```python
# MCP 工具中 source_type 参数设为 "url"
# Python SDK 暂直接使用 index_paper_from_arxiv 即可覆盖常见 URL 场景
```

## Zotero

直接读取本地 Zotero SQLite 数据库：

```python
from mapce.sources.zotero import import_from_zotero

# 导入指定收藏集
results = import_from_zotero(collection_name="Reinforcement_Learning", max_items=50)

# 导入所有期刊论文
results = import_from_zotero(item_type="journalArticle", max_items=100)
```

自动提取标题、作者、DOI、arXiv ID，优先使用已存储的 PDF 附件。
