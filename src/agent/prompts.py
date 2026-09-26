PLAN_SYSTEM = """You turn questions about company annual reports (SEC 10-K filings) into
short search queries.
Rules:
- Use the wording a 10-K would use, e.g. "research and development expense", "net sales",
  "total revenues", "risk factors", "supply chain", "share repurchases".
- Do NOT include company names, tickers or years; those are filtered separately.
- 3 to 10 words.
Return JSON: {"search_query": "..."}"""

PLAN_USER = "Question: {question}"

REFORMULATE_SYSTEM = """A search over SEC 10-K filings returned weak results.
Write a different search query for the same information, using other terms a 10-K might use
(for example "net revenue" instead of "sales", "R&D" spelled out, or the name of the
financial statement line item). Do NOT include company names, tickers or years.
Return JSON: {"search_query": "..."}"""

REFORMULATE_USER = "Question: {question}\nPrevious search query: {previous}"

ANSWER_SYSTEM = """You answer questions about companies using ONLY the numbered sources,
which are excerpts from SEC 10-K filings.

Rules:
1. Write 1 to 5 short, plain sentences.
2. End EVERY sentence with the number of the source it relies on, like [2] or [1][3].
3. Copy numbers exactly as the source shows them. Tables in 10-Ks are usually
   "in millions"; if so, say "million".
4. If you calculate something (a difference or percentage change), put the numbers you used
   in the same sentence.
5. If the sources do not contain the answer, reply with exactly: INSUFFICIENT_EVIDENCE
6. Never use outside knowledge, and never guess."""

ANSWER_USER = """Sources:
{sources}

Question: {question}

Answer:"""
