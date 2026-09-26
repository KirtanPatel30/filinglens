"""Benchmark the pipeline and produce an ablation table.

Run:  python -m eval.run_eval                 (all modes)
      python -m eval.run_eval --modes full     (one mode)
      python -m eval.run_eval --limit 5        (quick check)

Writes eval/results/ablation.md and eval/results/ablation.json.

Metrics
  Recall@5        a gold passage (right company, section, containing the key phrase) is in the top 5 sources
  Numbers         every expected figure appears in the answer (only questions with expected_numbers)
  Refusals        refuses the unanswerable questions and answers the answerable ones
  Faithfulness    share of answer sentences verified against their sources
  Median latency  seconds per question
"""
import argparse
import json
import statistics
import time
from pathlib import Path

from src.agent.pipeline import answer
from src.config import PipelineOptions
from src.numbers import extract_numbers, number_in_text

HERE = Path(__file__).parent
MODES = {
    "vector only": dict(use_bm25=False, use_rerank=False, use_agent=False, use_verify=True),
    "+ keyword (hybrid)": dict(use_bm25=True, use_rerank=False, use_agent=False, use_verify=True),
    "+ reranker": dict(use_bm25=True, use_rerank=True, use_agent=False, use_verify=True),
    "+ router and retry (full)": dict(use_bm25=True, use_rerank=True, use_agent=True, use_verify=True),
}


def gold_hit(sources: list[dict], gold: dict, k: int = 5) -> bool:
    for s in sources[:k]:
        if gold.get("ticker") and s["ticker"] != gold["ticker"]:
            continue
        if gold.get("fiscal_year") and s["fiscal_year"] != gold["fiscal_year"]:
            continue
        if gold.get("section_code") and s["section_code"] != gold["section_code"]:
            continue
        if gold.get("contains") and gold["contains"].lower() not in (s["content"] + s["caption"]).lower():
            continue
        return True
    return False


def numbers_ok(answer_text: str, expected: list[str]) -> bool:
    found = extract_numbers(answer_text or "")
    for e in expected:
        nums = extract_numbers(e)
        if not nums or not number_in_text(nums[0], found):
            return False
    return True


def pct(xs: list[bool]) -> str:
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"


def run_mode(name: str, flags: dict, questions: list[dict]) -> dict:
    opts = PipelineOptions(**flags)
    recall, nums, refusals, faith, latency, errors = [], [], [], [], [], 0
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        out = answer(q["question"], opts)
        secs = time.perf_counter() - t0
        latency.append(secs)
        if out["error"]:
            errors += 1
        refused = out["refused"]
        refusals.append(refused == (not q.get("answerable", True)))
        if q.get("answerable", True):
            if q.get("gold"):
                recall.append(gold_hit(out["sources"], q["gold"]))
            if q.get("expected_numbers"):
                nums.append(numbers_ok(out["answer"], q["expected_numbers"]))
            if out["verification"] and not refused:
                faith.append(out["verification"]["faithfulness"])
        rows.append({"id": q["id"], "refused": refused, "seconds": round(secs, 2),
                     "answer": out["answer"], "error": out["error"]})
        print(f"  [{name}] {q['id']:<28} {'refused' if refused else 'answered'}  {secs:.1f}s")
    return {
        "mode": name,
        "recall@5": pct(recall),
        "numbers": pct(nums),
        "refusals": pct(refusals),
        "faithfulness": f"{100 * statistics.mean(faith):.0f}%" if faith else "n/a",
        "median_s": f"{statistics.median(latency):.1f}" if latency else "n/a",
        "errors": errors,
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="*", help="subset of modes, e.g. --modes full")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    questions = json.loads((HERE / "questions.json").read_text())["questions"]
    if args.limit:
        questions = questions[: args.limit]
    modes = {k: v for k, v in MODES.items() if not args.modes or any(m in k for m in args.modes)}

    results = [run_mode(name, flags, questions) for name, flags in modes.items()]

    lines = [
        f"# Ablation results ({len(questions)} questions)\n",
        "| Setup | Recall@5 | Numbers correct | Correct refusals | Faithfulness | Median latency (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['mode']} | {r['recall@5']} | {r['numbers']} | {r['refusals']} | {r['faithfulness']} | {r['median_s']} |")
    if any(r["errors"] for r in results):
        lines.append("\nSome questions errored; see ablation.json.")
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "ablation.md").write_text("\n".join(lines) + "\n")
    (out_dir / "ablation.json").write_text(json.dumps(results, indent=2))
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
