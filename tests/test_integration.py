"""End-to-end test against a real Postgres (with pgvector).

Skipped unless FILINGLENS_TEST_DB=1, because it DROPS the chunks table.
CI sets this up with a throwaway database; don't point it at your real one.
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("FILINGLENS_TEST_DB") != "1", reason="needs a throwaway Postgres")


@pytest.fixture(scope="module")
def indexed():
    from src import db
    from src.embeddings import get_embedder
    from src.ingest.parse import parse_filing

    html = (Path(__file__).parent / "sample_10k.html").read_text()
    meta = {"ticker": "NVDA", "company": "NVIDIA", "fiscal_year": 2024, "filing_date": "2024-02-21"}
    chunks = parse_filing(html, meta, min_chars=100)
    db.reset_table()
    db.insert_chunks(chunks, get_embedder().embed_passages([c["context"] + "\n" + c["content"] for c in chunks]))
    return chunks


def test_pipeline_answers_and_verifies(indexed):
    from src.agent.pipeline import answer

    out = answer("What supply chain risks does Nvidia describe about a single supplier?")
    assert out["error"] is None, out["error"]
    assert out["sources"], "no sources retrieved"
    assert any(s["section_code"] == "1A" for s in out["sources"][:3])
    assert out["answer"] and not out["refused"]
    assert out["verification"]["total"] >= 1


def test_filters_exclude_unindexed_company(indexed):
    from src.agent.pipeline import answer

    out = answer("What was Netflix revenue in 2024?")
    assert out["refused"]


def test_api_endpoints(indexed):
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").json()["database"] is True
        cov = client.get("/api/coverage").json()
        assert cov["filings"][0]["ticker"] == "NVDA"
        r = client.post("/api/ask/stream", json={"question": "What research and development expense did Nvidia report in 2024?"})
        assert r.status_code == 200
        types = [line for line in r.text.split("\n") if line.startswith("data:")]
        assert any('"type": "done"' in t for t in types)
        assert client.get("/").status_code == 200
