"""Embedding and reranking models.

Uses fastembed (ONNX, CPU-only, no PyTorch) so the same code runs on a laptop and on a
small Render instance. The "hash" backend is a tiny deterministic stand-in used by the
tests and CI so they never need to download a model.
"""
import hashlib
import math
import re
from functools import lru_cache

import numpy as np

from src.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class HashEmbedder:
    """Bag-of-words feature hashing. Not smart, but fast and dependency-free."""

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        toks = _TOKEN_RE.findall(text.lower())
        for tok in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        return v

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack([self._vec(t) for t in texts])) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


class FastEmbedder:
    def __init__(self, model: str, cache_dir: str):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed_passages(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, settings.embed_dim), dtype=np.float32)
        vecs = list(self.model.passage_embed(texts, batch_size=batch_size))
        return _normalize(np.array(vecs, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        vec = next(iter(self.model.query_embed(text)))
        return _normalize(np.array([vec], dtype=np.float32))[0]


class HashReranker:
    """Stand-in reranker: word overlap squashed to 0..1."""

    def score(self, query: str, docs: list[str]) -> list[float]:
        q = set(_TOKEN_RE.findall(query.lower()))
        out = []
        for d in docs:
            dt = set(_TOKEN_RE.findall(d.lower()))
            overlap = len(q & dt) / (len(q) or 1)
            out.append(overlap)
        return out


class CrossEncoderReranker:
    def __init__(self, model: str, cache_dir: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        logits = list(self.model.rerank(query, docs))
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]


@lru_cache(maxsize=1)
def get_embedder():
    if settings.embed_backend == "hash":
        return HashEmbedder(settings.embed_dim)
    return FastEmbedder(settings.embed_model, settings.model_cache)


@lru_cache(maxsize=1)
def get_reranker():
    if settings.embed_backend == "hash":
        return HashReranker()
    return CrossEncoderReranker(settings.rerank_model, settings.model_cache)


def warm_up() -> None:
    """Load models once at startup so the first question isn't slow."""
    get_embedder().embed_query("warm up")
    if settings.use_rerank:
        get_reranker().score("warm up", ["warm up"])
