"""The full question -> verified answer pipeline.

`run()` is a generator of events so the UI can show each step live:
  {"type": "step", ...}         a step started or finished
  {"type": "sources", ...}      the passages the answer may cite
  {"type": "answer", ...}       the drafted answer
  {"type": "verification", ...} per-sentence verification
  {"type": "done", ...}         summary (refused?, total time)
  {"type": "error", ...}        something failed; message says what to fix
"""
import time
from typing import Iterator

from src.agent import prompts
from src.agent.router import SubQuery, plan_subqueries
from src.agent.verify import verify_answer
from src.config import PipelineOptions, settings
from src.llm import LLMError, get_llm
from src.retrieval.search import confidence, is_weak, retrieve

REFUSAL_TEXT = "The indexed filings don't contain enough evidence to answer this."
MAX_PASSAGE_CHARS = 1800


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _step(sid: str, label: str, status: str, detail: str = "", ms: int | None = None, **extra) -> dict:
    return {"type": "step", "id": sid, "label": label, "status": status, "detail": detail, "ms": ms, **extra}


def _plan_query(question: str) -> str:
    try:
        data = get_llm().complete_json(prompts.PLAN_SYSTEM, prompts.PLAN_USER.format(question=question), task="plan")
        q = str(data.get("search_query", "")).strip()
        return q if 2 <= len(q.split()) <= 16 else question
    except Exception:
        return question  # planning is an optimization; fall back to the raw question


def _reformulate(question: str, previous: str) -> str | None:
    try:
        data = get_llm().complete_json(
            prompts.REFORMULATE_SYSTEM,
            prompts.REFORMULATE_USER.format(question=question, previous=previous),
            task="reformulate",
        )
        q = str(data.get("search_query", "")).strip()
        return q if q and q.lower() != previous.lower() else None
    except Exception:
        return None


def _merge(results: list[list[dict]], limit: int) -> list[dict]:
    """Round-robin across sub-searches so every company/year gets represented."""
    merged, seen = [], set()
    for rank in range(max((len(r) for r in results), default=0)):
        for r in results:
            if rank < len(r) and r[rank]["id"] not in seen:
                seen.add(r[rank]["id"])
                merged.append(r[rank])
    return merged[:limit]


def format_sources(passages: list[dict]) -> str:
    blocks = []
    for i, p in enumerate(passages, 1):
        head = f"[{i}] {p['company']} ({p['ticker']}), fiscal {p['fiscal_year']}, Item {p['section_code']} {p['section']}"
        if p["kind"] == "table":
            head += " (table)"
            if "Table:" in p["context"]:
                head += " - " + p["context"].split("Table:", 1)[1].strip()
        blocks.append(f"{head}\n{p['content'][:MAX_PASSAGE_CHARS]}")
    return "\n\n".join(blocks)


def public_source(i: int, p: dict) -> dict:
    return {
        "n": i,
        "id": p["id"],
        "ticker": p["ticker"],
        "company": p["company"],
        "fiscal_year": p["fiscal_year"],
        "section_code": p["section_code"],
        "section": p["section"],
        "kind": p["kind"],
        "caption": p["context"].split("Table:", 1)[1].strip() if "Table:" in p["context"] else "",
        "content": p["content"],
        "rerank": None if p.get("rerank") is None else round(p["rerank"], 3),
        "dense": None if p.get("dense") is None else round(p["dense"], 3),
    }


def run(question: str, opts: PipelineOptions | None = None) -> Iterator[dict]:
    opts = opts or PipelineOptions()
    t_start = time.perf_counter()
    question = question.strip()
    try:
        llm = get_llm()
    except LLMError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    # 1. Plan ---------------------------------------------------------------
    t0 = time.perf_counter()
    yield _step("plan", "Read the question", "running")
    if opts.use_agent:
        subqueries = plan_subqueries(question)
        search_query = _plan_query(question)
    else:
        subqueries, search_query = [SubQuery()], question
    detail = f'Search for "{search_query}" in ' + "; ".join(s.label for s in subqueries)
    yield _step("plan", "Read the question", "done", detail, _ms(t0),
                search_query=search_query, subqueries=[s.label for s in subqueries])

    # 2. Retrieve (with one retry per weak sub-search) ------------------------
    per_query: list[list[dict]] = []
    try:
        for i, sq in enumerate(subqueries):
            sid = f"search-{i}"
            label = f"Search {sq.label}"
            yield _step(sid, label, "running")
            passages, info = retrieve(search_query, sq.tickers, sq.years, opts)
            detail = (f"{info['vector_hits']} by meaning, {info['keyword_hits']} by keyword; "
                      f"best match {info['confidence']:.2f}")
            yield _step(sid, label, "done", detail, info["ms"], confidence=info["confidence"])

            retries = settings.max_retries if opts.use_agent else 0
            query = search_query
            while retries > 0 and is_weak(passages, opts):
                retries -= 1
                t0 = time.perf_counter()
                rid = f"retry-{i}"
                yield _step(rid, f"Retry {sq.label}", "running", "Best match was weak; rewording the search")
                new_query = _reformulate(question, query)
                if not new_query:
                    yield _step(rid, f"Retry {sq.label}", "done", "No better wording found", _ms(t0))
                    break
                alt, alt_info = retrieve(new_query, sq.tickers, sq.years, opts)
                better = confidence(alt) > confidence(passages)
                if better:
                    passages, query = alt, new_query
                yield _step(rid, f"Retry {sq.label}", "done",
                            f'Tried "{new_query}": best match {alt_info["confidence"]:.2f}'
                            + (" (kept)" if better else " (discarded)"), _ms(t0))
            per_query.append(passages)
    except Exception as exc:
        yield {"type": "error", "message": f"Search failed: {exc}. Is the database running and indexed?"}
        return

    passages = _merge(per_query, settings.max_context_passages)
    yield {"type": "sources", "sources": [public_source(i, p) for i, p in enumerate(passages, 1)]}

    def refuse(reason: str):
        yield {"type": "answer", "text": REFUSAL_TEXT, "refused": True, "reason": reason}
        yield {"type": "done", "refused": True, "total_ms": _ms(t_start)}

    if not passages:
        yield from refuse("No passages matched these companies and years.")
        return
    if opts.use_rerank and confidence(passages) < settings.refuse_below_rerank:
        yield from refuse("Nothing in the filings is close to this question.")
        return

    # 3. Draft ------------------------------------------------------------------
    t0 = time.perf_counter()
    yield _step("draft", f"Write the answer with {llm.model}", "running")
    try:
        answer = llm.complete(
            prompts.ANSWER_SYSTEM,
            prompts.ANSWER_USER.format(sources=format_sources(passages), question=question),
            task="answer",
        ).strip()
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}
        return
    yield _step("draft", f"Write the answer with {llm.model}", "done", f"{len(answer.split())} words", _ms(t0))

    if "INSUFFICIENT_EVIDENCE" in answer or not answer:
        yield from refuse("The model found no answer in the sources.")
        return
    yield {"type": "answer", "text": answer, "refused": False}

    # 4. Verify -----------------------------------------------------------------
    if opts.use_verify:
        t0 = time.perf_counter()
        yield _step("verify", "Check each sentence against its sources", "running")
        result = verify_answer(answer, passages)
        yield _step("verify", "Check each sentence against its sources", "done",
                    f"{result['verified']} of {result['total']} sentences agree with the filings", _ms(t0))
        yield {"type": "verification", **result}

    yield {"type": "done", "refused": False, "total_ms": _ms(t_start)}


def answer(question: str, opts: PipelineOptions | None = None) -> dict:
    """Non-streaming helper: run the pipeline and collect everything into one dict."""
    out = {"question": question, "steps": [], "sources": [], "answer": None, "refused": False,
           "verification": None, "error": None, "total_ms": None}
    for ev in run(question, opts):
        t = ev["type"]
        if t == "step" and ev["status"] == "done":
            out["steps"].append(ev)
        elif t == "sources":
            out["sources"] = ev["sources"]
        elif t == "answer":
            out["answer"], out["refused"] = ev["text"], ev["refused"]
        elif t == "verification":
            out["verification"] = {k: v for k, v in ev.items() if k != "type"}
        elif t == "done":
            out["total_ms"] = ev["total_ms"]
        elif t == "error":
            out["error"] = ev["message"]
    return out
