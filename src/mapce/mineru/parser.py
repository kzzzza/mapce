"""MinerU output parser.

Reads MinerU's output directory (markdown, layout.json, images, content_list.json)
and produces normalized structured representations suitable for chunking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MinerUOutput:
    """Parsed MinerU output for a single paper."""

    def __init__(self, paper_dir: Path):
        self.paper_dir = Path(paper_dir)
        self.data_id = self.paper_dir.name

    # ---- markdown body ----

    @property
    def md_path(self) -> Path:
        """Path to the main markdown file."""
        candidates = list(self.paper_dir.glob("*.md"))
        if not candidates:
            raise FileNotFoundError(f"No .md file found in {self.paper_dir}")
        # prefer the one matching the dir name
        named = self.paper_dir / f"{self.data_id}.md"
        return named if named.exists() else candidates[0]

    def read_markdown(self) -> str:
        return self.md_path.read_text(encoding="utf-8")

    # ---- layout.json ----

    @property
    def layout_path(self) -> Path | None:
        p = self.paper_dir / "layout.json"
        return p if p.exists() else None

    def read_layout(self) -> list[dict] | None:
        """Return list of per-element layout dicts, or None."""
        path = self.layout_path
        if not path:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- content_list.json (pipeline model) ----

    @property
    def content_list_path(self) -> Path | None:
        # Prefer v2 (richer structure with table HTML) over v1
        candidates = list(self.paper_dir.glob("*_content_list_v2.json"))
        if candidates:
            return candidates[0]
        candidates = list(self.paper_dir.glob("*_content_list.json"))
        return candidates[0] if candidates else None

    def read_content_list(self) -> list[dict] | None:
        path = self.content_list_path
        if not path:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- images ----

    @property
    def images_dir(self) -> Path:
        return self.paper_dir / "images"

    def list_images(self) -> list[Path]:
        d = self.images_dir
        if not d.exists():
            return []
        return sorted(p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"))

    # ---- structured extraction ----

    def extract_sections(self) -> list[dict[str, Any]]:
        """Attempt to split the markdown into sections based on heading markers.

        Returns a list of {"heading": str, "level": int, "content": str, "page": int|None}.
        Falls back to a single section if no headings detected.
        """
        md = self.read_markdown()
        lines = md.split("\n")
        sections: list[dict[str, Any]] = []
        current_lines: list[str] = []
        current_heading = "Abstract"
        current_level = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("####"):  # up to ###
                # save previous
                if current_lines:
                    sections.append({
                        "heading": current_heading,
                        "level": current_level,
                        "content": "\n".join(current_lines).strip(),
                    })
                # start new
                level = len(stripped) - len(stripped.lstrip("#"))
                current_heading = stripped.lstrip("#").strip()
                current_level = level
                current_lines = []
            else:
                current_lines.append(line)

        # final section
        if current_lines:
            sections.append({
                "heading": current_heading,
                "level": current_level,
                "content": "\n".join(current_lines).strip(),
            })

        return sections

    def extract_figures_and_tables(self) -> dict[str, list[dict]]:
        """Extract figure and table captions + image references from markdown.

        MinerU outputs SHA256-hashed image filenames referenced as:
            ![](images/hash.jpg)
            Fig. 1. Caption text

        This method pairs each caption with its preceding image reference.

        Returns {"figures": [...], "tables": [...]} where each entry has
        {"caption": str, "index": int, "image_ref": str|None}.
        """
        import re

        md = self.read_markdown()
        # Build two indexes: stem→path and filename→path (MinerU uses SHA256 filenames)
        images_by_stem = {p.stem: str(p) for p in self.list_images()}
        images_by_name = {p.name: str(p) for p in self.list_images()}
        lines = md.split("\n")

        # Build index: line_number → image_stem for ![](images/...) lines
        img_ref_by_line: dict[int, str] = {}
        img_line_pattern = re.compile(r"!\[\]\(images/([^)]+)\)")
        for i, line in enumerate(lines):
            m = img_line_pattern.search(line)
            if m:
                filename = m.group(1)  # e.g., "dab63539...jpg"
                img_ref_by_line[i] = filename

        figures = []
        tables = []

        fig_pattern = re.compile(
            r"(?:Figure|Fig\.?)\s*(\d+)[:.]\s*(.+)$", re.IGNORECASE
        )
        tbl_pattern = re.compile(
            r"Table\s*(\d+)[:.]\s*(.+)$", re.IGNORECASE
        )

        # Helper: find nearest image reference — look backward then forward
        def _find_image_ref(line_idx: int, window: int = 3) -> str | None:
            for direction in (-1, 1):  # backward first, then forward
                for offset in range(1, window + 1):
                    target = line_idx + offset * direction
                    if target in img_ref_by_line:
                        filename = img_ref_by_line[target]
                        if filename in images_by_name:
                            return images_by_name[filename]
                        stem = Path(filename).stem
                        if stem in images_by_stem:
                            return images_by_stem[stem]
            return None

        for i, line in enumerate(lines):
            # Check for figure caption
            fm = fig_pattern.search(line)
            if fm:
                idx = int(fm.group(1))
                caption = fm.group(2).strip()
                image_ref = _find_image_ref(i)
                figures.append({"caption": caption, "index": idx, "image_ref": image_ref})
                continue

            # Check for table caption
            tm = tbl_pattern.search(line)
            if tm:
                idx = int(tm.group(1))
                caption = tm.group(2).strip()
                image_ref = _find_image_ref(i)
                tables.append({"caption": caption, "index": idx, "image_ref": image_ref})

        return {"figures": figures, "tables": tables}

    def extract_table_data(self) -> dict[int, dict]:
        """Extract detailed table data from MinerU content_list JSON.

        MinerU stores tables with HTML content, image references, and structured
        captions in the content_list_v2.json file. This method reads that data
        and indexes it by table number.

        Returns:
            Dict mapping table index (int) to:
            {"html": str, "image_path": str|None, "caption": str, "bbox": list}
        """
        import re

        content_list = self.read_content_list()
        if content_list is None:
            return {}

        tables: dict[int, dict] = {}
        for page_items in content_list:
            for item in page_items:
                if not isinstance(item, dict) or item.get("type") != "table":
                    continue
                content = item.get("content", {})
                if not isinstance(content, dict):
                    continue

                # Extract table number from caption
                caption_parts = content.get("table_caption", [])
                caption_text = ""
                for part in caption_parts:
                    if part.get("type") == "text":
                        caption_text += part.get("content", "")
                    elif part.get("type") == "equation_inline":
                        caption_text += part.get("content", "")

                idx_match = re.search(r"Table\s*(\d+)", caption_text, re.IGNORECASE)
                if idx_match:
                    tbl_idx = int(idx_match.group(1))
                else:
                    continue  # can't determine table number

                # Image reference
                image_source = content.get("image_source", {})
                image_path = image_source.get("path") if isinstance(image_source, dict) else None

                # HTML content (the actual table)
                html = content.get("html", "")

                tables[tbl_idx] = {
                    "html": html,
                    "image_path": image_path,
                    "caption": caption_text.strip(),
                    "bbox": item.get("bbox", []),
                }

        return tables
