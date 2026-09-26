"""Step 2: turn raw 10-K HTML into searchable chunks.

Run:  python -m src.ingest.parse
Reads data/raw/*.html + manifest.json, writes data/processed/chunks.jsonl.

What it does:
  1. Strips hidden XBRL data, scripts and styles.
  2. Converts real data tables into pipe-separated rows (and drops the table of contents).
  3. Splits the document into 10-K Items (Risk Factors, MD&A, Financial Statements, ...).
  4. Cuts each Item into ~300-word text chunks, and keeps every table as its own chunk
     together with the sentence that introduces it.
"""
import json
import re
import sys

from bs4 import BeautifulSoup, NavigableString

from src.config import PROCESSED_DIR, RAW_DIR
from src.ingest.companies import SECTION_NAMES

TABLE_OPEN, TABLE_CLOSE = "[[TABLE]]", "[[/TABLE]]"
BLOCK_TAGS = ["p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"]
TEXT_CHUNK_WORDS = 300
TEXT_OVERLAP_WORDS = 40
TABLE_CHUNK_WORDS = 350
MIN_SECTION_CHARS = 400

HEADING_RE = re.compile(
    r"^\s*(?:part\s+[iv]+\W*)?item\s+(\d{1,2}[a-c]?)\b[\s.:\-\u2013\u2014]*(.{0,120})$", re.I
)
PAGE_NOISE_RE = re.compile(
    r"^(\d{1,3}|page \d+|table of contents|index)$|form 10-k.{0,30}\|?\s*\d{1,3}$", re.I
)


# ---------------------------------------------------------------- HTML -> text

def _clean_cells(cells: list[str]) -> list[str]:
    """Merge the '$', '(' and ')' / '%' fragments that 10-K tables put in their own cells."""
    out: list[str] = []
    carry = ""
    for raw in cells:
        c = re.sub(r"\s+", " ", raw).strip()
        if not c:
            continue
        if c in {"$", "(", "$(", "($"}:
            carry += c
            continue
        if c in {")", "%", ")%", "%)"} and out:
            out[-1] += c
            continue
        out.append(carry + c)
        carry = ""
    return out


def table_to_rows(table) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = _clean_cells([td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])])
        if cells:
            rows.append(cells)
    return rows


def _is_toc(rows: list[list[str]]) -> bool:
    item_rows = sum(1 for r in rows if re.match(r"^item\s*\d", r[0], re.I))
    return item_rows >= 3


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "head", "title", "meta", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(lambda t: t.name and t.name.lower() in {"ix:header", "ix:hidden"}):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()

    # Tables first (innermost only), so their rows are kept together.
    for table in soup.find_all("table"):
        if table.find("table"):
            continue
        rows = table_to_rows(table)
        multi_cell_rows = [r for r in rows if len(r) >= 2]
        if not rows:
            table.replace_with(NavigableString("\n"))
        elif _is_toc(rows):
            table.replace_with(NavigableString("\n"))
        elif len(multi_cell_rows) >= 2 and any(re.search(r"\d", " ".join(r)) for r in rows):
            body = "\n".join(" | ".join(r) for r in rows)
            table.replace_with(NavigableString(f"\n{TABLE_OPEN}\n{body}\n{TABLE_CLOSE}\n"))
        else:  # layout table: keep as normal text
            table.replace_with(NavigableString("\n" + "\n".join(" ".join(r) for r in rows) + "\n"))

    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for tag in soup.find_all(BLOCK_TAGS):
        tag.append(NavigableString("\n"))

    text = soup.get_text()
    text = text.replace("\xa0", " ").replace("\u200b", "")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line or PAGE_NOISE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------- sections

def split_sections(text: str, min_chars: int = MIN_SECTION_CHARS) -> dict[str, str]:
    """Return {item_code: text}. When an Item appears more than once (the table of
    contents, cross-references), keep the longest block, which is the real section."""
    lines = text.split("\n")
    marks: list[tuple[int, str]] = []
    in_table = False
    for i, line in enumerate(lines):
        if line == TABLE_OPEN:
            in_table = True
        elif line == TABLE_CLOSE:
            in_table = False
        elif not in_table and len(line) < 160:
            m = HEADING_RE.match(line)
            if m and m.group(1).upper() in SECTION_NAMES:
                code = m.group(1).upper()
                # Some 10-Ks (Microsoft's, for example) repeat "Item 7" as a header on every
                # page. A repeat of the current item continues that section.
                if marks and marks[-1][1] == code:
                    lines[i] = ""
                    continue
                marks.append((i, code))

    best: dict[str, str] = {}
    for idx, (start, code) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        block = "\n".join(lines[start + 1 : end]).strip()
        if len(block) > len(best.get(code, "")):
            best[code] = block
    return {k: v for k, v in best.items() if len(v) >= min_chars}


# ---------------------------------------------------------------- chunking

def _word_windows(words: list[str], size: int, overlap: int) -> list[str]:
    out, step = [], max(1, size - overlap)
    for i in range(0, len(words), step):
        out.append(" ".join(words[i : i + size]))
        if i + size >= len(words):
            break
    return out


def chunk_section(text: str) -> list[dict]:
    """Split one section into text chunks and table chunks."""
    chunks: list[dict] = []
    buf: list[str] = []
    buf_words = 0
    last_para = ""

    def flush():
        nonlocal buf, buf_words
        if buf:
            chunks.append({"kind": "text", "content": "\n".join(buf), "caption": ""})
            tail = " ".join(" ".join(buf).split()[-TEXT_OVERLAP_WORDS:])
            buf, buf_words = ([tail], len(tail.split())) if tail else ([], 0)

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == TABLE_OPEN:
            j = i + 1
            rows = []
            while j < len(lines) and lines[j] != TABLE_CLOSE:
                rows.append(lines[j])
                j += 1
            chunks.extend(_chunk_table(rows, caption=last_para))
            i = j + 1
            continue
        if line == TABLE_CLOSE:  # stray marker from a cut-off block
            i += 1
            continue

        words = line.split()
        if len(words) > TEXT_CHUNK_WORDS * 1.5:
            flush()
            for piece in _word_windows(words, TEXT_CHUNK_WORDS, TEXT_OVERLAP_WORDS):
                chunks.append({"kind": "text", "content": piece, "caption": ""})
            buf, buf_words = [], 0
        else:
            buf.append(line)
            buf_words += len(words)
            if buf_words >= TEXT_CHUNK_WORDS:
                flush()
        if len(line) < 400:
            last_para = line
        i += 1

    if buf and buf_words > TEXT_OVERLAP_WORDS:
        chunks.append({"kind": "text", "content": "\n".join(buf), "caption": ""})
    return [c for c in chunks if len(c["content"].split()) >= 8]


def _chunk_table(rows: list[str], caption: str) -> list[dict]:
    if not rows:
        return []
    header = rows[:2]
    out, current, count = [], [], 0
    for row in rows:
        n = len(row.split())
        if current and count + n > TABLE_CHUNK_WORDS:
            out.append(current)
            current = list(header) if len(rows) > 4 else []
            count = sum(len(r.split()) for r in current)
        current.append(row)
        count += n
    if current:
        out.append(current)
    return [{"kind": "table", "content": "\n".join(rs), "caption": caption[:300]} for rs in out]


# ---------------------------------------------------------------- filing -> chunks

def parse_filing(html: str, meta: dict, min_chars: int = MIN_SECTION_CHARS) -> list[dict]:
    text = html_to_text(html)
    sections = split_sections(text, min_chars)
    chunks = []
    for code, body in sections.items():
        name = SECTION_NAMES.get(code, f"Item {code}")
        for c in chunk_section(body):
            context = (
                f"{meta['company']} ({meta['ticker']}) 10-K, fiscal {meta['fiscal_year']}, "
                f"Item {code} {name}"
            )
            if c["kind"] == "table" and c["caption"]:
                context += f". Table: {c['caption']}"
            chunks.append(
                {
                    "ticker": meta["ticker"],
                    "company": meta["company"],
                    "fiscal_year": meta["fiscal_year"],
                    "filing_date": meta.get("filing_date"),
                    "section_code": code,
                    "section": name,
                    "kind": c["kind"],
                    "context": context,
                    "content": c["content"],
                }
            )
    return chunks


def main() -> None:
    manifest_path = RAW_DIR / "manifest.json"
    if not manifest_path.exists():
        sys.exit("No data/raw/manifest.json found. Run: python -m src.ingest.download")
    manifest = json.loads(manifest_path.read_text())
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "chunks.jsonl"

    total = 0
    with out_path.open("w", encoding="utf-8") as out:
        for meta in manifest:
            path = RAW_DIR / meta["file"]
            if not path.exists():
                print(f"  missing {meta['file']}")
                continue
            chunks = parse_filing(path.read_text(encoding="utf-8", errors="ignore"), meta)
            sections = sorted({c["section_code"] for c in chunks})
            tables = sum(c["kind"] == "table" for c in chunks)
            print(f"  {meta['file']:<22} {len(chunks):>5} chunks  {tables:>4} tables  items {', '.join(sections)}")
            if len(sections) < 4:
                print("    warning: few sections found; this filing may use an unusual layout")
            for c in chunks:
                out.write(json.dumps(c) + "\n")
            total += len(chunks)
    print(f"\nDone. {total} chunks written to {out_path}")


if __name__ == "__main__":
    main()
