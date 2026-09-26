"""Postgres + pgvector: schema, inserts, and the two searches (vector and keyword)."""
import re
from functools import lru_cache

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.config import settings

COLUMNS = "id, ticker, company, fiscal_year, section_code, section, kind, context, content"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "is", "was", "what", "how",
    "did", "does", "do", "its", "it", "their", "they", "which", "from", "with", "by", "as", "at",
    "be", "are", "were", "this", "that", "about", "much", "many", "between", "compare", "vs",
}


def init_schema() -> None:
    dim = int(settings.embed_dim)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id           BIGSERIAL PRIMARY KEY,
                ticker       TEXT NOT NULL,
                company      TEXT NOT NULL,
                fiscal_year  INT  NOT NULL,
                filing_date  DATE,
                section_code TEXT NOT NULL,
                section      TEXT NOT NULL,
                kind         TEXT NOT NULL,
                context      TEXT NOT NULL,
                content      TEXT NOT NULL,
                embedding    vector({dim}) NOT NULL,
                tsv tsvector GENERATED ALWAYS AS
                    (to_tsvector('english', context || ' ' || content)) STORED
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv)")
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_filter_idx ON chunks (ticker, fiscal_year)")
        # No approximate (HNSW) index on purpose: at ~20k chunks an exact scan takes a few
        # milliseconds and stays correct when filtering by company and year.


def reset_table() -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks")
    init_schema()


@lru_cache(maxsize=1)
def pool() -> ConnectionPool:
    init_schema()
    return ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        configure=register_vector,
        open=True,
    )


def insert_chunks(rows: list[dict], vectors: np.ndarray) -> None:
    with psycopg.connect(settings.database_url) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (ticker, company, fiscal_year, filing_date, section_code,
                   section, kind, context, content, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [
                    (
                        r["ticker"], r["company"], r["fiscal_year"], r.get("filing_date"),
                        r["section_code"], r["section"], r["kind"], r["context"], r["content"], v,
                    )
                    for r, v in zip(rows, vectors)
                ],
            )
        conn.commit()


def delete_tickers(tickers: list[str]) -> int:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        return conn.execute("DELETE FROM chunks WHERE ticker = ANY(%s)", (tickers,)).rowcount


def _filters(tickers: list[str] | None, years: list[int] | None) -> tuple[str, dict]:
    clauses, params = [], {}
    if tickers:
        clauses.append("ticker = ANY(%(tickers)s)")
        params["tickers"] = list(tickers)
    if years:
        clauses.append("fiscal_year = ANY(%(years)s)")
        params["years"] = list(years)
    return (" AND ".join(clauses) or "TRUE"), params


def dense_search(qvec: np.ndarray, k: int, tickers=None, years=None) -> list[dict]:
    where, params = _filters(tickers, years)
    params.update({"q": np.asarray(qvec, dtype=np.float32), "k": k})
    sql = f"""SELECT {COLUMNS}, 1 - (embedding <=> %(q)s) AS score
              FROM chunks WHERE {where}
              ORDER BY embedding <=> %(q)s LIMIT %(k)s"""
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def keyword_query(text: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in STOPWORDS]
    return " | ".join(dict.fromkeys(toks))  # OR the words together, keep order, no repeats


def keyword_search(text: str, k: int, tickers=None, years=None) -> list[dict]:
    tsq = keyword_query(text)
    if not tsq:
        return []
    where, params = _filters(tickers, years)
    params.update({"tsq": tsq, "k": k})
    sql = f"""SELECT {COLUMNS}, ts_rank_cd(tsv, q, 32) AS score
              FROM chunks, to_tsquery('english', %(tsq)s) q
              WHERE tsv @@ q AND {where}
              ORDER BY score DESC LIMIT %(k)s"""
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def coverage() -> list[dict]:
    sql = """SELECT ticker, company, fiscal_year, COUNT(*) AS chunks,
                    SUM((kind = 'table')::int) AS tables
             FROM chunks GROUP BY ticker, company, fiscal_year
             ORDER BY ticker, fiscal_year"""
    with pool().connection() as conn:
        return conn.execute(sql).fetchall()


def ping() -> bool:
    try:
        with pool().connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
