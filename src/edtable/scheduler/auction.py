"""Аукцион очков: у каждого участника одинаковый бюджет, и он раскладывает его по
своим пожеланиям.

Равный бюджет — главное правило честности. Тот, кто написал двадцать пожеланий,
не получает больше веса, чем тот, кто написал одно: его очки просто размазаны
тоньше. Поэтому бюджет всегда тратится целиком — неиспользованные очки
распределяются пропорционально, иначе скромный участник проигрывал бы громкому.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from edtable.scheduler.schedule import Schedule
from edtable.scheduler.wishes import Bid, Wish

if TYPE_CHECKING:
    from edtable.scheduler.problem import SchedulingProblem

BUDGET = 100


@dataclass(frozen=True)
class Offer:
    """Пожелание до перевода в очки — то, что выдаёт разбор текста."""

    wish: Wish
    # Важность от 1 до 10, если человек не назвал очки сам.
    weight: float = 5
    points: int | None = None
    text: str = ""

    @property
    def raw(self) -> float:
        # Важность 10 — «готов отдать за это весь бюджет».
        return self.points if self.points is not None else self.weight * BUDGET / 10


def split_budget(raw: list[float], budget: int = BUDGET) -> list[int]:
    """Пропорционально делит бюджет в целых очках, сумма ровно budget.

    Округляем методом наибольшего остатка, чтобы не терять и не печатать очки.
    """
    total = sum(raw)
    if total <= 0:
        return [0] * len(raw)
    exact = [r * budget / total for r in raw]
    points = [int(x) for x in exact]
    by_remainder = sorted(range(len(raw)), key=lambda i: exact[i] - points[i], reverse=True)
    for i in by_remainder[: budget - sum(points)]:
        points[i] += 1
    return points


@dataclass(frozen=True)
class Refusal:
    owner: str
    offer: Offer
    reason: str


def screen(
    offers: dict[str, list[Offer]], problem: SchedulingProblem
) -> tuple[dict[str, list[Offer]], list[Refusal]]:
    """Убирает заведомо невыполнимые пожелания до аукциона.

    Иначе очки за них сгорают зря: участник поставил 100 на невозможное и
    остался ни с чем, хотя мог бы выиграть остальное. Убранные возвращаются
    с причиной, чтобы человеку можно было объяснить, что не так.
    """
    kept: dict[str, list[Offer]] = {}
    refused = []
    for owner, owner_offers in offers.items():
        kept[owner] = []
        for offer in owner_offers:
            if reason := offer.wish.impossible(problem):
                refused.append(Refusal(owner, offer, reason))
            else:
                kept[owner].append(offer)
    return kept, refused


def run_auction(offers: dict[str, list[Offer]], budget: int = BUDGET) -> list[Bid]:
    bids = []
    for owner, owner_offers in offers.items():
        points = split_budget([o.raw for o in owner_offers], budget)
        for n, (offer, p) in enumerate(zip(owner_offers, points, strict=True), start=1):
            if offer.wish.owner != owner:
                raise ValueError(f"пожелание {offer.wish} лежит не у своего владельца {owner}")
            if p > 0:
                bids.append(Bid(id=f"{owner}#{n}", wish=offer.wish, points=p, text=offer.text))
    return bids


@dataclass
class Account:
    """Итог аукциона для одного участника."""

    owner: str
    won: list[Bid] = field(default_factory=list)
    lost: list[Bid] = field(default_factory=list)

    @property
    def points(self) -> int:
        return sum(b.points for b in self.won)

    @property
    def spent(self) -> int:
        return self.points + sum(b.points for b in self.lost)


def settle(bids, schedule: Schedule) -> dict[str, Account]:
    accounts: dict[str, Account] = {}
    for bid in bids:
        account = accounts.setdefault(bid.owner, Account(bid.owner))
        (account.won if bid.wish.holds(schedule) else account.lost).append(bid)
    return accounts
