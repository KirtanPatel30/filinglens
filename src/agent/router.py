"""Work out which companies and years a question is about, and split comparison
questions into one search per company/year.

This part is deterministic on purpose: small local models are unreliable at extracting
filters, and regex + an alias list is fast, testable and never hallucinates a ticker.
"""
import itertools
import re
from dataclasses import dataclass, field

from src.ingest.companies import COMPANIES

MAX_SUBQUERIES = 6


@dataclass
class SubQuery:
    tickers: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)

    @property
    def label(self) -> str:
        parts = []
        if self.tickers:
            parts.append(", ".join(self.tickers))
        if self.years:
            parts.append("FY" + ", FY".join(str(y) for y in self.years))
        return " ".join(parts) or "all filings"


def find_tickers(question: str) -> list[str]:
    q = question.lower()
    found: list[str] = []
    for ticker, info in COMPANIES.items():
        names = info["aliases"] + [info["name"].lower()]
        if any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", q) for n in names):
            found.append(ticker)
            continue
        if len(ticker) >= 2 and re.search(rf"(?<![A-Za-z$]){ticker}(?![A-Za-z])", question):
            found.append(ticker)
    return found


def find_years(question: str) -> list[int]:
    years = {int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", question)}
    years |= {2000 + int(y) for y in re.findall(r"\bFY\s?'?(\d{2})\b", question, re.I)}
    return sorted(years)


def plan_subqueries(question: str) -> list[SubQuery]:
    tickers, years = find_tickers(question), find_years(question)
    if len(tickers) > 1 and len(years) > 1:
        combos = [SubQuery([t], [y]) for t, y in itertools.product(tickers, years)]
    elif len(tickers) > 1:
        combos = [SubQuery([t], years) for t in tickers]
    elif len(years) > 1:
        combos = [SubQuery(tickers, [y]) for y in years]
    else:
        combos = [SubQuery(tickers, years)]
    return combos[:MAX_SUBQUERIES]
