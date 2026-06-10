"""Fastembed wrapper for multilingual-e5-large text embedding.

Provides a lightweight singleton model that is lazy-loaded on first use,
suitable for embedding both paper text and code snippets.
"""

from __future__ import annotations

import os
from typing import Sequence

_DEFAULT_MODEL = "intfloat/multilingual-e5-large"

_model = None
_model_name: str | None = None


def _get_model_name() -> str:
    return os.environ.get("MAPCE_EMBEDDING_MODEL", _DEFAULT_MODEL)


def get_model():
    """Return the global embedding model, loading it on first call."""
    global _model, _model_name
    name = _get_model_name()
    if _model is None or _model_name != name:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=name)
        _model_name = name
    return _model


BATCH_SIZE = 32  # smaller batches → lower peak memory


def embed(texts: Sequence[str], batch_size: int = BATCH_SIZE) -> list[list[float]]:
    """Embed a batch of texts, returning 1024-d float vectors.

    Processes texts in mini-batches to keep ONNX runtime memory low.

    Args:
        texts: One or more strings to embed.
        batch_size: Number of texts per ONNX inference batch (default 32).

    Returns:
        List of embedding vectors, each as a list of 1024 floats.
    """
    model = get_model()
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        for emb in model.embed(chunk):
            results.append(emb.tolist())
    return results


def embed_single(text: str) -> list[float]:
    """Embed a single text, returning a single 1024-d vector."""
    return embed([text])[0]
