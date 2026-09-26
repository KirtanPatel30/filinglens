"""Check every sentence of an answer against the sources it cites.

For each sentence we ask two questions:
  1. Numbers: does every figure in the sentence appear in a cited source (allowing for
     "in millions" tables and rounding)?
  2. Meaning: is the sentence close in meaning to some sentence or table row of a cited
     source (embedding similarity)?

Statuses:
  verified         cited, numbers found, meaning supported
  number_mismatch  a figure in the sentence isn't in any cited source
  weak_support     cited, but no source passage says something close to it
  uncited          no source number at all
"""
import re

import numpy as np

from src.config import settings
from src.embeddings import get_embedder
from src.numbers import checkable, extract_numbers, number_in_text

CITE_RE = re.compile(r"\[(\d+)\]")
ABBREVIATIONS = ["Inc.", "Corp.", "Co.", "Ltd.", "U.S.", "No.", "vs.", "approx.", "e.g.", "i.e."]
MAX_SEGMENTS_PER_SOURCE = 80


def split_sentences(answer: str) -> list[str]:
    text = answer.strip()
    for i, abbr in enumerate(ABBREVIATIONS):
        text = text.replace(abbr, f"\u0000{i}\u0000")
    # "...billion. [1]" -> "...billion [1]."
    text = re.sub(r"([.!?])\s*((?:\[\d+\]\s*)+)", lambda m: " " + m.group(2).strip() + m.group(1) + " ", text)
    parts = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*[-*\u2022]\s*", "", line).strip()
        if line:
            parts.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+(?=\S)", line) if p.strip())
    out = []
    for p in parts:
        for i, abbr in enumerate(ABBREVIATIONS):
            p = p.replace(f"\u0000{i}\u0000", abbr)
        if CITE_RE.fullmatch(p.strip(" .")) and out:  # a lone "[2]." belongs to the previous one
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def segments(passage: dict) -> list[str]:
    """Break a source into sentences (text) or rows (tables) for fine-grained matching."""
    if passage["kind"] == "table":
        segs = [row for row in passage["content"].split("\n") if row.strip()]
    else:
        flat = passage["content"].replace("\n", " ")
        segs = [s for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.split()) >= 4]
    return segs[:MAX_SEGMENTS_PER_SOURCE] or [passage["content"][:500]]


def verify_answer(answer: str, passages: list[dict]) -> dict:
    embedder = get_embedder()
    sentences = split_sentences(answer)
    seg_cache: dict[int, tuple[list[str], np.ndarray]] = {}

    def source_segments(idx: int):
        if idx not in seg_cache:
            segs = segments(passages[idx])
            seg_cache[idx] = (segs, embedder.embed_passages(segs))
        return seg_cache[idx]

    claims = []
    for sentence in sentences:
        cites = [int(n) for n in CITE_RE.findall(sentence)]
        valid = sorted({n for n in cites if 1 <= n <= len(passages)})
        clean = re.sub(r"\s+([.,;:!?])", r"\1", CITE_RE.sub("", sentence)).strip()
        claim = {
            "text": clean,
            "cites": valid,
            "status": "uncited",
            "similarity": None,
            "evidence": None,
            "evidence_source": None,
            "numbers_checked": [],
            "numbers_missing": [],
        }
        if not valid:
            claims.append(claim)
            continue

        # 1) numbers
        source_text = " ".join(passages[n - 1]["content"] + " " + passages[n - 1]["context"] for n in valid)
        source_nums = extract_numbers(source_text)
        for num in checkable(extract_numbers(clean)):
            (claim["numbers_checked"] if number_in_text(num, source_nums) else claim["numbers_missing"]).append(num.raw)

        # 2) meaning
        qvec = embedder.embed_passages([clean])[0]
        best = (-1.0, None, None)
        for n in valid:
            segs, vecs = source_segments(n - 1)
            sims = vecs @ qvec
            j = int(np.argmax(sims))
            if sims[j] > best[0]:
                best = (float(sims[j]), segs[j], n)
        claim["similarity"] = round(best[0], 3)
        claim["evidence"], claim["evidence_source"] = best[1], best[2]

        numbers_ok = not claim["numbers_missing"]
        has_numbers = bool(claim["numbers_checked"])
        # A sentence whose figures all check out needs a little less wording overlap.
        threshold = settings.support_threshold - (0.08 if has_numbers else 0.0)
        if not numbers_ok:
            claim["status"] = "number_mismatch"
        elif best[0] >= threshold:
            claim["status"] = "verified"
        else:
            claim["status"] = "weak_support"
        claims.append(claim)

    verified = sum(c["status"] == "verified" for c in claims)
    return {
        "claims": claims,
        "verified": verified,
        "total": len(claims),
        "faithfulness": round(verified / len(claims), 3) if claims else 0.0,
    }
