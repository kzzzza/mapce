"""Shared helpers for the paper and code chunkers."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Generate a URL-safe slug from text (lowercased, non-word chars stripped)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    return text[:80]
