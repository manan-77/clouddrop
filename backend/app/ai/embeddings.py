"""Turns text into vectors. The model and its size are decided here and nowhere else.

Changing either means re-embedding every chunk and a new migration (docs/adr/0013).
"""

import threading
from collections.abc import Sequence
from typing import Protocol

from app.core.config import get_settings

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


class EmbeddingError(Exception):
    """The embedder could not produce usable vectors (never carries document text)."""


class Embedder(Protocol):
    model: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """fastembed (ONNX, no PyTorch). Queries and documents are embedded differently on purpose:
    the BGE models are trained with a search instruction on the query side only."""

    model = EMBEDDING_MODEL
    dim = EMBEDDING_DIM

    def __init__(self, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding  # imported late: it loads onnxruntime

        self._engine = TextEmbedding(self.model, cache_dir=cache_dir)
        # onnxruntime sessions are safe to share, but fastembed's tokenizer is not documented as
        # such, so calls are serialised; throughput is bounded by the worker anyway.
        self._lock = threading.Lock()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return [vector.tolist() for vector in self._engine.passage_embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            vector: list[float] = next(iter(self._engine.query_embed([text]))).tolist()
            return vector


_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    "The shared embedder. Loaded on first use (the model is downloaded once into the cache dir)."
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = LocalEmbedder(get_settings().embedding_cache_dir or None)
        return _embedder
