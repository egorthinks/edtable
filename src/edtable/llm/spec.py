"""Промежуточный формат пожеланий: его выдаёт любой разборщик текста.

Формат специально плоский и простой — такой локальная модель заполняет без
ошибок. В пожелания ядра его переводит to_offers().
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from edtable.scheduler.auction import Offer
from edtable.scheduler.models import DAY_NAMES, TimeSlot
from edtable.scheduler.wishes import AllOf, AnyOf, AvoidSlots, MaxDays, MaxPerDay, NoGaps, Wish

ATOM_KINDS = ("avoid", "no_gaps", "max_per_day", "max_days")
KINDS = (*ATOM_KINDS, "any", "all")


@dataclass
class WishSpec:
    kind: str
    # Дни с 0 (понедельник). Пусто — все дни.
    days: list[int] = field(default_factory=list)
    # Номера уроков с 1. Пусто — весь день.
    periods: list[int] = field(default_factory=list)
    limit: int | None = None
    parts: list["WishSpec"] = field(default_factory=list)
    # Важность 1..10, если человек не назвал очки сам.
    weight: float = 5
    points: int | None = None
    text: str = ""


class WishParserError(Exception):
    pass


def to_wish(owner: str, spec: WishSpec, slots: Iterable[TimeSlot]) -> Wish | None:
    """Возвращает None, если пожелание пустое или бессмысленное для этой сетки."""
    slots = list(slots)
    match spec.kind:
        case "avoid":
            chosen = frozenset(
                s
                for s in slots
                if (not spec.days or s.day in spec.days)
                and (not spec.periods or s.period in spec.periods)
            )
            if not chosen:
                return None
            label = ""
            if spec.days and not spec.periods:
                label = "свободно: " + ", ".join(DAY_NAMES[d] for d in sorted(set(spec.days)))
            return AvoidSlots(owner, chosen, label)
        case "no_gaps":
            return NoGaps(owner)
        case "max_per_day" if spec.limit:
            return MaxPerDay(owner, spec.limit)
        case "max_days" if spec.limit:
            return MaxDays(owner, spec.limit)
        case "any" | "all" if not spec.parts and (spec.days or spec.periods):
            # Маленькие модели иногда пишут «any» с днями вместо avoid — понимаем как avoid.
            return to_wish(owner, replace(spec, kind="avoid"), slots)
        case "any" | "all":
            parts = tuple(w for p in spec.parts if (w := to_wish(owner, p, slots)) is not None)
            if len(parts) <= 1:
                return parts[0] if parts else None
            return (AnyOf if spec.kind == "any" else AllOf)(owner, parts)
    return None


def to_offers(owner: str, specs: list[WishSpec], slots: Iterable[TimeSlot]) -> list[Offer]:
    slots = list(slots)
    offers = []
    for spec in specs:
        wish = to_wish(owner, spec, slots)
        if wish is not None:
            offers.append(Offer(wish, weight=spec.weight, points=spec.points, text=spec.text))
    return offers
