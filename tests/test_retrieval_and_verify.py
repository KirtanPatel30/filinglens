from src.agent.verify import split_sentences, verify_answer
from src.retrieval.search import rrf

PASSAGES = [
    {"kind": "table", "context": "Acme (ACME) 10-K, fiscal 2024, Item 7",
     "content": "2024 | 2023\nResearch and development | $8,675 | $7,339"},
    {"kind": "text", "context": "Acme (ACME) 10-K, fiscal 2024, Item 1A",
     "content": "The Company depends on a single supplier for rocket motors. Disruption could harm the supply chain."},
]


def test_rrf_rewards_agreement():
    a = [{"id": 1}, {"id": 2}, {"id": 3}]
    b = [{"id": 3}, {"id": 1}]
    assert [r["id"] for r in rrf([a, b])][:2] == [1, 3]


def test_sentence_split_moves_citations():
    s = split_sentences("R&D was $8,675 million. [1] Acme Inc. relies on one supplier [2].")
    assert len(s) == 2 and s[0].endswith("[1].") and "Inc." in s[1]


def test_verification_statuses():
    answer = (
        "Research and development was $8,675 million in 2024 [1]. "
        "Research and development was $9,999 million in 2024 [1]. "
        "The Company depends on a single supplier for rocket motors [2]. "
        "Acme plans to open stores on the moon."
    )
    result = verify_answer(answer, PASSAGES)
    statuses = [c["status"] for c in result["claims"]]
    assert statuses == ["verified", "number_mismatch", "verified", "uncited"]
    assert result["faithfulness"] == 0.5
