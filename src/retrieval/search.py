"""Hybrid retrieval: vector search + keyword search, fused with Reciprocal Rank Fusion,
then reordered by a cross-encoder reranker."""
import time

from src import db
from src.config import PipelineOptions, settings
from src.embeddings import get_embedder, get_reranker

RRF_K = 60


def rrf(result_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion: each list votes 1/(k + rank) for its items."""
    fused: dict[int, dict] = {}
    for results in result_lists:
        for rank, row in enumerate(results, start=1):
            item = fused.setdefault(row["id"], {**row, "rrf": 0.0})
            item["rrf"] += 1.0 / (k + rank)
    return sorted(fused.values(), key=lambda r: r["rrf"], reverse=True)


def confidence(passages: list[dict]) -> float:
    """How strong the best passage looks: rerank probability if we have it, else cosine."""
    if not passages:
        return 0.0
    if passages[0].get("rerank") is not None:
        return max(p["rerank"] for p in passages)
    return max((p.get("dense") or 0.0) for p in passages)


def is_weak(passages: list[dict], opts: PipelineOptions) -> bool:
    conf = confidence(passages)
    threshold = settings.retry_min_rerank if opts.use_rerank else settings.retry_min_cosine
    return conf < threshold


def retrieve(query: str, tickers=None, years=None, opts: PipelineOptions | None = None) -> tuple[list[dict], dict]:
    opts = opts or PipelineOptions()
    t0 = time.perf_counter()
    qvec = get_embedder().embed_query(query)
    dense = db.dense_search(qvec, settings.candidates_per_retriever, tickers, years)
    for r in dense:
        r["dense"] = float(r["score"])

    keyword: list[dict] = []
    if opts.use_bm25:
        keyword = db.keyword_search(query, settings.candidates_per_retriever, tickers, years)

    dense_scores = {r["id"]: r["dense"] for r in dense}
    fused = rrf([dense, keyword]) if keyword else [dict(r, rrf=0.0) for r in dense]
    for r in fused:
        r["dense"] = dense_scores.get(r["id"])
        r.pop("score", None)
        r["rerank"] = None

    if opts.use_rerank and fused:
        pool = fused[: settings.rerank_pool]
        scores = get_reranker().score(query, [f"{p['context']}\n{p['content']}"[:2000] for p in pool])
        for p, s in zip(pool, scores):
            p["rerank"] = float(s)
        fused = sorted(pool, key=lambda p: p["rerank"], reverse=True)

    top = fused[: opts.top_k]
    info = {
        "query": query,
        "tickers": tickers or [],
        "years": years or [],
        "vector_hits": len(dense),
        "keyword_hits": len(keyword),
        "confidence": round(confidence(top), 3),
        "ms": round((time.perf_counter() - t0) * 1000),
    }
    return top, info
