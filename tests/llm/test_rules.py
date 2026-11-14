import pytest

from edtable.llm import RuleParser, WishSpec

DAYS, PERIODS = [0, 1, 2, 3, 4], 6


def parse(text: str) -> list[WishSpec]:
    return RuleParser().parse(text, DAYS, PERIODS)


def shape(spec: WishSpec):
    return spec.kind, spec.days, spec.periods, spec.limit


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Не ставьте мне первые уроки", ("avoid", [], [1], None)),
        ("Не раньше второго урока", ("avoid", [], [1], None)),
        ("Свободная пятница", ("avoid", [4], [], None)),
        ("Не ставьте в понедельник", ("avoid", [0], [], None)),
        ("По средам не могу после 4 урока", ("avoid", [2], [5, 6], None)),
        ("В пятницу заканчивать не позже 4 урока", ("avoid", [4], [5, 6], None)),
        ("Без окон", ("no_gaps", [], [], None)),
        ("Не больше 3 уроков в день", ("max_per_day", [], [], 3)),
        ("Работаю не больше двух дней в неделю", ("max_days", [], [], 2)),
    ],
)
def test_single_wishes(text, expected):
    [spec] = parse(text)

    assert shape(spec) == expected


def test_free_day_with_alternatives_becomes_any():
    [spec] = parse("Нужен один свободный день — понедельник или пятница")

    assert spec.kind == "any"
    assert [shape(p) for p in spec.parts] == [("avoid", [0], [], None), ("avoid", [4], [], None)]


def test_several_sentences_and_importance():
    specs = parse("Очень прошу не ставить первые пары. Желательно без окон.")

    assert [(s.kind, s.weight) for s in specs] == [("avoid", 9), ("no_gaps", 3)]


def test_explicit_points():
    [spec] = parse("Свободная среда — 70 очков")

    assert spec.points == 70


def test_nothing_to_parse():
    assert parse("Без разницы.") == []
    assert parse("") == []
