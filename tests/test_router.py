from src.agent.router import find_tickers, find_years, plan_subqueries


def test_aliases_and_tickers():
    assert find_tickers("How did Google and Facebook compare?") == ["GOOGL", "META"]
    assert find_tickers("What does NVDA say about export controls?") == ["NVDA"]
    assert find_tickers("What did the purchase agreement say?") == []  # 'chase' inside a word


def test_years():
    assert find_years("from 2022 to 2024") == [2022, 2024]
    assert find_years("in FY23") == [2023]


def test_comparison_split():
    subs = plan_subqueries("Compare Nvidia R&D in 2022 and 2024")
    assert [(s.tickers, s.years) for s in subs] == [(["NVDA"], [2022]), (["NVDA"], [2024])]
    subs = plan_subqueries("Apple vs Microsoft revenue in 2024")
    assert [(s.tickers, s.years) for s in subs] == [(["AAPL"], [2024]), (["MSFT"], [2024])]
