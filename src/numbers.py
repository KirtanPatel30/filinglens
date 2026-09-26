"""Find numbers in text and check whether a number in an answer appears in a source.

10-K tables usually report "in millions", so "$8.7 billion" in an answer should match
"8,675" in a table. We therefore compare values at several scales and allow for the
rounding the answer itself implies (8.7 means anything from 8.65 to 8.75).
"""
import re
from dataclasses import dataclass

SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
NUM_RE = re.compile(
    r"(?P<dollar>\$\s*)?\(?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<dec>\d+))?\)?"
    r"\s*(?P<unit>%|percent\b|thousand\b|million\b|billion\b|trillion\b)?",
    re.I,
)
IGNORE_RE = re.compile(r"\[\d+\]|10-k|10-q|item\s+\d+[a-c]?|form\s+\d+", re.I)


@dataclass
class Num:
    raw: str
    value: float  # as written, before scale
    decimals: int
    unit: str  # "%", a scale word, or ""
    dollar: bool

    @property
    def is_percent(self) -> bool:
        return self.unit in {"%", "percent"}

    @property
    def scale(self) -> float:
        return SCALES.get(self.unit, 1.0)

    @property
    def is_year(self) -> bool:
        return (
            not self.unit and not self.dollar and self.decimals == 0
            and 1990 <= self.value <= 2039 and "," not in self.raw
        )

    @property
    def is_trivial(self) -> bool:
        """Small bare integers (like 'three segments' written as 3) aren't worth checking."""
        return not self.unit and not self.dollar and self.decimals == 0 and self.value < 10


def extract_numbers(text: str) -> list[Num]:
    text = IGNORE_RE.sub(" ", text)
    out = []
    for m in NUM_RE.finditer(text):
        whole = m.group("int").replace(",", "")
        dec = m.group("dec") or ""
        value = float(f"{whole}.{dec}" if dec else whole)
        unit = (m.group("unit") or "").lower()
        out.append(Num(m.group(0).strip(), value, len(dec), unit, bool(m.group("dollar"))))
    return out


def checkable(nums: list[Num]) -> list[Num]:
    return [n for n in nums if not n.is_year and not n.is_trivial]


def number_in_text(n: Num, source_nums: list[Num]) -> bool:
    """True if the answer number `n` agrees with any number in the source."""
    half_step = 0.5 * 10 ** (-n.decimals)  # rounding room implied by how n was written

    if n.is_percent:
        return any(abs(s.value - n.value) <= half_step + 1e-9 for s in source_nums)

    target = n.value * n.scale
    tol = half_step * n.scale + 1e-9
    for s in source_nums:
        if s.is_percent:
            continue
        if s.unit in SCALES:
            candidates = [s.value * s.scale]
        else:  # table numbers are usually "in thousands/millions"; try each
            candidates = [s.value * k for k in (1.0, 1e3, 1e6, 1e9)]
        if any(abs(c - target) <= tol for c in candidates):
            return True
    return False
