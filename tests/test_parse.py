from pathlib import Path

from src.ingest.parse import TABLE_OPEN, chunk_section, html_to_text, split_sections

HTML = (Path(__file__).parent / "sample_10k.html").read_text()


def test_hidden_xbrl_and_toc_removed():
    text = html_to_text(HTML)
    assert "999999" not in text
    assert "Risk Factors | 12" not in text  # table of contents dropped


def test_dollar_cells_merged():
    text = html_to_text(HTML)
    assert "Research and development | $8,675 | $7,339" in text
    assert "14.2%" in text


def test_sections_found_and_longest_kept():
    sections = split_sections(html_to_text(HTML), min_chars=100)
    assert {"1", "1A", "7", "8"} <= set(sections)
    assert "single supplier" in sections["1A"]
    assert TABLE_OPEN in sections["7"]


def test_table_chunk_keeps_caption():
    sections = split_sections(html_to_text(HTML), min_chars=100)
    chunks = chunk_section(sections["7"])
    tables = [c for c in chunks if c["kind"] == "table"]
    assert len(tables) == 1
    assert "8,675" in tables[0]["content"]
    assert "research and development expense" in tables[0]["caption"].lower()
