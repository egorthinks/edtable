"""Слой разбора пожеланий: текст участника -> пожелания и важность для аукциона.

Любой разборщик реализует parse(text, days, periods) -> list[WishSpec].
"""

from typing import Protocol

from edtable.llm.lmstudio import LMStudioParser
from edtable.llm.rules import RuleParser
from edtable.llm.spec import WishParserError, WishSpec, to_offers
from edtable.scheduler.auction import Offer
from edtable.scheduler.problem import SchedulingProblem


class WishParser(Protocol):
    name: str

    def parse(self, text: str, days: list[int], periods: int) -> list[WishSpec]: ...


def parse_wishes(
    parser: WishParser, texts: dict[str, str], problem: SchedulingProblem
) -> dict[str, list[Offer]]:
    days = list(problem.days)
    periods = max(slot.period for slot in problem.slots)
    return {
        owner: to_offers(owner, parser.parse(text, days, periods), problem.slots)
        for owner, text in texts.items()
    }


__all__ = [
    "LMStudioParser",
    "RuleParser",
    "WishParser",
    "WishParserError",
    "WishSpec",
    "parse_wishes",
    "to_offers",
]
