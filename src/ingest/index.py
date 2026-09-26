"""Step 3: embed every chunk and load it into Postgres.

Run:  python -m src.ingest.index            (adds to the existing table)
      python -m src.ingest.index --reset    (wipes the table first; use after re-parsing)
      python -m src.ingest.index --limit 500  (quick test run)
      python -m src.ingest.index --only MSFT  (replace just these companies)
"""
import argparse
import json
import sys
import time

from src import db
from src.config import PROCESSED_DIR
from src.embeddings import get_embedder

BATCH = 256


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate the chunks table")
    ap.add_argument("--limit", type=int, default=0, help="only index the first N chunks")
    ap.add_argument("--only", nargs="+", metavar="TICKER", help="re-index only these companies")
    args = ap.parse_args()

    path = PROCESSED_DIR / "chunks.jsonl"
    if not path.exists():
        sys.exit("No data/processed/chunks.jsonl found. Run: python -m src.ingest.parse")

    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    if args.only:
        wanted = {t.upper() for t in args.only}
        rows = [r for r in rows if r["ticker"] in wanted]
        if not rows:
            sys.exit(f"No chunks for {', '.join(sorted(wanted))}. Did you run the parse step?")
    if args.limit:
        rows = rows[: args.limit]

    if args.reset:
        db.reset_table()
    else:
        db.init_schema()
    if args.only:
        removed = db.delete_tickers(sorted({r["ticker"] for r in rows}))
        print(f"  removed {removed} old chunks for {', '.join(args.only).upper()}")

    embedder = get_embedder()
    start = time.time()
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vectors = embedder.embed_passages([f"{r['context']}\n{r['content']}" for r in batch])
        db.insert_chunks(batch, vectors)
        done = i + len(batch)
        rate = done / max(time.time() - start, 1e-6)
        left = (len(rows) - done) / max(rate, 1e-6)
        print(f"  {done:>6}/{len(rows)} chunks   ~{left / 60:.1f} min left", end="\r")
    print(f"\nDone. Indexed {len(rows)} chunks in {(time.time() - start) / 60:.1f} min.")


if __name__ == "__main__":
    main()
