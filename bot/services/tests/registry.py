# bot/services/tests/registry.py
from dataclasses import dataclass

@dataclass(frozen=True)
class TestMeta:
    code: str
    title: str
    file: str  # путь до JSON
    depends_on: str | None = None  # код теста-предшественника

TESTS: list[TestMeta] = [
    TestMeta(code="theory_1", title="1 тест", file="bot/data/tests/theory_1.json", depends_on=None),
    TestMeta(code="theory_2", title="2 тест", file="bot/data/tests/theory_2.json", depends_on="theory_1"),
    TestMeta(code="theory_3", title="3 тест", file="bot/data/tests/theory_3.json", depends_on="theory_2"),
    TestMeta(code="theory_4", title="4 тест", file="bot/data/tests/theory_4.json", depends_on="theory_3"),
    TestMeta(code="theory_5", title="5 тест", file="bot/data/tests/theory_5.json", depends_on="theory_4"),
    TestMeta(code="theory_6", title="6 тест", file="bot/data/tests/theory_6.json", depends_on="theory_5"),
    TestMeta(code="theory_7", title="7 тест", file="bot/data/tests/theory_7.json", depends_on="theory_6"),
    TestMeta(code="theory_8", title="8 тест", file="bot/data/tests/theory_8.json", depends_on="theory_7"),
    TestMeta(code="theory_9", title="9 тест", file="bot/data/tests/theory_9.json", depends_on="theory_8"),
    TestMeta(code="theory_10", title="10 тест", file="bot/data/tests/theory_10.json", depends_on="theory_9"),
]

def get_tests():
    return TESTS

def get_test(code: str) -> TestMeta | None:
    for t in TESTS:
        if t.code == code:
            return t
    return None