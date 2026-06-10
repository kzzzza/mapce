"""One-shot database initializer.

Creates the LanceDB tables and downloads the embedding model so
the MCP server starts cold without delay.

Usage:
    python scripts/init_db.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Load .env if present
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path)


def main():
    print("MAPCE — initializing database and embedding model...")
    print()

    # 1. Database tables
    print("[1/2] Initializing LanceDB tables...")
    from mapce.db.connection import get_connection
    from mapce.db.operations import init_chunks, init_mapping, init_index_meta

    db = get_connection()
    init_chunks(db)
    init_mapping(db)
    init_index_meta(db)
    print(f"  ✓ chunks, paper_code_mapping, index_meta ready")

    # 2. Embedding model (warm-up download)
    print("[2/2] Downloading embedding model (first-time only)...")
    from mapce.core.embedding import embed_single
    _ = embed_single("MAPCE initialization warm-up")
    print(f"  ✓ Embedding model loaded")

    print()
    print("Initialization complete. MAPCE is ready.")
    print(f"Data directory: {os.environ.get('MAPCE_DATA_DIR', '~/.mapce/data')}")


if __name__ == "__main__":
    main()
