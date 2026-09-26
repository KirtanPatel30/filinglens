from src.numbers import checkable, extract_numbers, number_in_text


def src(text):
    return extract_numbers(text)


def one(text):
    return checkable(extract_numbers(text))[0]


def test_billion_matches_table_in_millions():
    assert number_in_text(one("R&D was $8.7 billion"), src("Research and development | $8,675 | $7,339"))


def test_exact_millions():
    assert number_in_text(one("$8,675 million"), src("R&D | $8,675"))


def test_wrong_number_rejected():
    assert not number_in_text(one("$9.4 billion"), src("R&D | $8,675 | $7,339"))


def test_percent_rounding():
    assert number_in_text(one("about 14%"), src("Percentage of net sales 14.2%"))
    assert not number_in_text(one("16.0%"), src("Percentage of net sales 14.2%"))


def test_years_and_citations_ignored():
    nums = checkable(extract_numbers("In fiscal 2024 revenue rose [3] per the 10-K"))
    assert nums == []
