[中文](storage.md)<br>[← Back](../README_EN.md)

# Storage

## Overview

```
~/.mapce/data/                    ← LanceDB index (persistent)
  ├── chunks.lance/               # Main table
  ├── paper_code_mapping.lance/   # Paper ↔ Code mapping
  ├── index_meta.lance/           # Index metadata
  └── papers/                     # MinerU output (persistent, never deleted)
      ├── 2510.02252/
      ├── 2603.22201/
      └── ...
/var/folders/.../T/fastembed_cache/  ← Embedding model cache (persistent)
/tmp/mapce_repo_<random>/         ← Code clone temp dir (auto-deleted after indexing)
```

---

## 1. LanceDB Index (Persistent)

**Location**: `~/.mapce/data/` (overridable via `MAPCE_DATA_DIR` env var)

All indexed data resides here after indexing. This is MAPCE's core storage.

### Directory Structure

```
~/.mapce/data/
├── chunks.lance/                  # Main table: all chunks (papers + code)
│   ├── data/                      # Lance columnar data files
│   ├── _versions/                 # Versioned data (incremental write support)
│   └── _indices/                  # Vector indices (IVF-PQ etc.)
├── paper_code_mapping.lance/      # Paper ↔ Code mapping table
├── index_meta.lance/              # Index metadata table
└── _metadata.db                   # LanceDB internal metadata (SQLite)
```

### Disk Usage Estimate

| Data | Per Paper |
|------|-----------|
| Paper chunks (~220 rows × 1024-d) | ~5–10 MB |
| Code chunks (~1300 rows × 1024-d) | ~30–50 MB |
| Metadata + mappings | < 1 MB |
| **Per paper + code total** | **~40–60 MB** |

### Lifecycle

- **Write**: appended on `index_paper` / `index_code`
- **Delete**: marked as deleted on `delete_paper`; data still occupies disk
- **Compact**: call `compact_database()` to reclaim space from deleted data
- **Migrate**: copy the entire `~/.mapce/data/` directory to migrate the index

---

## 2. Embedding Model Cache (Persistent)

**Location**: managed by `fastembed`, typically under the system temp directory.

```
/var/folders/.../T/fastembed_cache/
└── models--qdrant--multilingual-e5-large-onnx/
    └── snapshots/<hash>/
        ├── model.onnx           # ONNX model weights (~2.2 GB)
        ├── tokenizer.json       # Tokenizer
        └── config.json          # Model config
```

**Lifecycle**: auto-downloaded on first `embed()` call, then loaded from cache. The cache typically survives reboots (macOS does not auto-clean `T/fastembed_cache/`), but may be cleaned in extreme cases. If cleaned, it will re-download on the next run.

**Manual management**: delete `T/fastembed_cache/` to free disk space.

---

## 3. Temp Directories (Auto-Cleaned After Indexing)

### 3.1 Code Clone Temp

**Location**: `/tmp/mapce_repo_<random>/`

```
/tmp/mapce_repo_abc123/
└── <repo_name>/                 # git clone --depth 1
    ├── .git/
    ├── *.py
    └── ...
```

**Flow**:
1. `git clone --depth 1` → `/tmp/mapce_repo_xxx/<repo>/`
2. AST parsing → chunking → embedding
3. Data written to LanceDB
4. `shutil.rmtree()` removes the entire temp directory

The temp directory is always deleted (guaranteed by `try/finally`), regardless of success or failure.

### 3.2 MinerU Output (Persistent Cache)

**Location**: `~/.mapce/data/papers/<paper_id>/`

MinerU output is the sole source of figure and table data. It is **never deleted** after indexing — `figure_path` and `table_image` in LanceDB point to this directory, ensuring availability across restarts.

```
~/.mapce/data/papers/
└── 2510.02252/                  # Named by paper_id
    ├── 2510.02252.md            # Markdown body ($$..$$ formulas)
    ├── images/                  # Image files (SHA256-hashed names)
    │   ├── dab63539...jpg
    │   └── ...
    └── <uuid>_content_list_v2.json  # Structured content blocks (with table HTML)
```

**Retention policy**: redundant files (original PDF, `layout.json`, `model.json`, v1 `content_list.json`) are auto-deleted after indexing. Only the three categories above are kept.

**Flow**:
1. PDF uploaded to MinerU → parsed → zip downloaded → extracted to `~/.mapce/data/papers/<paper_id>/`
2. `.md`, layout JSON, and images read for chunking
3. Image paths and table data written to LanceDB
4. **Directory retained**

**Disk usage**:

| Paper | Raw output | Cleaned (md + v2 json + images) |
|-------|-----------|---------------------------------|
| Text-heavy (few figures) | 3–8 MB | ~0.5–1.5 MB |
| Figure-rich | 15–25 MB | ~1–2 MB |
| **Average per paper** | **~13 MB** | **~1.3 MB** |

**Lifecycle**: same as the LanceDB index — persists with the paper. Delete a paper's cache via `shutil.rmtree(~/.mapce/data/papers/<paper_id>/)`.

### 3.3 Zotero Database Temp Copy

**Location**: `/tmp/<random>.sqlite`

When Zotero desktop is running, its SQLite database (`~/Zotero/zotero.sqlite`) is locked. MAPCE's Zotero adapter auto-detects the lock and creates a temp copy:

```
/tmp/tmpXXXXXX.sqlite    ← copy of zotero.sqlite (read-only, deleted immediately after read)
```

**Flow**:
1. Call `list_zotero_items()`, `get_zotero_item_detail()`, etc.
2. Try direct connection to `~/Zotero/zotero.sqlite` (read-only)
3. If locked → `shutil.copy2()` to `/tmp/tmpXXXXXX.sqlite`
4. Read from copy
5. Immediately `unlink()` the copy after closing the connection

```python
# Auto-handled, no user intervention needed
from mapce.sources.zotero import list_zotero_items

# Works even when Zotero is running
items = list_zotero_items(collection_name='EAI')
for item in items:
    print(item['title'])
```

**Disk usage**: the copy is the same size as the original database (typically 20–50 MB), exists only for milliseconds during read. Zero overhead when Zotero is not running.

---

## 4. Disk Cleanup

### Check Usage

```bash
du -sh ~/.mapce/data/
du -sh ~/.mapce/data/papers/   # MinerU output
```

### Clean a Single Paper's MinerU Cache

```bash
rm -rf ~/.mapce/data/papers/<paper_id>/
```

### Compact Index (Reclaim Deleted Space)

```python
from mapce.core.incremental import compact_database
compact_database()
```

### Full Reset

```bash
rm -rf ~/.mapce/data/
rm -rf /var/folders/*/T/fastembed_cache/
```
